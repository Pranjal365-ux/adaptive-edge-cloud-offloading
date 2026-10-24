# Azure Container Apps deployment (manual)

This deployment is optional. The local Docker Compose stack is the normal development path. Terraform commands below validate and plan; this guide never runs `apply` or `destroy`. Read `docs/BLOCKERS.md` and `docs/DECISIONS.md` first. Azure budget alerts notify only; they do not cap spending.

## 1. Prerequisites

Use PowerShell, Azure CLI, Terraform 1.14.x, Docker Desktop, and an Azure subscription where you can create a resource group, storage account, Container Apps environment, Key Vault, Log Analytics, Application Insights, and budget/action group resources. Confirm region and quota support with your tenant.

```powershell
.\tasks.ps1 preflight
az login
az account show
```

The preflight is read-only. Select the intended subscription explicitly before provisioning: `az account set --subscription <subscription-id>`. Do not paste credentials, subscription secrets, API keys, or Terraform state into chat or Git.

## 2. Build and publish both images

Push the reviewed branch, then create a version tag only when you intend to publish. The GitHub workflow publishes edge and cloud images to GHCR with commit SHA and release tags, SBOM, and provenance. Verify both package pages and image pull visibility. If the packages are private, configure Azure registry authentication before continuing; the Terraform example expects pullable image references.

Use full immutable SHA image references for deployment, for example `ghcr.io/<owner>/offloadops-cloud:sha-<commit>`. Do not use `latest` for a release.

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

For one environment at a time, copy `infra/envs/dev/backend.hcl.example` to ignored `backend.hcl` and `terraform.tfvars.example` to ignored `terraform.tfvars`. Repeat under `infra/envs/prod` only if a separate environment is intended. Fill in a real, immutable cloud image, resource names, location, alert email, and the pre-created Key Vault secret URI. Never commit either local file.

The cloud worker key must already exist as a Key Vault secret. Supply only its secret URI to Terraform; the Container App reads the secret through its user-assigned managed identity and Key Vault RBAC. Keep the edge API key and cloud API key aligned in the local `demo-azure` session.

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
