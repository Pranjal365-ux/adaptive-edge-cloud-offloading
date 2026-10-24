# CI/CD workflow

## What runs

- `.github/workflows/ci.yml` runs lint, tests with coverage, a simulator smoke run, container builds, and Terraform formatting/validation on the configured branch pushes and pull requests. Terraform validation does not use Azure credentials or apply infrastructure.
- `.github/workflows/build-push.yml` runs the Python quality gates before publishing the edge and cloud images to GHCR. Version tags such as `v1.2.3` are published with a release tag and a full immutable `sha-<commit>` tag. Publishing does not deploy to Azure.
- `.github/workflows/deploy-azure.yml` is a manually started, protected deployment from `main` of one full-SHA cloud image to an existing Azure Container App. It checks that the new revision runs and that its `/ready` endpoint responds. It does not create infrastructure, deploy the edge gateway, or run Terraform apply.

This split gives the release artifact a reviewable boundary: CI validates the source, publishing creates immutable images, and an operator chooses the exact image to deploy. Configure the GitHub `azure-production` environment with a required reviewer before using the deployment workflow.

## Azure and GitHub setup

Use GitHub Actions OpenID Connect (OIDC) federation rather than giving GitHub a client secret, publish profile, or Azure password. Create or select a Microsoft Entra application/service principal for GitHub Actions and add a federated credential with:

- Issuer: `https://token.actions.githubusercontent.com`
- Audience: `api://AzureADTokenExchange`
- Subject: `repo:<OWNER>/<REPOSITORY>:environment:azure-production`

Grant that identity only the permissions required to update the existing cloud-worker Container App. Scope the role assignment to that Container App where possible. Create the `azure-production` environment in GitHub repository settings and configure a required reviewer.

Add these **environment variables** to `azure-production` (these are identifiers and configuration, not credentials):

| Variable | Value |
|---|---|
| `AZURE_CLIENT_ID` | Client ID of the federated Entra application |
| `AZURE_TENANT_ID` | Entra tenant ID |
| `AZURE_SUBSCRIPTION_ID` | Subscription containing the existing Container App |
| `AZURE_RESOURCE_GROUP` | Resource group containing that app |
| `AZURE_CLOUD_APP_NAME` | Existing cloud-worker Container App name |

Before deploying, provision the Azure infrastructure with the reviewed Terraform process in [the Azure deployment guide](AZURE_DEPLOY.md). The worker image must be pullable by Azure Container Apps. The current Terraform module does not configure GHCR credentials, so either make the GHCR cloud package public or separately configure a supported registry pull identity before deployment.

## Release and deploy

1. Push a reviewed commit to GitHub and wait for CI to pass.
2. To publish a release, create and push a semantic version tag, for example `v1.2.3`. The build/publish workflow repeats quality checks before it publishes both container images.
3. Copy the full immutable cloud image tag (`sha-<40-character commit SHA>`) from the workflow summary.
4. In GitHub Actions, run **Deploy cloud worker to Azure**, enter that exact image tag, and approve the protected environment deployment.
5. Confirm the deployment job's revision and `/ready` smoke check succeed. Monitor the revision and telemetry in Azure before closing the release.

Do not paste credentials into chat, workflow files, or command-line arguments. This workflow needs no long-lived Azure secret. If OIDC federation, environment protection, the existing Container App, or image pull access is not ready, the deployment job should remain blocked until that setup is complete.
