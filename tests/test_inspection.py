import base64
import hashlib
import io
import unittest

from PIL import Image, ImageDraw

from offloader.inspection import inspect_surface
from offloader.tasks import execute
from offloader.workload import compute


def image_payload(image: Image.Image, sensitivity: str = "normal") -> dict:
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return {
        "image_base64": base64.b64encode(stream.getvalue()).decode("ascii"),
        "image_width": image.width,
        "image_height": image.height,
        "sensitivity": sensitivity,
    }


class InspectionTests(unittest.TestCase):
    def test_flat_surface_passes_and_returns_jpeg_annotation(self):
        result = inspect_surface(image_payload(Image.new("RGB", (64, 64), "gray")))

        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["defect_count"], 0)
        self.assertEqual(result["pixels_processed"], 64 * 64)
        annotated = Image.open(io.BytesIO(base64.b64decode(result["annotated_image_base64"])))
        self.assertEqual(annotated.format, "JPEG")

    def test_contrasting_scratch_is_grouped_and_bounded(self):
        image = Image.new("RGB", (128, 128), (120, 120, 120))
        ImageDraw.Draw(image).line((20, 64, 105, 64), fill=(0, 0, 0), width=2)

        result = inspect_surface(image_payload(image))

        self.assertEqual(result["verdict"], "REVIEW")
        self.assertEqual(result["defect_count"], 1)
        self.assertGreaterEqual(result["defects"][0]["area_pixels"], 12)
        self.assertGreater(result["defects"][0]["width"], result["defects"][0]["height"])

    def test_sensitivity_controls_subtle_contrast(self):
        image = Image.new("RGB", (128, 128), (100, 100, 100))
        ImageDraw.Draw(image).line((20, 64, 105, 64), fill=(65, 65, 65), width=2)
        payload = image_payload(image)

        high = inspect_surface({**payload, "sensitivity": "high"})
        normal = inspect_surface({**payload, "sensitivity": "normal"})

        self.assertEqual(high["verdict"], "REVIEW")
        self.assertEqual(normal["verdict"], "PASS")
        self.assertEqual(high["contrast_threshold"], 30)
        self.assertEqual(normal["contrast_threshold"], 48)

    def test_tiny_anomaly_below_minimum_area_is_ignored(self):
        image = Image.new("RGB", (64, 64), (100, 100, 100))
        ImageDraw.Draw(image).line((20, 32, 24, 32), fill=(0, 0, 0), width=1)

        result = inspect_surface(image_payload(image))

        self.assertEqual(result["verdict"], "PASS")

    def test_rejects_missing_image_and_unknown_sensitivity(self):
        with self.assertRaisesRegex(ValueError, "image_base64 is required"):
            inspect_surface({})
        with self.assertRaisesRegex(ValueError, "sensitivity must be"):
            inspect_surface({"image_base64": "YQ==", "sensitivity": "extreme"})

    def test_rejects_oversized_base64_and_invalid_encoding(self):
        with self.assertRaisesRegex(ValueError, "image is too large"):
            inspect_surface({"image_base64": "A" * (4_000_000 + 17)})
        with self.assertRaisesRegex(ValueError, "valid base64"):
            inspect_surface({"image_base64": "%%%not-base64%%%"})

    def test_rejects_mismatched_or_too_small_dimensions(self):
        payload = image_payload(Image.new("RGB", (64, 64), "white"))
        with self.assertRaisesRegex(ValueError, "dimensions do not match"):
            inspect_surface({**payload, "image_width": 65})
        with self.assertRaisesRegex(ValueError, "at least 64"):
            inspect_surface(image_payload(Image.new("RGB", (32, 64), "white")))

    def test_rejects_oversized_pixels_and_unsupported_format(self):
        large = image_payload(Image.new("RGB", (1600, 1600), "white"))
        with self.assertRaisesRegex(ValueError, "image is too large"):
            inspect_surface(large)

        stream = io.BytesIO()
        Image.new("RGB", (64, 64), "white").save(stream, format="GIF")
        gif_payload = {
            "image_base64": base64.b64encode(stream.getvalue()).decode("ascii"),
            "image_width": 64,
            "image_height": 64,
        }
        with self.assertRaisesRegex(ValueError, "supported image formats"):
            inspect_surface(gif_payload)

    def test_rejects_corrupt_image_bytes(self):
        payload = {
            "image_base64": base64.b64encode(b"not an image").decode("ascii"),
            "image_width": 64,
            "image_height": 64,
        }
        with self.assertRaisesRegex(ValueError, "could not be decoded safely"):
            inspect_surface(payload)


class TaskAndWorkloadTests(unittest.TestCase):
    def test_task_dispatch_runs_surface_inspection(self):
        result = execute(
            {
                "task_type": "surface_defect_inspection",
                **image_payload(Image.new("RGB", (64, 64), "white")),
            }
        )
        self.assertEqual(result["task_type"], "surface_defect_inspection")
        self.assertEqual(result["verdict"], "PASS")

    def test_task_dispatch_rejects_unknown_task_type(self):
        with self.assertRaisesRegex(ValueError, "task_type must be"):
            execute({"task_type": "unknown"})

    def test_workload_digest_is_deterministic(self):
        payload = {"iterations": 4, "data": "edge-cloud"}
        result = compute(payload)
        digest = hashlib.sha256(payload["data"].encode()).digest()
        for _ in range(payload["iterations"]):
            digest = hashlib.sha256(digest).digest()

        self.assertEqual(result["digest"], digest.hex())
        self.assertEqual(result["iterations"], 4)
        self.assertEqual(result["input_bytes"], len(payload["data"]))

    def test_workload_rejects_invalid_payload_iterations_and_data(self):
        with self.assertRaisesRegex(ValueError, "payload must be"):
            compute([])
        for iterations in (True, 0, 2_000_001, "2"):
            with (
                self.subTest(iterations=iterations),
                self.assertRaisesRegex(ValueError, "iterations"),
            ):
                compute({"iterations": iterations, "data": "x"})
        with self.assertRaisesRegex(ValueError, "data must be"):
            compute({"iterations": 1, "data": 1})
        with self.assertRaisesRegex(ValueError, "data must be"):
            compute({"iterations": 1, "data": "x" * 200_001})


if __name__ == "__main__":
    unittest.main()
