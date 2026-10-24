import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from experiments.live_experiment import trace, execute, choose, compute, calibrate
import tempfile

class LiveTests(unittest.TestCase):
    def test_trace_pairing(self):
        self.assertEqual(trace(3001, 20, 100), trace(3001, 20, 100))
        self.assertNotEqual(trace(3001, 20, 100), trace(3002, 20, 100))

    def test_only_one_compute_during_execution(self):
        job = {'task': 0, 'arrival_s': 0, 'iterations': 10, 'data': 'abc'}
        job['expected_digest'] = compute(job)['digest']
        with patch('experiments.live_experiment.compute', wraps=compute) as fn:
            row = execute(job, 'edge', '', '', 0)
        self.assertEqual(fn.call_count, 1)
        self.assertTrue(row['digest_match'])

    def test_remote_failure_retained_without_secret(self):
        job = {'task': 0, 'arrival_s': 0, 'iterations': 10, 'data': 'abc', 'expected_digest': ''}
        with patch('experiments.live_experiment.cloud_compute', side_effect=RuntimeError('SECRET')):
            row = execute(job, 'cloud', '', '', 0)
        self.assertEqual(row['error'], 'RuntimeError')
        self.assertNotIn('SECRET', json.dumps(row))

    def test_threshold_boundary_and_adaptive(self):
        m = {'fixed_threshold_iterations': 100, 'edge_ms_per_iteration': 1,
             'cloud_ms_per_iteration': .1, 'cloud_overhead_ms': 50}
        pending = {'edge': [], 'cloud': []}
        self.assertEqual(choose('fixed', {'iterations':100}, m, pending, 1, 4), 'edge')
        self.assertEqual(choose('fixed', {'iterations':101}, m, pending, 1, 4), 'cloud')
        self.assertEqual(choose('adaptive', {'iterations':10}, m, pending, 1, 4), 'edge')
        self.assertEqual(choose('adaptive', {'iterations':100}, m, pending, 1, 4), 'cloud')

    def test_calibration_retains_failed_attempt(self):
        from experiments.live_experiment import cloud_compute
        calls = [0]
        def remote(url, key, payload):
            calls[0] += 1
            if calls[0] == 1:
                raise TimeoutError('secret')
            return {'digest': 'reference', 'compute_ms': 1}
        with tempfile.TemporaryDirectory() as folder:
            with patch('experiments.live_experiment.cloud_compute', side_effect=remote), patch('experiments.live_experiment.compute', return_value={'digest':'reference'}), patch('experiments.live_experiment.time.sleep'):
                result=calibrate('', '', Path(folder))
            self.assertEqual(result['development_observations'], 24)
            self.assertEqual(result['calibration_failed_attempts'], 1)
            log=(Path(folder)/'calibration-errors.csv').read_text()
            self.assertIn('TimeoutError',log)
            self.assertNotIn('secret',log)

    def test_function_returns_400_for_nonobject(self):
        import azure.functions as func
        sys.path.insert(0, str(Path('azure_function').resolve()))
        import function_app
        response = function_app.compute_task(func.HttpRequest(method='POST', url='https://localhost/compute', body=b'[]'))
        self.assertEqual(response.status_code, 400)

if __name__ == '__main__':
    unittest.main()
