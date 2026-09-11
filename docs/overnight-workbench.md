# Overnight Workbench

This is the standing backlog for longer autonomous work sessions. The goal is
to keep moving the app toward a niche meme operating system: topic radar,
domain packs, generation, review, gallery, and publishing-safe preview.

## Priority 1: Topic Radar Reliability

- Cache radar output per domain to `data/topic_radar/<domain>.json`.
- Include generated timestamp, candidate counts, lane counts, and source notes.
- Let the web UI fall back to cached radar if live search fails.
- Add a manual watchlist in domain config for artists, festivals, sources, and
  recurring scene rituals.

Verification:

- `python scripts/cache_topic_radar.py --domain bluegrass --no-news`
- Inspect `data/topic_radar/bluegrass.json`
- `python scripts/report_topic_radar.py --domain bluegrass`
- `GET /memes/generate/api/topic-radar?domain=bluegrass`
- Confirm Billy Strings, emerging bands, festivals, and evergreen rituals appear.

## Priority 2: Safer Remote Viewing

- Export a static gallery to `output/static_gallery/`.
- Copy only images and metadata needed for viewing.
- Avoid exposing Flask generate/discovery endpoints through public tunnels.
- Add filters/labels in the static export: latest, original/classic, date.

Verification:

- `python scripts/export_static_gallery.py --limit 48`
- Open `output/static_gallery/index.html`.
- Inspect `output/static_gallery/manifest.json`.
- Confirm images load from relative paths.

Tunnel note:

- Prefer tunneling `output/static_gallery/` with a static file server instead of
  tunneling Flask debug mode. This exposes only exported images and metadata.

## Priority 3: Domain Pack Authoring

- Make new packs fast to create and edit.
- Add a checklist for audience, sources, entities, taboos, rituals, and humor.
- Add example radar config to scaffolds.

Verification:

- `python scripts/create_domain_pack.py golf "Golf Culture"`
- Confirm generated config has `topic_radar`.

## Priority 4: Quality Feedback Loop

- Use existing feedback to influence topic radar and selection.
- Track which lanes produce accepted memes.
- Record “topic -> selected/generated/rated” metadata.
- Generate `data/feedback_summary.json` from saved feedback.

Verification:

- Inspect `data/feedback.json`.
- `python scripts/summarize_feedback.py`
- Inspect `data/feedback_summary.json`.

## Priority 5: Video Readiness

- Keep video as an optional lane, not default.
- Add cost estimates before production.
- Require provider credential checks before the user can start paid video work.

Verification:

- API key status shows Kling/ElevenLabs missing or ready.
- UI does not surprise-spend on video generation.
