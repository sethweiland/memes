"""
Home blueprint — life/ops inbox.

`/` is Waiting on you plus, when the calendar module is on, This week and
On the horizon. It is not a hub of section cards and not the meme stats
dashboard. Waiting on you lists `waiting_on_you` project cards and, when
the X module is on, a pending-draft count — never invented X rows.

Calendar is a read-only module (snapshot or optional ICS). Not a sixth
primitive. Horizon starts the Monday after this week's Sunday.
"""

from datetime import datetime

from flask import Blueprint, render_template

from src.core.project_board import get_project_board, waiting_on_you
from src.core.tenant import module_enabled


bp = Blueprint("home", __name__)


def _waiting_projects():
    if not module_enabled("projects"):
        return []
    try:
        data = get_project_board().ensure_seeded()
        return waiting_on_you(list((data or {}).get("projects") or []))
    except Exception:
        return []


def _pending_x_count():
    """Return today's pending X count, or None when there is no queue file."""
    if not module_enabled("x"):
        return None
    try:
        from src.core.x_activity import get_x_activity_queue

        today = datetime.now().strftime("%Y-%m-%d")
        return get_x_activity_queue().pending_count(today)
    except Exception:
        return None


def _calendar_home():
    if not module_enabled("calendar"):
        return None
    try:
        from src.core.calendar import get_calendar

        return get_calendar().home_lists()
    except Exception:
        return {
            "has_snapshot": False,
            "this_week": [],
            "horizon": [],
            "empty_message": "No calendar snapshot yet.",
            "this_week_label": "",
            "horizon_label": "",
            "updated_at": None,
            "timezone": "America/New_York",
        }


@bp.route("/")
def index():
    pending_x = _pending_x_count()
    return render_template(
        "home/index.html",
        active_page="home",
        section="home",
        waiting_projects=_waiting_projects(),
        pending_x_count=pending_x if isinstance(pending_x, int) and pending_x > 0 else None,
        calendar=_calendar_home(),
    )


@bp.route("/healthz")
def healthz():
    """Health check endpoint for container orchestration."""
    return {"status": "ok"}, 200
