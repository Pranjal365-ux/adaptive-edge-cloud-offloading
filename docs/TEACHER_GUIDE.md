# Project Structure & Teacher Walkthrough Guide

Use this quick-reference guide during your viva/presentation to explain the architecture, demonstrate the live system, and show the examiner your cloud deployment.

---

## 1. What This Project Actually Is

**OffloadOps** is an **Adaptive Edge-to-Cloud Task Offloader** designed for Industrial Computer Vision (Surface-Defect Inspection on Manufactured Parts).

### The Real-World Engineering Problem
- **Edge Device (Local Gateway):** Fast, zero-bandwidth latency, but bounded compute (limited CPU/workers). Queues build up under high load.
- **Cloud Worker (Azure Container Apps):** Elastic, scalable, high-throughput compute, but incurs network transit time (uploading high-res images) and cloud costs.
- **The Core Solution:** An intelligent edge gateway that monitors real-time network latency (EWMA RTT via Toxiproxy), available throughput, and local vs. cloud worker queues to make optimal, per-task routing decisions (*Process locally* vs. *Offload to Cloud*). If the cloud connection degrades or severs, a built-in **Circuit Breaker** automatically falls back to local execution.

---

## 2. Clean Project Architecture Map

Here is the clean breakdown of the repository to show your professor:

```text
offloadops/
├── services/               # 🚀 LIVE RUNTIME MICROSERVICES
│   ├── edge_gateway.py     # FastAPI edge gateway: adaptive policy engine & circuit breaker
│   ├── cloud_worker.py     # Cloud worker: surface-defect anomaly detector & health API
│   └── console.html        # Interactive browser UI for live image testing & metrics
│
├── offloader/              # 🧠 CORE PROCESSING & ALGORITHMS
│   ├── inspection.py       # Deterministic pixel neighborhood contrast inspection heuristic
│   ├── tasks.py            # Unified task dispatcher
│   ├── costs.py            # Synthetic cost model
│   └── workload.py         # Deterministic CPU compute benchmark
│
├── infra/                  # ☁️ INFRASTRUCTURE AS CODE (TERRAFORM)
│   ├── modules/            # Reusable modules (Container Apps, Key Vault, Monitoring, Budget)
│   ├── envs/dev/           # Active development environment deployed to Azure
│   └── bootstrap/          # Azure storage backend for remote .tfstate locking
│
├── .github/workflows/      # 🔄 DEVOPS & CI/CD PIPELINES
│   ├── ci.yml              # Automated quality gates (Pytest, Ruff, Container build, TF validate)
│   ├── deploy-azure.yml    # Continuous Deployment: builds tested commit & deploys to ACA
│   └── build-push.yml      # Container packaging & image publishing
│
├── toxiproxy/              # ⚡ CHAOS ENGINEERING & NETWORK SIMULATION
│   └── config.json         # Emulates high latency, packet loss, bandwidth throttling
│
├── monitoring/             # 📊 SRE & OBSERVABILITY
│   ├── prometheus.yml      # Time-series metrics collection configuration
│   └── grafana/            # Pre-provisioned dashboards (worker utilization, RTT, queue depth)
│
├── tests/                  # 🧪 AUTOMATED TESTS & VERIFICATION
│   ├── test_inspection.py  # Computer vision & defect detection test cases
│   ├── test_integrity.py   # System invariants & regression checks
│   └── test_live.py        # Edge gateway routing & fallback tests
│
├── offloading.py           # 📈 Monte Carlo discrete-event simulator (baseline comparisons)
├── docker-compose.yml      # Complete local reproducible multi-container stack
└── tasks.ps1               # Automated developer task runner
```

---

## 3. Live Azure Cloud Deployment

The cloud worker is already live and running on serverless **Azure Container Apps**:

- **Live Azure Worker URL:**  
  `https://ca-offloadops-kfopl1-cloud.bluesand-000252f5.centralindia.azurecontainerapps.io`
- **Readiness Verification Endpoint:**  
  `https://ca-offloadops-kfopl1-cloud.bluesand-000252f5.centralindia.azurecontainerapps.io/ready`
- **Service Version & Replica Status:**  
  `https://ca-offloadops-kfopl1-cloud.bluesand-000252f5.centralindia.azurecontainerapps.io/version`
- **Azure Region:** `centralindia`
- **Resource Group:** `rg-offloadops-kfopl1`

---

## 4. How to Run the 5-Minute Presentation for Your Teacher

### Step 1: Open the Interactive Local Console
In PowerShell, run:
```powershell
.\tasks.ps1 demo
```
This launches the Docker Compose stack (Edge Gateway, Cloud Worker, Toxiproxy, Prometheus, Grafana) and opens your browser at **`http://localhost:8000/console`**.

### Step 2: Demonstrate Edge vs. Cloud Offloading
1. Click **Generate sample part** or upload an image.
2. Select **Adaptive** policy and click **Inspect surface**.
3. Point out:
   - The annotated image highlighting surface scratches.
   - The decision metric explaining *why* it chose Edge or Cloud based on queue size and latency.
4. Click **Compare edge + cloud** to run both simultaneously and show the latency breakdown.

### Step 3: Demonstrate Chaos Engineering & Circuit Breaker (The "Wow" Factor)
1. In the console, switch the network scenario from `good` to `poor` or `lossy` (powered by Toxiproxy).
2. Show how the measured RTT increases. The adaptive policy will immediately shift heavy image processing away from the slow cloud link to local edge execution.
3. If the cloud container is killed (`docker compose stop cloud`), show the teacher that the **Circuit Breaker** trips, preventing cascading failures and instantly executing tasks locally with zero downtime.

---

## 5. CD Pipeline Fix & Clarification

### Why the CD Was Blocked & How It Is Configured
In [`.github/workflows/deploy-azure.yml`](file:///c:/dev/offloadops/.github/workflows/deploy-azure.yml), the deployment job targets a GitHub Environment named `azure-production`. It uses passwordless **GitHub Actions OIDC Federation** with Azure instead of fragile long-lived passwords.

The pipeline is triggered automatically whenever `CI` succeeds on `main`, or via manual `workflow_dispatch`. 

For the CD job to execute in GitHub Actions:
1. Go to your GitHub repository: `https://github.com/Pranjal365-ux/adaptive-edge-cloud-offloading`.
2. Navigate to **Settings** $\rightarrow$ **Environments** $\rightarrow$ Create `azure-production`.
3. Add the following repository/environment variables:
   - `AZURE_CLIENT_ID`: (Your Entra App Client ID for GitHub OIDC)
   - `AZURE_TENANT_ID`: `29bebd42-f1ff-4c3d-9688-067e3460dc1f`
   - `AZURE_SUBSCRIPTION_ID`: `a2a44ef0-d95e-4ca6-82a8-d0e057f8b75e`
   - `AZURE_RESOURCE_GROUP`: `rg-offloadops-kfopl1`
   - `AZURE_CLOUD_APP_NAME`: `ca-offloadops-kfopl1-cloud`
   - `AZURE_ACR_NAME`: `offloadopskfopl1`
