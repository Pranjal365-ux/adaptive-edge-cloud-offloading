# Implementation audit and reproducibility

Baseline inspected: c0bdfade4b7bff4ec364734344988907a2e55b66.

| Component | Purpose | Scope and audit finding |
|---|---|---|
| offloading.py | FIFO discrete-event simulator and development-only threshold selection | Synthetic MI, Mbps, one-way delay, CPU service prices; queued transfer sampling and nearest-rank p95 corrected |
| services/edge_gateway.py, services/cloud_worker.py | Live HTTP routing and workers | Image inspection request validation, adaptive route, local fallback, Prometheus metrics |
| offloader/inspection.py | Surface scratch inspection processor | Explainable neighborhood contrast heuristic; pixel and image input are bounded; returns candidate boxes and annotated image; not a certified QA model |
| azure_function/workload.py, azure_function/function_app.py | Retained Azure Functions prototype | Deterministic SHA-256 chain and authenticated HTTP worker from the original experiment; separate from the active image-inspection demo |
| experiments/live_probe.py | Sequential paired historical pilot | Digests, local wall/compute time, Azure compute, full HTTPS call, JSON-body byte counts; saves after each observation |
| experiments/live_experiment.py | Historical four-policy live experiment | Separate development calibration, immutable pre-run protocol, identical seeded traces, shuffled policy order, per-task error retention, process-based local executor |
| terraform/ | Retained legacy Azure Functions infrastructure prototype | Kept for provenance and prior deployment work; active Container Apps deployment is under infra/ |
| tests/ | Behavioral and regression checks | Simulator, policy, integrity, historical live-experiment, and package checks |
| experiments/plot_results.py, experiments/dashboard.py | Synthetic result visualization | Dashboard reads simulator; not deployment monitoring |
| sample_results/ | Historical synthetic examples | Never cite as measured Azure results; regenerate final simulation |

## Claims and boundaries

- Completion time: finish minus scheduled arrival includes scheduler lateness and client queueing. Per-task service time begins inside a worker. Throughput is successful tasks divided by last finish relative to run start.
- p95: nearest-rank ceil(0.95*N), not interpolation. Live latency summaries use successful tasks; errors are separately counted. A policy with failures must not be declared superior from survivor latency.
- Network: HTTPS round trip includes connection setup, transfer, service queueing, and execution. Round trip minus reported compute is combined overhead, never pure network latency. JSON request/response body lengths are application bytes, not total wire traffic or available bandwidth. Wi-Fi link speed is descriptive only.
- CPU and memory: psutil samples whole-system CPU percentage, used memory percentage and available RAM. These include unrelated programs; they are descriptive measurements and are not current inputs to the adaptive decision. System CPU percentages are interval measurements with unequal sample intervals; retain raw telemetry rather than calling an unweighted sample mean time-weighted utilization.
- Adaptive live rule: calibrated per-iteration service and HTTPS overhead plus unfinished client work divided by pool size. It is queue-aware, not a bandwidth-, RAM-, billing-, or server-load-aware optimizer. Full unfinished service overestimates remaining work and assumes divisible capacity. No oracle server queues are observed.
- Cloud cost: simulator uses an assumed CPU-second price. No actual Azure invoice, per-task billed GB-seconds, storage cost or egress bill is measured. Do not equate simulation price to Azure billing or call student credit zero cost.
- Resource use: simulator records edge busy-time/capacity/horizon. Live telemetry is not Azure CPU/RAM utilization. Energy, mobility, RAM constraints and failure/retry simulation are absent.
- Original live code ran a full reference hash inside executor workers after stopping the timer, delaying subsequent jobs. References now run before the experiment; a regression test ensures exactly one local compute per measured execution.
- Local execution uses a process pool to isolate Python hash-loop work from the scheduler and avoid treating Python threads as independent CPU workers. One local process versus four HTTP request threads is an explicit resource-budget asymmetry, not equal hardware.
- Calibration and pilot have separate payloads/work sizes from final data. Fixed threshold selection minimizes predicted unqueued latency on development classes; it is not an empirically optimal queued baseline. Include the all-cloud and all-edge candidates.
- Protocol is saved before final tasks; code hash and settings are checked on replay. Trace generation and ordering are deterministic; timing is not. Matched traces do not imply identical time-varying network conditions.

## Changes after pilot and freeze

Final protocol and pilot analysis live in the saved evidence directory. Do not tune a threshold against final results. Any rerun after a code/rule change must receive a new protocol and be distinguished from the original evaluation.

## Commands

Use an isolated Python environment with the versions retained in evidence/software.txt. The maintained project checks are in `tests/` and run with `python -m pytest`; the simulator command is `python offloading.py --tasks 300 --seeds 20 --output results`. Historical live SHA-chain experiment entry points are retained under `experiments/` for provenance and are separate from the current surface-inspection service demo. Azure Functions code and its older Terraform prototype remain under `azure_function/` and `terraform/`; active Azure Container Apps deployment instructions are in `docs/AZURE_DEPLOY.md` and use `infra/`. Keep all Terraform state, saved plans and keys private.

Byte accounting with failures: transferred_input_bytes counts attempted offload payloads, including failed requests, not confirmed delivery. request_body_bytes and response_body_bytes sum successful exchanges; failure rows use zero as an unmeasured placeholder, not proof of no transfer. Report failed-exchange bytes as unknown.
