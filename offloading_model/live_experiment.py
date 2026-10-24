"""Run paired edge/Azure Function experiments with four offloading policies.

This is a small live benchmark, separate from the discrete-event simulation.
Keep the function key in AZURE_FUNCTION_KEY, never in source or results.
"""

import argparse
import csv
import importlib.util
import json
import os
import random
import statistics
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("workload", ROOT / "azure_function" / "workload.py")
workload = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workload)

POLICIES = ("edge", "cloud", "fixed", "adaptive")
ITERATIONS = (10_000, 40_000, 100_000, 200_000)
SIZES = (1024, 16_384, 65_536)


def cloud_compute(url, key, payload):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "x-functions-key": key},
    )
    with urllib.request.urlopen(req, timeout=90) as response:
        return json.load(response)


def trace(seed, count, arrival_gap_ms):
    rng = random.Random(seed)
    arrival = 0.0
    jobs = []
    for index in range(count):
        arrival += rng.expovariate(1 / arrival_gap_ms) / 1000 if index else 0
        jobs.append(
            {
                "task": index,
                "arrival_s": arrival,
                "iterations": rng.choice(ITERATIONS),
                "data": chr(97 + index % 26) * rng.choice(SIZES),
            }
        )
    return jobs


def calibrate(url, key):
    """Separate development calls fit a simple latency model; never use final-task outcomes."""
    observations = []
    for iterations in ITERATIONS:
        for size in (SIZES[0], SIZES[-1]):
            payload = {"iterations": iterations, "data": "z" * size}
            t0 = time.perf_counter()
            local = workload.compute(payload)
            edge_ms = (time.perf_counter() - t0) * 1000
            t0 = time.perf_counter()
            remote = cloud_compute(url, key, payload)
            cloud_ms = (time.perf_counter() - t0) * 1000
            if local["digest"] != remote.get("digest"):
                raise RuntimeError("Calibration digest mismatch")
            observations.append((iterations, size, edge_ms, cloud_ms, remote["compute_ms"]))
    # Fit CPU slope from paired light/heavy tasks. Cloud overhead uses the median
    # measured round-trip minus compute time; it includes network and service time.
    edge_rate = statistics.median(x[2] / x[0] for x in observations)
    cloud_rate = statistics.median(x[4] / x[0] for x in observations)
    overhead = statistics.median(max(0, x[3] - x[4]) for x in observations)
    threshold = min(
        ITERATIONS,
        key=lambda cut: statistics.mean(
            overhead + cloud_rate * it if it > cut else edge_rate * it for it in ITERATIONS
        ),
    )
    return {
        "edge_ms_per_iteration": edge_rate,
        "cloud_ms_per_iteration": cloud_rate,
        "cloud_overhead_ms": overhead,
        "fixed_threshold_iterations": threshold,
        "development_observations": len(observations),
    }


def execute(job, place, url, key, run_start):
    started = time.perf_counter()
    payload = {"iterations": job["iterations"], "data": job["data"]}
    result = workload.compute(payload) if place == "edge" else cloud_compute(url, key, payload)
    finished = time.perf_counter()
    # Validate against a short independent reference digest, outside measured time.
    expected = workload.compute(payload)["digest"]
    if result.get("digest") != expected:
        raise RuntimeError(f"Digest mismatch for task {job['task']}")
    return {
        "task": job["task"],
        "place": place,
        "iterations": job["iterations"],
        "input_bytes": len(job["data"]),
        "arrival_s": job["arrival_s"],
        "start_s": started - run_start,
        "finish_s": finished - run_start,
        "service_ms": (finished - started) * 1000,
        "compute_ms": result["compute_ms"],
    }


