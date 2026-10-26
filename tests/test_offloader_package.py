import base64
import io
import json
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from offloader.costs import CostModel
from offloader.inspection import inspect_surface
from offloader.tasks import execute
from services import cloud_worker, edge_gateway


def image_job():
    image = Image.new("RGB", (160, 120), (185, 190, 195))
    draw = ImageDraw.Draw(image)
    draw.line((18, 42, 144, 76), fill=(10, 12, 14), width=2)
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=90)
    return {
        "task_id": "JOB-TEST-001",
        "task_type": "surface_defect_inspection",
        "source": "test-camera",
        "priority": "normal",
        "workload_profile": "balanced",
        "record_count": 1,
        "image_base64": base64.b64encode(output.getvalue()).decode("ascii"),
        "image_width": 160,
        "image_height": 120,
        "sensitivity": "normal",
    }


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


class DeliverableTests(unittest.TestCase):
    def test_toxiproxy_startup_config_uses_documented_array_shape(self):
        config = json.loads(Path("toxiproxy/config.json").read_text(encoding="utf-8"))
        self.assertIsInstance(config, list)
        self.assertEqual(config[0]["name"], "cloud")
        self.assertEqual(config[0]["listen"], "0.0.0.0:8666")

    def test_cost_model_validates_and_accounts_components(self):
        costs = CostModel(0.1, 0.02, 0.5)
        self.assertAlmostEqual(costs.estimate(2, 1000), 0.72)
        with self.assertRaises(ValueError):
            costs.estimate(-1, 0)

    def test_inspection_returns_review_and_annotated_image_for_scratch(self):
        result = inspect_surface(image_job())
        self.assertEqual(result["verdict"], "REVIEW")
        self.assertGreater(result["defect_count"], 0)
        self.assertTrue(result["annotated_image_base64"])

    def test_inspection_rejects_missing_or_malformed_image(self):
        with self.assertRaisesRegex(ValueError, "image_base64 is required"):
            inspect_surface({})
        with self.assertRaisesRegex(ValueError, "valid base64"):
            inspect_surface({**image_job(), "image_base64": "not-base64!"})

    def test_inspection_rejects_bad_dimensions_and_sensitivity(self):
        job = image_job()
        with self.assertRaisesRegex(ValueError, "sensitivity"):
            inspect_surface({**job, "sensitivity": "extreme"})
        with self.assertRaisesRegex(ValueError, "dimensions"):
            inspect_surface({**job, "image_width": 159})

    def test_worker_utilization_uses_busy_time_over_capacity_window(self):
        history = deque([(99.0, 2.0)])
        self.assertAlmostEqual(edge_gateway.worker_utilization(history, (), 2, now=100.0), 0.1)
        self.assertEqual(edge_gateway.worker_utilization(history, (), 0, now=100.0), 0.2)

    def test_status_exposes_live_worker_graph_and_throughput_fields(self):
        old_url = edge_gateway.CLOUD_URL
        old_policy = edge_gateway.POLICY
        edge_gateway.CLOUD_URL = "http://127.0.0.1:1"
        edge_gateway.POLICY = "edge_only"
        previous_completions = list(edge_gateway._recent_completions)
        edge_gateway._recent_completions.clear()
        try:
            with TestClient(edge_gateway.app) as client:
                status = client.get("/status").json()
            self.assertIn("edge", status["worker_utilization"])
            self.assertIn("cloud", status["worker_utilization"])
            self.assertEqual(status["throughput_per_minute"]["total"], 0)
            self.assertFalse(status["scenario_controls_enabled"])
        finally:
            edge_gateway._recent_completions.clear()
            edge_gateway._recent_completions.extend(previous_completions)
            edge_gateway.CLOUD_URL = old_url
            edge_gateway.POLICY = old_policy

    def test_edge_task_and_same_image_comparison_return_real_worker_results(self):
        old_url = edge_gateway.CLOUD_URL
        old_policy = edge_gateway.POLICY
        edge_gateway.CLOUD_URL = "http://127.0.0.1:1"
        edge_gateway.POLICY = "edge_only"
        try:
            with TestClient(edge_gateway.app) as client:
                single = client.post("/tasks", json=image_job())
                self.assertEqual(single.status_code, 200, single.text)
                self.assertEqual(single.json()["destination"], "edge")

            edge_result = execute(image_job())

            async def fake_post(url, **kwargs):
                self.assertTrue(url.endswith("/compute"))
                return FakeResponse(edge_result)

            with TestClient(edge_gateway.app) as client:
                with patch.object(
                    edge_gateway.app.state, "client", wraps=edge_gateway.app.state.client
                ):
                    edge_gateway.app.state.client.post = fake_post
                    comparison = client.post("/compare", json=image_job())
                self.assertEqual(comparison.status_code, 200, comparison.text)
                body = comparison.json()
                self.assertTrue(body["same_input"])
                self.assertEqual(body["mode"], "live_comparison")
                self.assertIn("annotated_image_base64", body["results"]["edge"])
                self.assertIn("annotated_image_base64", body["results"]["cloud"])
        finally:
            edge_gateway.CLOUD_URL = old_url
            edge_gateway.POLICY = old_policy

    def test_cloud_telemetry_requires_the_worker_key(self):
        with TestClient(cloud_worker.app) as client:
            self.assertEqual(client.get("/telemetry").status_code, 401)
            response = client.get("/telemetry", headers={"X-API-Key": cloud_worker.API_KEY})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertGreaterEqual(body["worker_slots"], 1)
        self.assertGreaterEqual(body["utilization_pct"], 0)


if __name__ == "__main__":
    unittest.main()
