# Azure Container Apps deployment (manual)

This deployment is optional. The local Docker Compose stack is the normal development path. Terraform commands below validate and plan; this guide never runs `apply` or `destroy`. Read `docs/BLOCKERS.md` and `docs/DECISIONS.md` first. Azure budget alerts notify only; they do not cap spending.

## 1. Prerequisites

Use PowerShell, Azure CLI, Terraform 1.14 or later (below 2.0), Docker Desktop, and an Azure subscription where you can create a resource group, storage account, Container Apps environment, Key Vault, Log Analytics, Application Insights, and budget/action group resources. Confirm region and quota support with your tenant.

```powershell
.\tasks.ps1 preflight
az login
az account show
```

The preflight is read-only. Select the intended subscription explicitly before provisioning: `az account set --subscription <subscription-id>`. Do not paste credentials, subscription secrets, API keys, or Terraform state into chat or Git.

## 2. Build and publish both images

Push the reviewed branch, then create a version tag only when you intend to publish. The GitHub workflow publishes edge and cloud images to GHCR with commit SHA and release tags, SBOM, and provenance. The dev Terraform stack also creates a private Basic Azure Container Registry; its Container App uses a user-assigned managed identity for `AcrPull`. The post-CI Azure workflow builds and publishes the tested cloud-worker image to this ACR.

Use full immutable SHA image references for deployment, for example `offloadopskfopl1.azurecr.io/offloadops-cloud:sha-<40-character-commit>`. Do not use `latest` for a release.

## 3. Bootstrap remote state

Create a dedicated state resource group and globally unique storage account name. Copy `infra/bootstrap/terraform.tfvars.example` to the ignored local file `infra/bootstrap/terraform.tfvars`, then fill in the resource group, region, and storage account name.

```powershell
Copy-Item infra/bootstrap/terraform.tfvars.example infra/bootstrap/terraform.tfvars
# Edit infra/bootstrap/terraform.tfvars with your approved values.
terraform -chdir=infra/bootstrap init
terraform -chdir=infra/bootstrap validate
terraform -chdir=infra/bootstrap plan -out=bootstrap.tfplan
terraform -chdir=infra/bootstrap show bootstrap.tfplan
```

Only after reviewing the plan and confirming the subscription, region, names, and expected cost should you apply the bootstrap plan yourself. Keep its state storage private and enable the recommended storage protections. Then record the backend resource-group, storage-account, container, and key values locally.

## 4. Configure dev or prod

For one environment at a time, copy `infra/envs/dev/backend.hcl.example` to ignored `backend.hcl` and `terraform.tfvars.example` to ignored `terraform.tfvars`. Repeat under `infra/envs/prod` only if a separate environment is intended. Fill in an immutable cloud image tag, location, alert email, and the versionless Key Vault secret URI. The dev ACR name and Container App resource group/name are printed as Terraform outputs or can be read from Azure after the initial provisioning. Never commit either local file.

The cloud worker key must already exist as a Key Vault secret. Standard workload-profile Container Apps can reference it through the worker managed identity and Key Vault RBAC. The current dev environment is Azure Container Apps Express, which rejects Key Vault secret references. For this dev deployment, keep the key in Key Vault and set it in the Windows user environment as CLOUD_API_KEY; Terraform passes it to the app through the sensitive TF_VAR_api_key_value variable. Terraform state still contains secret values, so protect state storage and delete generated plan files after applying. The worker uses single-revision mode in Express. Keep the edge API key and cloud API key aligned in the local demo-azure session.

```powershell
terraform -chdir=infra/envs/dev init -backend-config=backend.hcl
terraform -chdir=infra/envs/dev validate
terraform -chdir=infra/envs/dev plan -out=dev.tfplan
terraform -chdir=infra/envs/dev show dev.tfplan
```

Review every resource and cost implication. Applying infrastructure is a deliberate operator action outside CI. After apply, configure the local edge gateway with the Container App HTTPS URL and matching API key, then use `.\tasks.ps1 demo-azure`. Do not expose local demo ports beyond loopback.

## 5. Operations and teardown

Check Container App revisions, replica count, readiness, Log Analytics, Application Insights, Key Vault access, and budget notifications in Azure. Use the queries in `docs/KQL.md`. Canary revisions require an explicit traffic split before they receive production traffic.

To remove resources, first inspect Terraform state and a fresh destroy plan. The repository and CI do not run destroy automatically. Keep or delete the state storage only after confirming that every environment and operator no longer needs it.
