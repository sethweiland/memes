"""
Dashboard blueprint — Master ops home for the meme pipeline.
Displays stats, daily candidate queue, and quick links to all tools.
"""

import json
import os
from datetime import datetime
from pathlib import Path

from flask import Blueprint, render_template, session, request

bp = Blueprint("dashboard", __name__)


def _load_brands():
    """Load Instagram brands from config file if it exists."""
    brands_path = Path("instagram_brands.json")
    if brands_path.exists():
        try:
            data = json.loads(brands_path.read_text(encoding="utf-8"))
            return data.get("brands", [])
        except Exception:
            pass
    # Return default brand if no config exists
    return [{"id": "high_lonesome", "name": "High Lonesome Memes"}]


def _get_selected_brand():
    """Get currently selected brand from session or querystring."""
    # Check querystring first
    brand_id = request.args.get("brand")
    if brand_id:
        session["selected_brand"] = brand_id
        return brand_id
    # Fall back to session
    return session.get("selected_brand", "high_lonesome")


def _get_template_count():
    """Count templates in the catalog if it exists."""
    catalog_path = Path("data/meme_templates_expanded.json")
    if not catalog_path.exists():
        return None
    try:
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
        return len(data.get("templates", []))
    except Exception:
        return None


def _get_daily_candidates_count():
    """Count pending daily candidates for today."""
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        from src.core.meme_assets import get_queue_storage
        queue_storage = get_queue_storage()
        data = queue_storage.load(today)
        if not data:
            return None
        # Count candidates with status == "pending"
        candidates = data.get("candidates", [])
        pending = [c for c in candidates if c.get("status") == "pending"]
        return len(pending)
    except Exception:
        return None


def _get_gallery_count():
    """Count memes in the gallery."""
    memes_dir = Path("output/memes")
    if not memes_dir.exists():
        return 0
    return len(list(memes_dir.glob("*.jpg")))


def _get_recent_memes(limit=8):
    """Get most recent memes from gallery."""
    memes_dir = Path("output/memes")
    if not memes_dir.exists():
        return []
    
    files = sorted(
        memes_dir.glob("*.jpg"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )[:limit]
    
    return [{"filename": f.name} for f in files]


def _has_s3_configured():
    """Check if S3/bucket env vars are configured."""
    return bool(os.environ.get("MEME_ASSETS_BUCKET") or os.environ.get("AWS_S3_BUCKET"))


@bp.route("/")
def index():
    brands = _load_brands()
    selected_brand_id = _get_selected_brand()
    
    # Find selected brand object
    selected_brand = next(
        (b for b in brands if b.get("id") == selected_brand_id),
        brands[0] if brands else {"id": "default", "name": "Memes"}
    )
    
    # Gather stats
    stats = {
        "template_count": _get_template_count(),
        "daily_candidates": _get_daily_candidates_count(),
        "gallery_count": _get_gallery_count(),
        "s3_configured": _has_s3_configured(),
    }
    
    recent_memes = _get_recent_memes(limit=8)
    
    return render_template(
        "dashboard/index.html",
        brands=brands,
        selected_brand=selected_brand,
        stats=stats,
        recent_memes=recent_memes,
        active_page="dashboard",
    )
