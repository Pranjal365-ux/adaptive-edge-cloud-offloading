# CI/CD workflow

## What runs

- `.github/workflows/ci.yml` runs lint, tests with coverage, a simulator smoke run, container builds, and Terraform formatting/validation on the configured branch pushes and pull requests. Terraform validation does not use Azure credentials or apply infrastructure.
- `.github/workflows/build-push.yml` runs the Python quality gates before publishing the edge and cloud images to GHCR. Version tags such as `v1.2.3` are published with a release tag and a full immutable `sha-<commit>` tag. Publishing does not deploy to Azure.
- `.github/workflows/deploy-azure.yml` runs after successful CI on `main`, builds that tested cloud-worker commit, pushes its immutable SHA image to Azure Container Registry, updates the Azure Container App, and verifies the revision and `/ready` endpoint. Manual dispatch supports rollback to an existing immutable ACR image. Infrastructure provisioning remains a reviewed Terraform operation; the edge gateway remains local.

CI gates the release: the CD workflow only builds and deploys after the `CI` workflow succeeds on `main`. Configure the GitHub `azure-production` environment with a required reviewer before enabling deployment.

## Azure and GitHub setup

Use GitHub Actions OpenID Connect (OIDC) federation rather than giving GitHub a client secret, publish profile, or Azure password. Create or select a Microsoft Entra application/service principal for GitHub Actions and add a federated credential with:

- Issuer: `https://token.actions.githubusercontent.com`
- Audience: `api://AzureADTokenExchange`
- Subject: `repo:<OWNER>/<REPOSITORY>:environment:azure-production`

Grant that identity `AcrPush` on the project ACR and `Container App Contributor` scoped to the cloud-worker Container App. Create the `azure-production` environment in GitHub repository settings and configure a required reviewer.

Add these **environment variables** to `azure-production` (these are identifiers and configuration, not credentials):

| Variable | Value |
|---|---|
| `AZURE_CLIENT_ID` | Client ID of the federated Entra application |
| `AZURE_TENANT_ID` | Entra tenant ID |
| `AZURE_SUBSCRIPTION_ID` | Subscription containing the existing Container App |
| `AZURE_RESOURCE_GROUP` | Resource group containing that app |
| `AZURE_CLOUD_APP_NAME` | Cloud-worker Container App name |
| `AZURE_ACR_NAME` | ACR name created by the dev Terraform stack |

Before deploying, provision the Azure infrastructure with the reviewed Terraform process in [the Azure deployment guide](AZURE_DEPLOY.md). The dev Terraform stack creates a private Basic ACR, and the Container App pulls from it with a user-assigned managed identity granted `AcrPull`; no registry password is stored in Terraform or GitHub.

## Release and deploy

1. Push a reviewed commit to `main` and wait for CI to pass.
2. After successful CI, GitHub Actions builds the exact tested cloud-worker commit, tags it `sha-<full commit SHA>`, pushes it to ACR, deploys it to the Container App, and checks the revision and `/ready` endpoint.
3. For rollback, manually run **Deploy cloud worker to Azure** with an existing full immutable ACR SHA tag.
Do not paste credentials into chat, workflow files, or command-line arguments. This workflow needs no long-lived Azure secret. If OIDC federation, environment protection, the existing Container App, or image pull access is not ready, the deployment job should remain blocked until that setup is complete.
