variable "app_name" {
  description = "Application name prefix for resources"
  type        = string
  default     = "bluegrass-meme-pipeline"
}

variable "environment" {
  description = "Environment name (dev, prod, etc.)"
  type        = string
  default     = "dev"
}

variable "bucket_name_suffix" {
  description = "Suffix for the S3 bucket name (full name will be {app_name}-{environment}-meme-assets-{suffix})"
  type        = string
  default     = ""
}

variable "public_prefix" {
  description = "S3 prefix that will be publicly readable (Instagram-safe JPEGs + template catalog)"
  type        = string
  default     = "public/memes/"
}

variable "ops_prefix" {
  description = "Private prefix for queue JSON and token usage. Not in the public bucket policy. App IAM must allow Get/Put/List on this prefix."
  type        = string
  default     = "ops/"
}

variable "tags" {
  description = "Additional tags to apply to resources"
  type        = map(string)
  default     = {}
}
