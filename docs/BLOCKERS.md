# Verification blockers

These items require the target laptop or an Azure/GitHub environment that is not available to this execution session.

| Blocker | Evidence here | PowerShell action to unblock |
|---|---|---|
| Docker engine and Compose integration | `docker` was not discoverable on the agent shell PATH, even though the supplied target-machine notes say Docker Desktop is installed and working. Images and service health were not tested. | `docker version` and `docker compose version`; then run `.\tasks.ps1 docker-build`, `.\tasks.ps1 demo`, and `.\tasks.ps1 demo-check`. |
| Python 3.12 environment | The available workspace interpreter is Python 3.14.3; the project `.venv` points to that interpreter. This differs from the supplied target-machine notes. | Preserve the existing environment, then run `Rename-Item .venv .venv-py314; py -3.12 -m venv .venv; .\tasks.ps1 setup`. |
| Pinned dependency installation | Installing `.[dev,live,services]` failed because sandbox network access to PyPI is blocked (`WinError 10013`). | In PowerShell on the laptop run `.\tasks.ps1 setup`. If it fails, keep the full pip error output and check the configured package index/proxy. |
| Terraform CLI and schema validation | `terraform` was not discoverable on the agent shell PATH. HCL was manually reviewed but not formatted or validated. | `terraform version; .\tasks.ps1 tf-validate`. Fix any provider/API schema errors before planning. |
| Azure subscription and provider registration | No Azure login, subscription, Key Vault secret, Container App, or provider registration was used or verified in this session. | Run `.\tasks.ps1 preflight`; follow the output, then read `docs/AZURE_DEPLOY.md`. |
| GitHub CI and package publication | Workflows are local files only. No GitHub account or repository was accessed. | Push `codex/offloadops` to the intended GitHub repository, inspect Actions, then trigger the build/publish workflow only when you want GHCR packages created. |

No blocker above permits skipping later verification. In particular, a successful Terraform `validate` does not prove Azure deployment, and a successful image build does not prove service behavior until `demo-check` passes.
