"""Container cloud worker: authenticated CPU service with health and metrics endpoints."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel, ConfigDict, Field, model_validator

from offloader.tasks import execute

LOG = logging.getLogger("offloadops.cloud")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
if os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(
            connection_string=os.environ["APPLICATIONINSIGHTS_CONNECTION_STRING"]
        )
    except Exception as exc:
        LOG.error("Application Insights configuration failed: %s", type(exc).__name__)
WORKER_ID = hashlib.sha256(f"{os.getenv('HOSTNAME', 'local')}:{os.getpid()}".encode()).hexdigest()[
    :12
]
BUILD_SHA = os.getenv("BUILD_SHA", "development")
API_KEY = os.getenv("CLOUD_API_KEY", "local-demo-key")
TASKS = Counter("cloud_tasks_total", "Cloud tasks", ["outcome"])
INSPECTIONS = Counter("cloud_inspections_total", "Surface inspections by verdict", ["verdict"])
DEFECTS = Counter("cloud_defects_detected_total", "Surface anomalies detected by cloud workers")
COMPLETION = Histogram(
    "cloud_compute_seconds", "Cloud compute time", buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10)
)
ERRORS = Counter("cloud_errors_total", "Cloud service errors", ["kind"])
ACTIVE_WORKERS = Gauge("cloud_active_workers", "Cloud worker processes currently executing jobs")
UTILIZATION = Gauge(
    "cloud_worker_utilization_ratio", "Rolling cloud worker slot utilization over 10 seconds"
)
WORKER_CAPACITY = max(1, int(os.getenv("CLOUD_WORKERS", "2")))
_first_lock = threading.Lock()
_first_request = True
_utilization_lock = threading.Lock()
_recent_compute: deque[tuple[float, float]] = deque(maxlen=2000)


class ComputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    task_type: Literal["surface_defect_inspection"] = "surface_defect_inspection"
    image_base64: str | None = Field(default=None, max_length=4_000_000)
    image_width: int | None = Field(default=None, ge=64, le=2048)
    image_height: int | None = Field(default=None, ge=64, le=2048)
    sensitivity: Literal["low", "normal", "high"] = "normal"

    @model_validator(mode="after")
    def validate_task(self):
        if not self.image_base64 or self.image_width is None or self.image_height is None:
            raise ValueError(
                "image_base64, image_width, and image_height are required for inspection"
            )
        if self.image_width * self.image_height > 2_400_000:
            raise ValueError("image is too large")
        return self


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = ProcessPoolExecutor(max_workers=WORKER_CAPACITY)
    app.state.semaphore = asyncio.Semaphore(WORKER_CAPACITY)
    app.state.active_started = {}
    yield
    app.state.pool.shutdown(wait=True, cancel_futures=True)


app = FastAPI(title="OffloadOps Cloud Worker", version=BUILD_SHA, lifespan=lifespan)


@app.middleware("http")
async def correlation_and_access_log(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))[:128]
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    LOG.info(
        json.dumps(
            {
                "event": "http_request",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            }
        )
    )
    return response


def require_key(value: str | None) -> None:
    if not value or not secrets.compare_digest(value, API_KEY):
        raise HTTPException(status_code=401, detail="invalid API key")


def worker_load(now: float | None = None) -> dict:
    """Return measured worker-slot occupancy over a rolling ten-second window."""
    now = time.monotonic() if now is None else now
    cutoff = now - 10.0
    with _utilization_lock:
        while _recent_compute and _recent_compute[0][0] < cutoff:
            _recent_compute.popleft()
        completed_busy = sum(seconds for _, seconds in _recent_compute)
    active = (
        tuple(app.state.active_started.values()) if hasattr(app.state, "active_started") else ()
    )
    active_busy = sum(max(0.0, now - max(started, cutoff)) for started in active)
    utilization = min(1.0, (completed_busy + active_busy) / (WORKER_CAPACITY * 10.0))
    UTILIZATION.set(utilization)
    return {
        "worker_slots": WORKER_CAPACITY,
        "active_workers": len(active),
        "utilization_pct": round(utilization * 100, 2),
        "window_seconds": 10,
        "replica": WORKER_ID,
    }


@app.get("/health")
def health():
    return {"status": "ok", "replica": WORKER_ID}


@app.get("/ready")
def ready():
    return {"status": "ready", "build_sha": BUILD_SHA}


@app.get("/version")
def version():
    return {"service": "cloud-worker", "build_sha": BUILD_SHA, "replica": WORKER_ID}


@app.get("/telemetry")
def telemetry(x_api_key: str | None = Header(default=None)):
    require_key(x_api_key)
    return worker_load()


@app.post("/probe")
def probe(byte_count: int = 4096, x_api_key: str | None = Header(default=None)):
    require_key(x_api_key)
    if not 1 <= byte_count <= 262_144:
        raise HTTPException(status_code=422, detail="byte_count must be between 1 and 262144")
    return Response(content=b"x" * byte_count, media_type="application/octet-stream")


@app.post("/compute")
async def compute_task(
    payload: ComputeRequest, request: Request, x_api_key: str | None = Header(default=None)
):
    global _first_request
    require_key(x_api_key)
    try:
        async with request.app.state.semaphore:
            token = uuid.uuid4().hex
            started = time.monotonic()
            request.app.state.active_started[token] = started
            ACTIVE_WORKERS.inc()
            try:
                result = await asyncio.get_running_loop().run_in_executor(
                    request.app.state.pool, execute, payload.model_dump()
                )
            finally:
                elapsed = time.monotonic() - started
                request.app.state.active_started.pop(token, None)
                ACTIVE_WORKERS.dec()
                with _utilization_lock:
                    _recent_compute.append((time.monotonic(), elapsed))
                worker_load()
        with _first_lock:
            cold_start = _first_request
            _first_request = False
        result.update(
            {
                "replica": WORKER_ID,
                "build_sha": BUILD_SHA,
                "cold_start": cold_start,
                "cold_start_signal": (
                    "first successful task handled by this worker process; "
                    "not platform launch time"
                ),
                "request_id": request.headers.get("x-request-id", ""),
            }
        )
        TASKS.labels(outcome="success").inc()
        if result.get("verdict"):
            INSPECTIONS.labels(verdict=result["verdict"]).inc()
            DEFECTS.inc(result.get("defect_count", 0))
        COMPLETION.observe(elapsed)
        return result
    except ValueError as exc:
        ERRORS.labels(kind="validation").inc()
        TASKS.labels(outcome="rejected").inc()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.middleware("http")
async def request_size_limit(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > 4_500_000:
        return Response(status_code=413, content="request too large")
    return await call_next(request)


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
