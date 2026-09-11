# Video Extraction Status

The video ad workflow has been copied into the sibling project at
`/Users/sethweiland/code/videos`.

## Detached In Bluegrass

- `web/__init__.py` no longer registers the `/video` blueprint
- `web/templates/base.html` no longer links to video routes
- `src/config/prompt_templates.py` no longer treats video prompts as part of the domain prompt set
- `src/core/__init__.py` no longer re-exports video modules

## Remaining Files To Remove After Verification

- `web/blueprints/video.py`
- `web/templates/video/`
- video-specific functions still embedded in `web/static/app.js`
- `src/core/video_*.py`
- `src/core/tts_provider.py`
- `domains/bluegrass/prompts/video_*.j2`

## Standalone Video Project

The extracted project currently includes:

- copied video pipeline modules
- copied `grok.py` and `fallback_context.py`
- copied web blueprint, templates, and static assets
- minimal `run.py`, `web/__init__.py`, and requirements

See `/Users/sethweiland/code/videos/docs/import-rewrite-map.md` for the extracted project notes.
