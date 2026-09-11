# Meme Assets S3 Bucket

Terraform module for creating an S3 bucket to host meme images with public HTTPS access for Instagram publishing.

## Architecture

- **S3 bucket** with public read access restricted to `public/memes/*` prefix
- **Versioning** enabled for asset management
- **Lifecycle rules** to clean up old versions and incomplete uploads
- **CORS** configuration for potential browser uploads

## Security

- Public access is limited to the `public/memes/` prefix only
- No public ACLs allowed (bucket policy controls access)
- Objects outside the public prefix remain private

## Setup

### 1. Initialize Terraform

```bash
cd infra/meme-assets
terraform init
```

### 2. Plan and Apply

```bash
terraform plan
terraform apply
```

The bucket name will be: `bluegrass-meme-pipeline-dev-meme-assets` (by default)

### 3. Capture Outputs

```bash
terraform output bucket_name
terraform output public_base_url
```

### 4. Configure Application

Add to `.env`:

```bash
MEME_ASSETS_BUCKET=bluegrass-meme-pipeline-dev-meme-assets
MEME_ASSETS_PUBLIC_BASE_URL=https://bluegrass-meme-pipeline-dev-meme-assets.s3.amazonaws.com
AWS_DEFAULT_REGION=us-east-1
```

Or update AWS Secrets Manager:

```bash
aws secretsmanager put-secret-value \
  --secret-id bluegrass-meme-pipeline/dev/app-secrets \
  --secret-string file://<(jq '. + {
    "MEME_ASSETS_BUCKET": "bluegrass-meme-pipeline-dev-meme-assets",
    "MEME_ASSETS_PUBLIC_BASE_URL": "https://bluegrass-meme-pipeline-dev-meme-assets.s3.amazonaws.com"
  }' secrets.local.json)
```

## IAM Permissions Required

The application runtime identity (EC2 instance profile, Lambda role, or local AWS credentials) needs:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::bluegrass-meme-pipeline-dev-meme-assets/public/memes/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:ListBucket"
      ],
      "Resource": "arn:aws:s3:::bluegrass-meme-pipeline-dev-meme-assets",
      "Condition": {
        "StringLike": {
          "s3:prefix": "public/memes/*"
        }
      }
    }
  ]
}
```

## Variables

| Name | Description | Default |
|------|-------------|---------|
| `app_name` | Application name prefix | `bluegrass-meme-pipeline` |
| `environment` | Environment name | `dev` |
| `bucket_name_suffix` | Optional bucket name suffix | `""` |
| `public_prefix` | Public readable prefix | `public/memes/` |

## Outputs

| Name | Description |
|------|-------------|
| `bucket_name` | S3 bucket name |
| `bucket_arn` | S3 bucket ARN |
| `public_base_url` | Base HTTPS URL for public objects |
| `public_prefix` | Public prefix path |
| `public_url_template` | URL template for objects |

## Testing Public Access

After deployment:

```bash
# Upload a test image
aws s3 cp test.jpg s3://bluegrass-meme-pipeline-dev-meme-assets/public/memes/test.jpg

# Verify public HTTPS access
curl -I https://bluegrass-meme-pipeline-dev-meme-assets.s3.amazonaws.com/public/memes/test.jpg
# Should return 200 OK

# Test non-public prefix (should fail)
aws s3 cp test.jpg s3://bluegrass-meme-pipeline-dev-meme-assets/private/test.jpg
curl -I https://bluegrass-meme-pipeline-dev-meme-assets.s3.amazonaws.com/private/test.jpg
# Should return 403 Forbidden
```

## CloudFront Alternative (Optional)

For better performance and custom domain support, you can add CloudFront:

1. Create a CloudFront distribution pointing to the S3 bucket
2. Set origin path to `/public/memes`
3. Use the CloudFront URL as `MEME_ASSETS_PUBLIC_BASE_URL`

This is not required for basic functionality but recommended for production.

## Cleanup

To destroy resources:

```bash
terraform destroy
```

**Warning**: This will delete the bucket and all objects. Back up any important assets first.
