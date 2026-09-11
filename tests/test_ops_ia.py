"""Redirects and home hub for the ops IA (life shell, memes nested)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlparse

from flask import Blueprint, Flask

import tests.bootstrap  # noqa: F401

from src.core.x_activity import XActivityQueue, reset_x_activity_queue
from tests.fakes import MemoryS3Store
from web.blueprints.dashboard import bp as dashboard_bp
from web.blueprints.grok_bot import bp as grok_bot_bp
from web.blueprints.home import bp as home_bp
from web.blueprints.legacy import register_legacy_redirects
from web.blueprints.projects import bp as projects_bp
from web.blueprints.x_activity import bp as x_activity_bp

_WEB_ROOT = Path(__file__).resolve().parents[1] / "web"


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
        self.client = _ops_app().test_client()

    def tearDown(self):
        reset_x_activity_queue()
        self.tmp.cleanup()

    def test_home_is_life_ops_hub(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn(">Ops<", html)
        self.assertIn("Life overview", html)
        self.assertIn("Projects", html)
        self.assertIn("Spend", html)
        self.assertIn(">X<", html)
        self.assertIn("Grok Bot", html)
        self.assertIn("Memes", html)
        self.assertIn("Waiting on you", html)
        self.assertIn("Cloudflare Access", html)
        self.assertNotIn("Meme Pipeline", html)
        self.assertNotIn("Meme Ops Dashboard", html)
        self.assertNotIn("Pending Today", html)

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

    def test_projects_placeholder_and_real_x_activity(self):
        projects = self.client.get("/projects/")
        self.assertEqual(projects.status_code, 200)
        self.assertIn("idea", projects.get_data(as_text=True))
        self.assertNotIn("$", projects.get_data(as_text=True))

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
        self.assertIn("Routines catalog landing in a follow-up.", grok_html)
        self.assertNotIn("<tr", grok_html)

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
