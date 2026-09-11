output "bucket_name" {
  description = "Name of the S3 bucket for meme assets"
  value       = aws_s3_bucket.meme_assets.bucket
}

output "bucket_arn" {
  description = "ARN of the S3 bucket"
  value       = aws_s3_bucket.meme_assets.arn
}

output "bucket_regional_domain_name" {
  description = "Regional domain name of the S3 bucket"
  value       = aws_s3_bucket.meme_assets.bucket_regional_domain_name
}

output "public_base_url" {
  description = "Base HTTPS URL for publicly accessible objects"
  value       = "https://${aws_s3_bucket.meme_assets.bucket}.s3.amazonaws.com"
}

output "public_prefix" {
  description = "Prefix within the bucket that has public read access"
  value       = var.public_prefix
}

output "ops_prefix" {
  description = "Private prefix for queue JSON and token usage (not publicly readable)"
  value       = var.ops_prefix
}

output "public_url_template" {
  description = "Template for public object URLs (replace {filename} with actual filename)"
  value       = "https://${aws_s3_bucket.meme_assets.bucket}.s3.amazonaws.com/${var.public_prefix}{filename}"
}
