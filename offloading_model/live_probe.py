"""Compare identical work on the laptop and an Azure Function.

Set AZURE_FUNCTION_KEY in your shell, then run:
python live_probe.py --url https://YOUR_APP.azurewebsites.net/api/compute
"""
import argparse
import csv
import importlib.util
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("workload", HERE / "azure_function" / "workload.py")
workload = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workload)


def run_probe(url, key, payload):
    edge_start = time.perf_counter()
    local = workload.compute(payload)
    edge_wall_ms = (time.perf_counter() - edge_start) * 1000
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "x-functions-key": key})
    cloud_start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            remote = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Function returned HTTP {exc.code}: {exc.read(300).decode('utf-8', 'replace')}") from exc
    cloud_wall_ms = (time.perf_counter() - cloud_start) * 1000
    if remote.get("digest") != local["digest"]:
        raise RuntimeError("Edge and cloud returned different results")
    return {"iterations": payload["iterations"], "input_bytes": len(payload["data"].encode()),
            "edge_wall_ms": edge_wall_ms, "edge_compute_ms": local["compute_ms"],
            "cloud_wall_ms": cloud_wall_ms, "cloud_compute_ms": remote["compute_ms"],
            "cloud_overhead_ms": cloud_wall_ms - remote["compute_ms"], "digests_match": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Terraform's function_url output")
    parser.add_argument("--output", default="live_probe.csv")
    args = parser.parse_args()
    key = os.environ.get("AZURE_FUNCTION_KEY")
    if not key:
        sys.exit("Set AZURE_FUNCTION_KEY to the function key; see README. Do not put it on the command line.")
    jobs = [{"iterations": 10000, "data": "a" * 1024},
            {"iterations": 50000, "data": "b" * 16384},
            {"iterations": 100000, "data": "c" * 65536}]
    rows = []
    for job in jobs:
        for repetition in range(3):
            row = run_probe(args.url, key, job)
            row["repetition"] = repetition + 1
            rows.append(row)
            print(f"{row['iterations']:6d} iterations: edge {row['edge_wall_ms']:.1f} ms, "
                  f"cloud round trip {row['cloud_wall_ms']:.1f} ms")
    with Path(args.output).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved {len(rows)} paired observations to {args.output}")


if __name__ == "__main__":
    main()
