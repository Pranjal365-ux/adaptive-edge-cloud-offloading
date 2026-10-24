terraform {
  backend "azurerm" {}
  required_version = ">= 1.9.0, < 2.0.0"
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "= 4.81.0" }
    random  = { source = "hashicorp/random", version = "= 3.9.1" }
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

resource "random_string" "suffix" {
  length  = 6
  lower   = true
  upper   = false
  numeric = true
  special = false
}

locals {
  name = "${var.project_name}-${random_string.suffix.result}"
  tags = merge(var.tags, { environment = "dev", project = var.project_name })
}

resource "azurerm_resource_group" "main" {
  name     = "rg-${local.name}"
  location = var.location
  tags     = local.tags
}

module "monitoring" {
  source              = "../../modules/monitoring"
  name                = local.name
  location            = var.location
  resource_group_name = azurerm_resource_group.main.name
  alert_email         = var.alert_email
  tags                = local.tags
}

module "container_app_env" {
  source                    = "../../modules/container_app_env"
  name                      = "cae-${local.name}"
  location                  = var.location
  resource_group_name       = azurerm_resource_group.main.name
  log_analytics_workspace_id = module.monitoring.workspace_id
  tags                      = local.tags
}

module "keyvault" {
  source              = "../../modules/keyvault"
  name                = "kv${replace(local.name, "-", "")}" 
  location            = var.location
  resource_group_name = azurerm_resource_group.main.name
  tenant_id           = var.tenant_id
  tags                = local.tags
}

module "cloud_worker" {
  source                               = "../../modules/cloud_worker"
  name                                 = "ca-${local.name}-cloud"
  location                             = var.location
  resource_group_name                  = azurerm_resource_group.main.name
  container_app_environment_id        = module.container_app_env.id
  key_vault_id                         = module.keyvault.id
  api_key_secret_uri                   = var.api_key_secret_uri
  image                                = var.cloud_worker_image
  min_replicas                         = var.min_replicas
  max_replicas                         = var.max_replicas
  application_insights_connection_string = module.monitoring.application_insights_connection_string
  tags                                 = local.tags
}

module "budget" {
  source           = "../../modules/budget"
  name             = "${local.name}-budget"
  resource_group_id = azurerm_resource_group.main.id
  amount_usd       = var.budget_amount_usd
  alert_email      = var.alert_email
}

resource "azurerm_monitor_metric_alert" "http_5xx" {
  name                = "${local.name}-http-5xx"
  resource_group_name = azurerm_resource_group.main.name
  scopes              = [module.cloud_worker.id]
  description         = "Container App request failures exceed the configured alert threshold."
  severity            = 2
  frequency           = "PT5M"
  window_size         = "PT15M"
  criteria {
    metric_namespace = "Microsoft.App/containerApps"
    metric_name      = "Requests"
    aggregation      = "Count"
    operator         = "GreaterThan"
    threshold        = 10
  }
  action { action_group_id = module.monitoring.action_group_id }
  tags = local.tags
}

output "resource_group_name" { value = azurerm_resource_group.main.name }
output "cloud_worker_url" {
  value       = "https://${module.cloud_worker.fqdn}"
  description = "Set this as AZURE_WORKER_URL after infrastructure is deployed."
}
