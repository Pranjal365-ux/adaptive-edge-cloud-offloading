resource "azurerm_log_analytics_workspace" "main" {
  name                = var.name
  location            = var.location
  resource_group_name = var.resource_group_name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  daily_quota_gb      = 1
  tags                = var.tags
}

resource "azurerm_application_insights" "main" {
  name                 = "${var.name}-appi"
  location             = var.location
  resource_group_name  = var.resource_group_name
  workspace_id         = azurerm_log_analytics_workspace.main.id
  application_type     = "web"
  retention_in_days    = 30
  daily_data_cap_in_gb = 1
  tags                 = var.tags
}

resource "azurerm_monitor_action_group" "email" {
  name                = "${var.name}-alerts"
  resource_group_name = var.resource_group_name
  short_name          = "offloadops"
  email_receiver {
    name          = "budget-owner"
    email_address = var.alert_email
  }
  tags = var.tags
}

