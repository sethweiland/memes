# Instagram Publishing

Human-in-the-loop Instagram publishing for approved memes via Meta Graph API.

## Overview

This feature enables manual approval and posting of generated memes to Instagram Professional accounts. **Nothing posts automatically** — every post requires explicit human approval through the web UI.

## Requirements

### Instagram Account Setup

1. **Instagram Professional Account**: Your Instagram account must be a Professional account (Creator or Business)
2. **Facebook Page**: The Instagram account must be connected to a Facebook Page
3. **Meta App**: A Meta (Facebook) app with Instagram Graph API permissions
4. **Access Token**: A long-lived User Access Token with `instagram_basic`, `instagram_content_publish`, and `pages_read_engagement` permissions

### Get Your IDs

- **Instagram Business Account ID**: Find in Meta Graph API Explorer or via `GET /{page-id}?fields=instagram_business_account`
- **Facebook Page ID**: Find in your Facebook Page settings or Graph API Explorer
- **Meta App ID**: Found in your Meta App dashboard

## Configuration

### Environment Variables

Add these to your `.env` file or AWS Secrets Manager:

```bash
# Required
META_IG_ACCESS_TOKEN=your_instagram_access_token_here

# Optional (defaults shown)
META_IG_USER_ID=17841449649203293
META_APP_ID=1042489268787325
META_PAGE_ID=1370368009487261
```

**Never commit access tokens to git.** Use `.env` for local development and AWS Secrets Manager for production.

### Multi-Brand Support

To manage multiple Instagram accounts, create `instagram_brands.json`:

```json
{
  "brands": {
    "default": {
      "name": "High Lonesome Memes",
      "ig_user_id": "17841449649203293",
      "page_id": "1370368009487261",
      "app_id": "1042489268787325",
      "access_token_env": "META_IG_ACCESS_TOKEN",
      "description": "Bluegrass memes"
    },
    "mybrand": {
      "name": "My Other Meme Page",
      "ig_user_id": "your_ig_user_id",
      "page_id": "your_page_id",
      "app_id": "your_app_id",
      "access_token_env": "MYBRAND_IG_ACCESS_TOKEN",
      "description": "Another meme account"
    }
  },
  "active_brand": "default"
}
```

Add environment variables for each brand's access token (e.g., `MYBRAND_IG_ACCESS_TOKEN`).

## How to Use

### From Gallery

1. Go to `/gallery` in the web UI
2. Click on any meme thumbnail
3. Click **📸 Instagram** button
4. Edit the caption if needed
5. **Important**: Upload your meme image to a public URL (CDN, S3 with public access, etc.)
6. Paste the public image URL into the form
7. Click **Post to Instagram**
8. Wait for confirmation (creates container → polls until ready → publishes)

### From Generate Results

1. Complete a meme generation workflow
2. On the results page, click **📸 Post to Instagram** for any generated meme
3. Follow the same approval flow as above

### Important: Public Image URL Constraint

Instagram Graph API requires a **publicly accessible HTTPS image URL**. The API fetches the image from this URL during container creation.

Options for hosting:
- Upload to AWS S3 with public read permissions
- Use a CDN (CloudFront, Cloudflare, etc.)
- Any public web server serving the JPEG over HTTPS

The local file served by `/gallery/image/` is **not** accessible to Instagram's servers and won't work.

## Publishing Workflow

1. **Container Creation**: POST to `/{ig-user-id}/media` with `image_url` and `caption`
2. **Polling**: Check container `status_code` until it becomes `FINISHED` (usually 5-15 seconds)
3. **Publishing**: POST to `/{ig-user-id}/media_publish` with `creation_id`
4. **Result**: Get Instagram post ID and permalink

All publish attempts are logged to `data/instagram_publish_log.json` (credentials are never logged).

## API Reference

### POST /gallery/api/instagram/publish

Publish an approved meme to Instagram.

**Request:**
```json
{
  "public_image_url": "https://cdn.example.com/meme.jpg",
  "caption": "Your caption here #memes #funny",
  "filename": "meme_20240915_123456.jpg"
}
```

**Response (success):**
```json
{
  "success": true,
  "post_id": "18123456789012345",
  "permalink": "https://www.instagram.com/p/ABC123xyz/",
  "error": null
}
```

**Response (error):**
```json
{
  "success": false,
  "post_id": null,
  "permalink": null,
  "error": "Instagram API error: Invalid image URL"
}
```

### GET /gallery/api/instagram/history

Get Instagram publish history.

**Response:**
```json
{
  "history": [
    {
      "timestamp": "2024-09-15T14:30:00",
      "filename": "meme.jpg",
      "caption": "Caption preview...",
      "success": true,
      "post_id": "18123456789012345",
      "permalink": "https://www.instagram.com/p/ABC123xyz/",
      "error": null,
      "container_id": "17987654321098765"
    }
  ],
  "count": 1
}
```

## Programmatic Usage

```python
from src.core.instagram_publisher import publish_to_instagram

# Simple publish (uses default brand)
result = publish_to_instagram(
    image_url="https://cdn.example.com/meme.jpg",
    caption="This is a meme! #memes #funny"
)

if result.success:
    print(f"Published: {result.permalink}")
else:
    print(f"Error: {result.error}")

# Multi-brand publish
result = publish_to_instagram(
    image_url="https://cdn.example.com/meme.jpg",
    caption="Another meme!",
    brand="mybrand"
)
```

## Troubleshooting

### Missing Access Token

**Error:** `META_IG_ACCESS_TOKEN is required`

**Solution:** Add your Instagram access token to `.env` or AWS Secrets Manager.

### Invalid Image URL

**Error:** `Instagram API error: Invalid image URL`

**Solution:** Ensure your image URL is:
- Publicly accessible (no authentication required)
- HTTPS (not HTTP)
- A direct link to a JPEG file
- Under 8MB

### Container Processing Failed

**Error:** `Container processing failed` or `Timeout waiting for container`

**Solution:** 
- Check that your image URL is accessible
- Verify image format (JPEG is most reliable)
- Try a smaller image (under 1MB recommended)
- Wait and retry — Meta's servers can be slow

### Rate Limits

Instagram Graph API has rate limits. If you hit them:
- Wait 1 hour before retrying
- Reduce posting frequency
- Consider requesting a higher rate limit from Meta

## Security Notes

- **Never commit access tokens to git**
- Use environment variables or AWS Secrets Manager
- Rotate access tokens regularly
- Use long-lived tokens (60+ days) for production
- Monitor the publish log for suspicious activity

## References

- [Instagram Graph API Content Publishing](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/content-publishing)
- [Instagram Graph API Reference](https://developers.facebook.com/docs/instagram-api/reference)
- [Getting Access Tokens](https://developers.facebook.com/docs/facebook-login/guides/access-tokens)
