variable "subscription_id" {
  type        = string
  description = "Azure subscription GUID; supply through a private tfvars file or environment."
  validation {
    condition     = can(regex("^[0-9a-fA-F-]{36}$", var.subscription_id))
    error_message = "subscription_id must be a GUID."
  }
}
variable "tenant_id" {
  type        = string
  description = "Azure tenant GUID."
  validation {
    condition     = can(regex("^[0-9a-fA-F-]{36}$", var.tenant_id))
    error_message = "tenant_id must be a GUID."
  }
}
variable "location" {
  type        = string
  description = "Azure region selected for the subscription; intentionally has no default."
  validation {
    condition     = length(trimspace(var.location)) > 0
    error_message = "Choose an Azure region supported by Container Apps."
  }
}
variable "project_name" {
  type    = string
  default = "offloadops"
  validation {
    condition     = can(regex("^[a-z0-9-]{3,14}$", var.project_name))
    error_message = "project_name must use 3-14 lowercase letters, digits or hyphens."
  }
}
variable "cloud_worker_image" {
  type        = string
  description = "Public GHCR image for the cloud worker."
  validation {
    condition     = startswith(var.cloud_worker_image, "ghcr.io/")
    error_message = "Use a public GHCR image."
  }
}
variable "api_key_secret_uri" {
  type        = string
  sensitive   = true
  description = "Versionless Key Vault secret URI; the secret value never belongs in Terraform variables."
  validation {
    condition     = startswith(var.api_key_secret_uri, "https://")
    error_message = "Use a Key Vault HTTPS secret URI."
  }
}
variable "alert_email" {
  type        = string
  description = "Email recipient for budget and service alerts."
  validation {
    condition     = can(regex("^[^@ ]+@[^@ ]+\\.[^@ ]+$", var.alert_email))
    error_message = "Enter an email address for alerts."
  }
}
variable "min_replicas" {
  type    = number
  default = 0
  validation {
    condition     = var.min_replicas >= 0
    error_message = "min_replicas cannot be negative."
  }
}
variable "max_replicas" {
  type    = number
  default = 3
  validation {
    condition     = var.max_replicas >= 1 && var.max_replicas <= 3
    error_message = "Keep the student deployment within three replicas."
  }
}
variable "budget_amount_usd" {
  type    = number
  default = 100
}
variable "tags" {
  type    = map(string)
  default = { managed_by = "terraform", project_type = "course-demo" }
}
