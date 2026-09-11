import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Blueprint, Flask

import tests.bootstrap  # noqa: F401

from web.blueprints.spend import _get_xai_token_usage, bp as spend_bp

_WEB_ROOT = Path(__file__).resolve().parents[1] / "web"


def _spend_app() -> Flask:
    """Spend + stub nav endpoints so base.html can render without the full app."""
    app = Flask(
        __name__,
        template_folder=str(_WEB_ROOT / "templates"),
        static_folder=str(_WEB_ROOT / "static"),
    )
    nav = [
        ("dashboard", "index", "/"),
        ("generate", "start", "/generate/"),
        ("video", "start", "/video/"),
        ("gallery", "index", "/gallery/"),
        ("daily_candidates", "index", "/gallery/daily-candidates/"),
        ("x_activity", "index", "/x/"),
        ("templates_review", "review_page", "/templates/"),
    ]
    for name, endpoint, path in nav:
        stub = Blueprint(name, name)
        stub.add_url_rule(path, endpoint, lambda: "")
        app.register_blueprint(stub)
    app.register_blueprint(spend_bp, url_prefix="/spend")
    return app


class SpendUsageTests(unittest.TestCase):
    def test_spend_reads_shared_s3_month(self):
        usage = {
            "total_tokens": 1800,
            "total_cost_usd": 0.081,
            "call_count": 4,
            "source": "s3",
        }
        with patch("src.core.token_tracker.get_month_usage", return_value=usage):
            result = _get_xai_token_usage()

        self.assertIsNotNone(result)
        self.assertEqual(result["source"], "s3")
        self.assertEqual(result["tokens"], 1800)
        self.assertEqual(result["calls"], 4)
        self.assertAlmostEqual(result["amount"], 0.08)

    def test_no_usage_returns_none(self):
        with patch(
            "src.core.token_tracker.get_month_usage",
            return_value={"total_tokens": 0, "total_cost_usd": 0.0, "call_count": 0},
        ):
            self.assertIsNone(_get_xai_token_usage())

    def test_spend_page_shows_s3_source(self):
        usage = {
            "total_tokens": 12500,
            "total_cost_usd": 0.56,
            "call_count": 7,
            "source": "s3",
            "by_project": {
                "memes": {"total_cost_usd": 0.56, "call_count": 7, "total_tokens": 12500}
            },
        }
        app = _spend_app()
        with patch("src.core.token_tracker.get_month_usage", return_value=usage):
            response = app.test_client().get("/spend/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("xAI / Grok API", html)
        self.assertIn("12,500 tokens", html)
        self.assertIn("7 calls", html)
        self.assertIn("· S3", html)
        self.assertIn("By Project", html)
        self.assertIn("Memes $0.56", html)
