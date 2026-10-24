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
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from offloader.costs import CostModel
from offloader.workload import compute

LOG = logging.getLogger("offloadops.edge")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
if os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        configure_azure_monitor(connection_string=os.environ["APPLICATIONINSIGHTS_CONNECTION_STRING"])
    except Exception as exc:
        LOG.error("Application Insights configuration failed: %s", type(exc).__name__)
POLICIES = {"edge_only", "cloud_only", "threshold", "adaptive"}
POLICY = os.getenv("OFFLOAD_POLICY", "adaptive")
CLOUD_URL = os.getenv("CLOUD_URL", "http://cloud:8081").rstrip("/")
CLOUD_PROXY_API = os.getenv("TOXIPROXY_API", "http://toxiproxy:8474").rstrip("/")
CLOUD_API_KEY = os.getenv("CLOUD_API_KEY", "local-demo-key")
EDGE_WORKERS = max(1, int(os.getenv("EDGE_WORKERS", "2")))
EDGE_MIPS = float(os.getenv("EDGE_MIPS", "500"))
CLOUD_MIPS = float(os.getenv("CLOUD_MIPS", "3000"))
EDGE_MS_PER_ITERATION = float(os.getenv("EDGE_MS_PER_ITERATION", "0.00012"))
CLOUD_MS_PER_ITERATION = float(os.getenv("CLOUD_MS_PER_ITERATION", "0.00004"))
CLOUD_WORKERS = max(1, int(os.getenv("CLOUD_WORKERS", "2")))
FIXED_THRESHOLD = float(os.getenv("FIXED_THRESHOLD_MI", "500"))
CLOUD_COST_PER_SECOND = float(os.getenv("CLOUD_USD_PER_COMPUTE_SECOND", "0.0001"))
COST_WEIGHT = float(os.getenv("COST_WEIGHT_SECONDS_PER_USD", "100"))
MAX_BODY_BYTES = 262_144
TASKS = Counter("edge_decisions_total", "Edge decisions", ["policy", "destination"])
COMPLETION = Histogram("edge_completion_seconds", "End-to-end task latency", ["policy"],
                       buckets=(.01, .05, .1, .25, .5, 1, 2, 5, 10, 30))
