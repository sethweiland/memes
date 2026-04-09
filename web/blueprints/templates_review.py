"""
Templates review blueprint — migrated from scripts/review_templates.py.
"""

import json
from pathlib import Path

from flask import Blueprint, render_template, request, jsonify

from src.core.templates import TemplatesCatalog, TEMPLATE_DESCRIPTIONS

bp = Blueprint("templates_review", __name__)

AI_DESCRIPTIONS_PATH = Path("data/ai_template_descriptions.json")
REVIEW_QUEUE_PATH = Path("data/template_descriptions_review.json")


def _load_json(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def _save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@bp.route("/")
def review_page():
    review_queue = _load_json(REVIEW_QUEUE_PATH)
    catalog = TemplatesCatalog()
    items = []
    for tid, entry in review_queue.items():
        template = catalog.templates.get(tid)
        items.append({
            "id": tid,
            "name": entry.get("name", tid),
            "description": entry.get("description", ""),
            "panel_structure": entry.get("panel_structure", ""),
            "comedic_pattern": entry.get("comedic_pattern", ""),
            "confidence": entry.get("confidence", "?"),
            "img_url": template.url if template else "",
            "box_count": template.box_count if template else "?",
        })
    return render_template(
        "templates_review/review.html",
        items=items,
        total=len(review_queue),
    )


@bp.route("/approved")
def approved_page():
    ai_descriptions = _load_json(AI_DESCRIPTIONS_PATH)
    catalog = TemplatesCatalog()
    items = []
    for tid, entry in ai_descriptions.items():
        template = catalog.templates.get(tid)
        items.append({
            "id": tid,
            "name": entry.get("name", tid),
            "description": entry.get("description", ""),
            "panel_structure": entry.get("panel_structure", ""),
            "comedic_pattern": entry.get("comedic_pattern", ""),
            "confidence": entry.get("confidence", "?"),
            "img_url": template.url if template else "",
        })
    return render_template(
        "templates_review/approved.html",
        items=items,
        count=len(ai_descriptions),
    )


@bp.route("/stats")
def stats_page():
    catalog = TemplatesCatalog()
    ai_descriptions = _load_json(AI_DESCRIPTIONS_PATH)
    review_queue = _load_json(REVIEW_QUEUE_PATH)

    total = len(catalog.templates)
    handwritten = sum(
        1 for t in catalog.templates.values() if t.name in TEMPLATE_DESCRIPTIONS
    )
    ai_approved = len(ai_descriptions)
    in_review = len(review_queue)
    undescribed = total - handwritten - ai_approved - in_review

    return render_template(
        "templates_review/stats.html",
        total=total,
        handwritten=handwritten,
        ai_approved=ai_approved,
        review_queue=in_review,
        undescribed=max(0, undescribed),
    )


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@bp.route("/api/approve/<template_id>", methods=["POST"])
def api_approve(template_id):
    review_queue = _load_json(REVIEW_QUEUE_PATH)
    ai_descriptions = _load_json(AI_DESCRIPTIONS_PATH)

    if template_id not in review_queue:
        return jsonify({"ok": False, "error": "Not in review queue"}), 404

    entry = review_queue.pop(template_id)

    body = request.get_json(silent=True) or {}
    if body.get("description"):
        entry["description"] = body["description"]

    ai_descriptions[template_id] = entry

    _save_json(REVIEW_QUEUE_PATH, review_queue)
    _save_json(AI_DESCRIPTIONS_PATH, ai_descriptions)

    return jsonify({"ok": True})


@bp.route("/api/reject/<template_id>", methods=["POST"])
def api_reject(template_id):
    review_queue = _load_json(REVIEW_QUEUE_PATH)

    if template_id not in review_queue:
        return jsonify({"ok": False, "error": "Not in review queue"}), 404

    review_queue.pop(template_id)
    _save_json(REVIEW_QUEUE_PATH, review_queue)

    return jsonify({"ok": True})


@bp.route("/api/unapprove/<template_id>", methods=["POST"])
def api_unapprove(template_id):
    ai_descriptions = _load_json(AI_DESCRIPTIONS_PATH)
    review_queue = _load_json(REVIEW_QUEUE_PATH)

    if template_id not in ai_descriptions:
        return jsonify({"ok": False, "error": "Not in approved"}), 404

    entry = ai_descriptions.pop(template_id)
    review_queue[template_id] = entry

    _save_json(AI_DESCRIPTIONS_PATH, ai_descriptions)
    _save_json(REVIEW_QUEUE_PATH, review_queue)

    return jsonify({"ok": True})


@bp.route("/api/stats")
def api_stats():
    catalog = TemplatesCatalog()
    ai_descriptions = _load_json(AI_DESCRIPTIONS_PATH)
    review_queue = _load_json(REVIEW_QUEUE_PATH)

    total = len(catalog.templates)
    handwritten = sum(
        1 for t in catalog.templates.values() if t.name in TEMPLATE_DESCRIPTIONS
    )
    ai_approved = len(ai_descriptions)
    in_review = len(review_queue)
    undescribed = total - handwritten - ai_approved - in_review

    return jsonify({
        "total": total,
        "handwritten": handwritten,
        "ai_approved": ai_approved,
        "review_queue": in_review,
        "undescribed": max(0, undescribed),
    })
