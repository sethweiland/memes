locals {
  name_prefix = "${var.app_name}/${var.environment}"
}

resource "aws_secretsmanager_secret" "app" {
  name                    = "${local.name_prefix}/app-secrets"
  description             = "Runtime API credentials for the bluegrass meme pipeline. Secret value is managed outside Terraform."
  recovery_window_in_days = var.recovery_window_in_days

  tags = {
    Application = var.app_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}
