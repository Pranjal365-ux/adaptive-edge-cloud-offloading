# Design decisions

| Decision | Reason |
|---|---|
| Keep `offloading.py` as a compatibility wrapper | Existing course commands and imports continue to work while the simulator lives under `offloader/`. |
| Separate `adaptive` from `adaptive_oracle` | `adaptive` uses EWMA link probes, queue counts, and online service-rate estimates. `adaptive_oracle` can inspect exact simulator state and is only an upper-bound comparison. |
| Keep simulator and live service evidence separate | Simulator inputs are synthetic; container timings are measurements from the local machine. Azure measurements are a separate optional stage. |
| Use nearest-rank p95 and paired seeded differences | Small samples are discrete; matched traces make policy deltas interpretable. The bootstrap seed is deterministic and stored in run metadata. |
| Model cloud cost as configurable synthetic inputs | Current simulation rate is a teaching assumption, not provider billing. Real pricing depends on account, region, plan, free grants, resource allocation, and egress tier. |
| Execute CPU work in process pools | CPU-bound Python workloads should not be modeled as parallel merely because they run in an async server or thread pool. |
| Do not retry timed task submissions automatically | A client timeout can happen after remote work completed; blind retry could perform and charge for duplicate work. The gateway falls back locally and reports the failure. Health and throughput probes back off after failures. |
| Keep local service ports bound to loopback | The demo API and dashboards are for a classroom laptop, not an internet-facing deployment. The Azure Container App is the separate HTTPS ingress path. |
| Keep the older `terraform/` tree intact | It already contains local state and a reviewed plan in this checkout. New Container Apps infrastructure uses `infra/`; the older Azure Functions prototype is a reference only. |
| Keep Azure operations manual | CI validates Terraform but never applies or destroys resources. Budget alerts are notifications, not spending caps. |
| Use `codex/offloadops` as requested | The provided checkout was already dirty on another branch. A new branch was created from that current HEAD so its existing edits remain present. |

## Scope still requiring follow-up

The live experiment runner still targets the legacy Azure Functions API. The new Container Apps worker and local gateway provide a separate service demo; the live benchmark protocol should be adapted to the container API before claiming the same calibrated comparison across both deployment paths.
