resource "azurerm_key_vault" "main" {
  name                            = var.name
  location                        = var.location
  resource_group_name             = var.resource_group_name
  tenant_id                       = var.tenant_id
  sku_name                        = "standard"
  soft_delete_retention_days      = 7
  purge_protection_enabled        = true
  rbac_authorization_enabled      = true
  public_network_access_enabled   = true
  enabled_for_template_deployment = false
  tags                            = var.tags
}
