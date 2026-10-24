output "id" { value = azurerm_container_app.worker.id }
output "fqdn" { value = azurerm_container_app.worker.latest_revision_fqdn }
output "identity_id" { value = azurerm_user_assigned_identity.worker.id }
