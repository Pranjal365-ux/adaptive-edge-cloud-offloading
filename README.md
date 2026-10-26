# OffloadOps

OffloadOps is a live edge-to-cloud image-inspection demo. A browser submits a part image to a FastAPI edge gateway. The gateway chooses local processing or an authenticated cloud worker, and the interface shows the decision and annotated result.

The inspection algorithm flags local-contrast anomalies with an explainable image-processing heuristic. It is a classroom prototype, not a trained or certified factory quality system.

## How the services fit together

    Browser UI
       |
    Edge gateway and local worker pool
       |  adaptive routing / cloud fallback
       +-------------------------------> Cloud worker
       |
    Prometheus -> Grafana

In the local demo, Docker Compose runs the edge gateway, local cloud worker, Toxiproxy, Prometheus, and Grafana. In Azure-backed mode, the edge gateway still runs locally, while the cloud worker URL points to an Azure Container App. Docker Desktop is therefore needed for that mode. The checked-in Azure infrastructure currently provisions the cloud worker; the dashboard and edge gateway are not yet a full Azure-hosted frontend deployment.

## What the console shows

- Live edge and cloud worker-slot utilization over a rolling ten-second window. This is application-level busy-slot time, not host CPU utilization.
- Completed task throughput over the last minute, split by destination, plus measured cloud round-trip time.
- The active routing policy, recent decisions, and the decision estimates/reason.
- A live comparison option that processes the same image independently on edge and cloud and shows both annotated outputs and timings.
- Local network impairment controls through Toxiproxy. They are disabled when the gateway connects directly to Azure because that traffic does not pass through the local proxy.

Adaptive routing predicts completion from workload size, measured network RTT/throughput, worker queues, learned service rates, and a synthetic cloud-cost term. It may correctly choose edge when the task is small or the network makes offloading slower. Choose Cloud only to demonstrate the remote worker explicitly, or use the same-image comparison to run both. The comparison is actual live work, not a simulator replay.

## Run locally on Windows

Requirements: PowerShell, Python 3.12, Git, and Docker Desktop with its Linux engine running.

- Install Python dependencies: run **.\tasks.ps1 setup**.
- Start the whole local demo: run **.\tasks.ps1 demo**.
- Open the console at **http://localhost:8000/console**.
- Open Grafana at **http://localhost:3000** and Prometheus at **http://localhost:9090**.
- Stop the stack: run **.\tasks.ps1 down**.

The ports bind to localhost only. Compose sets CPU/memory limits and health checks for the services.

## Use the Azure worker with the local demo

Set the deployed HTTPS worker URL in the Windows user environment as AZURE_WORKER_URL and the matching shared API key as CLOUD_API_KEY. Then run **.\tasks.ps1 demo-azure** from a new or existing PowerShell window. The script reads saved user-level values when they are absent from the current process.

This mode uses Azure for cloud processing, but keeps the UI and edge gateway on the laptop. For the laptop to be turned off, the dashboard and edge gateway still need Azure hosting.

## Project layout

- offloader/: shared image inspection and the synthetic cost estimate used by routing.
- services/: edge gateway, cloud worker, and browser console.
- infra/: active Terraform for Azure Container Apps, registry, monitoring, Key Vault, and budget alerts.
- monitoring/: Prometheus and Grafana configuration and dashboards.
- toxiproxy/ and scenarios/: local network emulation.
- tests/: automated checks for inspection, routing, telemetry, and packaging.
- scripts/: setup checks, live demo checks, and scenario helpers.
- docs/: deployment steps, the demo walkthrough, inspection details, and measurement limits.

Historical experiments, simulator implementation, and generated result files are preserved outside this repository in the sibling archive folder, so the deliverable tree contains the live application and its deployment/support files.

## DevOps and observability

GitHub Actions runs Linux/Windows quality checks, container builds, and Terraform formatting/validation. Dockerfiles build separate non-root edge and cloud images. Azure configuration uses Terraform, Container Apps, managed identity, a container registry, Key Vault, Log Analytics, Application Insights, and budget/availability alerts. Alerts notify; they do not stop resource spending.

Prometheus exposes application metrics locally. Azure Monitor collects Container Apps logs and optional OpenTelemetry traces. Cloud-cost values shown by the router are synthetic estimates, not Azure billing data. Worker-slot utilization is not Azure host CPU.

See docs/DEMO.md for a presentation walkthrough, docs/AZURE_DEPLOY.md for Azure setup, and docs/SURFACE_INSPECTION.md for request/response details and algorithm limits.