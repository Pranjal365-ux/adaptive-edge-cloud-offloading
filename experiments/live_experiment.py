"""Measured four-policy experiment. Freeze calibration before final evaluation.

CPU tasks use processes; digest references are prepared before measured runs.
HTTPS sizes count JSON bodies only, not TCP/TLS/IP bytes or available bandwidth.
"""
import argparse
import csv
import hashlib
import json
import math
import os
import platform
import random
import statistics
import time
import urllib.request
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import psutil
from azure_function.workload import compute

POLICIES = ('edge', 'cloud', 'fixed', 'adaptive')
ITERATIONS = (100_000, 300_000, 800_000, 1_600_000)
DEV_ITERATIONS = (80_000, 250_000, 700_000, 1_400_000)
SIZES = (1024, 16384, 65536)

def utc():
    return datetime.now(timezone.utc).isoformat()

def cloud_compute(url, key, payload):
    body = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=body, method='POST',
        headers={'Content-Type': 'application/json', 'x-functions-key': key})
    with urllib.request.urlopen(req, timeout=90) as response:
        raw = response.read()
    result = json.loads(raw)
    result['request_body_bytes'] = len(body)
    result['response_body_bytes'] = len(raw)
    return result

def trace(seed, count, arrival_gap_ms):
    rng = random.Random(seed)
    arrival = 0.0
    jobs = []
    for index in range(count):
        if index:
            arrival += rng.expovariate(1000 / arrival_gap_ms)
        jobs.append({'task': index, 'arrival_s': arrival,
            'iterations': rng.choice(ITERATIONS),
            'data': chr(97 + index % 26) * rng.choice(SIZES)})
    return jobs

