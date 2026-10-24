import hashlib
import math
import unittest
from dataclasses import replace
from unittest.mock import patch
from azure_function.workload import compute
from offloading import Simulation, Scenario, Task

class IntegrityTests(unittest.TestCase):
    def test_digest_reference_and_unicode(self):
        data = 'é'
        digest = hashlib.sha256(data.encode()).digest()
        for _ in range(10):
            digest = hashlib.sha256(digest).digest()
        result = compute({'data': data, 'iterations': 10})
        self.assertEqual(result['digest'], digest.hex())
        self.assertEqual(result['input_bytes'], 2)

    def test_bad_payloads(self):
        for payload in (None, [], 'x', {}, {'iterations': True, 'data': ''},
                        {'iterations': 2000001, 'data': ''}):
            with self.assertRaises(ValueError):
                compute(payload)

    def test_p95_nearest_rank_small_sample(self):
        tasks = [Task(i, i * 5, 100 + i, .01, .01) for i in range(21)]
        rows, summary = Simulation(Scenario('test', 1, 80, 20), tasks, 'edge_only', 100).run()
        values = sorted(r['completion_s'] for r in rows)
        self.assertEqual(summary['p95_completion_s'], values[19])

    def test_queued_transfer_uses_start_time_bandwidth(self):
        s = Scenario('vary', 1, 8, 0, variable_network=True)
        sim = Simulation(s, [], 'cloud_only', 1)
        sim.now = 29
        sim.request('upload', 2, 'uploaded', Task(0, 29, 0, 2, 0))
        sim.request('upload', 1, 'uploaded', Task(1, 29, 0, 1, 0))
        sim.now = 31
        sim.resources['upload'].active.clear()
        sim.start('upload', sim.resources['upload'].queue.pop())
        self.assertEqual(list(sim.resources['upload'].active.values()), [36])

if __name__ == '__main__':
    unittest.main()
