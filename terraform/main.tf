terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 4.0, < 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = ">= 2.4, < 3.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.6, < 4.0"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

variable "subscription_id" {
  description = "The Azure subscription to use for the project"
  type        = string
}

variable "location" {
  description = "Azure region that supports Linux Consumption Functions in your subscription"
  type        = string
  default     = "centralindia"
}

variable "project_name" {
  description = "Prefix for project resource names"
  type        = string
  default     = "edgeoffloading"
}

resource "random_string" "suffix" {
  length  = 6
  lower   = true
  upper   = false
  numeric = true
  special = false
}

locals {
  app_name     = "${var.project_name}-${random_string.suffix.result}"
  storage_name = "edgeoff${random_string.suffix.result}"
}

resource "azurerm_resource_group" "project" {
  name     = "rg-${local.app_name}"
  location = var.location
}

resource "azurerm_storage_account" "functions" {
  name                     = local.storage_name
  resource_group_name      = azurerm_resource_group.project.name
  location                 = azurerm_resource_group.project.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
}

resource "azurerm_service_plan" "functions" {
  name                = "plan-${local.app_name}"
  resource_group_name = azurerm_resource_group.project.name
  location            = azurerm_resource_group.project.location
  os_type             = "Linux"
  sku_name            = "Y1"
}

data "archive_file" "code" {
  type        = "zip"
  source_dir  = "${path.module}/../azure_function"
  output_path = "${path.module}/function.zip"
  excludes    = ["__pycache__", "local.settings.json", ".venv"]
}

resource "azurerm_linux_function_app" "worker" {
  name                        = local.app_name
  resource_group_name         = azurerm_resource_group.project.name
  location                    = azurerm_resource_group.project.location
  service_plan_id             = azurerm_service_plan.functions.id
  storage_account_name        = azurerm_storage_account.functions.name
  storage_account_access_key  = azurerm_storage_account.functions.primary_access_key
  functions_extension_version = "~4"
  https_only                  = true
  zip_deploy_file             = data.archive_file.code.output_path

  app_settings = {
    FUNCTIONS_WORKER_RUNTIME       = "python"
    SCM_DO_BUILD_DURING_DEPLOYMENT = "true"
    PYTHON_THREADPOOL_THREAD_COUNT = "1"
    FUNCTIONS_WORKER_PROCESS_COUNT = "1"
    ENABLE_ORYX_BUILD              = "true"
  }

  site_config {
    application_stack {
      python_version = "3.12"
    }
  }
}

output "function_url" {
  description = "Pass this URL to live_probe.py"
  value       = "https://${azurerm_linux_function_app.worker.default_hostname}/api/compute"
}

output "function_app_name" {
  value = azurerm_linux_function_app.worker.name
}

output "resource_group_name" {
  value = azurerm_resource_group.project.name
}