QUEUE = Gauge("edge_queue_depth", "Queued or active local edge tasks")
_cloud_inflight_metric = Gauge("edge_cloud_inflight", "Cloud requests currently in flight")
RTT = Gauge("edge_rtt_estimate_ms", "Measured cloud probe round-trip time")
BANDWIDTH = Gauge("edge_bandwidth_estimate_mbps", "Application-level cloud probe throughput estimate")
CLOUD_COST = Counter("edge_cloud_cost_usd_total", "Synthetic estimated cloud CPU cost")
ERRORS = Counter("edge_errors_total", "Edge errors", ["kind"])
_active_local = 0
_active_cloud = 0
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
    task_id: str = Field(default_factory=lambda: f"JOB-{uuid.uuid4().hex[:10].upper()}", min_length=1, max_length=80)
    task_type: Literal["synthetic_telemetry_digest"] = "synthetic_telemetry_digest"
    source: str = Field(default="sensor-gateway-07", min_length=1, max_length=100)
    priority: Literal["low", "normal", "high"] = "normal"
    workload_profile: Literal["quick", "balanced", "heavy"] = "balanced"
    record_count: int = Field(default=1, ge=1, le=10_000)
    iterations: int | None = Field(default=None, ge=1, le=2_000_000)
    data: str | dict | list = Field(default="{}")

    @field_validator("data", mode="before")
    @classmethod
    def encode_data(cls, value):
        if isinstance(value, (dict, list)):
            return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return value

    @field_validator("data")
    @classmethod
    def validate_utf8_size(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("data must be text, a JSON object, or a JSON array")
        if len(value.encode("utf-8")) > 200_000:
            raise ValueError("data must be at most 200000 UTF-8 bytes")
        return value

    @model_validator(mode="after")
    def resolve_profile(self):
        if self.iterations is None:
            self.iterations = {"quick": 50_000, "balanced": 300_000, "heavy": 900_000}[self.workload_profile]
        return self


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
    LOG.info(json.dumps({"event": "http_request", "request_id": request_id,
        "method": request.method, "path": request.url.path, "status": response.status_code,
        "duration_ms": round((time.perf_counter() - started) * 1000, 3)}))
    return response


def add_event(event: dict) -> None:
    _events.append(event)
    if _events_signal and _events_signal.empty():
        _events_signal.put_nowait(None)


def choose_destination(payload: ComputeRequest, active_local: int) -> tuple[str, dict]:
    workload_ms = payload.iterations * EDGE_MS_PER_ITERATION
    edge_wait_ms = active_local * workload_ms / EDGE_WORKERS
    edge_ms = edge_wait_ms + workload_ms
    input_bytes = len(payload.data.encode("utf-8"))
    transfer_ms = input_bytes * 0.008 / max(_bandwidth_ewma_mbps, 0.01)
    cloud_service_ms = payload.iterations * CLOUD_MS_PER_ITERATION
    cloud_wait_ms = (_active_cloud / CLOUD_WORKERS) * cloud_service_ms
    cloud_ms = _rtt_ewma_ms + transfer_ms + cloud_wait_ms + cloud_service_ms
    cost_usd = CostModel(compute_usd_per_second=CLOUD_COST_PER_SECOND).estimate(
        cloud_service_ms / 1000, 0)
    policy = POLICY
    if policy == "edge_only":
        destination = "edge"
        reason = "Local-only policy"
    elif policy == "cloud_only":
        destination = "cloud"
        reason = "Cloud-only policy"
    elif policy == "threshold":
        destination = "cloud" if payload.iterations > FIXED_THRESHOLD else "edge"
        reason = f"Fixed work threshold {FIXED_THRESHOLD:g} iterations"
    else:
        cloud_adjusted_ms = cloud_ms + COST_WEIGHT * cost_usd * 1000
        destination = "cloud" if cloud_adjusted_ms < edge_ms else "edge"
        reason = (f"Predicted edge {edge_ms:.1f} ms vs cloud {cloud_ms:.1f} ms; "
                  f"cloud cost estimate ${cost_usd:.7f}; edge activity {active_local}")
    return destination, {"policy": policy, "destination": destination, "reason": reason,
        "predicted_edge_ms": edge_ms, "predicted_cloud_ms": cloud_ms,
        "rtt_estimate_ms": _rtt_ewma_ms, "bandwidth_estimate_mbps": _bandwidth_ewma_mbps,
        "edge_queue_depth": active_local, "cloud_inflight_estimate": _active_cloud,
        "cloud_cost_estimate_usd": cost_usd}


def learn_service_rate(destination: str, iterations: int, compute_ms: float) -> None:
    """Update measured milliseconds per iteration using successful worker responses."""
    global EDGE_MS_PER_ITERATION, CLOUD_MS_PER_ITERATION
    if iterations <= 0 or compute_ms < 0:
        return
    measured = compute_ms / iterations
    if destination == "edge":
        EDGE_MS_PER_ITERATION = .8 * EDGE_MS_PER_ITERATION + .2 * measured
    else:
        CLOUD_MS_PER_ITERATION = .8 * CLOUD_MS_PER_ITERATION + .2 * measured


async def run_edge(payload: ComputeRequest, request_id: str):
    global _active_local
    async with _local_lock:
        _active_local += 1
        active = _active_local
    QUEUE.set(active)
    try:
        async with app.state.semaphore:
            result = await asyncio.get_running_loop().run_in_executor(
                app.state.pool, compute, {"iterations": payload.iterations, "data": payload.data})
        learn_service_rate("edge", payload.iterations, result["compute_ms"])
        return result
    finally:
        async with _local_lock:
            _active_local -= 1
            QUEUE.set(_active_local)


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
            _rtt_ewma_ms = .8 * _rtt_ewma_ms + .2 * rtt_ms
            RTT.set(_rtt_ewma_ms)
            started = time.perf_counter()
            response = await app.state.client.post(f"{CLOUD_URL}/probe?byte_count=32768",
                headers={"X-API-Key": CLOUD_API_KEY})
            response.raise_for_status()
            elapsed = max(time.perf_counter() - started, .001)
            measured = len(response.content) * 8 / elapsed / 1_000_000
            _bandwidth_ewma_mbps = .8 * _bandwidth_ewma_mbps + .2 * measured
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
            f"{CLOUD_PROXY_API}/proxies/cloud/toxics/{toxic['name']}")
        removed.raise_for_status()
    for spec in specs:
        created = await app.state.client.post(f"{CLOUD_PROXY_API}/proxies/cloud/toxics", json=spec)
        created.raise_for_status()


