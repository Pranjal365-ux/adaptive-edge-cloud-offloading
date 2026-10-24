"""Reproducible edge-cloud task-offloading discrete-event experiment.

Run: python offloading.py --output results
Python 3.10+; no third-party packages needed for simulation.
"""

from __future__ import annotations

import argparse
import csv
import heapq
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean


@dataclass(frozen=True)
class Task:
    id: int
    arrival: float
    work_mi: float
    input_mb: float
    output_mb: float


@dataclass(frozen=True)
class Scenario:
    name: str
    arrival_rate: float
    bandwidth_mbps: float
    latency_ms: float
    edge_mips: float = 500.0
    cloud_mips: float = 3000.0
    edge_workers: int = 2
    cloud_workers: int = 4
    cloud_usd_per_compute_second: float = 0.0001
    # A constant latency-to-cost tradeoff. One dollar is treated as 100 seconds.
    cost_weight_seconds_per_usd: float = 100.0
    # In the variable scenario, each 30-second interval alternates good/poor.
    variable_network: bool = False

    def network_at(self, time: float) -> tuple[float, float]:
        if self.variable_network and int(time // 30) % 2 == 1:
            return self.bandwidth_mbps / 5, self.latency_ms * 3
        return self.bandwidth_mbps, self.latency_ms


SCENARIOS = [
    Scenario("light_good", 1.2, 80, 20),
    Scenario("heavy_good", 5.0, 80, 20),
    Scenario("light_poor", 1.2, 8, 150),
    Scenario("heavy_poor", 5.0, 8, 150),
    Scenario("variable_network", 3.5, 60, 35, variable_network=True),
]
POLICIES = ("edge_only", "cloud_only", "threshold", "adaptive")


def generate_tasks(seed: int, count: int, arrival_rate: float) -> list[Task]:
    rng = random.Random(seed)
    time = 0.0
    tasks = []
    for i in range(count):
        time += rng.expovariate(arrival_rate)
        # Two workload classes keep transfer size distinct from CPU demand.
        if rng.random() < 0.60:
            work, size = rng.uniform(80, 300), rng.uniform(0.1, 1.0)
        else:
            work, size = rng.uniform(500, 1500), rng.uniform(1.0, 5.0)
        tasks.append(Task(i, time, work, size, size * rng.uniform(0.05, 0.25)))
    return tasks


class Resource:
    """FIFO servers; the event loop owns time and starts queued requests."""

    def __init__(self, capacity: int):
        self.capacity = capacity
        self.active: dict[int, float] = {}  # request ID -> finish time
        self.queue: list[tuple[int, float, str, Task]] = []
        self.busy_seconds = 0.0

    def wait_estimate(self, now: float) -> float:
        remaining = sum(max(0, finish - now) for finish in self.active.values())
        queued = sum(duration for _, duration, _, _ in self.queue)
        return max(0.0, (remaining + queued) / self.capacity)


class Simulation:
    def __init__(self, scenario: Scenario, tasks: list[Task], policy: str, threshold_mi: float):
        self.scenario, self.tasks, self.policy = scenario, tasks, policy
        self.threshold_mi = threshold_mi
        self.resources = {
            "edge": Resource(scenario.edge_workers),
            "cloud": Resource(scenario.cloud_workers),
            "upload": Resource(1),
            "download": Resource(1),
        }
        self.events: list[tuple[float, int, str, object]] = []
        self.serial = 0
        self.request_id = 0
        self.records: dict[int, dict] = {}
        self.now = 0.0
        for task in tasks:
            self.schedule(task.arrival, "arrival", task)

    def schedule(self, when: float, kind: str, data: object) -> None:
        self.serial += 1
        heapq.heappush(self.events, (when, self.serial, kind, data))

    def transfer_seconds(self, mb: float, now: float) -> float:
        bandwidth, _ = self.scenario.network_at(now)
        return 8.0 * mb / bandwidth

    def choose(self, task: Task) -> str:
        if self.policy == "edge_only":
            return "edge"
        if self.policy == "cloud_only":
            return "cloud"
        if self.policy == "threshold":
            return "cloud" if task.work_mi > self.threshold_mi else "edge"
        s = self.scenario
        edge_t = self.resources["edge"].wait_estimate(self.now) + task.work_mi / s.edge_mips
        _, latency_ms = s.network_at(self.now)
        cloud_t = (
            self.resources["upload"].wait_estimate(self.now)
            + self.transfer_seconds(task.input_mb, self.now)
            + latency_ms / 1000
            + self.resources["cloud"].wait_estimate(self.now)
            + task.work_mi / s.cloud_mips
            + self.resources["download"].wait_estimate(self.now)
            + self.transfer_seconds(task.output_mb, self.now)
            + latency_ms / 1000
        )
        cost = task.work_mi / s.cloud_mips * s.cloud_usd_per_compute_second
        return "cloud" if cloud_t + s.cost_weight_seconds_per_usd * cost < edge_t else "edge"

    def request(self, name: str, duration: float, next_stage: str, task: Task) -> None:
        self.request_id += 1
        req = (self.request_id, duration, next_stage, task)
        resource = self.resources[name]
        if len(resource.active) < resource.capacity:
            self.start(name, req)
        else:
            resource.queue.append(req)

    def start(self, name: str, req: tuple[int, float, str, Task]) -> None:
        request_id, duration, next_stage, task = req
        resource = self.resources[name]
        finish = self.now + duration
        resource.active[request_id] = finish
        resource.busy_seconds += duration
        self.schedule(finish, "service_done", (name, request_id, next_stage, task))

    def run(self) -> tuple[list[dict], dict]:
        s = self.scenario
        while self.events:
            self.now, _, kind, data = heapq.heappop(self.events)
            if kind == "arrival":
                task = data
                destination = self.choose(task)
                self.records[task.id] = {
                    "task_id": task.id,
                    "arrival_s": task.arrival,
                    "work_mi": task.work_mi,
                    "input_mb": task.input_mb,
                    "output_mb": task.output_mb,
                    "destination": destination,
                }
                if destination == "edge":
                    self.request("edge", task.work_mi / s.edge_mips, "finished", task)
                else:
                    self.request(
                        "upload", self.transfer_seconds(task.input_mb, self.now), "uploaded", task
                    )
            elif kind == "service_done":
                name, request_id, next_stage, task = data
                resource = self.resources[name]
                del resource.active[request_id]
                if resource.queue:
                    self.start(name, resource.queue.pop(0))
                if next_stage == "finished":
                    self.records[task.id]["finish_s"] = self.now
                elif next_stage == "uploaded":
                    _, latency = s.network_at(self.now)
                    self.schedule(self.now + latency / 1000, "cloud_arrival", task)
                elif next_stage == "computed":
                    self.request(
                        "download",
                        self.transfer_seconds(task.output_mb, self.now),
                        "downloaded",
                        task,
                    )
                elif next_stage == "downloaded":
                    _, latency = s.network_at(self.now)
                    self.schedule(self.now + latency / 1000, "finished_cloud", task)
            elif kind == "cloud_arrival":
                task = data
                self.request("cloud", task.work_mi / s.cloud_mips, "computed", task)
            elif kind == "finished_cloud":
                task = data
                self.records[task.id]["finish_s"] = self.now

        rows = []
        for task in self.tasks:
            row = self.records[task.id]
            row["completion_s"] = row["finish_s"] - row["arrival_s"]
            row["cloud_cost_usd"] = (
                task.work_mi / s.cloud_mips * s.cloud_usd_per_compute_second
                if row["destination"] == "cloud"
                else 0.0
            )
            row["network_mb"] = (
                task.input_mb + task.output_mb if row["destination"] == "cloud" else 0.0
            )
            rows.append(row)
        durations = sorted(row["completion_s"] for row in rows)
        horizon = max(row["finish_s"] for row in rows) - min(task.arrival for task in self.tasks)
        summary = {
            "scenario": s.name,
            "policy": self.policy,
            "tasks": len(rows),
            "mean_completion_s": mean(durations),
            "p95_completion_s": durations[max(0, int(0.95 * len(durations)) - 1)],
            "throughput_tasks_per_s": len(rows) / horizon,
            "edge_utilization": self.resources["edge"].busy_seconds / (s.edge_workers * horizon),
            "network_mb": sum(row["network_mb"] for row in rows),
            "cloud_cost_usd": sum(row["cloud_cost_usd"] for row in rows),
            "cloud_task_fraction": sum(row["destination"] == "cloud" for row in rows) / len(rows),
            "makespan_s": horizon,
        }
        return rows, summary


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)]


