"""
Niche Discovery blueprint.

Routes:
    /memes/discovery              - Dashboard
    /memes/discovery/review       - Review & rate niches
    /memes/discovery/api/*        - API endpoints
"""

import json
import os
import sys
from pathlib import Path
from flask import Blueprint, render_template, request, jsonify, redirect, url_for

# Add niche-discovery to path
NICHE_DIR = Path(__file__).parent.parent.parent / "niche-discovery"
sys.path.insert(0, str(NICHE_DIR / "src"))

from run_tracker import RunTracker, NicheRecord
from src.core.secrets import get_secret_value

bp = Blueprint("discovery", __name__, template_folder="../templates/discovery")


def get_tracker() -> RunTracker:
    """Get the run tracker instance."""
    return RunTracker(data_dir=NICHE_DIR / "data")


def _has_apify_token() -> bool:
    return bool(get_secret_value("APIFY_API_TOKEN", ("APIFY_API_TOKEN", "apify_api_token")))


def _ensure_apify_env() -> bool:
    token = get_secret_value("APIFY_API_TOKEN", ("APIFY_API_TOKEN", "apify_api_token"))
    if token:
        os.environ["APIFY_API_TOKEN"] = token
        return True
    return False


@bp.route("/")
def dashboard():
    """Main discovery dashboard."""
    tracker = get_tracker()

    # Summary stats
    total_niches = len(tracker.niches)
    by_status = {}
    by_category = {}

    for n in tracker.niches.values():
        by_status[n.status] = by_status.get(n.status, 0) + 1
        by_category[n.category] = by_category.get(n.category, 0) + 1

    # Top niches
    top_niches = sorted(
        tracker.niches.values(),
        key=lambda x: -x.final_score
    )[:20]

    # Recent runs
    recent_runs = tracker.runs[-5:] if tracker.runs else []

    return render_template("discovery/dashboard.html",
        total_niches=total_niches,
        by_status=by_status,
        by_category=by_category,
        top_niches=top_niches,
        recent_runs=recent_runs,
    )


@bp.route("/review")
def review():
    """Review niches and mark Instagram status."""
    tracker = get_tracker()

    # Filter params
    status_filter = request.args.get("status", "new")
    category_filter = request.args.get("category", "")
    min_score = float(request.args.get("min_score", 0))

    # Get niches
    niches = list(tracker.niches.values())

    # Apply filters
    if status_filter and status_filter != "all":
        niches = [n for n in niches if n.status == status_filter]
    if category_filter:
        niches = [n for n in niches if n.category == category_filter]
    if min_score > 0:
        niches = [n for n in niches if n.final_score >= min_score]

    # Sort by score
    niches.sort(key=lambda x: -x.final_score)

    # Get unique categories for filter dropdown
    categories = sorted(set(n.category for n in tracker.niches.values()))

    return render_template("discovery/review.html",
        niches=niches[:50],  # Limit to 50 per page
        categories=categories,
        current_status=status_filter,
        current_category=category_filter,
        current_min_score=min_score,
    )


@bp.route("/niche/<niche_name>")
def niche_detail(niche_name: str):
    """Detailed view of a single niche."""
    tracker = get_tracker()

    key = niche_name.lower().strip()
    niche = tracker.niches.get(key)

    if not niche:
        return "Niche not found", 404

    return render_template("discovery/niche_detail.html", niche=niche)


# === API Endpoints ===

@bp.route("/api/niches")
def api_list_niches():
    """Get all niches as JSON."""
    tracker = get_tracker()

    niches = [
        {
            "niche_name": n.niche_name,
            "category": n.category,
            "subreddit": n.subreddit,
            "subscribers": n.subscribers,
            "final_score": n.final_score,
            "qualitative_score": n.qualitative_score,
            "status": n.status,
            "instagram_page_exists": n.instagram_page_exists,
            "top_themes": n.top_themes,
        }
        for n in sorted(tracker.niches.values(), key=lambda x: -x.final_score)
    ]

    return jsonify(niches)


@bp.route("/api/niche/<niche_name>", methods=["GET"])
def api_get_niche(niche_name: str):
    """Get a single niche."""
    tracker = get_tracker()
    key = niche_name.lower().strip()
    niche = tracker.niches.get(key)

    if not niche:
        return jsonify({"error": "Not found"}), 404

    from dataclasses import asdict
    return jsonify(asdict(niche))


@bp.route("/api/niche/<niche_name>/instagram", methods=["POST"])
def api_update_instagram(niche_name: str):
    """Update Instagram status for a niche."""
    tracker = get_tracker()
    key = niche_name.lower().strip()

    if key not in tracker.niches:
        return jsonify({"error": "Not found"}), 404

    data = request.get_json()
    niche = tracker.niches[key]

    # Update fields
    if "exists" in data:
        niche.instagram_page_exists = data["exists"]
    if "url" in data:
        niche.instagram_page_url = data["url"]
    if "followers" in data:
        niche.instagram_followers = data["followers"]

    tracker._save()

    return jsonify({"status": "ok", "niche": niche.niche_name})


