"""HTTP smoke checks for the live local stack, including the cloud circuit breaker."""

from __future__ import annotations

import base64
import io
import json
import subprocess
import time
import urllib.error
import urllib.request
import uuid

from PIL import Image, ImageDraw

GATEWAY = "http://127.0.0.1:8000"


def request(path: str, *, method: str = "GET", payload: dict | None = None, timeout: float = 5):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{GATEWAY}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read()
        return response.status, json.loads(body) if body.startswith(b"{") else body


def check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(f"FAIL {message}")
    print(f"PASS {message}")


def inspection_payload(source: str) -> dict:
    """Build a small repeatable scratch-image job for routing smoke checks."""
    image = Image.new("RGB", (640, 480), (184, 190, 196))
    draw = ImageDraw.Draw(image)
    draw.rectangle((105, 90, 530, 390), fill=(205, 210, 214), outline=(90, 98, 105), width=5)
    draw.line((250, 160, 392, 310), fill=(42, 45, 47), width=9)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=88)
    return {
        "task_id": f"smoke-{uuid.uuid4().hex[:12]}",
        "task_type": "surface_defect_inspection",
        "source": source,
        "priority": "normal",
        "workload_profile": "standard",
        "record_count": 1,
        "image_base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
        "image_width": image.width,
        "image_height": image.height,
        "sensitivity": "normal",
    }


def main() -> int:
    check(request("/healthz")[0] == 200, "gateway health")
    check(request("/readyz")[0] == 200, "gateway readiness")
    status, console = request("/console")
    check(status == 200 and b"OffloadOps" in console, "offline console asset")
    check(request("/version")[1]["build_sha"], "build metadata")
    original = request("/policy")[1]["policy"]
    try:
        request("/policy", method="PUT", payload={"policy": "edge_only"})
        _, edge = request("/tasks", method="POST", payload=inspection_payload("edge-smoke"))
        check(edge["destination"] == "edge", "policy hot-swap to edge")
        request("/policy", method="PUT", payload={"policy": "cloud_only"})
        _, cloud = request("/tasks", method="POST", payload=inspection_payload("cloud-smoke"))
        check(cloud["destination"] == "cloud", "policy hot-swap to cloud")
        _, metrics = request("/metrics")
        check(
            b"edge_decisions_total" in metrics and b"edge_completion_seconds" in metrics,
            "Prometheus metrics endpoint",
        )
        _, scenario = request("/scenario", method="PUT", payload={"name": "poor"})
        check(scenario["applied"], "Toxiproxy poor-network scenario applied")
        before = request("/status")[1]["rtt_ms"]
        deadline = time.monotonic() + 20
        changed = False
        while time.monotonic() < deadline:
            time.sleep(1)
            if request("/status")[1]["rtt_ms"] > before + 50:
                changed = True
                break
        check(changed, "poor scenario measurably changes the cloud probe estimate")
        request("/scenario", method="PUT", payload={"name": "good"})

        stop = subprocess.run(
            ["docker", "compose", "stop", "cloud"], capture_output=True, text=True
        )
        check(stop.returncode == 0, "stop cloud container for fallback test")
        try:
            for _ in range(3):
                _, fallback = request(
                    "/tasks", method="POST", payload=inspection_payload("fallback-smoke")
                )
                check(
                    fallback["destination"] == "edge" and fallback["fallback"],
                    "cloud failure falls back to local edge execution",
                )
            check(
                request("/status")[1]["circuit_open"], "cloud circuit breaker opens after failures"
            )
        finally:
            subprocess.run(
                ["docker", "compose", "start", "cloud"], check=False, capture_output=True, text=True
            )
            request("/scenario", method="PUT", payload={"name": "good"})
            time.sleep(2)
    finally:
        request("/policy", method="PUT", payload={"policy": original})
    print("Live stack smoke checks completed. No Azure resources were changed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc
