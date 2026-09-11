output "app_secret_arn" {
  description = "ARN to set as BLUEGRASS_SECRET_ARN or APP_SECRET_ARN."
  value       = aws_secretsmanager_secret.app.arn
}

output "app_secret_name" {
  description = "Secrets Manager name for CLI updates."
  value       = aws_secretsmanager_secret.app.name
}
