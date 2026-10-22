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
from dataclasses import dataclass, asdict
from pathlib import Path
from statistics import mean
from .costs import CostModel
from .policies import AdaptiveObserved, AdaptiveOracle, CloudOnly, DecisionContext, EdgeOnly, Threshold
from .stats import bootstrap_mean_ci, mean_std, nearest_rank, paired_mean_ci


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
    random_walk_network: bool = False
    cloud_usd_per_request: float = 0.0
    cloud_egress_usd_per_gb: float = 0.0

    def network_at(self, time: float) -> tuple[float, float]:
        if self.variable_network and int(time // 30) % 2 == 1:
            return self.bandwidth_mbps / 5, self.latency_ms * 3
        return self.bandwidth_mbps, self.latency_ms


SCENARIOS = [
    Scenario("stable_light", 0.8, 80, 20),
    Scenario("light_good", 1.2, 80, 20),
    Scenario("stable_moderate", 2.5, 40, 60),
    Scenario("heavy_good", 5.0, 80, 20),
    Scenario("light_poor", 1.2, 8, 150),
    Scenario("heavy_poor", 5.0, 8, 150),
    Scenario("variable_network", 3.5, 60, 35, variable_network=True),
    Scenario("random_walk_bandwidth", 3.5, 40, 60, random_walk_network=True),
]
POLICIES = ("edge_only", "cloud_only", "threshold", "adaptive", "adaptive_oracle")


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
    def __init__(self, scenario: Scenario, tasks: list[Task], policy: str, threshold_mi: float,
                 network_seed: int = 0):
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
        self.network_rng = random.Random(network_seed)
        self.network_tick = -1
        self.last_probe_tick = -1
        self.walk_bandwidth = scenario.bandwidth_mbps
        self.walk_latency = scenario.latency_ms
        self.network_step_seconds = 5.0
        self.measured_bandwidth_mbps = scenario.bandwidth_mbps
        self.measured_rtt_ms = scenario.latency_ms
        self.edge_ms_per_mi = 1000.0 / scenario.edge_mips
        self.cloud_ms_per_mi = 1000.0 / scenario.cloud_mips
        self.service_started: dict[int, float] = {}
        for task in tasks:
            self.schedule(task.arrival, "arrival", task)

    def schedule(self, when: float, kind: str, data: object) -> None:
        self.serial += 1
        heapq.heappush(self.events, (when, self.serial, kind, data))

    def transfer_seconds(self, mb: float, now: float) -> float:
        bandwidth, _ = self.network_at(now)
        return 8.0 * mb / bandwidth

    def _actual_network_at(self, now: float) -> tuple[float, float]:
        if not self.scenario.random_walk_network:
            return self.scenario.network_at(now)
        tick = max(0, int(now // self.network_step_seconds))
        while self.network_tick < tick:
            self.network_tick += 1
            self.walk_bandwidth = min(100.0, max(1.0,
                self.walk_bandwidth * (1.0 + self.network_rng.uniform(-0.25, 0.25))))
            target_latency = self.scenario.latency_ms * (self.scenario.bandwidth_mbps / self.walk_bandwidth) ** 0.35
            self.walk_latency = min(500.0, max(5.0,
                0.7 * self.walk_latency + 0.3 * target_latency + self.network_rng.uniform(-5.0, 5.0)))
        return self.walk_bandwidth, self.walk_latency

    def network_at(self, now: float) -> tuple[float, float]:
        probe_tick = max(0, int(now // self.network_step_seconds))
        while self.last_probe_tick < probe_tick:
            self.last_probe_tick += 1
            bandwidth, latency = self._actual_network_at(self.last_probe_tick * self.network_step_seconds)
            self.measured_bandwidth_mbps = .8 * self.measured_bandwidth_mbps + .2 * bandwidth
            self.measured_rtt_ms = .8 * self.measured_rtt_ms + .2 * latency
        return self._actual_network_at(now)

    def choose(self, task: Task) -> str:
        if self.policy == "edge_only":
            return EdgeOnly().choose(self._context(task, observable=True))
        if self.policy == "cloud_only":
            return CloudOnly().choose(self._context(task, observable=True))
        if self.policy == "threshold":
            return Threshold(self.threshold_mi).choose(self._context(task, observable=True))
        if self.policy == "adaptive_oracle":
            return AdaptiveOracle().choose(self._context(task, observable=False))
        return AdaptiveObserved().choose(self._context(task, observable=True))

    def _context(self, task: Task, *, observable: bool) -> DecisionContext:
        s = self.scenario
        actual_bandwidth, actual_latency = self.network_at(self.now)
        if observable:
            bandwidth = max(self.measured_bandwidth_mbps, .01)
            latency_ms = self.measured_rtt_ms
            edge_service = task.work_mi * self.edge_ms_per_mi / 1000
            cloud_service = task.work_mi * self.cloud_ms_per_mi / 1000
            edge_wait = self._observed_wait("edge", self.edge_ms_per_mi * task.work_mi / 1000)
            cloud_wait = self._observed_wait("cloud", self.cloud_ms_per_mi * task.work_mi / 1000)
            upload_wait = self._observed_wait("upload", 8 * task.input_mb / bandwidth)
            download_wait = self._observed_wait("download", 8 * task.output_mb / bandwidth)
            upload_seconds = 8 * task.input_mb / bandwidth
            download_seconds = 8 * task.output_mb / bandwidth
        else:
            bandwidth = actual_bandwidth
            latency_ms = actual_latency
            edge_service = task.work_mi / s.edge_mips
            cloud_service = task.work_mi / s.cloud_mips
            edge_wait = self.resources["edge"].wait_estimate(self.now)
            cloud_wait = self.resources["cloud"].wait_estimate(self.now)
            upload_wait = self.resources["upload"].wait_estimate(self.now)
            download_wait = self.resources["download"].wait_estimate(self.now)
            upload_seconds = self.transfer_seconds(task.input_mb, self.now)
            download_seconds = self.transfer_seconds(task.output_mb, self.now)
        compute_seconds = cloud_service
        cost = CostModel(s.cloud_usd_per_compute_second, s.cloud_usd_per_request,
                         s.cloud_egress_usd_per_gb).estimate(compute_seconds, task.output_mb)
        return DecisionContext(task.work_mi, task.input_mb, task.output_mb,
            edge_service, compute_seconds, upload_seconds, download_seconds,
            latency_ms / 1000, edge_wait, cloud_wait, upload_wait, download_wait,
            cost, s.cost_weight_seconds_per_usd)

    def _observed_wait(self, resource_name: str, expected_service_seconds: float) -> float:
        resource = self.resources[resource_name]
        backlog = len(resource.active) + len(resource.queue)
        return backlog * expected_service_seconds / resource.capacity

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
        # A queued transfer uses the link state when service actually starts.
        if name in ("upload", "download"):
            duration = self.transfer_seconds(task.input_mb if name == "upload" else task.output_mb, self.now)
        resource = self.resources[name]
        finish = self.now + duration
        self.service_started[request_id] = self.now
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
                    "task_id": task.id, "arrival_s": task.arrival,
                    "work_mi": task.work_mi, "input_mb": task.input_mb,
                    "output_mb": task.output_mb, "destination": destination,
                }
                if destination == "edge":
                    self.request("edge", task.work_mi / s.edge_mips, "finished", task)
                else:
                    self.request("upload", self.transfer_seconds(task.input_mb, self.now), "uploaded", task)
            elif kind == "service_done":
                name, request_id, next_stage, task = data
                resource = self.resources[name]
                del resource.active[request_id]
                elapsed = self.now - self.service_started.pop(request_id)
                if name in ("edge", "cloud") and task.work_mi > 0:
                    observed_rate = elapsed * 1000 / task.work_mi
                    old_rate = self.edge_ms_per_mi if name == "edge" else self.cloud_ms_per_mi
                    learned_rate = .8 * old_rate + .2 * observed_rate
                    if name == "edge":
                        self.edge_ms_per_mi = learned_rate
                    else:
                        self.cloud_ms_per_mi = learned_rate
                if resource.queue:
                    self.start(name, resource.queue.pop(0))
                if next_stage == "finished":
                    self.records[task.id]["finish_s"] = self.now
                elif next_stage == "uploaded":
                    _, latency = self.network_at(self.now)
                    self.schedule(self.now + latency / 1000, "cloud_arrival", task)
                elif next_stage == "computed":
                    self.request("download", self.transfer_seconds(task.output_mb, self.now), "downloaded", task)
                elif next_stage == "downloaded":
                    _, latency = self.network_at(self.now)
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
            row["cloud_cost_usd"] = (CostModel(s.cloud_usd_per_compute_second,
                s.cloud_usd_per_request, s.cloud_egress_usd_per_gb).estimate(
                    task.work_mi / s.cloud_mips, task.output_mb)
                if row["destination"] == "cloud" else 0.0)
            row["network_mb"] = (task.input_mb + task.output_mb
                                 if row["destination"] == "cloud" else 0.0)
            rows.append(row)
        durations = sorted(row["completion_s"] for row in rows)
        horizon = max(row["finish_s"] for row in rows) - min(task.arrival for task in self.tasks)
        summary = {
            "scenario": s.name, "policy": self.policy, "tasks": len(rows),
            "mean_completion_s": mean(durations),
            "p95_completion_s": nearest_rank(durations, 0.95),
            "throughput_tasks_per_s": len(rows) / horizon,
            "edge_utilization": self.resources["edge"].busy_seconds / (s.edge_workers * horizon),
            "network_mb": sum(row["network_mb"] for row in rows),
            "cloud_cost_usd": sum(row["cloud_cost_usd"] for row in rows),
            "cloud_task_fraction": sum(row["destination"] == "cloud" for row in rows) / len(rows),
            "makespan_s": horizon,
        }
        return rows, summary


def percentile(values: list[float], fraction: float) -> float:
    return nearest_rank(values, fraction)


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
        scores.append({"threshold_mi": threshold, "development_mean_completion_s": mean(measurements)})
    chosen = min(scores, key=lambda x: (x["development_mean_completion_s"], x["threshold_mi"]))
    return chosen["threshold_mi"], scores


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def aggregate_results(rows: list[dict], resamples: int, *, task_count: int,
                      seeds: list[int], threshold: float) -> tuple[list[dict], list[dict], list[dict]]:
    """Create seed-level intervals, matched-policy deltas and cost sensitivity."""
    by_scenario_policy: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        by_scenario_policy.setdefault((row["scenario"], row["policy"]), []).append(row)
    metrics = ("mean_completion_s", "p95_completion_s", "throughput_tasks_per_s",
               "edge_utilization", "network_mb", "cloud_cost_usd")
    aggregate = []
    for (scenario, policy), runs in sorted(by_scenario_policy.items()):
        output = {"scenario": scenario, "policy": policy, "seeds": len(runs)}
        for metric in metrics:
            values = [float(row[metric]) for row in runs]
            metric_mean, metric_std = mean_std(values)
            low, high = bootstrap_mean_ci(values,
                seed=sum(map(ord, scenario + policy + metric)), resamples=resamples)
            output.update({f"{metric}_mean": metric_mean, f"{metric}_std": metric_std,
                           f"{metric}_ci95_low": low, f"{metric}_ci95_high": high})
        aggregate.append(output)
    paired = []
    for scenario in SCENARIOS:
        policy_runs = {policy: {row["seed"]: row for row in runs}
            for (name, policy), runs in by_scenario_policy.items() if name == scenario.name}
        for baseline in ("edge_only", "cloud_only", "threshold"):
            common = sorted(set(policy_runs.get("adaptive", {})) & set(policy_runs.get(baseline, {})))
            if not common:
                continue
            output = {"scenario": scenario.name, "comparison": f"adaptive - {baseline}",
                      "seeds": len(common)}
            for metric in metrics:
                delta, low, high = paired_mean_ci(
                    [float(policy_runs["adaptive"][seed][metric]) for seed in common],
                    [float(policy_runs[baseline][seed][metric]) for seed in common],
                    seed=sum(map(ord, scenario.name + baseline + metric)), resamples=resamples)
                output.update({f"{metric}_delta_mean": delta,
                    f"{metric}_delta_ci95_low": low, f"{metric}_delta_ci95_high": high})
            paired.append(output)
    cost_sweep = []
    for weight in (0.0, 100.0, 1_000.0, 10_000.0):
        for scenario in SCENARIOS:
            weighted = Scenario(**{**asdict(scenario), "cost_weight_seconds_per_usd": weight})
            for seed in seeds:
                trace = generate_tasks(seed, task_count, weighted.arrival_rate)
                _, summary = Simulation(weighted, trace, "adaptive", threshold,
                                        network_seed=seed).run()
                cost_sweep.append({"cost_weight_seconds_per_usd": weight,
                                   "seed": seed, **summary})
    return aggregate, paired, cost_sweep


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="results", help="Output directory")
    parser.add_argument("--tasks", type=int, default=300, help="Tasks per scenario and seed")
    parser.add_argument("--seeds", type=int, default=20, help="Final repetitions")
    parser.add_argument("--bootstrap-resamples", type=int, default=2000,
                        help="Seeded paired bootstrap draws for aggregate confidence intervals")
    args = parser.parse_args()
    if args.tasks < 20 or args.seeds < 1 or args.bootstrap_resamples < 1:
        parser.error("Use at least 20 tasks, one seed and one bootstrap resample")
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
                rows, summary = Simulation(scenario, trace, policy, threshold,
                                           network_seed=seed).run()
                summary["seed"] = seed
                all_summaries.append(summary)
                for row in rows:
                    all_tasks.append({"scenario": scenario.name, "seed": seed, "policy": policy, **row})
    write_csv(output / "summary.csv", all_summaries)
    write_csv(output / "tasks.csv", all_tasks)
    aggregate, paired, cost_sweep = aggregate_results(all_summaries,
        args.bootstrap_resamples, task_count=args.tasks, seeds=final_seeds, threshold=threshold)
    write_csv(output / "aggregate.csv", aggregate)
    write_csv(output / "paired.csv", paired)
    write_csv(output / "cost_sweep.csv", cost_sweep)
    metadata = {
        "model": "FIFO discrete event simulator; separate upload/download links; two one-way latency delays",
        "scenarios": [asdict(s) for s in SCENARIOS],
        "development_seeds": development_seeds, "final_seeds": final_seeds,
        "tasks_per_scenario_seed": args.tasks,
        "threshold_selection": "minimum mean completion time on separate development runs",
        "threshold_candidates": tuning, "selected_threshold_mi": threshold,
        "adaptive_rule": "simulator-only oracle: predicted cloud completion + cost weight times estimated cloud cost < predicted edge completion",
        "network_models": "constant, periodic good/poor, and seeded bounded random walk at five-second ticks",
        "cost_model": "synthetic CPU-second, request and egress inputs; not an Azure invoice estimate; verify against current pricing",
        "confidence_intervals": "seeded percentile bootstrap of run means; paired.csv preserves matched seeds",
        "bootstrap_resamples": args.bootstrap_resamples,
        "units": {"work": "million instructions", "processing_rate": "million instructions per second",
                  "input_output": "MB (decimal)", "bandwidth": "megabits per second", "time": "seconds"},
    }
    (output / "experiment.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"Selected fixed threshold: {threshold:.2f} million instructions")
    print(f"Saved {len(all_summaries)} runs and {len(all_tasks)} task records to {output}")
    print(f"Also wrote {len(aggregate)} aggregate rows, {len(paired)} paired comparisons and {len(cost_sweep)} cost-sensitivity rows")


if __name__ == "__main__":
    main()
