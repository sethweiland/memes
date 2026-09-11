# Daily Meme Candidate Queue

Human-in-the-loop workflow for reviewing and approving daily meme candidates before publishing to Instagram.

## Overview

The daily candidate queue provides a structured workflow for:
1. **Generating** a batch of meme candidates each day
2. **Reviewing** candidates in a web UI
3. **Approving** selected memes → publishes to Instagram using pre-uploaded S3 URLs

**S3-Backed Storage (Fly/Container-Friendly):**
- Candidate images uploaded to S3 at generation time
- Queue metadata stored in S3 (`ops/queue/daily-candidates/{date}.json`, private)
- Local cache maintained for backward compatibility
- No shared filesystem required between generation and web host

No memes post automatically. Every Instagram publish requires explicit human approval.

## Quick Start

### 1. Generate Today's Candidates

```bash
python scripts/generate_daily_candidates.py
```

This:
- Generates ~10 candidate memes
- Uploads each image to S3 (if configured)
- Saves queue JSON to S3 under `ops/queue/daily-candidates/{YYYY-MM-DD}.json`
- Also saves a local cache copy in `data/daily_candidates/` for backward compatibility

### 2. Review in Web UI

Navigate to: **http://localhost:5050/memes/gallery/daily-candidates/** (old `/gallery/daily-candidates/` 302s here)

- View all pending candidates
- Edit captions
- Click **✅ Approve & Post** to upload to S3 and publish to Instagram
- Click **⏭️ Skip** to mark a candidate as skipped

### 3. Approved Candidates

Once approved:
- Uses existing S3 URL from generation (no upload needed at approve-time)
- Published to Instagram via Graph API using S3 URL
- Status updated to "approved" with Instagram post link
- Queue JSON updated in S3 and local cache

## Script Usage

### Basic Generation

```bash
# Generate 10 candidates (default)
python scripts/generate_daily_candidates.py

# Generate 15 candidates
python scripts/generate_daily_candidates.py --count 15

# Specific topic
python scripts/generate_daily_candidates.py --topic "banjo tuning jokes"

# Different domain pack
python scripts/generate_daily_candidates.py --domain generic
```

### Advanced Options

```bash
python scripts/generate_daily_candidates.py \
  --count 12 \
  --domain bluegrass \
  --creativity 1.5 \
  --date 2026-09-10
```

**Options:**
- `--count N`: Number of candidates to generate (default: 10)
- `--domain NAME`: Domain pack to use (default: bluegrass)
- `--topic TEXT`: Specific topic (random if not provided)
- `--creativity FLOAT`: Creativity parameter 0.5-2.0 (default: 1.2)
- `--date YYYY-MM-DD`: Date for candidates (default: today)

## Recommended Schedule

**Weekday mornings** (9am local time):

```bash
0 9 * * 1-5 cd /path/to/memes && python scripts/generate_daily_candidates.py --count 12
```

This generates 12 fresh candidates Monday–Friday for daily review and posting throughout the day.

## Data Structure

Candidates are stored in S3 (`ops/queue/daily-candidates/{date}.json`) with local cache fallback:

```json
{
  "date": "2026-09-11",
  "topic": "mandolin vs guitar debates",
  "domain": "bluegrass",
  "generated_at": "2026-09-11T09:00:00",
  "output_dir": "output/memes/2026-09-11_090000_bluegrass",
  "total_count": 10,
  "candidates": [
    {
      "id": "2026-09-11_0",
      "index": 0,
      "template": "Drake Hotline Bling",
      "top_text": "Playing a guitar",
      "bottom_text": "Playing a mandolin (the superior instrument)",
      "caption": "Mandolin > Guitar, fight me 🎸🔥 #bluegrass #mandolin",
      "public_url": "https://bucket.s3.amazonaws.com/public/memes/abc123_drake_hotline_0.jpg",
      "s3_key": "public/memes/abc123_drake_hotline_0.jpg",
      "local_path": "output/memes/drake_hotline_0.jpg",
      "filename": "drake_hotline_0.jpg",
      "status": "pending",
      "created_at": "2026-09-11T09:15:23",
      "scores": {
        "humor": 8,
        "brand_fit": 9,
        "relatability": 7
      },
      "overall_score": 8.5
    }
  ]
}
```

### Candidate Status Values

- **`pending`**: Awaiting human review
- **`approved`**: Approved and published to Instagram
- **`skipped`**: Reviewed but not published

When approved, additional fields are added:
- `approved_at`: ISO timestamp
- `instagram_post_id`: Instagram media ID
- `instagram_permalink`: Instagram post URL

### New Fields (S3-Backed Storage)

- **`public_url`**: S3 HTTPS URL for the meme image (set at generation time)
- **`s3_key`**: S3 object key (e.g. `public/memes/abc123_meme.jpg`)
- **`local_path`**: Optional local cache path (may not exist on web host)

## S3 Setup

**Required for container deployments (Fly, Docker, etc.)** and recommended for all deployments. The queue and images are stored in S3 so generation can happen on one machine (e.g. Mac) and review/approve on another (e.g. Fly container).

See `infra/meme-assets/README.md` for full setup.

### Required Environment Variables

