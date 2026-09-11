"""
Home blueprint — life/ops hub for ops.sethweiland.com.

`/` is a section index (Projects, Spend, X, Memes), not the meme stats dashboard.
"""

from flask import Blueprint, render_template

bp = Blueprint("home", __name__)


@bp.route("/")
def index():
    return render_template(
        "home/index.html",
        active_page="home",
        section="home",
    )


@bp.route("/healthz")
def healthz():
    """Health check endpoint for container orchestration."""
    return {"status": "ok"}, 200
