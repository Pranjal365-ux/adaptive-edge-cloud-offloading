"""Small behavioral checks for the simulator. Run: python -m unittest -v."""
import unittest
from dataclasses import replace

from offloading import Scenario, Simulation, Task, generate_tasks, tune_threshold


class OffloadingTests(unittest.TestCase):
    def setUp(self):
        self.scenario = Scenario("test", 2, 40, 50)
        self.tasks = generate_tasks(42, 80, 2)

    def test_same_trace_is_reproducible(self):
        self.assertEqual(self.tasks, generate_tasks(42, 80, 2))
        first = Simulation(self.scenario, self.tasks, "adaptive", 300).run()
        second = Simulation(self.scenario, self.tasks, "adaptive", 300).run()
        self.assertEqual(first, second)

    def test_every_task_completes_once_and_baselines_choose_correctly(self):
        for policy, expected in (("edge_only", "edge"), ("cloud_only", "cloud")):
            rows, summary = Simulation(self.scenario, self.tasks, policy, 300).run()
            self.assertEqual(len(rows), len(self.tasks))
            self.assertTrue(all(r["destination"] == expected and
                                r["finish_s"] >= r["arrival_s"] for r in rows))
            self.assertEqual(summary["tasks"], len(self.tasks))
            self.assertLessEqual(summary["edge_utilization"], 1.000001)
            if policy == "edge_only":
                self.assertEqual(summary["network_mb"], 0)
                self.assertEqual(summary["cloud_cost_usd"], 0)

    def test_high_latency_discourages_cloud_in_adaptive_policy(self):
        task = [Task(0, 1.0, 100, 0.2, 0.02)]
        fast = replace(self.scenario, bandwidth_mbps=100, latency_ms=1)
        slow = replace(self.scenario, bandwidth_mbps=1, latency_ms=2000)
        self.assertEqual(Simulation(fast, task, "adaptive", 300).run()[0][0]["destination"], "cloud")
        self.assertEqual(Simulation(slow, task, "adaptive", 300).run()[0][0]["destination"], "edge")

    def test_threshold_tuning_produces_candidate_and_value(self):
        chosen, scores = tune_threshold(30, [1001, 1002])
        self.assertIn(chosen, [s["threshold_mi"] for s in scores])


if __name__ == "__main__":
    unittest.main()
