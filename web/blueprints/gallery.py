"""
Gallery blueprint — browse past meme output and serve images.
"""

import os
import json
from datetime import datetime, timedelta
from pathlib import Path

from flask import Blueprint, render_template, send_from_directory, send_file, request, abort, jsonify

from web.image_export import resize_for_instagram

bp = Blueprint("gallery", __name__)

MEMES_DIR = Path("output/memes")


def _get_meme_files() -> list[dict]:
    """Get all .jpg files in output/memes, newest first."""
    if not MEMES_DIR.exists():
        return []

    files = sorted(MEMES_DIR.glob("*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True)
    results = []
    for f in files:
        stat = f.stat()
        created_at = datetime.fromtimestamp(stat.st_mtime)
        meta_path = f.with_suffix(".txt")
        metadata = {}
        if meta_path.exists():
            metadata = _parse_metadata(meta_path)
        template_name = metadata.get("template") or f.stem
        is_original = template_name.lower().startswith("original")
        results.append({
            "filename": f.name,
            "path": str(f),
            "metadata": metadata,
            "template_name": template_name,
            "is_original": is_original,
            "meme_type": "Original" if is_original else "Classic",
            "created_at": created_at,
            "created_label": created_at.strftime("%b %-d, %Y %-I:%M %p"),
            "date_key": created_at.strftime("%Y-%m-%d"),
        })
    return results


def _parse_metadata(meta_path: Path) -> dict:
    """Parse a meme .txt metadata file into a dict."""
    text = meta_path.read_text(errors="replace")
    data = {}
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("MEME:"):
            data["template"] = line.split(":", 1)[1].strip()
        elif line.startswith("TOP TEXT:"):
            data["top_text"] = line.split(":", 1)[1].strip()
        elif line.startswith("BOTTOM TEXT:"):
            data["bottom_text"] = line.split(":", 1)[1].strip()
        elif line.startswith("SUGGESTED CAPTION FOR POSTING:"):
            data["caption"] = line.split(":", 1)[1].strip()
    return data


@bp.route("/")
def index():
    date_filter = request.args.get("date", "all")
    type_filter = request.args.get("type", "all")
    all_memes = _get_meme_files()
    memes = all_memes
    now = datetime.now()

    if date_filter == "latest":
        memes = memes[:24]
    elif date_filter == "today":
        today_key = now.strftime("%Y-%m-%d")
        memes = [m for m in memes if m["date_key"] == today_key]
    elif date_filter == "week":
        cutoff = now - timedelta(days=7)
        memes = [m for m in memes if m["created_at"] >= cutoff]
    elif date_filter and date_filter not in ("all", "today", "week"):
        memes = [m for m in memes if m["date_key"] == date_filter]

    if type_filter == "original":
        memes = [m for m in memes if m["is_original"]]
    elif type_filter == "classic":
        memes = [m for m in memes if not m["is_original"]]

    available_dates = []
    seen = set()
    for meme in all_memes:
        if meme["date_key"] not in seen:
            seen.add(meme["date_key"])
            available_dates.append({
                "key": meme["date_key"],
                "label": meme["created_at"].strftime("%b %-d"),
            })

    totals = {
        "all": len(all_memes),
        "original": sum(1 for m in all_memes if m["is_original"]),
        "classic": sum(1 for m in all_memes if not m["is_original"]),
    }

    return render_template(
        "gallery/index.html",
        memes=memes,
        date_filter=date_filter,
        type_filter=type_filter,
        available_dates=available_dates[:14],
        totals=totals,
    )


@bp.route("/image/<path:filename>")
def serve_image(filename):
    if not MEMES_DIR.exists():
        abort(404)
    return send_from_directory(MEMES_DIR.resolve(), filename)


@bp.route("/download/<path:filename>")
def download(filename):
    """Download a meme image, optionally resized for Instagram."""
    filepath = MEMES_DIR / filename
    if not filepath.is_file():
        abort(404)

    fmt = request.args.get("format", "")

    if fmt == "instagram":
        buf = resize_for_instagram(str(filepath))
        stem = filepath.stem
        return send_file(
            buf,
            mimetype="image/jpeg",
            as_attachment=True,
            download_name=f"{stem}_instagram.jpg",
        )

    return send_file(
        filepath,
        as_attachment=True,
        download_name=filename,
    )


# ---------------------------------------------------------------------------
# Instagram Publishing
# ---------------------------------------------------------------------------

PUBLISH_LOG_PATH = Path("data/instagram_publish_log.json")


def _load_publish_log() -> list[dict]:
    """Load Instagram publish history."""
    if not PUBLISH_LOG_PATH.exists():
        return []
    try:
        return json.loads(PUBLISH_LOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_publish_log(entry: dict):
    """Append a publish entry to the log."""
    log = _load_publish_log()
    log.append(entry)
    PUBLISH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    PUBLISH_LOG_PATH.write_text(
        json.dumps(log, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


@bp.route("/api/instagram/publish", methods=["POST"])
def api_instagram_publish():
    """
    Publish an approved meme to Instagram.
    
    Expects JSON:
    {
        "public_image_url": "https://...",  # Publicly accessible image URL
        "caption": "Your caption here",
        "filename": "optional-for-logging.jpg"
    }
    
    Returns:
    {
        "success": true,
        "post_id": "...",
        "permalink": "https://instagram.com/p/...",
        "error": null
    }
    """
    data = request.get_json(silent=True) or {}
    
    public_image_url = data.get("public_image_url", "").strip()
    caption = data.get("caption", "").strip()
    filename = data.get("filename", "")
    
    if not public_image_url:
        return jsonify({
            "success": False,
            "error": "public_image_url is required (must be a publicly accessible JPEG URL)"
        }), 400
    
    if not caption:
        return jsonify({
            "success": False,
            "error": "caption is required"
        }), 400
    
    # Validate that credentials are available
    try:
        from src.core.instagram_publisher import publish_to_instagram
        
        result = publish_to_instagram(
            image_url=public_image_url,
            caption=caption,
        )
        
        # Log the publish attempt
        log_entry = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "filename": filename,
            "caption": caption[:100] + ("..." if len(caption) > 100 else ""),
            "success": result.success,
            "post_id": result.post_id,
            "permalink": result.permalink,
            "error": result.error,
            "container_id": result.container_id,
        }
        _save_publish_log(log_entry)
        
        if result.success:
            return jsonify({
                "success": True,
                "post_id": result.post_id,
                "permalink": result.permalink,
                "error": None,
            })
        else:
            return jsonify({
                "success": False,
                "post_id": None,
                "permalink": None,
                "error": result.error,
            }), 500
            
    except ValueError as e:
        # Missing credentials
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400
    except Exception as e:
        # Unexpected error
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": f"Unexpected error: {str(e)}"
        }), 500


@bp.route("/api/instagram/history")
def api_instagram_history():
    """Get Instagram publish history."""
    log = _load_publish_log()
    return jsonify({
        "history": log,
        "count": len(log),
    })
