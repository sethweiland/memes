"""
Grok Bot blueprint — placeholder until the routines catalog PR lands.

Sibling work will persist ops/grok-bot/routines.json. No fake rows here.
"""

from flask import Blueprint, render_template

bp = Blueprint("grok_bot", __name__)


@bp.route("/")
def index():
    return render_template(
        "grok_bot/index.html",
        active_page="grok_bot",
        section="grok_bot",
    )
