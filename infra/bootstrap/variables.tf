variable "subscription_id" { type = string }
variable "location" {
  type = string
  validation {
    condition     = length(trimspace(var.location)) > 0
    error_message = "Choose an Azure region."
  }
}
variable "project_name" {
  type    = string
  default = "offloadops"
}
variable "tags" {
  type    = map(string)
  default = { managed_by = "terraform", purpose = "terraform-state" }
}
