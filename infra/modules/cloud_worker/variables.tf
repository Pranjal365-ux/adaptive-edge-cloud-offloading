variable "name" { type = string }
variable "location" { type = string }
variable "resource_group_name" { type = string }
variable "container_app_environment_id" { type = string }
variable "key_vault_id" { type = string }
variable "api_key_secret_uri" {
  type      = string
  sensitive = true
}
variable "image" {
  type = string
  validation {
    condition     = startswith(var.image, "ghcr.io/") || can(regex("^[a-z0-9]+\\.azurecr\\.io/", var.image))
    error_message = "Use a GHCR image or a valid Azure Container Registry image."
  }
}
variable "registry_server" {
  type    = string
  default = ""
}
variable "registry_id" {
  type    = string
  default = ""
}
variable "min_replicas" {
  type    = number
  default = 0
}
variable "max_replicas" {
  type    = number
  default = 3
}
variable "api_key_value" {
  type      = string
  sensitive = true
  default   = ""
}

variable "revision_mode" {
  type    = string
  default = "Multiple"
}
variable "application_insights_connection_string" {
  type      = string
  sensitive = true
}
variable "tags" { type = map(string) }