def run_policy(jobs, policy, model, url, key, edge_workers, cloud_workers):
    started = time.perf_counter()
    records = []
    outstanding = {"edge": [], "cloud": []}
    all_futures = []
    with (
        ThreadPoolExecutor(max_workers=edge_workers) as edge_pool,
        ThreadPoolExecutor(max_workers=cloud_workers) as cloud_pool,
    ):
        for job in jobs:
            delay = started + job["arrival_s"] - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            for place in outstanding:
                outstanding[place] = [f for f in outstanding[place] if not f.done()]
            if policy == "fixed":
                place = (
                    "cloud" if job["iterations"] > model["fixed_threshold_iterations"] else "edge"
                )
            elif policy == "adaptive":
                edge_ms = (
                    model["edge_ms_per_iteration"]
                    * job["iterations"]
                    * (1 + len(outstanding["edge"]) / edge_workers)
                )
                cloud_ms = model["cloud_overhead_ms"] + model["cloud_ms_per_iteration"] * job[
                    "iterations"
                ] * (1 + len(outstanding["cloud"]) / cloud_workers)
                place = "cloud" if cloud_ms < edge_ms else "edge"
            else:
                place = policy
            pool = edge_pool if place == "edge" else cloud_pool
            future = pool.submit(execute, job, place, url, key, started)
            outstanding[place].append(future)
            all_futures.append(future)
        records = [f.result() for f in all_futures]
    records.sort(key=lambda r: r["task"])
    for row in records:
        row["completion_ms"] = (row["finish_s"] - row["arrival_s"]) * 1000
    duration = max(r["finish_s"] for r in records)
    latencies = sorted(r["completion_ms"] for r in records)
    summary = {
        "policy": policy,
        "tasks": len(records),
        "mean_completion_ms": statistics.mean(latencies),
        "p95_completion_ms": latencies[max(0, int(0.95 * len(latencies) + 0.999999) - 1)],
        "throughput_tasks_per_s": len(records) / duration,
        "cloud_fraction": sum(r["place"] == "cloud" for r in records) / len(records),
        "transferred_input_bytes": sum(r["input_bytes"] for r in records if r["place"] == "cloud"),
    }
    return summary, records


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", default="live_results")
    parser.add_argument("--tasks", type=int, default=20)
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--arrival-gap-ms", type=float, default=35)
    parser.add_argument("--edge-workers", type=int, default=1)
    parser.add_argument("--cloud-workers", type=int, default=4)
    args = parser.parse_args()
    if not args.url.startswith("https://"):
        parser.error("--url must be an HTTPS endpoint")
    if (
        min(args.tasks, args.seeds, args.edge_workers, args.cloud_workers) < 1
        or args.arrival_gap_ms <= 0
    ):
        parser.error("tasks, seeds, worker counts and arrival gap must be positive")
    key = os.environ.get("AZURE_FUNCTION_KEY")
    if not key:
        sys.exit(
            "Set AZURE_FUNCTION_KEY in your shell; do not put it in the command or source code."
        )
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    model = calibrate(args.url, key)
    summaries, task_rows = [], []
    for i in range(args.seeds):
        seed = 3001 + i
        jobs = trace(seed, args.tasks, args.arrival_gap_ms)
        order = list(POLICIES)
        random.Random(seed).shuffle(order)
        for policy in order:
            summary, records = run_policy(
                jobs, policy, model, args.url, key, args.edge_workers, args.cloud_workers
            )
            summaries.append({"seed": seed, **summary})
            task_rows.extend({"seed": seed, "policy": policy, **r} for r in records)
            print(
                f"seed={seed} {policy}: mean={summary['mean_completion_ms']:.1f} ms, "
                f"p95={summary['p95_completion_ms']:.1f} ms"
            )
    write_csv(output / "summary.csv", summaries)
    write_csv(output / "tasks.csv", task_rows)
    (output / "protocol.json").write_text(
        json.dumps(
            {
                "model": model,
                "settings": vars(args),
                "final_seeds": list(range(3001, 3001 + args.seeds)),
                "policies": POLICIES,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Saved {len(summaries)} runs in {output}")


if __name__ == "__main__":
    main()