def tune_threshold(count: int, seeds: list[int]) -> tuple[float, list[dict]]:
    # A separate development scenario; never use final test seeds for tuning.
    dev = Scenario("development", 3.0, 40, 60)
    pool = [t.work_mi for seed in seeds for t in generate_tasks(seed, count, dev.arrival_rate)]
    candidates = sorted({percentile(pool, q) for q in (0.25, 0.50, 0.75)})
    scores = []
    for threshold in candidates:
        measurements = []
        for seed in seeds:
            trace = generate_tasks(seed, count, dev.arrival_rate)
            _, summary = Simulation(dev, trace, "threshold", threshold).run()
            measurements.append(summary["mean_completion_s"])
        scores.append(
            {"threshold_mi": threshold, "development_mean_completion_s": mean(measurements)}
        )
    chosen = min(scores, key=lambda x: (x["development_mean_completion_s"], x["threshold_mi"]))
    return chosen["threshold_mi"], scores


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="results", help="Output directory")
    parser.add_argument("--tasks", type=int, default=300, help="Tasks per scenario and seed")
    parser.add_argument("--seeds", type=int, default=5, help="Final repetitions")
    args = parser.parse_args()
    if args.tasks < 20 or args.seeds < 1:
        parser.error("Use at least 20 tasks and one seed")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    development_seeds = list(range(1001, 1006))
    final_seeds = list(range(2001, 2001 + args.seeds))
    threshold, tuning = tune_threshold(args.tasks, development_seeds)
    all_summaries, all_tasks = [], []
    for scenario in SCENARIOS:
        for seed in final_seeds:
            trace = generate_tasks(seed, args.tasks, scenario.arrival_rate)
            for policy in POLICIES:
                rows, summary = Simulation(scenario, trace, policy, threshold).run()
                summary["seed"] = seed
                all_summaries.append(summary)
                for row in rows:
                    all_tasks.append(
                        {"scenario": scenario.name, "seed": seed, "policy": policy, **row}
                    )
    write_csv(output / "summary.csv", all_summaries)
    write_csv(output / "tasks.csv", all_tasks)
    metadata = {
        "model": (
            "FIFO discrete event simulator; separate upload/download links; "
            "two one-way latency delays"
        ),
        "scenarios": [asdict(s) for s in SCENARIOS],
        "development_seeds": development_seeds,
        "final_seeds": final_seeds,
        "tasks_per_scenario_seed": args.tasks,
        "threshold_selection": "minimum mean completion time on separate development runs",
        "threshold_candidates": tuning,
        "selected_threshold_mi": threshold,
        "adaptive_rule": (
            "predicted cloud completion + cost weight times estimated cloud cost "
            "< predicted edge completion"
        ),
        "units": {
            "work": "million instructions",
            "processing_rate": "million instructions per second",
            "input_output": "MB (decimal)",
            "bandwidth": "megabits per second",
            "time": "seconds",
        },
    }
    (output / "experiment.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"Selected fixed threshold: {threshold:.2f} million instructions")
    print(
        f"Saved {len(all_summaries)} runs and {len(all_tasks)} task records to {output.resolve()}"
    )


if __name__ == "__main__":
    main()
