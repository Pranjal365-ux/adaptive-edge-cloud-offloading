import unittest

from offloading import Scenario, Simulation, Task


class IntegrityTests(unittest.TestCase):
    def test_p95_nearest_rank_small_sample(self):
        tasks = [Task(i, i * 5, 100 + i, 0.01, 0.01) for i in range(21)]
        rows, summary = Simulation(Scenario("test", 1, 80, 20), tasks, "edge_only", 100).run()
        values = sorted(r["completion_s"] for r in rows)
        self.assertEqual(summary["p95_completion_s"], values[19])

    def test_queued_transfer_uses_start_time_bandwidth(self):
        s = Scenario("vary", 1, 8, 0, variable_network=True)
        sim = Simulation(s, [], "cloud_only", 1)
        sim.now = 29
        sim.request("upload", 2, "uploaded", Task(0, 29, 0, 2, 0))
        sim.request("upload", 1, "uploaded", Task(1, 29, 0, 1, 0))
        sim.now = 31
        sim.resources["upload"].active.clear()
        sim.start("upload", sim.resources["upload"].queue.pop())
        self.assertEqual(list(sim.resources["upload"].active.values()), [36])


if __name__ == "__main__":
    unittest.main()
