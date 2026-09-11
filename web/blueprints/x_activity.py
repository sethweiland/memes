"""
X activity blueprint — review Stevie's X drafts.

Approve / skip / edit only. This app never posts to X.
"""

from datetime import datetime

from flask import Blueprint, abort, jsonify, render_template, request

from src.core.x_activity import KINDS, get_x_activity_queue, require_date, summarize


bp = Blueprint("x_activity", __name__, url_prefix="/x")


def _queue():
    return get_x_activity_queue()


def _parse_date(date_str: str) -> str:
    try:
        return require_date(date_str)
    except ValueError:
        abort(400)


@bp.route("/")
def index():
    today = datetime.now().strftime("%Y-%m-%d")
    raw_date = request.args.get("date", today)
    try:
        selected_date = require_date(raw_date)
    except ValueError:
        selected_date = today

    kind = request.args.get("kind", "all")
    if kind not in KINDS:
        kind = "all"

    data = _queue().load(selected_date)
    summary = summarize(data, selected_date)
    candidates = list((data or {}).get("candidates") or [])
    if kind != "all":
        candidates = [c for c in candidates if c.get("kind") == kind]

    grouped = []
    for section in KINDS:
        section_candidates = [c for c in candidates if c.get("kind") == section]
        if section_candidates:
            grouped.append((section, section_candidates))
    other = [c for c in candidates if c.get("kind") not in KINDS]
    if other:
        grouped.append(("other", other))

    return render_template(
        "x_activity/index.html",
        selected_date=selected_date,
        selected_kind=kind,
        data=data,
        summary=summary,
        grouped=grouped,
        kinds=KINDS,
        available_dates=_queue().list_dates(),
    )


@bp.route("/api/candidates/<date_str>")
def api_get_candidates(date_str: str):
    date_str = _parse_date(date_str)
    data = _queue().load(date_str)
    if not data:
        return jsonify({"error": "No X drafts found for this date"}), 404
    return jsonify(data)


@bp.route("/api/candidates/<date_str>/approve/<candidate_id>", methods=["POST"])
def api_approve_candidate(date_str: str, candidate_id: str):
    """Mark a draft approved. Does not send anything to X."""
    date_str = _parse_date(date_str)
    request_data = request.get_json(silent=True) or {}
    body = request_data.get("body")
    if body is not None:
        body = str(body)
    candidate = _queue().approve(date_str, candidate_id, body=body)
    if not candidate:
        return jsonify({"error": "Candidate not found"}), 404
    return jsonify({"success": True, "status": candidate.get("status")})


@bp.route("/api/candidates/<date_str>/skip/<candidate_id>", methods=["POST"])
def api_skip_candidate(date_str: str, candidate_id: str):
    date_str = _parse_date(date_str)
    candidate = _queue().skip(date_str, candidate_id)
    if not candidate:
        return jsonify({"error": "Candidate not found"}), 404
    return jsonify({"success": True, "status": candidate.get("status")})


@bp.route("/api/candidates/<date_str>/update-body/<candidate_id>", methods=["POST"])
def api_update_body(date_str: str, candidate_id: str):
    date_str = _parse_date(date_str)
    request_data = request.get_json(silent=True) or {}
    if "body" not in request_data:
        return jsonify({"error": "body is required"}), 400
    candidate = _queue().update_body(date_str, candidate_id, str(request_data.get("body") or ""))
    if not candidate:
        return jsonify({"error": "Candidate not found"}), 404
    return jsonify({"success": True})
