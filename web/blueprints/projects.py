"""
Projects blueprint — compact list of named bets.

Status is the existing lane enum. This page does not post, buy, or start
routines. Lane moves are same-origin JSON POSTs (same pattern as the X tab).
"""

from flask import Blueprint, abort, jsonify, render_template, request

from src.core.project_board import (
    get_project_board,
    present_project,
    project_owners,
    sort_projects,
)
from src.core.tenant import LANES, LANE_LABELS, load_tenant, module_enabled, normalize_lane


bp = Blueprint("projects", __name__)


def _board():
    return get_project_board()


def _agent_names() -> dict[str, str]:
    try:
        tenant = load_tenant()
    except Exception:
        return {}
    return {agent["id"]: agent["name"] for agent in tenant.agents}


@bp.route("/")
def index():
    if not module_enabled("projects"):
        abort(404)
    data = _board().ensure_seeded()
    projects = sort_projects(list((data or {}).get("projects") or []))
    owners = project_owners(projects)
    agent_names = _agent_names()
    owner_filters = [
        {"id": owner, "name": agent_names.get(owner, owner)}
        for owner in owners
    ]
    return render_template(
        "projects/index.html",
        active_page="projects",
        section="projects",
        data=data,
        projects=[present_project(card) for card in projects],
        owners=owners,
        owner_filters=owner_filters,
        agent_names=agent_names,
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