@bp.route("/api/niche/<niche_name>/status", methods=["POST"])
def api_update_status(niche_name: str):
    """Update status for a niche (new, researching, launched, skipped)."""
    tracker = get_tracker()
    key = niche_name.lower().strip()

    if key not in tracker.niches:
        return jsonify({"error": "Not found"}), 404

    data = request.get_json()
    niche = tracker.niches[key]

    if "status" in data:
        niche.status = data["status"]
    if "notes" in data:
        niche.notes = data["notes"]

    tracker._save()

    return jsonify({"status": "ok", "niche": niche.niche_name})


@bp.route("/api/niche/<niche_name>/generate", methods=["POST"])
def api_generate_memes(niche_name: str):
    """Generate test memes for a niche (redirects to main generator)."""
    tracker = get_tracker()
    key = niche_name.lower().strip()
    niche = tracker.niches.get(key)

    if not niche:
        return jsonify({"error": "Not found"}), 404

    # Return the topic to use for generation
    return jsonify({
        "topic": f"{niche.niche_name} memes",
        "redirect": f"/memes/generate/?topic={niche.niche_name}+memes"
    })


@bp.route("/api/export")
def api_export():
    """Export all niches as CSV."""
    tracker = get_tracker()
    csv_path = tracker.export_csv()

    # Read and return CSV content
    with open(csv_path) as f:
        content = f.read()

    from flask import Response
    return Response(
        content,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=niches_export.csv"}
    )


# === Instagram Search API ===

@bp.route("/api/instagram/search-terms/<niche_name>")
def api_instagram_search_terms(niche_name: str):
    """Preview search terms that would be used for a niche."""
    try:
        from instagram_search import generate_search_terms
        terms = generate_search_terms(niche_name)
        return jsonify({"niche": niche_name, "search_terms": terms})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/api/instagram/search/<niche_name>", methods=["POST"])
def api_instagram_search(niche_name: str):
    """
    Search Instagram for competitors for a single niche.
    Requires APIFY_API_TOKEN in environment.
    """
    if not _ensure_apify_env():
        return jsonify({
            "error": "APIFY_API_TOKEN not configured",
            "message": "Add APIFY_API_TOKEN to .env or AWS Secrets Manager. Get one at https://apify.com"
        }), 400

    tracker = get_tracker()
    key = niche_name.lower().strip()
    niche = tracker.niches.get(key)

    if not niche:
        return jsonify({"error": "Niche not found"}), 404

    try:
        from instagram_search import search_niche_competitors

        result = search_niche_competitors(niche.niche_name)

        # Update niche with results
        niche.instagram_page_exists = result.meme_pages_found > 0
        if result.meme_pages_found > 0:
            niche.instagram_page_url = f"https://instagram.com/{result.largest_competitor}"
            niche.instagram_followers = result.largest_competitor_followers
        tracker._save()

        return jsonify({
            "niche": niche.niche_name,
            "search_terms": result.search_terms,
            "accounts_found": len(result.accounts_found),
            "meme_pages_found": result.meme_pages_found,
            "largest_competitor": result.largest_competitor,
            "largest_competitor_followers": result.largest_competitor_followers,
            "instagram_page_exists": niche.instagram_page_exists,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/api/instagram/bulk-search", methods=["POST"])
def api_instagram_bulk_search():
    """
    Search Instagram for multiple niches.
    Request body: {"niche_names": ["niche1", "niche2", ...], "max_niches": 10}
    """
    if not _ensure_apify_env():
        return jsonify({
            "error": "APIFY_API_TOKEN not configured",
            "message": "Add APIFY_API_TOKEN to .env or AWS Secrets Manager"
        }), 400

    data = request.get_json() or {}
    niche_names = data.get("niche_names", [])
    max_niches = min(data.get("max_niches", 10), 50)  # Cap at 50

    if not niche_names:
        # Default to unsearched niches
        tracker = get_tracker()
        niche_names = [
            n.niche_name for n in tracker.niches.values()
            if not getattr(n, "instagram_searched", False)
        ][:max_niches]

    try:
        from instagram_search import search_all_niches, update_niches_with_instagram_data

        results = search_all_niches(niches=niche_names, max_niches=max_niches)
        update_niches_with_instagram_data(results)

        summary = {
            "searched": len(results),
            "opportunities": sum(1 for r in results.values() if r.meme_pages_found == 0),
            "saturated": sum(1 for r in results.values() if r.meme_pages_found > 0),
            "results": [
                {
                    "niche": name,
                    "meme_pages_found": r.meme_pages_found,
                    "largest_competitor": r.largest_competitor,
                    "followers": r.largest_competitor_followers,
                }
                for name, r in results.items()
            ]
        }

        return jsonify(summary)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/api/instagram/status")
def api_instagram_status():
    """Check if Instagram search is configured."""
    has_token = _has_apify_token()

    return jsonify({
        "configured": has_token,
        "message": "Ready to search" if has_token else "Add APIFY_API_TOKEN to .env or AWS Secrets Manager"
    })
