# Niche Discovery UI Plan

## Overview

Add a new section to the web UI for reviewing niche opportunities and tracking Instagram page existence.

## Routes (add to web app)

```
/discovery              → Dashboard of all tracked niches
/discovery/run          → Trigger a new pipeline run
/discovery/review       → Review top opportunities, mark Instagram status
/discovery/export       → Export data as CSV
```

## Key Features

### 1. Discovery Dashboard (`/discovery`)
- Summary stats: total niches, by status, recent runs
- Quick filters: status, category, score threshold
- Search by niche name or subreddit

### 2. Review Interface (`/discovery/review`)
- Card-based view of top niches
- Each card shows:
  - Niche name, subreddit, subscribers
  - Scores (quant, qual, final)
  - Top themes, sample meme concepts
  - Risks
- Action buttons:
  - "Check Instagram" → opens search in new tab
  - "Has IG Page" / "No IG Page" → logs to database
  - "Add Notes" → free text field
  - "Mark Status" → new/researching/launched/skipped

### 3. Instagram Logging
When user clicks "Has IG Page":
```json
{
  "niche_name": "looksmaxxing",
  "instagram_page_exists": true,
  "instagram_page_url": "https://instagram.com/looksmax.memes",
  "instagram_followers": 50000,
  "checked_by": "user",
  "checked_at": "2024-02-23T12:00:00Z"
}
```

### 4. Data Export
- CSV with all fields including Instagram status
- Filter by: has_instagram, no_instagram, unchecked
- Use for analyzing market gaps

## Implementation

### New Blueprint: `web/blueprints/discovery.py`

```python
@bp.route("/")
def dashboard():
    tracker = RunTracker()
    return render_template("discovery/dashboard.html",
        summary=tracker.get_summary(),
        recent_runs=tracker.runs[-5:],
    )

@bp.route("/review")
def review():
    tracker = RunTracker()
    niches = tracker.get_niches_by_status("new")
    return render_template("discovery/review.html", niches=niches)

@bp.route("/api/mark-instagram", methods=["POST"])
def mark_instagram():
    data = request.json
    tracker = RunTracker()
    tracker.update_niche_instagram(
        niche_name=data["niche_name"],
        exists=data["exists"],
        url=data.get("url", ""),
        followers=data.get("followers", 0),
    )
    return jsonify({"status": "ok"})
```

## Future Enhancements

1. **Auto Instagram Search**: Open Instagram search with niche keywords pre-filled
2. **Competitor Analysis**: Track multiple IG pages per niche
3. **Trend Tracking**: Re-score niches weekly, track score changes
4. **Launch Tracker**: Track which niches you've actually launched pages for
