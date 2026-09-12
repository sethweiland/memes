"""Redirects and home hub for the ops IA (life shell, memes nested)."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from flask import Blueprint, Flask

import tests.bootstrap  # noqa: F401

from src.core.calendar import CalendarStore, reset_calendar
from src.core.grok_bot import reset_grok_bot_routines
from src.core.project_board import ProjectBoard, reset_project_board
from src.core.tenant import load_tenant_from_path, reset_tenant
from web.context import register_life_ops_context
from src.core.x_activity import XActivityQueue, reset_x_activity_queue
from tests.fakes import MemoryS3Store
from web.blueprints.dashboard import bp as dashboard_bp
from web.blueprints.grok_bot import bp as grok_bot_bp
from web.blueprints.home import bp as home_bp
from web.blueprints.legacy import register_legacy_redirects
from web.blueprints.projects import bp as projects_bp
from web.blueprints.x_activity import bp as x_activity_bp

_WEB_ROOT = Path(__file__).resolve().parents[1] / "web"
_SETH = Path(__file__).resolve().parent / "fixtures" / "seth_tenant.yaml"


def _ops_app() -> Flask:
    """Home/projects/real X/memes dashboard + legacy redirects; stub remaining nav."""
    app = Flask(
        __name__,
        template_folder=str(_WEB_ROOT / "templates"),
        static_folder=str(_WEB_ROOT / "static"),
    )
    app.secret_key = "test"
    nav = [
        ("spend", "index", "/spend/"),
        ("generate", "start", "/memes/generate/"),
        ("video", "start", "/memes/video/"),
        ("gallery", "index", "/memes/gallery/"),
        ("daily_candidates", "index", "/memes/gallery/daily-candidates/"),
        ("templates_review", "review_page", "/memes/templates/"),
        ("discovery", "dashboard", "/memes/discovery/"),
    ]
    for name, endpoint, path in nav:
        stub = Blueprint(name, name)
        stub.add_url_rule(path, endpoint, lambda **_kwargs: "")
        if name == "gallery":
            stub.add_url_rule(
                "/memes/gallery/image/<path:filename>",
                "serve_image",
                lambda **_kwargs: "",
            )
        app.register_blueprint(stub)

    app.register_blueprint(home_bp)
    app.register_blueprint(projects_bp, url_prefix="/projects")
    app.register_blueprint(x_activity_bp)
    app.register_blueprint(grok_bot_bp, url_prefix="/grok-bot")
    app.register_blueprint(dashboard_bp, url_prefix="/memes")
    register_legacy_redirects(app)
    register_life_ops_context(app)
    return app


def _location_path(response) -> str:
    return urlparse(response.headers["Location"]).path


def _location_query(response) -> str:
    return urlparse(response.headers["Location"]).query


class OpsIaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.queue = XActivityQueue(
            store=MemoryS3Store(),
            local_dir=Path(self.tmp.name),
        )
        reset_x_activity_queue(self.queue)
        reset_grok_bot_routines()
        reset_tenant(load_tenant_from_path(_SETH))
        self.board = ProjectBoard(
            store=MemoryS3Store(configured=False),
            local_path=Path(self.tmp.name) / "board.json",
        )
        reset_project_board(self.board)
        reset_calendar(
            CalendarStore(
                store=MemoryS3Store(configured=False),
                local_path=Path(self.tmp.name) / "calendar.json",
                ics_url=None,
            )
        )
        self.client = _ops_app().test_client()

    def tearDown(self):
        reset_x_activity_queue()
        reset_grok_bot_routines()
        reset_project_board()
        reset_calendar()
        reset_tenant()
        self.tmp.cleanup()

    def test_home_is_life_ops_inbox_not_hub_cards(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn(">Ops<", html)
        self.assertIn("Life overview", html)
        self.assertNotIn("ops-hub", html)
        self.assertNotIn("ops-card", html)
        waiting_at = html.find('id="waiting-heading"')
        week_at = html.find('id="cal-week-heading"')
        self.assertGreater(waiting_at, 0)
        self.assertGreater(week_at, waiting_at)
        self.assertIn("Waiting on you", html)
        self.assertIn("Cloudflare Access", html)
        self.assertNotIn("Meme Pipeline", html)
        self.assertNotIn("Meme Ops Dashboard", html)
        self.assertNotIn("Pending Today", html)
        self.assertIn("This week", html)
        self.assertIn("On the horizon", html)
        self.assertIn("No calendar snapshot yet.", html)
        self.assertNotIn("America/New_York", html)
        self.assertNotRegex(html, r"(?:America|Europe|Asia|Pacific|Africa|Australia)/[A-Za-z_]+")
        self.assertNotIn("Team standup", html)
        self.assertNotIn("Invented", html)
        peer = html.split("data-nav-folders")[0]
        self.assertIn(">Projects<", peer)
        self.assertIn(">Spend<", peer)
        self.assertIn(">X<", peer)
        self.assertNotIn(">Grok Bot<", peer)
        self.assertNotIn(">Memes<", peer)
        folders = html.split("data-nav-folders-menu")[1]
        self.assertIn("Folders", folders)
        self.assertNotIn(">More<", folders)
        self.assertIn("Software", folders)
        self.assertIn("Grok Bot", folders)
        self.assertIn("/grok-bot/", folders)
        self.assertIn("/memes/generate/", folders)
        self.assertIn("/projects/?project=sethweiland-com#sethweiland-com", folders)

    def test_healthz_still_at_root(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})

    def test_memes_dashboard_moved_under_memes(self):
        response = self.client.get("/memes/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Meme Ops Dashboard", html)
        self.assertIn("Daily Queue", html)

    def test_projects_board_and_real_x_activity(self):
        projects = self.client.get("/projects/")
        self.assertEqual(projects.status_code, 200)
        projects_html = projects.get_data(as_text=True)
        self.assertIn("idea", projects_html)
        self.assertIn("waiting_on_you", projects_html)
        self.assertIn("Waiting on you", projects_html)
        self.assertIn("Memes", projects_html)
        self.assertIn("Millgrass", projects_html)
        self.assertNotIn("waiting_on_seth", projects_html)
        self.assertNotIn("Kanban is not built yet", projects_html)
        self.assertNotIn("$", projects_html)

        x_page = self.client.get("/x/")
        self.assertEqual(x_page.status_code, 200)
        html = x_page.get_data(as_text=True)
        self.assertIn("X Activity", html)
        self.assertIn("this app never posts to X", html)
        self.assertIn("Approve or skip", html)
        self.assertIn("ops/queue/x-activity/", html)
        self.assertNotIn("X drafts land here", html)

        grok = self.client.get("/grok-bot/")
        self.assertEqual(grok.status_code, 200)
        grok_html = grok.get_data(as_text=True)
        self.assertIn("Whole Foods restock", grok_html)
        self.assertIn("X follow candidates", grok_html)
        self.assertIn("X reply candidates", grok_html)
        self.assertIn("X tweet drafts", grok_html)
        self.assertIn('<section class="grok-bot-section" data-category="x">', grok_html)
        self.assertIn("start/stop lives in Grok Bot settings", grok_html)
        self.assertNotIn("Routines catalog landing in a follow-up.", grok_html)
        self.assertNotIn("Start routine", grok_html)

    def test_home_shows_waiting_on_you_cards_when_present(self):
        self.board.save(
            {
                "updated_at": "2026-09-11T00:00:00+00:00",
                "projects": [
                    {
                        "id": "needs-a-call",
                        "name": "Needs a call",
                        "lane": "waiting_on_you",
                        "owner_agent": None,
                        "links": {"repo": None, "prod": None},
                        "summary": None,
                        "last_done": None,
                        "next_steps": None,
                    }
                ],
            }
        )
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Waiting on you", html)
        self.assertIn("Needs a call", html)
        self.assertNotIn("waiting_on_seth", html)
        self.assertNotIn("Nothing queued", html)

    def test_home_pending_x_is_a_count_link_not_fake_rows(self):
        today = datetime.now().strftime("%Y-%m-%d")
        self.queue.save(
            today,
            {
                "date": today,
                "candidates": [
                    {
                        "id": "draft-1",
                        "kind": "post",
                        "status": "pending",
                        "body": "SECRET_DRAFT_BODY_NOT_ON_HOME",
                        "project": "x",
                    }
                ],
            },
        )
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("1 pending X draft", html)
        self.assertIn("/x/", html)
        self.assertNotIn("SECRET_DRAFT_BODY_NOT_ON_HOME", html)

    def test_old_meme_paths_redirect(self):
        cases = (
            ("/generate/", "/memes/generate/"),
            ("/generate", "/memes/generate/"),
            ("/gallery/", "/memes/gallery/"),
            ("/gallery/daily-candidates/", "/memes/gallery/daily-candidates/"),
            ("/templates/", "/memes/templates/"),
            ("/video/", "/memes/video/"),
            ("/discovery/", "/memes/discovery/"),
            ("/memes/daily-queue/", "/memes/gallery/daily-candidates/"),
        )
        for old, new in cases:
            with self.subTest(old=old):
                response = self.client.get(old)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(_location_path(response), new)

    def test_legacy_redirect_keeps_query_string(self):
        response = self.client.get("/generate/?topic=banjo")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(_location_path(response), "/memes/generate/")
        self.assertEqual(_location_query(response), "topic=banjo")

        queued = self.client.get("/gallery/daily-candidates/?date=2026-09-10")
        self.assertEqual(queued.status_code, 302)
        self.assertEqual(_location_path(queued), "/memes/gallery/daily-candidates/")
        self.assertEqual(_location_query(queued), "date=2026-09-10")
