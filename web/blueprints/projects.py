"""
Projects blueprint — placeholder until the kanban lands.

Upcoming lanes (not built here): idea | active | blocked | waiting_on_seth | parked.
"""

from flask import Blueprint, render_template

bp = Blueprint("projects", __name__)


@bp.route("/")
def index():
    return render_template(
        "projects/index.html",
        active_page="projects",
        section="projects",
    )
