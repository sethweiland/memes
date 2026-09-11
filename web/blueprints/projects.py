"""
Projects blueprint — kanban of named bets.

Columns are attention lanes. This page does not post, buy, or start routines.
Lane moves are same-origin JSON POSTs (same pattern as the X tab).
"""

from flask import Blueprint, abort, jsonify, render_template, request

from src.core.project_board import get_project_board, group_by_lane
from src.core.tenant import LANES, LANE_LABELS, module_enabled, normalize_lane


bp = Blueprint("projects", __name__)


def _board():
    return get_project_board()


@bp.route("/")
def index():
    if not module_enabled("projects"):
        abort(404)
    data = _board().ensure_seeded()
    projects = list((data or {}).get("projects") or [])
    grouped = group_by_lane(projects)
    return render_template(
        "projects/index.html",
        active_page="projects",
        section="projects",
        data=data,
        grouped=grouped,
        lanes=LANES,
        lane_labels=LANE_LABELS,
        project_count=len(projects),
    )


@bp.route("/api/projects/<project_id>/lane", methods=["POST"])
def api_move_lane(project_id: str):
    """Move a card's lane. Does not start routines or post to X."""
    if not module_enabled("projects"):
        abort(404)
    payload = request.get_json(silent=True) or {}
    raw_lane = payload.get("lane")
    lane = normalize_lane(raw_lane, missing="")
    if lane not in LANES:
        return jsonify({"error": "invalid lane"}), 400
    card = _board().move_lane(project_id, lane)
    if not card:
        return jsonify({"error": "Project not found"}), 404
    return jsonify({"success": True, "lane": card.get("lane"), "project": card})
