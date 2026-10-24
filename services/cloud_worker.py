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
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

from offloader.tasks import execute

LOG = logging.getLogger("offloadops.cloud")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
if os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        configure_azure_monitor(connection_string=os.environ["APPLICATIONINSIGHTS_CONNECTION_STRING"])
    except Exception as exc:
        LOG.error("Application Insights configuration failed: %s", type(exc).__name__)
WORKER_ID = hashlib.sha256(f"{os.getenv('HOSTNAME', 'local')}:{os.getpid()}".encode()).hexdigest()[:12]
BUILD_SHA = os.getenv("BUILD_SHA", "development")
API_KEY = os.getenv("CLOUD_API_KEY", "local-demo-key")
CLOUD_WORKERS = max(1, int(os.getenv("CLOUD_WORKERS", "2")))
TASKS = Counter("cloud_tasks_total", "Cloud tasks", ["outcome"])
INSPECTIONS = Counter("cloud_inspections_total", "Surface inspections by verdict", ["verdict"])
DEFECTS = Counter("cloud_defects_detected_total", "Surface anomalies detected by cloud workers")
COMPLETION = Histogram("cloud_compute_seconds", "Cloud compute time", buckets=(.01, .05, .1, .25, .5, 1, 2, 5, 10))
ERRORS = Counter("cloud_errors_total", "Cloud service errors", ["kind"])
WORKERS_IN_USE = Gauge("cloud_worker_slots_in_use", "Cloud inspection worker slots currently processing work")
WORKER_CAPACITY = Gauge("cloud_worker_slots_capacity", "Configured cloud inspection worker slots")
QUEUED_TASKS = Gauge("cloud_queued_tasks", "Cloud inspection tasks waiting for a worker slot")
_first_lock = threading.Lock()
_first_request = True
_active_jobs = 0
_queued_jobs = 0


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
            raise ValueError("image_base64, image_width, and image_height are required for inspection")
        if self.image_width * self.image_height > 2_400_000:
            raise ValueError("image is too large")
        return self


@asynccontextmanager
async def lifespan(app: FastAPI):
    WORKER_CAPACITY.set(CLOUD_WORKERS)
    app.state.pool = ProcessPoolExecutor(max_workers=CLOUD_WORKERS)
    app.state.semaphore = asyncio.Semaphore(CLOUD_WORKERS)
    yield
    app.state.pool.shutdown(wait=True, cancel_futures=True)


app = FastAPI(title="OffloadOps Cloud Worker", version=BUILD_SHA, lifespan=lifespan)


@app.middleware("http")
async def correlation_and_access_log(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))[:128]
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    LOG.info(json.dumps({"event": "http_request", "request_id": request_id,
        "method": request.method, "path": request.url.path, "status": response.status_code,
        "duration_ms": round((time.perf_counter() - started) * 1000, 3)}))
    return response


def require_key(value: str | None) -> None:
    if not value or not secrets.compare_digest(value, API_KEY):
        raise HTTPException(status_code=401, detail="invalid API key")


@app.get("/health")
def health():
    return {"status": "ok", "replica": WORKER_ID}


@app.get("/ready")
def ready():
    return {"status": "ready", "build_sha": BUILD_SHA}


@app.get("/status")
def worker_status(x_api_key: str | None = Header(default=None)):
    require_key(x_api_key)
    in_use = min(_active_jobs, CLOUD_WORKERS)
    return {"available": True, "active_workers": in_use, "queued_tasks": _queued_jobs,
            "worker_capacity": CLOUD_WORKERS,
            "utilization_percent": round(100 * in_use / CLOUD_WORKERS, 1),
            "replica": WORKER_ID}


@app.get("/version")
def version():
    return {"service": "cloud-worker", "build_sha": BUILD_SHA, "replica": WORKER_ID}


@app.post("/probe")
def probe(byte_count: int = 4096, x_api_key: str | None = Header(default=None)):
    require_key(x_api_key)
    if not 1 <= byte_count <= 262_144:
        raise HTTPException(status_code=422, detail="byte_count must be between 1 and 262144")
    return Response(content=b"x" * byte_count, media_type="application/octet-stream")


@app.post("/compute")
async def compute_task(payload: ComputeRequest, request: Request,
                       x_api_key: str | None = Header(default=None)):
    global _first_request, _active_jobs, _queued_jobs
    require_key(x_api_key)
    try:
        started = time.perf_counter()
        waiting_for_slot = True
        _queued_jobs += 1
        QUEUED_TASKS.set(_queued_jobs)
        try:
            async with request.app.state.semaphore:
                _queued_jobs -= 1
                QUEUED_TASKS.set(_queued_jobs)
                waiting_for_slot = False
                _active_jobs += 1
                WORKERS_IN_USE.set(min(_active_jobs, CLOUD_WORKERS))
                try:
                    result = await asyncio.get_running_loop().run_in_executor(
                        request.app.state.pool, execute, payload.model_dump())
                finally:
                    _active_jobs -= 1
                    WORKERS_IN_USE.set(_active_jobs)
        finally:
            if waiting_for_slot:
                _queued_jobs -= 1
                QUEUED_TASKS.set(_queued_jobs)
        elapsed = time.perf_counter() - started
        with _first_lock:
            cold_start = _first_request
            _first_request = False
        result.update({"replica": WORKER_ID, "build_sha": BUILD_SHA, "cold_start": cold_start,
                       "cold_start_signal": "first successful task handled by this worker process; not platform launch time",
                       "request_id": request.headers.get("x-request-id", "")})
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
