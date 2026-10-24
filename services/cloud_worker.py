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

from fastapi import FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from offloader.workload import compute

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
TASKS = Counter("cloud_tasks_total", "Cloud tasks", ["outcome"])
COMPLETION = Histogram("cloud_compute_seconds", "Cloud compute time", buckets=(.01, .05, .1, .25, .5, 1, 2, 5, 10))
ERRORS = Counter("cloud_errors_total", "Cloud service errors", ["kind"])
_first_lock = threading.Lock()
_first_request = True


class ComputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    iterations: int = Field(ge=1, le=2_000_000)
    data: str = Field(max_length=200_000)

    @field_validator("data")
    @classmethod
    def validate_utf8_size(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 200_000:
            raise ValueError("data must be at most 200000 UTF-8 bytes")
        return value


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = ProcessPoolExecutor(max_workers=int(os.getenv("CLOUD_WORKERS", "2")))
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
    global _first_request
    require_key(x_api_key)
    try:
        started = time.perf_counter()
        result = await asyncio.get_running_loop().run_in_executor(request.app.state.pool, compute, payload.model_dump())
        elapsed = time.perf_counter() - started
        with _first_lock:
            cold_start = _first_request
            _first_request = False
        result.update({"replica": WORKER_ID, "build_sha": BUILD_SHA, "cold_start": cold_start,
                       "cold_start_signal": "first successful task handled by this worker process; not platform launch time",
                       "request_id": request.headers.get("x-request-id", "")})
        TASKS.labels(outcome="success").inc()
        COMPLETION.observe(elapsed)
        return result
    except ValueError as exc:
        ERRORS.labels(kind="validation").inc()
        TASKS.labels(outcome="rejected").inc()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
