"""Daily candidates review UI shows Why when rationale is present."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from flask import Blueprint, Flask

import tests.bootstrap  # noqa: F401

from src.core.calendar import CalendarStore, reset_calendar
from src.core.daily_queue import build_candidate_record, build_queue_document
from src.core.grok_bot import reset_grok_bot_routines
from src.core.meme_assets import QueueStorage, reset_queue_storage
from src.core.project_board import ProjectBoard, reset_project_board
from src.core.tenant import load_tenant_from_path, reset_tenant
from src.core.x_activity import reset_x_activity_queue
from tests.fakes import MemoryS3Store
from web.blueprints.daily_candidates import bp as daily_candidates_bp
from web.blueprints.home import bp as home_bp
from web.context import register_life_ops_context

_WEB_ROOT = Path(__file__).resolve().parents[1] / "web"
_SETH = Path(__file__).resolve().parent / "fixtures" / "seth_tenant.yaml"


def _app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(_WEB_ROOT / "templates"),
        static_folder=str(_WEB_ROOT / "static"),
    )
    app.secret_key = "test"
    nav = [
        ("projects", "index", "/projects/"),
        ("spend", "index", "/spend/"),
        ("x_activity", "index", "/x/"),
        ("dashboard", "index", "/memes/"),
        ("generate", "start", "/memes/generate/"),
        ("gallery", "index", "/memes/gallery/"),
        ("templates_review", "review_page", "/memes/templates/"),
        ("video", "start", "/memes/video/"),
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
    app.register_blueprint(daily_candidates_bp)
    register_life_ops_context(app)
    return app


class DailyCandidatesWhyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.queue = QueueStorage(
            store=MemoryS3Store(),
            local_dir=Path(self.tmp.name),
        )
        reset_queue_storage(self.queue)
        reset_x_activity_queue()
        reset_grok_bot_routines()
        reset_tenant(load_tenant_from_path(_SETH))
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
        self.client = _app().test_client()

    def tearDown(self):
        reset_queue_storage()
        reset_x_activity_queue()
        reset_grok_bot_routines()
        reset_project_board()
        reset_calendar()
        reset_tenant()
        self.tmp.cleanup()

    def test_why_block_shows_rationale_when_present(self):
        candidate = build_candidate_record(
            date_str="2026-09-15",
            index=1,
            template="Gru's Plan",
            top_text="Billy unplug the Telecaster",
            bottom_text="Monroe's ghost",
            caption="Keep it observational.",
            public_url="https://example.com/gru.jpg",
            s3_key="public/memes/generated/gru.jpg",
            local_path="",
            filename="gru.jpg",
            created_at="2026-09-15T12:00:00",
            scores={"humor": 4, "accuracy": 2},
            overall_score=3.1,
            rationale="Joke assumes Billy plays a Telecaster.",
            evaluation_notes="Could not verify the Telecaster beat.",
            grounding={
                "claim": "Billy Strings unplugs a Telecaster",
                "support": "no known beat",
                "confidence": "low",
            },
        )
        self.queue.save(
            "2026-09-15",
            build_queue_document(
                date_str="2026-09-15",
                topic="Billy Strings",
                topic_rationale="He's on a festival run.",
                domain="bluegrass",
                generated_at="2026-09-15T12:00:00",
                output_dir="output/memes",
                candidates=[candidate],
            ),
        )
        response = self.client.get("/memes/gallery/daily-candidates/?date=2026-09-15")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("candidate-why", html)
        self.assertIn("Joke assumes Billy plays a Telecaster.", html)
        self.assertIn("on a festival run.", html)
        self.assertIn("Could not verify the Telecaster beat.", html)
        self.assertIn("no known beat", html)
        self.assertIn("project-expand-more", html)
        self.assertIn(">Why<", html)

    def test_old_queue_hides_why_when_fields_missing(self):
        self.queue.save(
            "2026-09-14",
            {
                "date": "2026-09-14",
                "topic": "banjos",
                "domain": "bluegrass",
                "generated_at": "2026-09-14T09:00:00",
                "total_count": 1,
                "candidates": [
                    {
                        "id": "2026-09-14_1",
                        "index": 1,
                        "template": "Drake Hotline Bling",
                        "top_text": "Playing a guitar",
                        "bottom_text": "Playing a mandolin",
                        "caption": "fight me",
                        "public_url": "https://example.com/drake.jpg",
                        "status": "pending",
                        "scores": {},
                        "overall_score": None,
                    }
                ],
            },
        )
        response = self.client.get("/memes/gallery/daily-candidates/?date=2026-09-14")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Drake Hotline Bling", html)
        self.assertNotIn('data-field="why"', html)
        self.assertNotIn("Joke assumes", html)


if __name__ == "__main__":
    unittest.main()
