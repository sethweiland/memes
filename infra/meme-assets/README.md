# Meme Assets S3 Bucket

Terraform module for the shared meme-ops bucket: public Instagram JPEGs plus private ops JSON (daily queue and token usage).

All application writes go through `src/core/s3_store.py` (`S3Store` + `BucketLayout`).

## Layout

```
s3://bluegrass-meme-pipeline-dev-meme-assets/
├── public/memes/                         # PUBLIC GetObject (Instagram)
│   ├── templates/{id}.{ext}              # existing catalog (~3195 objects) — do not rename
│   └── generated/{hash}_{stem}.jpg       # new IG-ready JPEGs from MemeAssetUploader
└── ops/                                  # PRIVATE (no public GET)
    ├── projects/board.json
    ├── queue/daily-candidates/{YYYY-MM-DD}.json
    ├── queue/x-activity/{YYYY-MM-DD}.json
    ├── grok-bot/routines.json
    └── usage/{provider}/{YYYY}/{MM}.json
```

| Prefix | Visibility | Writer | Notes |
|--------|------------|--------|--------|
| `public/memes/templates/` | public | catalog harvest (existing) | Keep in place; no migration |
| `public/memes/generated/` | public | `MemeAssetUploader` | Default `MEME_ASSETS_PUBLIC_PREFIX` |
| `ops/projects/` | private | `ProjectBoard` | Kanban (`board.json`). Seeded from `config/tenant.yaml` when missing. |
| `ops/queue/` | private | `QueueStorage` / `XActivityQueue` | Daily candidates + X drafts |
| `ops/grok-bot/` | private | `GrokBotRoutines` | Recurring routine catalog (`routines.json`) |
| `ops/usage/` | private | `token_tracker` | Monthly JSON, ETag concurrency. Each event has `project`; rollup is on Spend, not a per-project prefix. |

Legacy (read-only fallback, not written by current code):

- `queue/daily-candidates/{date}.json` — PR #7 path
- `data/token_usage.jsonl` — local-only token log

**Never** put queue or usage JSON under `public/memes/`. That prefix is world-readable.

## Architecture

- **S3 bucket** with public read access restricted to `public/memes/*`
- **Versioning** enabled
- **Lifecycle rules** to clean up old versions and incomplete uploads
- **CORS** for GET/HEAD (ETag exposed for conditional writes)

## Security

- Public access is limited to the `public/memes/` prefix only
- No public ACLs allowed (bucket policy controls access)
- Everything under `ops/` remains private

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

The application runtime identity (Mac generate, Fly Spend, or any host with AWS creds) needs **both** the public meme prefix and the private `ops/` prefix. Queue and usage writes fail if IAM only allows `public/memes/*`.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicMemeObjects",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::bluegrass-meme-pipeline-dev-meme-assets/public/memes/*"
    },
    {
      "Sid": "PrivateOpsObjects",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::bluegrass-meme-pipeline-dev-meme-assets/ops/*"
    },
    {
      "Sid": "LegacyQueueRead",
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": "arn:aws:s3:::bluegrass-meme-pipeline-dev-meme-assets/queue/*"
    },
    {
      "Sid": "ListPublicAndOps",
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": "arn:aws:s3:::bluegrass-meme-pipeline-dev-meme-assets",
      "Condition": {
        "StringLike": {
          "s3:prefix": [
            "public/memes/",
            "public/memes/*",
            "ops/",
            "ops/*",
            "queue/",
            "queue/*"
          ]
        }
      }
    }
  ]
}
```

Attach the same policy (or equivalent role) to every machine that generates memes **and** to the Fly app that serves Spend. Token usage is shared only if both can read/write `ops/usage/*`.

## Variables

| Name | Description | Default |
|------|-------------|---------|
| `app_name` | Application name prefix | `bluegrass-meme-pipeline` |
| `environment` | Environment name | `dev` |
| `bucket_name_suffix` | Optional bucket name suffix | `""` |
| `public_prefix` | Public readable prefix | `public/memes/` |
| `ops_prefix` | Private ops prefix (documented; not in the public bucket policy) | `ops/` |

## Outputs

| Name | Description |
|------|-------------|
| `bucket_name` | S3 bucket name |
| `bucket_arn` | S3 bucket ARN |
| `public_base_url` | Base HTTPS URL for public objects |
| `public_prefix` | Public prefix path |
| `ops_prefix` | Private ops prefix |
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
