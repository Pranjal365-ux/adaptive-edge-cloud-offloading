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
    condition     = startswith(var.image, "ghcr.io/")
    error_message = "Use a public GHCR image unless registry authentication is explicitly configured."
  }
}
variable "min_replicas" {
  type    = number
  default = 0
}
variable "max_replicas" {
  type    = number
  default = 3
}
variable "application_insights_connection_string" {
  type      = string
  sensitive = true
}
variable "tags" { type = map(string) }
