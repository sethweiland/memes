locals {
  name_prefix = "${var.app_name}-${var.environment}"
  bucket_name = var.bucket_name_suffix != "" ? "${local.name_prefix}-meme-assets-${var.bucket_name_suffix}" : "${local.name_prefix}-meme-assets"
  
  default_tags = {
    Application = var.app_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
  
  all_tags = merge(local.default_tags, var.tags)
}

# Canonical object layout (application writers live in src/core/s3_store.py):
#
#   public/memes/templates/{id}.{ext}            # existing catalog; do not rename
#   public/memes/generated/{hash}_{stem}.jpg     # IG-ready JPEGs
#   ops/queue/daily-candidates/{YYYY-MM-DD}.json # private queue JSON
#   ops/queue/x-activity/{YYYY-MM-DD}.json       # private X drafts (Stevie)
#   ops/usage/{provider}/{YYYY}/{MM}.json        # private monthly token usage
#
# Bucket policy below grants public GetObject ONLY to var.public_prefix
# (public/memes/*). Everything under var.ops_prefix stays private.

# S3 bucket for meme assets
resource "aws_s3_bucket" "meme_assets" {
  bucket = local.bucket_name
  
  tags = local.all_tags
}

# Block public access for the bucket (we'll use bucket policy for controlled access)
resource "aws_s3_bucket_public_access_block" "meme_assets" {
  bucket = aws_s3_bucket.meme_assets.id

  # Allow public access via bucket policy (for the public prefix)
  block_public_acls       = true
  block_public_policy     = false
  ignore_public_acls      = true
  restrict_public_buckets = false
}

# Bucket policy to allow public read access to the public prefix
resource "aws_s3_bucket_policy" "meme_assets_public" {
  bucket = aws_s3_bucket.meme_assets.id

  # Ensure public access block is configured first
  depends_on = [aws_s3_bucket_public_access_block.meme_assets]

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "PublicReadGetObject"
        Effect    = "Allow"
        Principal = "*"
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.meme_assets.arn}/${var.public_prefix}*"
      }
    ]
  })
}

# Enable versioning (optional but recommended for asset management)
resource "aws_s3_bucket_versioning" "meme_assets" {
  bucket = aws_s3_bucket.meme_assets.id
  
  versioning_configuration {
    status = "Enabled"
  }
}

# Lifecycle rules to manage old versions and cleanup
resource "aws_s3_bucket_lifecycle_configuration" "meme_assets" {
  bucket = aws_s3_bucket.meme_assets.id

  rule {
    id     = "cleanup-old-versions"
    status = "Enabled"

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  rule {
    id     = "cleanup-incomplete-uploads"
    status = "Enabled"

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# CORS configuration for web uploads (if needed in future)
resource "aws_s3_bucket_cors_configuration" "meme_assets" {
  bucket = aws_s3_bucket.meme_assets.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "HEAD"]
    allowed_origins = ["*"]
    expose_headers  = ["ETag"]
    max_age_seconds = 3600
  }
}