```bash
MEME_ASSETS_BUCKET=bluegrass-meme-pipeline-dev-meme-assets
MEME_ASSETS_PUBLIC_BASE_URL=https://bluegrass-meme-pipeline-dev-meme-assets.s3.amazonaws.com
MEME_ASSETS_PUBLIC_PREFIX=public/memes/generated/
AWS_DEFAULT_REGION=us-east-1
```

### Quick S3 Setup

1. **Deploy Terraform infrastructure:**

```bash
cd infra/meme-assets
terraform init
terraform apply
```

2. **Add bucket name to environment:**

```bash
# .env
MEME_ASSETS_BUCKET=bluegrass-meme-pipeline-dev-meme-assets
MEME_ASSETS_PUBLIC_BASE_URL=https://bluegrass-meme-pipeline-dev-meme-assets.s3.amazonaws.com
```

Or via AWS Secrets Manager:

```bash
aws secretsmanager put-secret-value \
  --secret-id bluegrass-meme-pipeline/dev/app-secrets \
  --secret-string file://<(jq '. + {
    "MEME_ASSETS_BUCKET": "bluegrass-meme-pipeline-dev-meme-assets",
    "MEME_ASSETS_PUBLIC_BASE_URL": "https://bluegrass-meme-pipeline-dev-meme-assets.s3.amazonaws.com"
  }' secrets.local.json)
```

3. **Verify IAM permissions:**

The runtime identity needs:
- `s3:PutObject` / `s3:GetObject` on `arn:aws:s3:::BUCKET_NAME/public/memes/*` and `arn:aws:s3:::BUCKET_NAME/ops/*`
- `s3:ListBucket` on `arn:aws:s3:::BUCKET_NAME` with prefix filters for `public/memes/` and `ops/`

See `infra/meme-assets/README.md` for IAM policy example.

## Web UI Routes

| Route | Description |
|-------|-------------|
| `/memes/gallery/daily-candidates/` | Review page (defaults to today) |
| `/memes/gallery/daily-candidates/?date=2026-09-10` | View specific date |
| `/memes/gallery/daily-candidates/api/candidates/<date>` | Get candidates JSON |
| `/memes/gallery/daily-candidates/api/candidates/<date>/approve/<id>` | Approve & publish |
| `/memes/gallery/daily-candidates/api/candidates/<date>/skip/<id>` | Skip candidate |
| `/gallery/daily-candidates/` | 302 → `/memes/gallery/daily-candidates/` |

## Troubleshooting

### "No candidates for {date}"

Generate candidates first:

```bash
python scripts/generate_daily_candidates.py
```

### "S3 upload not configured"

Set `MEME_ASSETS_BUCKET` in `.env` or AWS Secrets Manager. See [S3 Setup](#s3-setup).

### "Failed to upload to S3: Access Denied"

Check IAM permissions. The runtime identity needs `s3:PutObject` on the bucket's public prefix.

### "Failed to post: Invalid Instagram credentials"

Verify `META_IG_ACCESS_TOKEN` is set and valid. See `docs/instagram-publishing.md`.

### Image not loading in review UI

If the image doesn't display:
1. Check that `public_url` is set in the candidate record
2. Verify the S3 bucket allows public reads for the `public/memes/*` prefix
3. Test the URL directly in a browser
4. If no `public_url`, regenerate candidates with S3 configured

### Queue JSON not found on web host

The web UI loads queue data from S3 first, then falls back to local cache. If S3 is configured but the queue isn't loading:
1. Check that `MEME_ASSETS_BUCKET` is set on the web host
2. Verify AWS credentials are available (IAM role, environment variables, or credentials file)
3. Check S3 bucket permissions for `ops/queue/daily-candidates/*` (and legacy `queue/daily-candidates/*` reads)

## Integration with Existing Workflow

Daily candidates integrate with the existing Instagram publisher:

1. **Manual Gallery Publishing**: Click "📸 Instagram" on any meme in `/memes/gallery/` (existing workflow)
2. **Daily Queue**: Click "✅ Approve & Post" in `/memes/gallery/daily-candidates/` (new workflow)
3. **Generate Results**: Click "📸 Post to Instagram" after generating (existing workflow)

All three paths use the same S3 auto-upload + Instagram Graph API backend.

## Brand Configuration

For multi-brand support, see `docs/instagram-publishing.md` and `instagram_brands.example.json`.

## Cost Estimates

- **S3 storage**: ~$0.023/GB/month (1,000 memes ≈ 500 MB ≈ $0.01/month)
- **S3 requests**: PUT $0.005/1000 requests, GET $0.0004/1000 requests
- **API costs**: OpenAI embeddings + xAI Grok (see existing pipeline docs)
- **Instagram API**: Free (no cost for publishing)

Typical daily batch (10 memes): **< $0.02/day** for S3 + existing generation costs.

## Next Steps

- [ ] Add scheduled cron job for weekday generation
- [ ] Integrate with Instagram Stories API (video/carousel support)
- [ ] Add email/Slack notifications when candidates are ready for review
- [ ] Track approval rate and A/B test different generation parameters
- [ ] Support bulk approve/skip actions in UI

## See Also

- [Instagram Publishing](./instagram-publishing.md) - Instagram Graph API setup
- [Terraform S3 Module](../infra/meme-assets/README.md) - Infrastructure setup
- [Pipeline Configuration](../src/config/domain_config.py) - Domain packs and tone rules
