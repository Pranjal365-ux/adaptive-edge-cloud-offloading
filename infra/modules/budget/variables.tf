variable "name" { type = string }
variable "resource_group_id" { type = string }
variable "amount_usd" {
  type = number
  validation {
    condition     = var.amount_usd > 0
    error_message = "Budget must be positive."
  }
}
variable "alert_email" { type = string }
