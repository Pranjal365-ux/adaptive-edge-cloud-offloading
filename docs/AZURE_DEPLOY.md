# Azure deployment

## What this deployment hosts

The active Terraform under infra/ deploys the cloud inspection worker as an Azure Container App, with HTTPS ingress, a managed identity, Key Vault-backed API key, Log Analytics, Application Insights, and budget/service alerts. It does not deploy the browser dashboard or edge gateway. In Azure-backed demo mode, those two components still run locally in Docker and call the remote worker.

## Prerequisites

Use PowerShell, Azure CLI, Terraform 1.14.x or compatible, Docker Desktop, and an Azure subscription with permission to create the resources in infra/. Check available Container Apps quota and budget before applying.

Run .\tasks.ps1 preflight, then sign in and select the intended subscription with az login and az account set --subscription <subscription-id>. Do not paste credentials, API keys, or Terraform state into chat or Git.

## Image publishing

The GitHub Actions build-push workflow validates source and publishes edge/cloud images to GHCR when manually dispatched or when a version tag is pushed. It does not deploy Azure. Use a public, immutable cloud image reference in the Terraform variables; do not use latest for a stable deployment.

## Configure and review Terraform

Copy infra/envs/dev/backend.hcl.example and infra/envs/dev/terraform.tfvars.example to private local files with the same names without .example. Set the subscription, tenant, region, alert email, public cloud-worker image, and versionless Key Vault secret URI. The referenced Key Vault secret must exist and the current identity must be allowed to assign the worker's Key Vault Secrets User role.

Initialize, validate, and create a plan from the project root:

    terraform -chdir=infra/envs/dev init -backend-config=backend.hcl
    terraform -chdir=infra/envs/dev validate
    terraform -chdir=infra/envs/dev plan -out=dev.tfplan
    terraform -chdir=infra/envs/dev show dev.tfplan

Review every planned resource, resource name, region, network exposure, and cost before applying. Apply only a reviewed plan when you intend to create/update the Azure resources. Budget alerts notify; they do not cap spending.

After apply, get the Terraform cloud_worker_url output. Store that HTTPS URL in the Windows user environment variable AZURE_WORKER_URL and the same worker API key in CLOUD_API_KEY. Then run .\tasks.ps1 demo-azure. The script starts the local UI/edge/observability stack and opens the console. Docker Desktop must stay running in this mode.

## CI and deployment status

The ci workflow runs tests, lint, container builds, and Terraform validation. The build-push workflow can publish container images. No checked-in workflow automatically applies Terraform or updates the Container App. Deploying a new code revision requires publishing the updated cloud image and updating the Container App image through an approved operator workflow. The currently deployed Azure worker will not gain new telemetry endpoints until its image is updated.

## Operations

Check Container App revisions and readiness, Key Vault access, Log Analytics, Application Insights, and budget/action-group notifications in Azure. Use docs/KQL.md for queries. To remove resources, inspect Terraform state and a fresh destroy plan first; do not remove state storage until all environments are confirmed retired.