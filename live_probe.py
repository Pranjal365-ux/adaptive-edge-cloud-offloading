"""Sequential local versus Azure pilot; not final evaluation data."""
import argparse
import os
import time
from pathlib import Path
from live_experiment import compute, cloud_compute, write_csv, utc

def run_probe(url, key, payload):
    t0 = time.perf_counter()
    local = compute(payload)
    edge_wall = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    remote = cloud_compute(url, key, payload)
    cloud_wall = (time.perf_counter() - t0) * 1000
    if local['digest'] != remote.get('digest'):
        raise RuntimeError('DigestMismatch')
    return {'utc': utc(), 'iterations': payload['iterations'], 'input_bytes': len(payload['data'].encode()),
        'edge_wall_ms': edge_wall, 'edge_compute_ms': local['compute_ms'],
        'cloud_wall_ms': cloud_wall, 'cloud_compute_ms': remote['compute_ms'],
        'cloud_overhead_ms': cloud_wall - remote['compute_ms'], 'digests_match': True,
        'digest': local['digest'], 'worker_instance': remote.get('worker_instance', ''),
        'first_on_process': remote.get('first_on_process', False),
        'request_body_bytes': remote['request_body_bytes'], 'response_body_bytes': remote['response_body_bytes']}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url', required=True)
    p.add_argument('--output', default='live_probe.csv')
    args = p.parse_args()
    if not args.url.startswith('https://') or '?' in args.url:
        p.error('HTTPS URL without query parameters required')
    key = os.environ.get('AZURE_FUNCTION_KEY')
    if not key:
        p.error('Set AZURE_FUNCTION_KEY privately in the environment')
    rows = []
    for iterations in (10_000, 50_000, 100_000, 500_000, 1_000_000, 1_800_000):
        for rep in range(3):
            row = run_probe(args.url, key, {'iterations': iterations, 'data': 'PILOT' * 3276})
            row['repetition'] = rep
            rows.append(row)
            write_csv(Path(args.output), rows)
            print(f"{iterations}: edge={row['edge_wall_ms']:.1f}, cloud={row['cloud_wall_ms']:.1f} ms", flush=True)
if __name__ == '__main__':
    main()
