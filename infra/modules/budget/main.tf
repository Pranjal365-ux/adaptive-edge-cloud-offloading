resource "azurerm_consumption_budget_resource_group" "main" {
  name              = var.name
  resource_group_id = var.resource_group_id
  amount            = var.amount_usd
  time_grain        = "Annually"
  time_period {
    start_date = format("%s-01-01T00:00:00Z", formatdate("YYYY", timestamp()))
    end_date   = format("%d-01-01T00:00:00Z", tonumber(formatdate("YYYY", timestamp())) + 1)
  }
  notification {
    enabled        = true
    threshold      = 50
    operator       = "EqualTo"
    threshold_type = "Forecasted"
    contact_emails = [var.alert_email]
  }
  notification {
    enabled        = true
    threshold      = 80
    operator       = "EqualTo"
    threshold_type = "Actual"
    contact_emails = [var.alert_email]
  }
  notification {
    enabled        = true
    threshold      = 100
    operator       = "GreaterThan"
    threshold_type = "Actual"
    contact_emails = [var.alert_email]
  }
}