def toxic(name: str, toxic_type: str, attributes: dict, stream: str = "downstream") -> dict:
    return {"name": name, "type": toxic_type, "stream": stream,
            "toxicity": 1.0, "attributes": attributes}


async def run_flapping() -> None:
    while True:
        await replace_toxics([toxic("latency", "latency", {"latency": 300, "jitter": 25}),
                              toxic("bandwidth", "bandwidth", {"rate": 128})])
        await asyncio.sleep(30)
        await replace_toxics([])
        await asyncio.sleep(30)


async def run_random_walk() -> None:
    rng = random.Random(2026)
    bandwidth_kbps = 2048.0
    latency_ms = 25.0
    while True:
        bandwidth_kbps = min(8192.0, max(64.0, bandwidth_kbps * (1 + rng.uniform(-.25, .25))))
        latency_ms = min(500.0, max(5.0, latency_ms * (1 + rng.uniform(-.25, .25))))
        await replace_toxics([toxic("latency", "latency", {"latency": round(latency_ms), "jitter": 10}),
                              toxic("bandwidth", "bandwidth", {"rate": round(bandwidth_kbps)})])
        await asyncio.sleep(5)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "build_sha": BUILD_SHA}


@app.get("/readyz")
def readyz():
    return {"status": "ready", "uptime_seconds": round(time.monotonic() - _started_at, 3)}


@app.get("/version")
def version():
    return {"service": "edge-gateway", "build_sha": BUILD_SHA,
            "active_policy": POLICY, "cloud_url_configured": bool(CLOUD_URL)}


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
        await replace_toxics([toxic("latency", "latency", {"latency": 300, "jitter": 25}),
                              toxic("bandwidth", "bandwidth", {"rate": 128})])
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
            response = await app.state.client.post(f"{CLOUD_URL}/compute",
                json={"iterations": payload.iterations, "data": payload.data},
                headers={"X-API-Key": CLOUD_API_KEY, "X-Request-ID": request_id})
            response.raise_for_status()
            result = response.json()
            learn_service_rate("cloud", payload.iterations, result.get("compute_ms", 0))
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
        result = await run_edge(payload, request_id)
        TASKS.labels(policy=decision["policy"], destination="edge").inc()
    elapsed = time.perf_counter() - start
    COMPLETION.labels(policy=decision["policy"]).observe(elapsed)
    event = {"request_id": request_id, "task_id": payload.task_id, "task_type": payload.task_type,
        "source": payload.source, "priority": payload.priority, "record_count": payload.record_count,
        "workload_profile": payload.workload_profile, "policy": decision["policy"],
        "destination": destination, "reason": decision["reason"],
        "completion_ms": round(elapsed * 1000, 3), "fallback": fallback,
        "digest": result["digest"]}
    add_event(event)
    return {**result, **decision, "task_id": payload.task_id, "task_type": payload.task_type,
        "source": payload.source, "priority": payload.priority, "record_count": payload.record_count,
        "workload_profile": payload.workload_profile, "destination": destination, "fallback": fallback,
        "completion_ms": round(elapsed * 1000, 3), "request_id": request_id}


@app.get("/status")
def status():
    return {"policy": POLICY, "queue_depth": _active_local, "rtt_ms": _rtt_ewma_ms,
            "bandwidth_mbps": _bandwidth_ewma_mbps,
            "circuit_open": time.monotonic() < _breaker_open_until,
            "recent_events": list(_events), "build_sha": BUILD_SHA}


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
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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
        _, summary = Simulation(scenario, tasks, policy, threshold,
                                network_seed=race_request.seed).run()
        results.append(summary)
    lower_is_better = {"mean_completion_s", "p95_completion_s", "cloud_cost_usd", "network_mb"}
    winners = {}
    for metric in ("mean_completion_s", "p95_completion_s", "throughput_tasks_per_s",
                   "cloud_cost_usd"):
        key = min if metric in lower_is_better else max
        winners[metric] = key(results, key=lambda row: row[metric])["policy"]
    return {"mode": "simulated", "scenario": scenario.name, "seed": race_request.seed,
        "tasks": race_request.tasks, "adaptive_note": "adaptive uses EWMA probes and learned service rates; adaptive_oracle sees exact simulator state",
        "results": results, "winners": winners}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/console")
def console():
    return FileResponse("services/console.html", media_type="text/html")
