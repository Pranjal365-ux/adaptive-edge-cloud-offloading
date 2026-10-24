resource "azurerm_user_assigned_identity" "worker" {
  name                = "${var.name}-identity"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags
}

resource "azurerm_role_assignment" "read_worker_secret" {
  count                = var.api_key_value == "" ? 1 : 0
  scope                = var.key_vault_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.worker.principal_id
}

resource "azurerm_role_assignment" "pull_image" {
  count                = var.registry_id == "" ? 0 : 1
  scope                = var.registry_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.worker.principal_id
}

resource "azurerm_container_app" "worker" {
  name                         = var.name
  container_app_environment_id = var.container_app_environment_id
  resource_group_name          = var.resource_group_name
  revision_mode                = var.revision_mode
  dynamic "registry" {
    for_each = var.registry_server == "" ? [] : [var.registry_server]
    content {
      server   = registry.value
      identity = azurerm_user_assigned_identity.worker.id
    }
  }
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.worker.id]
  }
  dynamic "secret" {
    for_each = var.api_key_value != "" ? [true] : []
    content {
      name  = "worker-api-key"
      value = var.api_key_value
    }
  }
  dynamic "secret" {
    for_each = var.api_key_value == "" ? [true] : []
    content {
      name                = "worker-api-key"
      key_vault_secret_id = var.api_key_secret_uri
      identity            = azurerm_user_assigned_identity.worker.id
    }
  }
  ingress {
    external_enabled = true
    target_port      = 8081
    transport        = "http"
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }
  template {
    min_replicas = var.min_replicas
    max_replicas = var.max_replicas
    container {
      name   = "cloud-worker"
      image  = var.image
      cpu    = 0.25
      memory = "0.5Gi"
      env {
        name        = "CLOUD_API_KEY"
        secret_name = "worker-api-key"
      }
      env {
        name  = "CLOUD_WORKERS"
        value = "1"
      }
      env {
        name  = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        value = var.application_insights_connection_string
      }
      liveness_probe {
        transport        = "HTTP"
        port             = 8081
        path             = "/health"
        interval_seconds = 30
      }
      readiness_probe {
        transport        = "HTTP"
        port             = 8081
        path             = "/ready"
        interval_seconds = 10
      }
    }
    http_scale_rule {
      name                = "http-concurrency"
      concurrent_requests = "20"
    }
  }
  tags       = var.tags
  depends_on = [azurerm_role_assignment.read_worker_secret, azurerm_role_assignment.pull_image]
}
