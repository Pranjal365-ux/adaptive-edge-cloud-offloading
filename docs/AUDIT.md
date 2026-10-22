# Implementation audit and reproducibility

Baseline inspected: c0bdfade4b7bff4ec364734344988907a2e55b66.

| Component | Purpose | Scope and audit finding |
|---|---|---|
| offloading.py | FIFO discrete-event simulator and development-only threshold selection | Synthetic MI, Mbps, one-way delay, CPU service prices; queued transfer sampling and nearest-rank p95 corrected |
| azure_function/workload.py | Deterministic SHA-256 chain shared by laptop and Function | One initial hash of input, then iteration hashes of the 32-byte digest; input size is not multiplied by iteration count; reject nonobject JSON |
| azure_function/function_app.py | Function-authenticated HTTP POST worker | Added hashed process identifier and first successful request flag; this flag does not establish platform cold-start duration |
| live_probe.py | Sequential paired pilot | Digests, local wall/compute time, Azure compute, full HTTPS call, JSON-body byte counts; saves after each observation |
| live_experiment.py | Four-policy live experiment | Separate development calibration, immutable pre-run protocol, identical seeded traces, shuffled policy order, per-task error retention, process-based local executor |
| terraform/main.tf | Azure infrastructure and ZIP code deployment | Central India; Python 3.12, Linux Y1, LRS storage; reviewed plan required and endpoint verification required |
| test_model.py, test_integrity.py, test_live.py | Behavioral and regression checks | Determinism, decisions, digest correctness, malformed input, p95, changing link state, no duplicate timed work, retained errors |
| plot_results.py, dashboard.py | Synthetic result visualization | Dashboard reads simulator; not deployment monitoring |
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

Use an isolated Python environment with the versions retained in evidence/software.txt. Run `python -m unittest -v` and `python offloading.py --tasks 300 --seeds 20 --output results`. Live usage is `python live_experiment.py --url HTTPS_ENDPOINT --calibrate-only --output live_results`, followed by the same settings with `--protocol live_results/protocol.json` instead of `--calibrate-only`. Obtain the Function key directly into AZURE_FUNCTION_KEY using Azure CLI; never paste it into chat or command-line arguments. Keep all Terraform state, saved plans and keys private.

Byte accounting with failures: transferred_input_bytes counts attempted offload payloads, including failed requests, not confirmed delivery. request_body_bytes and response_body_bytes sum successful exchanges; failure rows use zero as an unmeasured placeholder, not proof of no transfer. Report failed-exchange bytes as unknown.