def calibrate(url, key, output):
    observations = []
    errors = []
    # Development payloads and iteration values differ from evaluation.
    for repetition in range(3):
        for iterations in DEV_ITERATIONS:
            for size in (SIZES[0], SIZES[-1]):
                payload = {'iterations': iterations, 'data': 'CALIBRATION' * (size // 11)}
                t0 = time.perf_counter()
                local = compute(payload)
                edge_ms = (time.perf_counter() - t0) * 1000
                t0 = time.perf_counter()
                for attempt in range(3):
                    t0 = time.perf_counter()
                    try:
                        remote = cloud_compute(url, key, payload)
                        roundtrip = (time.perf_counter() - t0) * 1000
                        break
                    except Exception as exc:
                        errors.append({'utc': utc(), 'repetition': repetition, 'iterations': iterations, 'size': size, 'attempt': attempt, 'error': type(exc).__name__, 'elapsed_ms': (time.perf_counter()-t0)*1000})
                        write_csv(output / 'calibration-errors.csv', errors)
                        if attempt == 2:
                            raise RuntimeError('Calibration unavailable after three attempts') from None
                        time.sleep(2)
                if local['digest'] != remote.get('digest'):
                    raise RuntimeError('Calibration digest mismatch')
                observations.append({'utc': utc(), 'repetition': repetition, 'iterations': iterations,
                    'input_bytes': len(payload['data']), 'edge_ms': edge_ms,
                    'cloud_roundtrip_ms': roundtrip, 'cloud_compute_ms': remote['compute_ms'],
                    'digests_match': True})
                write_csv(output / 'calibration.csv', observations)
    edge_rate = statistics.median(x['edge_ms'] / x['iterations'] for x in observations)
    cloud_rate = statistics.median(x['cloud_compute_ms'] / x['iterations'] for x in observations)
    overhead = statistics.median(max(0, x['cloud_roundtrip_ms'] - x['cloud_compute_ms']) for x in observations)
    # Include all-cloud and all-edge candidates. Objective uses development classes only.
    candidates = (0,) + DEV_ITERATIONS
    scores = {cut: statistics.mean(overhead + cloud_rate * it if it > cut else edge_rate * it
        for it in DEV_ITERATIONS) for cut in candidates}
    threshold = min(scores, key=lambda cut: (scores[cut], cut))
    return {'edge_ms_per_iteration': edge_rate, 'cloud_ms_per_iteration': cloud_rate,
        'cloud_overhead_ms': overhead, 'fixed_threshold_iterations': threshold,
        'threshold_scores_ms': scores, 'development_observations': len(observations), 'calibration_failed_attempts': len(errors)}

def execute(job, place, url, key, run_start):
    started = time.perf_counter()
    result = {}
    error = ''
    try:
        payload = {'iterations': job['iterations'], 'data': job['data']}
        result = compute(payload) if place == 'edge' else cloud_compute(url, key, payload)
        if result.get('digest') != job['expected_digest']:
            error = 'DigestMismatch'
    except Exception as exc:
        # Exception type only: avoid leaking URLs, keys, or server response bodies.
        error = type(exc).__name__
    finished = time.perf_counter()
    return {'task': job['task'], 'place': place, 'iterations': job['iterations'],
        'input_bytes': len(job['data'].encode()), 'arrival_s': job['arrival_s'],
        'start_s': started - run_start, 'finish_s': finished - run_start,
        'service_ms': (finished - started) * 1000, 'compute_ms': result.get('compute_ms', ''),
        'request_body_bytes': result.get('request_body_bytes', 0),
        'response_body_bytes': result.get('response_body_bytes', 0),
        'worker_instance': result.get('worker_instance', ''),
        'first_on_process': result.get('first_on_process', False),
        'digest_match': not bool(error), 'error': error, 'utc_finished': utc()}

def choose(policy, job, model, outstanding, edge_workers, cloud_workers):
    if policy == 'fixed':
        return 'cloud' if job['iterations'] > model['fixed_threshold_iterations'] else 'edge'
    if policy != 'adaptive':
        return policy
    # Frozen rule: current unfinished client work, calibrated compute and HTTPS overhead.
    # Full remaining service is approximated by full submitted task work (conservative).
    edge = model['edge_ms_per_iteration'] * job['iterations']
    cloud = model['cloud_overhead_ms'] + model['cloud_ms_per_iteration'] * job['iterations']
    edge += sum(cost for f, cost in outstanding['edge'] if not f.done()) / edge_workers
    cloud += sum(cost for f, cost in outstanding['cloud'] if not f.done()) / cloud_workers
    return 'cloud' if cloud < edge else 'edge'

def run_policy(jobs, policy, model, url, key, edge_workers, cloud_workers):
    outstanding = {'edge': [], 'cloud': []}
    all_futures = []
    telemetry = []
    with ProcessPoolExecutor(max_workers=edge_workers) as edge_pool, ThreadPoolExecutor(max_workers=cloud_workers) as cloud_pool:
        # Exclude process spawn and digest-reference generation from the workload interval.
        warm = [edge_pool.submit(compute, {'iterations': 1, 'data': ''}) for _ in range(edge_workers)]
        for future in warm:
            future.result()
        psutil.cpu_percent(None)
        started = time.perf_counter()
        def sample():
            telemetry.append({'elapsed_s': time.perf_counter() - started,
                'system_cpu_percent': psutil.cpu_percent(None),
                'system_memory_percent': psutil.virtual_memory().percent,
                'available_memory_bytes': psutil.virtual_memory().available})
        for job in jobs:
            while time.perf_counter() < started + job['arrival_s']:
                sample()
                time.sleep(min(.1, max(0, started + job['arrival_s'] - time.perf_counter())))
            for place in outstanding:
                outstanding[place] = [(f, cost) for f, cost in outstanding[place] if not f.done()]
            place = choose(policy, job, model, outstanding, edge_workers, cloud_workers)
            pool = edge_pool if place == 'edge' else cloud_pool
            future = pool.submit(execute, job, place, url, key if place == 'cloud' else '', started)
            cost = model['edge_ms_per_iteration'] * job['iterations'] if place == 'edge' else model['cloud_overhead_ms'] + model['cloud_ms_per_iteration'] * job['iterations']
            outstanding[place].append((future, cost))
            all_futures.append(future)
            sample()
        while not all(f.done() for f in all_futures):
            sample()
            time.sleep(.1)
        records = [f.result() for f in all_futures]
    for row in records:
        row['completion_ms'] = (row['finish_s'] - row['arrival_s']) * 1000
    valid = [r for r in records if not r['error']]
    latencies = sorted(r['completion_ms'] for r in valid)
    duration = max(r['finish_s'] for r in records)
    return {'policy': policy, 'tasks': len(records), 'successes': len(valid),
        'errors': len(records) - len(valid),
        'mean_completion_ms': statistics.mean(latencies) if latencies else '',
        'p95_completion_ms': latencies[math.ceil(.95 * len(latencies)) - 1] if latencies else '',
        'throughput_tasks_per_s': len(valid) / duration,
        'cloud_fraction': sum(r['place'] == 'cloud' for r in records) / len(records),
        'transferred_input_bytes': sum(r['input_bytes'] for r in records if r['place'] == 'cloud'),
        'request_body_bytes': sum(r['request_body_bytes'] for r in records),
        'response_body_bytes': sum(r['response_body_bytes'] for r in records),
        'duration_s': duration}, records, telemetry

def write_csv(path, rows):
    if not rows:
        return
    with Path(path).open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--output', default='live_results')
    parser.add_argument('--tasks', type=int, default=40)
    parser.add_argument('--seeds', type=int, default=8)
    parser.add_argument('--arrival-gap-ms', type=float, default=100)
    parser.add_argument('--edge-workers', type=int, default=1)
    parser.add_argument('--cloud-workers', type=int, default=4)
    parser.add_argument('--calibrate-only', action='store_true')
    parser.add_argument('--protocol', type=Path)
    args = parser.parse_args()
    if not args.url.startswith('https://') or '?' in args.url:
        parser.error('Use an HTTPS endpoint without query parameters; key belongs in environment')
    if min(args.tasks, args.seeds, args.edge_workers, args.cloud_workers) < 1 or args.arrival_gap_ms <= 0:
        parser.error('Positive counts and arrival gap required')
    key = os.environ.get('AZURE_FUNCTION_KEY')
    if not key:
        parser.error('AZURE_FUNCTION_KEY must be set privately in the execution environment')
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    settings = {k: v for k, v in vars(args).items() if k not in ('protocol', 'calibrate_only', 'output')}
    if args.protocol:
        protocol = json.loads(args.protocol.read_text())
        if protocol['settings'] != settings:
            parser.error('Settings differ from frozen protocol')
        model = protocol['model']
    else:
        if not args.calibrate_only:
            parser.error('Run --calibrate-only first, then use --protocol for final runs')
        model = calibrate(args.url, key, output)
        orders = {}
        for seed in range(3001, 3001 + args.seeds):
            order = list(POLICIES)
            random.Random(seed).shuffle(order)
            orders[str(seed)] = order
        protocol = {'frozen_utc': utc(), 'model': model, 'settings': settings,
            'orders': orders, 'final_seeds': list(range(3001, 3001 + args.seeds)),
            'iteration_classes': ITERATIONS, 'input_sizes_bytes': SIZES,
            'adaptive_rule': 'calibrated own service + total full service of unfinished client tasks / pool workers; cloud iff strictly lower; no outcome fitting',
            'p95': 'nearest rank ceil(0.95*N), successful tasks only; errors reported separately',
            'telemetry': 'system CPU and RAM sampled during run, descriptive only, not policy input',
            'transfer': 'JSON request and response bodies, excludes HTTP/TLS/TCP overhead',
            'software': {'python': platform.python_version(), 'platform': platform.platform(), 'psutil': psutil.__version__},
            'hardware': {'logical_cpus': psutil.cpu_count(), 'physical_cores': psutil.cpu_count(logical=False), 'ram_bytes': psutil.virtual_memory().total},
            'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        (output / 'protocol.json').write_text(json.dumps(protocol, indent=2))
        print(json.dumps(model, indent=2))
        return
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != protocol['source_sha256']:
        parser.error('Source changed after freeze')
    summaries, task_rows, telemetry_rows = [], [], []
    for seed in protocol['final_seeds']:
        jobs = trace(seed, args.tasks, args.arrival_gap_ms)
        for job in jobs:
            job['expected_digest'] = compute(job)['digest']
        (output / f'trace-{seed}.json').write_text(json.dumps(jobs, indent=2))
        for order_index, policy in enumerate(protocol['orders'][str(seed)]):
            start_utc = utc()
            summary, records, telemetry = run_policy(jobs, policy, model, args.url, key, args.edge_workers, args.cloud_workers)
            summaries.append({'seed': seed, 'order_index': order_index, 'utc_started': start_utc, **summary})
            task_rows.extend({'seed': seed, 'policy': policy, **r} for r in records)
            telemetry_rows.extend({'seed': seed, 'policy': policy, **r} for r in telemetry)
            write_csv(output / 'summary.csv', summaries)
            write_csv(output / 'tasks.csv', task_rows)
            write_csv(output / 'telemetry.csv', telemetry_rows)
            print(f"seed={seed} {policy}: mean={summary['mean_completion_ms']} errors={summary['errors']}", flush=True)
    (output / 'completed.json').write_text(json.dumps({'utc': utc(), 'runs': len(summaries)}))

if __name__ == '__main__':
    main()
