"""Edge gateway with runtime policy selection, observable decisions and cloud fallback."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
import uuid
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel, ConfigDict, Field, model_validator

from offloader.costs import CostModel
from offloader.tasks import execute

LOG = logging.getLogger("offloadops.edge")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
if os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(
            connection_string=os.environ["APPLICATIONINSIGHTS_CONNECTION_STRING"]
        )
    except Exception as exc:
        LOG.error("Application Insights configuration failed: %s", type(exc).__name__)
POLICIES = {"edge_only", "cloud_only", "threshold", "adaptive"}
POLICY = os.getenv("OFFLOAD_POLICY", "adaptive")
CLOUD_URL = os.getenv("CLOUD_URL", "http://cloud:8081").rstrip("/")
CLOUD_PROXY_API = os.getenv("TOXIPROXY_API", "http://toxiproxy:8474").rstrip("/")
CLOUD_API_KEY = os.getenv("CLOUD_API_KEY", "local-demo-key")
EDGE_WORKERS = max(1, int(os.getenv("EDGE_WORKERS", "2")))
EDGE_MS_PER_WORK_UNIT = float(os.getenv("EDGE_MS_PER_WORK_UNIT", "0.00012"))
CLOUD_MS_PER_WORK_UNIT = float(os.getenv("CLOUD_MS_PER_WORK_UNIT", "0.00004"))
CLOUD_WORKERS = max(1, int(os.getenv("CLOUD_WORKERS", "2")))
FIXED_THRESHOLD = float(os.getenv("FIXED_THRESHOLD_UNITS", "500000"))
CLOUD_COST_PER_SECOND = float(os.getenv("CLOUD_USD_PER_COMPUTE_SECOND", "0.0001"))
COST_WEIGHT = float(os.getenv("COST_WEIGHT_SECONDS_PER_USD", "100"))
MAX_BODY_BYTES = 4_500_000
TASKS = Counter("edge_decisions_total", "Edge decisions", ["policy", "destination"])
INSPECTIONS = Counter(
    "edge_inspections_total",
    "Routed image inspections by destination and verdict",
    ["destination", "verdict"],
)
DEFECTS = Counter(
    "edge_suspected_defects_total",
    "Suspected surface anomalies returned to callers",
    ["destination"],
)
IMAGE_PIXELS = Histogram(
    "edge_inspection_pixels",
    "Pixels inspected per image job",
    buckets=(65_536, 262_144, 524_288, 1_000_000, 1_600_000, 2_400_000),
)
COMPLETION = Histogram(
    "edge_completion_seconds",
    "End-to-end task latency",
    ["policy"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
)
QUEUE = Gauge("edge_queue_depth", "Queued or active local edge tasks")
EDGE_WORKERS_IN_USE = Gauge(
    "edge_worker_slots_in_use", "Edge worker slots currently processing work"
)
EDGE_WORKER_CAPACITY = Gauge("edge_worker_slots_capacity", "Configured edge worker slots")
EDGE_WORKER_UTILIZATION = Gauge(
    "edge_worker_utilization_percent", "Edge worker slot utilization percentage"
)
CLOUD_WORKER_UTILIZATION = Gauge(
    "cloud_worker_utilization_percent", "Cloud worker slot utilization percentage"
)
TASK_THROUGHPUT = Gauge(
    "edge_tasks_per_minute", "Completed edge-gateway jobs in the trailing 60 seconds"
)
_cloud_inflight_metric = Gauge("edge_cloud_inflight", "Cloud requests currently in flight")
RTT = Gauge("edge_rtt_estimate_ms", "Measured cloud probe round-trip time")
BANDWIDTH = Gauge(
    "edge_bandwidth_estimate_mbps", "Application-level cloud probe throughput estimate"
)
CLOUD_COST = Counter("edge_cloud_cost_usd_total", "Synthetic estimated cloud CPU cost")
ERRORS = Counter("edge_errors_total", "Edge errors", ["kind"])
_active_local = 0
_active_edge_workers = 0
_active_cloud = 0
_cloud_worker_snapshot = {
    "available": False,
    "active_workers": 0,
    "queued_tasks": 0,
    "worker_capacity": CLOUD_WORKERS,
    "utilization_percent": 0,
}
_completion_times: deque[float] = deque()
_local_lock = asyncio.Lock()
_breaker_lock = asyncio.Lock()
_cloud_failures = 0
_breaker_open_until = 0.0
_rtt_ewma_ms = float(os.getenv("INITIAL_RTT_MS", "100"))
_bandwidth_ewma_mbps = float(os.getenv("INITIAL_BANDWIDTH_MBPS", "10"))
_events: deque[dict] = deque(maxlen=200)
_events_signal: asyncio.Queue[None] | None = None
_started_at = time.monotonic()
BUILD_SHA = os.getenv("BUILD_SHA", "development")
_scenario_task: asyncio.Task | None = None


class ComputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    task_id: str = Field(
        default_factory=lambda: f"JOB-{uuid.uuid4().hex[:10].upper()}", min_length=1, max_length=80
    )
    task_type: Literal["surface_defect_inspection"] = "surface_defect_inspection"
    source: str = Field(default="sensor-gateway-07", min_length=1, max_length=100)
    priority: Literal["low", "normal", "high"] = "normal"
    workload_profile: Literal["quick", "balanced", "heavy"] = "balanced"
    record_count: int = Field(default=1, ge=1, le=10_000)
    image_base64: str | None = Field(default=None, max_length=4_000_000)
    image_width: int | None = Field(default=None, ge=64, le=2048)
    image_height: int | None = Field(default=None, ge=64, le=2048)
    sensitivity: Literal["low", "normal", "high"] = "normal"

    @model_validator(mode="after")
    def validate_image(self):
        if not self.image_base64 or self.image_width is None or self.image_height is None:
            raise ValueError(
                "image_base64, image_width, and image_height are required for inspection"
            )
        if self.image_width * self.image_height > 2_400_000:
            raise ValueError("image is too large; choose a lower inspection detail")
        return self

    @property
    def work_units(self) -> int:
        return max(1, (self.image_width * self.image_height + 1) // 2)


class PolicyUpdate(BaseModel):
    policy: str


class ScenarioUpdate(BaseModel):
    name: str


class RaceRequest(BaseModel):
    seed: int = Field(default=3001, ge=1)
    tasks: int = Field(default=100, ge=20, le=1000)
    scenario: str = "random_walk_bandwidth"


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _events_signal
    EDGE_WORKER_CAPACITY.set(EDGE_WORKERS)
    EDGE_WORKER_UTILIZATION.set(0)
    app.state.pool = ProcessPoolExecutor(max_workers=EDGE_WORKERS)
    app.state.semaphore = asyncio.Semaphore(EDGE_WORKERS)
    app.state.client = httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0))
    _events_signal = asyncio.Queue(maxsize=1)
    probe = asyncio.create_task(probe_loop())
    yield
    probe.cancel()
    if _scenario_task:
        _scenario_task.cancel()
    await asyncio.gather(probe, return_exceptions=True)
    if _scenario_task:
        await asyncio.gather(_scenario_task, return_exceptions=True)
    await app.state.client.aclose()
    app.state.pool.shutdown(wait=True, cancel_futures=True)


app = FastAPI(title="OffloadOps Edge Gateway", version=BUILD_SHA, lifespan=lifespan)


@app.middleware("http")
async def request_guard_and_logging(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))[:128]
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_BODY_BYTES:
        return Response(status_code=413, content="request too large")
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


def add_event(event: dict) -> None:
    _events.append(event)
    if _events_signal and _events_signal.empty():
        _events_signal.put_nowait(None)


def record_completion() -> None:
    now = time.monotonic()
    _completion_times.append(now)
    while _completion_times and now - _completion_times[0] > 60:
        _completion_times.popleft()
    TASK_THROUGHPUT.set(len(_completion_times))


def choose_destination(payload: ComputeRequest, active_local: int) -> tuple[str, dict]:
    workload_ms = payload.work_units * EDGE_MS_PER_WORK_UNIT
    edge_wait_ms = active_local * workload_ms / EDGE_WORKERS
    edge_ms = edge_wait_ms + workload_ms
    input_bytes = (
        len(payload.image_base64.encode("ascii"))
        if payload.task_type == "surface_defect_inspection"
        else len(payload.data.encode("utf-8"))
    )
    transfer_ms = input_bytes * 0.008 / max(_bandwidth_ewma_mbps, 0.01)
    cloud_service_ms = payload.work_units * CLOUD_MS_PER_WORK_UNIT
    cloud_wait_ms = (_active_cloud / CLOUD_WORKERS) * cloud_service_ms
    cloud_ms = _rtt_ewma_ms + transfer_ms + cloud_wait_ms + cloud_service_ms
    cost_usd = CostModel(compute_usd_per_second=CLOUD_COST_PER_SECOND).estimate(
        cloud_service_ms / 1000, 0
    )
    policy = POLICY
    if policy == "edge_only":
        destination = "edge"
        reason = "Local-only policy"
    elif policy == "cloud_only":
        destination = "cloud"
        reason = "Cloud-only policy"
    elif policy == "threshold":
        destination = "cloud" if payload.work_units > FIXED_THRESHOLD else "edge"
        reason = f"Fixed workload threshold {FIXED_THRESHOLD:g} units"
    else:
        cloud_adjusted_ms = cloud_ms + COST_WEIGHT * cost_usd * 1000
        destination = "cloud" if cloud_adjusted_ms < edge_ms else "edge"
        reason = (
            f"Predicted edge {edge_ms:.1f} ms vs cloud {cloud_ms:.1f} ms; "
            f"cloud cost estimate ${cost_usd:.7f}; edge activity {active_local}"
        )
    return destination, {
        "policy": policy,
        "destination": destination,
        "reason": reason,
        "predicted_edge_ms": edge_ms,
        "predicted_cloud_ms": cloud_ms,
        "rtt_estimate_ms": _rtt_ewma_ms,
        "bandwidth_estimate_mbps": _bandwidth_ewma_mbps,
        "edge_queue_depth": active_local,
        "cloud_inflight_estimate": _active_cloud,
        "cloud_cost_estimate_usd": cost_usd,
    }


def learn_service_rate(destination: str, work_units: int, compute_ms: float) -> None:
    """Update measured milliseconds per image-work unit after successful processing."""
    global EDGE_MS_PER_WORK_UNIT, CLOUD_MS_PER_WORK_UNIT
    if work_units <= 0 or compute_ms < 0:
        return
    measured = compute_ms / work_units
    if destination == "edge":
        EDGE_MS_PER_WORK_UNIT = 0.8 * EDGE_MS_PER_WORK_UNIT + 0.2 * measured
    else:
        CLOUD_MS_PER_WORK_UNIT = 0.8 * CLOUD_MS_PER_WORK_UNIT + 0.2 * measured


async def run_edge(payload: ComputeRequest, request_id: str):
    global _active_local, _active_edge_workers
    async with _local_lock:
        _active_local += 1
        active = _active_local
    QUEUE.set(max(0, active - EDGE_WORKERS))
    try:
        async with app.state.semaphore:
            _active_edge_workers += 1
            EDGE_WORKERS_IN_USE.set(_active_edge_workers)
            EDGE_WORKER_UTILIZATION.set(100 * _active_edge_workers / EDGE_WORKERS)
            try:
                result = await asyncio.get_running_loop().run_in_executor(
                    app.state.pool, execute, payload.model_dump()
                )
                learn_service_rate("edge", payload.work_units, result["compute_ms"])
                return result
            finally:
                _active_edge_workers -= 1
                EDGE_WORKERS_IN_USE.set(_active_edge_workers)
                EDGE_WORKER_UTILIZATION.set(100 * _active_edge_workers / EDGE_WORKERS)
    finally:
        async with _local_lock:
            _active_local -= 1
            QUEUE.set(max(0, _active_local - EDGE_WORKERS))


async def cloud_open() -> bool:
    return time.monotonic() < _breaker_open_until


async def record_cloud_failure() -> None:
    global _cloud_failures, _breaker_open_until
    async with _breaker_lock:
        _cloud_failures += 1
        if _cloud_failures >= 3:
            _breaker_open_until = time.monotonic() + 15


async def record_cloud_success() -> None:
    global _cloud_failures, _breaker_open_until
    async with _breaker_lock:
        _cloud_failures = 0
        _breaker_open_until = 0


async def probe_loop() -> None:
    global _rtt_ewma_ms, _bandwidth_ewma_mbps
    retry_delay = 5
    while True:
        try:
            started = time.perf_counter()
            response = await app.state.client.get(f"{CLOUD_URL}/health")
            response.raise_for_status()
            rtt_ms = (time.perf_counter() - started) * 1000
            _rtt_ewma_ms = 0.8 * _rtt_ewma_ms + 0.2 * rtt_ms
            RTT.set(_rtt_ewma_ms)
            started = time.perf_counter()
            response = await app.state.client.post(
                f"{CLOUD_URL}/probe?byte_count=32768", headers={"X-API-Key": CLOUD_API_KEY}
            )
            response.raise_for_status()
            elapsed = max(time.perf_counter() - started, 0.001)
            measured = len(response.content) * 8 / elapsed / 1_000_000
            _bandwidth_ewma_mbps = 0.8 * _bandwidth_ewma_mbps + 0.2 * measured
            BANDWIDTH.set(_bandwidth_ewma_mbps)
            retry_delay = 5
        except (httpx.HTTPError, ValueError):
            ERRORS.labels(kind="probe").inc()
            retry_delay = min(retry_delay * 2, 30)
        await asyncio.sleep(retry_delay)


async def replace_toxics(specs: list[dict]) -> None:
    response = await app.state.client.get(f"{CLOUD_PROXY_API}/proxies/cloud/toxics")
    response.raise_for_status()
    for toxic in response.json():
        removed = await app.state.client.delete(
            f"{CLOUD_PROXY_API}/proxies/cloud/toxics/{toxic['name']}"
        )
        removed.raise_for_status()
    for spec in specs:
        created = await app.state.client.post(f"{CLOUD_PROXY_API}/proxies/cloud/toxics", json=spec)
        created.raise_for_status()


def toxic(name: str, toxic_type: str, attributes: dict, stream: str = "downstream") -> dict:
    return {
        "name": name,
        "type": toxic_type,
        "stream": stream,
        "toxicity": 1.0,
        "attributes": attributes,
    }


async def run_flapping() -> None:
    while True:
        await replace_toxics(
            [
                toxic("latency", "latency", {"latency": 300, "jitter": 25}),
                toxic("bandwidth", "bandwidth", {"rate": 128}),
            ]
        )
        await asyncio.sleep(30)
        await replace_toxics([])
        await asyncio.sleep(30)


async def run_random_walk() -> None:
    rng = random.Random(2026)
    bandwidth_kbps = 2048.0
    latency_ms = 25.0
    while True:
        bandwidth_kbps = min(8192.0, max(64.0, bandwidth_kbps * (1 + rng.uniform(-0.25, 0.25))))
        latency_ms = min(500.0, max(5.0, latency_ms * (1 + rng.uniform(-0.25, 0.25))))
        await replace_toxics(
            [
                toxic("latency", "latency", {"latency": round(latency_ms), "jitter": 10}),
                toxic("bandwidth", "bandwidth", {"rate": round(bandwidth_kbps)}),
            ]
        )
        await asyncio.sleep(5)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "build_sha": BUILD_SHA}


@app.get("/readyz")
def readyz():
    return {"status": "ready", "uptime_seconds": round(time.monotonic() - _started_at, 3)}


@app.get("/version")
def version():
    return {
        "service": "edge-gateway",
        "build_sha": BUILD_SHA,
        "active_policy": POLICY,
        "cloud_url_configured": bool(CLOUD_URL),
    }


@app.get("/policy")
def get_policy():
    return {"policy": POLICY, "available": sorted(POLICIES)}


@app.put("/policy")
def put_policy(update: PolicyUpdate):
    global POLICY
    if update.policy not in POLICIES:
        raise HTTPException(status_code=422, detail=f"policy must be one of {sorted(POLICIES)}")
    POLICY = update.policy
    return {"policy": POLICY}


@app.put("/scenario")
async def put_scenario(update: ScenarioUpdate):
    global _scenario_task
    if update.name not in {"good", "poor", "flapping", "random-walk", "lossy"}:
        raise HTTPException(status_code=422, detail="unknown network scenario")
    if _scenario_task:
        _scenario_task.cancel()
        await asyncio.gather(_scenario_task, return_exceptions=True)
        _scenario_task = None
    if update.name == "flapping":
        _scenario_task = asyncio.create_task(run_flapping())
    elif update.name == "random-walk":
        _scenario_task = asyncio.create_task(run_random_walk())
    elif update.name == "good":
        await replace_toxics([])
    elif update.name == "poor":
        await replace_toxics(
            [
                toxic("latency", "latency", {"latency": 300, "jitter": 25}),
                toxic("bandwidth", "bandwidth", {"rate": 128}),
            ]
        )
    else:
        await replace_toxics([toxic("timeout", "timeout", {"timeout": 1})])
    return {"scenario": update.name, "applied": True}


@app.post("/tasks")
async def submit_task(payload: ComputeRequest, request: Request):
    global _active_cloud
    start = time.perf_counter()
    request_id = request.headers.get("x-request-id", payload.task_id)[:128]
    destination, decision = choose_destination(payload, _active_local)
    fallback = False
    if destination == "cloud" and await cloud_open():
        destination = "edge"
        fallback = True
        decision["reason"] += "; cloud circuit breaker open, using edge fallback"
    result = None
    if destination == "cloud":
        _active_cloud += 1
        _cloud_inflight_metric.set(_active_cloud)
        try:
            response = await app.state.client.post(
                f"{CLOUD_URL}/compute",
                json={
                    key: getattr(payload, key)
                    for key in (
                        "task_type",
                        "image_base64",
                        "image_width",
                        "image_height",
                        "sensitivity",
                    )
                },
                headers={"X-API-Key": CLOUD_API_KEY, "X-Request-ID": request_id},
            )
            response.raise_for_status()
            result = response.json()
            learn_service_rate("cloud", payload.work_units, result.get("compute_ms", 0))
            await record_cloud_success()
            TASKS.labels(policy=decision["policy"], destination="cloud").inc()
            CLOUD_COST.inc(result.get("compute_ms", 0) / 1000 * CLOUD_COST_PER_SECOND)
        except (httpx.HTTPError, ValueError) as exc:
            await record_cloud_failure()
            ERRORS.labels(kind="cloud_fallback").inc()
            fallback = True
            destination = "edge"
            decision["reason"] += f"; cloud error {type(exc).__name__}, used edge fallback"
        finally:
            _active_cloud -= 1
            _cloud_inflight_metric.set(_active_cloud)
    if destination == "edge":
        try:
            result = await run_edge(payload, request_id)
        except ValueError as exc:
            ERRORS.labels(kind="task_validation").inc()
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        TASKS.labels(policy=decision["policy"], destination="edge").inc()
    if payload.task_type == "surface_defect_inspection":
        INSPECTIONS.labels(destination=destination, verdict=result["verdict"]).inc()
        DEFECTS.labels(destination=destination).inc(result.get("defect_count", 0))
        IMAGE_PIXELS.observe(result["pixels_processed"])
    record_completion()
    elapsed = time.perf_counter() - start
    COMPLETION.labels(policy=decision["policy"]).observe(elapsed)
    event = {
        "request_id": request_id,
        "task_id": payload.task_id,
        "task_type": payload.task_type,
        "source": payload.source,
        "priority": payload.priority,
        "record_count": payload.record_count,
        "workload_profile": payload.workload_profile,
        "policy": decision["policy"],
        "destination": destination,
        "reason": decision["reason"],
        "completion_ms": round(elapsed * 1000, 3),
        "fallback": fallback,
        "verdict": result.get("verdict"),
        "defect_count": result.get("defect_count"),
        "digest": result.get("digest"),
    }
    add_event(event)
    return {
        **result,
        **decision,
        "task_id": payload.task_id,
        "task_type": payload.task_type,
        "source": payload.source,
        "priority": payload.priority,
        "record_count": payload.record_count,
        "workload_profile": payload.workload_profile,
        "destination": destination,
        "fallback": fallback,
        "completion_ms": round(elapsed * 1000, 3),
        "request_id": request_id,
    }


@app.post("/tasks/compare")
async def compare_task(payload: ComputeRequest, request: Request):
    """Run the same image concurrently on both live workers without changing policy."""

    async def run_edge_comparison() -> dict:
        started = time.perf_counter()
        try:
            result = await run_edge(payload, f"{payload.task_id}-edge")
            return {
                **result,
                "available": True,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            }
        except (ValueError, RuntimeError) as exc:
            return {"available": False, "error": type(exc).__name__}

    async def run_cloud_comparison() -> dict:
        global _active_cloud
        if await cloud_open():
            return {"available": False, "error": "cloud circuit breaker is open"}
        started = time.perf_counter()
        request_id = request.headers.get("x-request-id", payload.task_id)[:128]
        _active_cloud += 1
        _cloud_inflight_metric.set(_active_cloud)
        try:
            response = await app.state.client.post(
                f"{CLOUD_URL}/compute",
                json={
                    key: getattr(payload, key)
                    for key in (
                        "task_type",
                        "image_base64",
                        "image_width",
                        "image_height",
                        "sensitivity",
                    )
                },
                headers={"X-API-Key": CLOUD_API_KEY, "X-Request-ID": f"{request_id}-cloud"},
            )
            response.raise_for_status()
            result = response.json()
            learn_service_rate("cloud", payload.work_units, result.get("compute_ms", 0))
            await record_cloud_success()
            return {
                **result,
                "available": True,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            }
        except (httpx.HTTPError, ValueError) as exc:
            await record_cloud_failure()
            return {"available": False, "error": type(exc).__name__}
        finally:
            _active_cloud -= 1
            _cloud_inflight_metric.set(_active_cloud)

    edge_result, cloud_result = await asyncio.gather(run_edge_comparison(), run_cloud_comparison())
    for destination, result in (("edge", edge_result), ("cloud", cloud_result)):
        if not result["available"]:
            continue
        TASKS.labels(policy="comparison", destination=destination).inc()
        COMPLETION.labels(policy="comparison").observe(result["elapsed_ms"] / 1000)
        INSPECTIONS.labels(destination=destination, verdict=result["verdict"]).inc()
        DEFECTS.labels(destination=destination).inc(result.get("defect_count", 0))
        IMAGE_PIXELS.observe(result["pixels_processed"])
    record_completion()
    if cloud_result["available"]:
        CLOUD_COST.inc(cloud_result.get("compute_ms", 0) / 1000 * CLOUD_COST_PER_SECOND)
    winner = None
    if edge_result["available"] and cloud_result["available"]:
        winner = "edge" if edge_result["elapsed_ms"] <= cloud_result["elapsed_ms"] else "cloud"
    elapsed_candidates = [
        item["elapsed_ms"] for item in (edge_result, cloud_result) if item["available"]
    ]
    add_event(
        {
            "request_id": request.headers.get("x-request-id", payload.task_id),
            "task_id": payload.task_id,
            "task_type": payload.task_type,
            "source": payload.source,
            "priority": payload.priority,
            "record_count": payload.record_count,
            "workload_profile": payload.workload_profile,
            "policy": "comparison",
            "destination": "comparison",
            "reason": "Same image processed concurrently on both workers",
            "completion_ms": round(max(elapsed_candidates, default=0), 3),
            "fallback": False,
            "verdict": None,
            "defect_count": None,
        }
    )
    return {
        "task_id": payload.task_id,
        "source": payload.source,
        "active_policy": POLICY,
        "winner": winner,
        "edge": edge_result,
        "cloud": cloud_result,
    }


@app.get("/status")
async def status():
    try:
        worker_status = await app.state.client.get(
            f"{CLOUD_URL}/status",
            headers={"X-API-Key": CLOUD_API_KEY},
            timeout=httpx.Timeout(0.8, connect=0.5),
        )
        worker_status.raise_for_status()
        _cloud_worker_snapshot.update(worker_status.json())
        _cloud_worker_snapshot["available"] = True
        CLOUD_WORKER_UTILIZATION.set(_cloud_worker_snapshot["utilization_percent"])
    except (httpx.HTTPError, ValueError, TimeoutError):
        _cloud_worker_snapshot["available"] = False
    now = time.monotonic()
    while _completion_times and now - _completion_times[0] > 60:
        _completion_times.popleft()
    TASK_THROUGHPUT.set(len(_completion_times))
    edge_utilization = 100 * _active_edge_workers / EDGE_WORKERS
    return {
        "policy": POLICY,
        "queue_depth": max(0, _active_local - EDGE_WORKERS),
        "edge_active_workers": _active_edge_workers,
        "edge_worker_capacity": EDGE_WORKERS,
        "edge_utilization_percent": round(edge_utilization, 1),
        "cloud_active_workers": _cloud_worker_snapshot["active_workers"],
        "cloud_queued_tasks": _cloud_worker_snapshot["queued_tasks"],
        "cloud_worker_capacity": _cloud_worker_snapshot["worker_capacity"],
        "cloud_utilization_percent": _cloud_worker_snapshot["utilization_percent"],
        "cloud_available": _cloud_worker_snapshot["available"],
        "cloud_replica": _cloud_worker_snapshot.get("replica"),
        "throughput_tasks_per_minute": len(_completion_times),
        "rtt_ms": _rtt_ewma_ms,
        "bandwidth_mbps": _bandwidth_ewma_mbps,
        "circuit_open": time.monotonic() < _breaker_open_until,
        "recent_events": list(_events),
        "build_sha": BUILD_SHA,
    }


@app.get("/events")
async def events():
    async def stream():
        cursor = len(_events)
        while True:
            if len(_events) > cursor:
                for event in list(_events)[cursor:]:
                    yield f"data: {json.dumps(event)}\n\n"
                cursor = len(_events)
            if _events_signal:
                try:
                    await asyncio.wait_for(_events_signal.get(), timeout=15)
                except TimeoutError:
                    yield ": keepalive\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/race")
def race(race_request: RaceRequest):
    """Replay one seeded simulator trace through every policy; this is not live traffic."""
    from offloader.simulator import POLICIES, SCENARIOS, Simulation, generate_tasks, tune_threshold

    scenario = next((item for item in SCENARIOS if item.name == race_request.scenario), None)
    if scenario is None:
        raise HTTPException(status_code=422, detail="unknown simulator scenario")
    tasks = generate_tasks(race_request.seed, race_request.tasks, scenario.arrival_rate)
    threshold, _ = tune_threshold(race_request.tasks, [1001, 1002])
    results = []
    for policy in POLICIES:
        _, summary = Simulation(
            scenario, tasks, policy, threshold, network_seed=race_request.seed
        ).run()
        results.append(summary)
    lower_is_better = {"mean_completion_s", "p95_completion_s", "cloud_cost_usd", "network_mb"}
    winners = {}
    for metric in (
        "mean_completion_s",
        "p95_completion_s",
        "throughput_tasks_per_s",
        "cloud_cost_usd",
    ):
        key = min if metric in lower_is_better else max
        winners[metric] = key(results, key=lambda row: row[metric])["policy"]
    return {
        "mode": "simulated",
        "scenario": scenario.name,
        "seed": race_request.seed,
        "tasks": race_request.tasks,
        "adaptive_note": (
            "adaptive uses EWMA probes and learned service rates; "
            "adaptive_oracle sees exact simulator state"
        ),
        "results": results,
        "winners": winners,
    }


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/console")
def console():
    return FileResponse("services/console.html", media_type="text/html")
