variable "aws_region" {
  description = "AWS region for Secrets Manager."
  type        = string
  default     = "us-east-1"
}

variable "app_name" {
  description = "Application name used for resource names."
  type        = string
  default     = "bluegrass-meme-pipeline"
}

variable "environment" {
  description = "Environment name."
  type        = string
  default     = "dev"
}

variable "recovery_window_in_days" {
  description = "Secrets Manager recovery window when deleting the secret."
  type        = number
  default     = 7
}
