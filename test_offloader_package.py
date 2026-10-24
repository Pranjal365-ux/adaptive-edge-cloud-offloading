import json
import unittest
from pathlib import Path
from unittest.mock import patch

from offloader.costs import CostModel
from offloader.policies import AdaptiveOracle, DecisionContext, EdgeOnly, CloudOnly, Threshold
from offloader.stats import bootstrap_mean_ci, mean_std, nearest_rank, paired_mean_ci
from offloader.workload import compute as shared_compute
from offloading import Scenario, Simulation, Task


def context(**changes):
    values = dict(work_mi=100, input_mb=0.1, output_mb=0.01,
        edge_service_seconds=1, cloud_service_seconds=0.1, upload_seconds=0.01,
        download_seconds=0.001, one_way_latency_seconds=0.01,
        edge_wait_seconds=0, cloud_wait_seconds=0, upload_wait_seconds=0,
        download_wait_seconds=0, cloud_cost_usd=0.0001,
        cost_weight_seconds_per_usd=100)
    values.update(changes)
    return DecisionContext(**values)


class PackageTests(unittest.TestCase):
    def test_toxiproxy_startup_config_uses_documented_array_shape(self):
        config = json.loads(Path("toxiproxy/config.json").read_text(encoding="utf-8"))
        self.assertIsInstance(config, list)
        self.assertEqual(config[0]["name"], "cloud")
        self.assertEqual(config[0]["listen"], "0.0.0.0:8666")

    def test_nearest_rank_and_seeded_bootstrap(self):
        values = list(range(1, 22))
        self.assertEqual(nearest_rank(values, .95), 20)
        self.assertEqual(bootstrap_mean_ci(values, seed=7, resamples=500),
                         bootstrap_mean_ci(values, seed=7, resamples=500))
        self.assertEqual(mean_std([4]), (4, 0))

    def test_paired_ci_retains_pairing_and_direction(self):
        mean, low, high = paired_mean_ci([3, 4, 5], [1, 2, 3], seed=5, resamples=500)
        self.assertEqual(mean, 2)
        self.assertEqual((low, high), (2, 2))

    def test_policy_behavior_and_cost_tradeoff(self):
        self.assertEqual(EdgeOnly().choose(context()), "edge")
        self.assertEqual(CloudOnly().choose(context()), "cloud")
        self.assertEqual(Threshold(100).choose(context()), "edge")
        self.assertEqual(Threshold(99).choose(context()), "cloud")
        self.assertEqual(AdaptiveOracle().choose(context()), "cloud")
        self.assertEqual(AdaptiveOracle().choose(context(
            one_way_latency_seconds=3, cloud_cost_usd=1)), "edge")

    def test_cost_model_validates_and_accounts_components(self):
        costs = CostModel(.1, .02, .5)
        self.assertAlmostEqual(costs.estimate(2, 1000), .72)
        with self.assertRaises(ValueError):
            costs.estimate(-1, 0)

    def test_random_walk_is_seeded_and_changes_over_time(self):
        scenario = Scenario("walk", 1, 40, 60, random_walk_network=True)
        task = [Task(0, 30, 1, .1, .01)]
        first = Simulation(scenario, task, "edge_only", 100, network_seed=19)
        second = Simulation(scenario, task, "edge_only", 100, network_seed=19)
        at_start = first.network_at(0)
        at_end = first.network_at(30)
        self.assertEqual(at_end, second.network_at(30))
        self.assertNotEqual(at_start, at_end)

    def test_shared_workload_matches_legacy_azure_function(self):
        from azure_function.workload import compute as legacy_compute

        payload = {"iterations": 12, "data": "same task λ"}
        self.assertEqual(shared_compute(payload)["digest"], legacy_compute(payload)["digest"])

    def test_observed_adaptive_ignores_unmeasured_current_link(self):
        task = [Task(0, 0, 1500, .01, .01)]
        scenario = Scenario("changing", 1, 80, 10)
        sim = Simulation(scenario, task, "adaptive", 0)
        sim.measured_rtt_ms = 10_000
        sim.measured_bandwidth_mbps = 1
        # The current true link is fast. The policy must continue using its probe EWMA.
        with patch.object(sim, "network_at", return_value=(1000, 1)):
            self.assertEqual(sim.choose(task[0]), "edge")
        sim.policy = "adaptive_oracle"
        with patch.object(sim, "network_at", return_value=(1000, 1)):
            self.assertEqual(sim.choose(task[0]), "cloud")


if __name__ == "__main__":
    unittest.main()
