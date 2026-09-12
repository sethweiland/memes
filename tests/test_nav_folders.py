"""Folders menu + Home inbox (no hub cards)."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from flask import Blueprint, Flask

import tests.bootstrap  # noqa: F401

from src.core.calendar import CalendarStore, reset_calendar
from src.core.grok_bot import reset_grok_bot_routines
from src.core.project_board import ProjectBoard, reset_project_board
from src.core.tenant import load_tenant_from_path, reset_tenant
from src.core.x_activity import reset_x_activity_queue
from tests.fakes import MemoryS3Store
from web.blueprints.dashboard import bp as dashboard_bp
from web.blueprints.grok_bot import bp as grok_bot_bp
from web.blueprints.home import bp as home_bp
from web.context import register_life_ops_context

_ROOT = Path(__file__).resolve().parents[1]
_WEB_ROOT = _ROOT / "web"
_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_SETH = _FIXTURES / "seth_tenant.yaml"
_EXAMPLE = _ROOT / "config" / "tenant.example.yaml"


def _nav_app():
    app = Flask(
        __name__,
        template_folder=str(_WEB_ROOT / "templates"),
        static_folder=str(_WEB_ROOT / "static"),
    )
    app.secret_key = "test"
    for name, endpoint, path in (
        ("projects", "index", "/projects/"),
        ("spend", "index", "/spend/"),
        ("x_activity", "index", "/x/"),
        ("generate", "start", "/memes/generate/"),
        ("video", "start", "/memes/video/"),
        ("gallery", "index", "/memes/gallery/"),
        ("daily_candidates", "index", "/memes/gallery/daily-candidates/"),
        ("templates_review", "review_page", "/memes/templates/"),
        ("discovery", "dashboard", "/memes/discovery/"),
    ):
        stub = Blueprint(name, name)
        stub.add_url_rule(path, endpoint, lambda **_kwargs: "")
        app.register_blueprint(stub)
    app.register_blueprint(home_bp)
    app.register_blueprint(grok_bot_bp, url_prefix="/grok-bot")
    app.register_blueprint(dashboard_bp, url_prefix="/memes")
    register_life_ops_context(app)
    return app


class FoldersNavAndHomeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        reset_x_activity_queue()
        reset_grok_bot_routines()
        reset_project_board(
            ProjectBoard(
                store=MemoryS3Store(configured=False),
                local_path=Path(self.tmp.name) / "board.json",
            )
        )
        reset_calendar(
            CalendarStore(
                store=MemoryS3Store(configured=False),
                local_path=Path(self.tmp.name) / "calendar.json",
                ics_url=None,
            )
        )
        self.client = _nav_app().test_client()

    def tearDown(self):
        reset_x_activity_queue()
        reset_grok_bot_routines()
        reset_project_board()
        reset_calendar()
        reset_tenant()
        self.tmp.cleanup()

    def test_seth_folders_nests_memes_and_grok_bot(self):
        reset_tenant(load_tenant_from_path(_SETH))
        html = self.client.get("/").get_data(as_text=True)
        peer = html.split('data-nav-folders')[0]
        folders = html.split("data-nav-folders-menu")[1].split("</nav>")[0]
        self.assertIn("data-nav-folders", html)
        self.assertNotIn(">Grok Bot<", peer)
        self.assertNotIn(">Memes<", peer)
        self.assertIn('data-nav-folder="music"', folders)
        self.assertIn('data-nav-folder="software"', folders)
        self.assertIn('data-nav-folder="social"', folders)
        self.assertIn('data-nav-folder="agents"', folders)
        self.assertIn('data-nav-item="memes"', folders)
        self.assertIn("/memes/generate/", folders)
        self.assertIn("/grok-bot/", folders)
        self.assertIn("Whippoorwill", folders)

    def test_folder_project_links_deep_link(self):
        reset_tenant(load_tenant_from_path(_SETH))
        html = self.client.get("/").get_data(as_text=True)
        folders = html.split("data-nav-folders-menu")[1].split("</nav>")[0]
        self.assertIn('href="/projects/?project=sethweiland-com#sethweiland-com"', folders)
        self.assertIn('href="/projects/?project=whippoorwill#whippoorwill"', folders)
        self.assertIn('href="/projects/?project=millgrass#millgrass"', folders)
        self.assertIn('href="/projects/?project=waiver-wire#waiver-wire"', folders)
        self.assertIn('href="/projects/?project=linkmarketcap#linkmarketcap"', folders)
        self.assertNotRegex(folders, r'href="/projects/"(?![?#])')
        self.assertIn('href="/memes/"', folders)
        self.assertIn('href="/x/"', folders)

    def test_folders_label_not_more_or_menu(self):
        reset_tenant(load_tenant_from_path(_SETH))
        html = self.client.get("/").get_data(as_text=True)
        nav = html.split("</nav>")[0]
        self.assertIn("Folders", nav)
        self.assertIn('aria-label="Folders"', nav)
        self.assertNotIn(">More<", nav)
        self.assertNotIn("More ▾", nav)
        self.assertNotIn(">Menu<", nav)
        self.assertNotIn('aria-label="More"', nav)
        self.assertNotIn('aria-label="Menu"', nav)

    def test_folders_control_is_details_not_hidden_button(self):
        reset_tenant(load_tenant_from_path(_SETH))
        html = self.client.get("/").get_data(as_text=True)
        nav = html.split("</nav>")[0]
        self.assertIn('<details class="nav-folders"', nav)
        self.assertIn("<summary", nav)
        self.assertNotIn("<button", nav)
        self.assertNotIn(" data-nav-folders-menu hidden", nav)
        self.assertNotIn('hidden role="navigation"', nav)

    def test_folders_default_open(self):
        reset_tenant(load_tenant_from_path(_SETH))
        html = self.client.get("/").get_data(as_text=True)
        tags = re.findall(r"<details class=\"nav-folders-folder\"[^>]*>", html)
        self.assertGreaterEqual(len(tags), 4)
        for tag in tags:
            self.assertRegex(tag, r"(?:\sopen(?:\s|>)|(?:\sopen)$)")

    def test_example_folders_hides_disabled_module_links(self):
        reset_tenant(load_tenant_from_path(_EXAMPLE))
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        folders = html.split("data-nav-folders-menu")[1].split("</nav>")[0]
        self.assertIn("data-nav-folders", html)
        self.assertNotIn("/memes/", folders)
        self.assertNotIn("/grok-bot/", folders)
        self.assertNotIn('href="/x/"', folders)
        self.assertNotIn(">Grok Bot<", folders)
        peer = html.split("data-nav-folders")[0]
        self.assertNotIn(">X<", peer)
        self.assertIn("Life", folders)
        self.assertIn("Work", folders)
        self.assertIn('href="/projects/?project=home-ops#home-ops"', folders)
        self.assertIn('href="/projects/?project=side-project#side-project"', folders)
        self.assertIn("Folders", html.split("</nav>")[0])

    def test_folders_is_active_on_grok_bot_and_memes(self):
        reset_tenant(load_tenant_from_path(_SETH))
        grok = self.client.get("/grok-bot/").get_data(as_text=True)
        memes = self.client.get("/memes/").get_data(as_text=True)
        home = self.client.get("/").get_data(as_text=True)
        self.assertIn("nav-folders-toggle active", grok)
        self.assertIn("nav-folders-toggle active", memes)
        self.assertNotIn("nav-folders-toggle active", home.split("</nav>")[0])
        self.assertIn('class="subnav"', memes)
        self.assertIn("Daily Queue", memes)

    def test_home_has_no_hub_cards_and_waiting_is_first(self):
        reset_tenant(load_tenant_from_path(_EXAMPLE))
        html = self.client.get("/").get_data(as_text=True)
        self.assertNotIn("ops-hub", html)
        self.assertNotIn("ops-card", html)
        waiting_at = html.find('id="waiting-heading"')
        week_at = html.find('id="cal-week-heading"')
        self.assertGreater(waiting_at, 0)
        self.assertGreater(week_at, waiting_at)
