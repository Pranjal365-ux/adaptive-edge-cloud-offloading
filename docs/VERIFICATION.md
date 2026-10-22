# Verification log

## Completed in this workspace

| Check | Result |
|---|---|
| Existing `python -m unittest -v` suite before core changes | 14 tests passed. |
| Current `python -m unittest -v` after core package and policy changes | 21 tests passed. |
| Simulator CLI smoke run (`20` tasks, `1` seed, `100` bootstrap resamples) | Completed; wrote legacy `summary.csv` and `tasks.csv`, plus aggregate, paired, and cost-sweep outputs. |
| Shared workload parity | SHA-256 digest parity between the new shared workload and the legacy Azure Function workload is covered by a unit test. |
| User data and state preservation | Existing Terraform state and reviewed plan were not opened, modified, or deleted. The prior dirty worktree changes were retained. |

## Not verified

- Docker image builds, Compose health, resource consumption, Prometheus scraping, Grafana dashboards, Toxiproxy scenario changes, SSE, and cloud-failure circuit-breaker behavior.
- Python 3.12, pytest coverage threshold, Ruff, and package installation. The available interpreter is Python 3.14.3; package installation was blocked by sandbox network policy.
- Terraform `fmt`, `init -backend=false`, and `validate` for bootstrap/dev/prod.
- Azure login, subscription limits, region support, permissions, actual service pricing, secret resolution, or deployment.
- GitHub Actions, GHCR visibility, image scanning, and public image pull from Azure.

Exact next commands and verification steps are in `docs/BLOCKERS.md` and `docs/AZURE_DEPLOY.md`. Do not interpret source inspection as a successful build or deployment.
