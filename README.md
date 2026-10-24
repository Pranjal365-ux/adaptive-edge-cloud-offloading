# OffloadOps

OffloadOps is a reproducible edge-to-cloud offloading project with a discrete-event simulator and a locally containerized service demo. It compares local-only, cloud-only, fixed-threshold, measured adaptive, and simulator-oracle policies. The console shows live container decisions separately from seeded simulator races.

The approved course synopsis is [the project synopsis](docs/Adaptive_Task_Offloading_Synopsis.docx). Implementation and measurement boundaries are recorded in [the audit](docs/AUDIT.md), [decisions](docs/DECISIONS.md), and [verification log](docs/VERIFICATION.md).

## Architecture

```text
PowerShell console / demo UI
            |
      Edge gateway ---- Prometheus ---- Grafana
       |       |
 local process  Toxiproxy ---- Cloud worker
       pool                       |
                              Process pool
```

The edge gateway accepts validated tasks, applies a runtime-selectable policy, and either computes locally in a process pool or calls the cloud worker. Toxiproxy lets the demo change latency and throughput without changing application code. Prometheus scrapes both services, and Grafana loads its dashboard and data source from checked-in provisioning files.

The simulator models the same baseline policies and adds stable, periodic, and seeded random-walk network scenarios. It writes the backward-compatible `summary.csv` and `tasks.csv`, plus seed-level `aggregate.csv`, matched-seed `paired.csv`, and `cost_sweep.csv`. The adaptive simulation policy uses EWMA network observations and learned service rates; `adaptive_oracle` uses exact simulator state and exists only as an upper-bound comparison.

## Local setup on Windows

Use PowerShell, Python 3.12, Git, and Docker Desktop with the WSL 2 engine. No Linux shell or GNU Make is required. Docker Desktop should have enough memory for the bounded local stack; each Compose service has an explicit memory and CPU limit.

```powershell
.\tasks.ps1 setup
.\tasks.ps1 test
.\tasks.ps1 lint
```

Run a full simulation with the project defaults:

```powershell
.\tasks.ps1 sim
```

For a short deterministic smoke run, call Python directly:

```powershell
.\.venv\Scripts\python.exe offloading.py --tasks 20 --seeds 1 --bootstrap-resamples 100 --output quick_results
```

## Local container demo

Start the edge gateway, cloud worker, Toxiproxy, Prometheus, and Grafana:

```powershell
.\tasks.ps1 demo
```

The console opens at [http://localhost:8000/console](http://localhost:8000/console). Grafana is at [http://localhost:3000](http://localhost:3000), and Prometheus is at [http://localhost:9090](http://localhost:9090). Those ports bind to loopback only. The local Grafana password is a demo default; set `GRAFANA_ADMIN_PASSWORD` in the PowerShell session before starting if you want a different local value.

Use the UI to change policy, submit a sample task, apply a Toxiproxy scenario, and run the simulated same-trace race. `good`, `poor`, `flapping`, `random-walk`, and `lossy` scenarios are described under `scenarios/`. The `lossy` preset applies a connection timeout toxic; it does not emulate random packet-level loss.

The gateway API is also available directly:

```powershell
Invoke-RestMethod http://localhost:8000/healthz
Invoke-RestMethod http://localhost:8000/policy
Invoke-RestMethod -Method Put -Uri http://localhost:8000/policy -ContentType 'application/json' -Body '{"policy":"adaptive"}'
Invoke-RestMethod -Method Post -Uri http://localhost:8000/tasks -ContentType 'application/json' -Body '{"iterations":300000,"data":"hello edge cloud"}'
Invoke-RestMethod -Method Put -Uri http://localhost:8000/scenario -ContentType 'application/json' -Body '{"name":"poor"}'
```

Run live HTTP smoke checks, including fallback after stopping the local cloud container:

```powershell
.\tasks.ps1 demo-check
```

Replay the committed historical synthetic session when a live demo is unavailable:

```powershell
.\tasks.ps1 demo-replay
```

Stop containers and leave named volumes available for the next run:

```powershell
.\tasks.ps1 down
```

`demo-offline` uses only local containers. `demo-azure` sends cloud work to a configured Azure Container App while retaining the local edge fallback. See [Azure deployment instructions](docs/AZURE_DEPLOY.md) before setting that up.

## Metrics and experimental claims

The gateway exports Prometheus metrics at `/metrics`: decisions by policy and destination, completion-time histograms, edge queue depth, cloud probe estimates, cloud in-flight work, synthetic cost accumulation, and errors. The bandwidth estimate is application-level probe throughput; the RTT estimate includes service and network overhead. Neither is a direct measurement of available link capacity.

Simulator cost is an explicit synthetic model and does not represent an Azure invoice. Live HTTP body byte counts are not wire-byte or billed-egress counts. Read `docs/AUDIT.md` before interpreting results. The project records cases where adaptive loses; it does not declare a universal winner.

## DevOps workflow

- **Packaging:** `pyproject.toml` defines the core package and direct development/service dependency pins.
- **Quality gates:** Ruff, pytest, branch coverage, simulator smoke run, and Linux/Windows CI.
- **Containers:** separate multi-stage edge and cloud images, non-root runtime users, health checks, bounded resources, and pinned direct service dependencies.
- **Observability:** Prometheus metrics, Grafana provisioning, JSON request logs, correlation IDs, and optional OpenTelemetry export when `APPLICATIONINSIGHTS_CONNECTION_STRING` is configured. The SDK follows the [Azure Monitor OpenTelemetry Python configuration](https://learn.microsoft.com/en-us/azure/azure-monitor/app/opentelemetry-configuration).
- **Supply chain:** Dependabot checks Python, Docker, Terraform, and GitHub Actions dependencies; a tag or manual workflow can publish SHA-tagged images to GHCR.
- **Infrastructure as code:** new Azure Container Apps environments are in `infra/`; `terraform/` retains the older Azure Functions prototype and its existing local state artifacts. Never run the new commands from the legacy folder.
- **Secrets:** no `.env`, API key, Terraform state, or plan belongs in Git. The Compose key is a local demo default only. Azure reads its worker key from Key Vault through a user-assigned managed identity.

## Azure

Terraform is organized into bootstrap state storage and separate `dev`/`prod` roots. The Container App uses HTTPS ingress, multiple revisions for canary traffic, scale-to-zero by default, bounded replicas, Log Analytics, Application Insights, a Key Vault secret reference, and email budget/service alerts. The region has no Terraform default. Alerts notify; they do not stop spending.

Only local formatting, initialization without a backend, and validation are part of normal CI. No workflow deploys Azure resources. Follow the manual PowerShell commands and university-tenant caveats in [docs/AZURE_DEPLOY.md](docs/AZURE_DEPLOY.md). Useful queries are in [docs/KQL.md](docs/KQL.md).

## Five-minute classroom demo

See [the presenter script](docs/DEMO.md) for click-by-click steps and what to point out at each step.
