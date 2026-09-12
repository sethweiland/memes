import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Blueprint, Flask

import tests.bootstrap  # noqa: F401

from src.core.projects import (
    UNALLOCATED_PROJECT,
    allocate_amount,
    build_project_rollup,
    monthly_equivalent,
    project_order,
    subscription_shares,
)
from src.core.tenant import load_tenant_from_path, reset_tenant
from src.core.s3_store import reset_s3_store
from src.core.token_tracker import get_month_usage
from tests.fakes import MemoryS3Store
from web.blueprints.spend import bp as spend_bp

_ROOT = Path(__file__).resolve().parents[1]
_LEDGER = Path(__file__).resolve().parent / "fixtures" / "tech_spend.json"
_SETH = Path(__file__).resolve().parent / "fixtures" / "seth_tenant.yaml"
_WEB_ROOT = _ROOT / "web"


def _spend_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(_WEB_ROOT / "templates"),
        static_folder=str(_WEB_ROOT / "static"),
    )
    nav = [
        ("home", "index", "/"),
        ("projects", "index", "/projects/"),
        ("x_activity", "index", "/x/"),
        ("grok_bot", "index", "/grok-bot/"),
        ("dashboard", "index", "/memes/"),
        ("generate", "start", "/memes/generate/"),
        ("video", "start", "/memes/video/"),
        ("gallery", "index", "/memes/gallery/"),
        ("daily_candidates", "index", "/memes/gallery/daily-candidates/"),
        ("templates_review", "review_page", "/memes/templates/"),
        ("discovery", "dashboard", "/memes/discovery/"),
    ]
    for name, endpoint, path in nav:
        stub = Blueprint(name, name)
        stub.add_url_rule(path, endpoint, lambda: "")
        app.register_blueprint(stub)
    app.register_blueprint(spend_bp, url_prefix="/spend")
    return app


class ProjectAllocationTests(unittest.TestCase):
    def setUp(self):
        reset_tenant(load_tenant_from_path(_SETH))

    def tearDown(self):
        reset_tenant()

    def test_x_is_a_first_class_project(self):
        order = project_order()
        self.assertIn("x", order)
        self.assertIn("shared", order)
        self.assertIn("unallocated", order)
        for pid in (
            "memes",
            "sethweiland-com",
            "waiver-wire",
            "x",
            "linkmarketcap",
            "whippoorwill",
            "millgrass",
        ):
            self.assertIn(pid, order)
        self.assertNotIn("equinox", order)
        rollup = build_project_rollup([])
        ids = [row["id"] for row in rollup["rows"]]
        self.assertEqual(ids[: len(order)], list(order))
        x_row = next(row for row in rollup["rows"] if row["id"] == "x")
        self.assertEqual(x_row["name"], "X / Twitter")
        self.assertEqual(x_row["total"], 0)

    def test_ledger_splits_sum_to_one(self):
        data = json.loads(_LEDGER.read_text(encoding="utf-8"))
        items = list(data.get("subscriptions") or []) + list(data.get("cancelled") or [])
        self.assertTrue(items)
        for item in items:
            shares = subscription_shares(item)
            self.assertAlmostEqual(sum(shares.values()), 1.0, places=3, msg=item.get("id"))
            self.assertGreater(len(shares), 0)

    def test_hosting_round_split_sums_to_invoice(self):
        data = json.loads(_LEDGER.read_text(encoding="utf-8"))
        hosting = next(item for item in data["subscriptions"] if item["id"] == "hosting-pro")
        shares = subscription_shares(hosting)
        self.assertAlmostEqual(shares["home-ops"], 0.75)
        self.assertAlmostEqual(shares["unallocated"], 0.25)
        amount = monthly_equivalent(hosting["amount_usd"], hosting["cadence"])
        allocated = allocate_amount(amount, shares)
        self.assertAlmostEqual(sum(allocated.values()), round(amount, 2), places=2)

    def test_unallocated_when_project_missing(self):
        shares = subscription_shares({"name": "mystery", "amount_usd": 5})
        self.assertEqual(shares, {UNALLOCATED_PROJECT: 1.0})

    def test_short_split_remainder_goes_to_unallocated(self):
        shares = subscription_shares({"projects": {"memes": 0.6}})
        self.assertAlmostEqual(shares["memes"], 0.6)
        self.assertAlmostEqual(shares[UNALLOCATED_PROJECT], 0.4)

    def test_rollup_includes_unallocated_row(self):
        rollup = build_project_rollup(
            [
                {
                    "id": "cursor",
                    "category": "fixed",
                    "amount_usd": 60,
                    "cadence": "monthly",
                    "status": "active",
                    "project": "shared",
                },
                {
                    "id": "x-premium",
                    "category": "fixed",
                    "amount_usd": 84,
                    "cadence": "yearly",
                    "status": "cancelling",
                    "project": "unallocated",
                },
            ]
        )
        ids = [row["id"] for row in rollup["rows"]]
        self.assertIn("unallocated", ids)
        unallocated = next(row for row in rollup["rows"] if row["id"] == "unallocated")
        self.assertGreater(unallocated["total"], 0)
        self.assertTrue(unallocated["always_visible"])

    def test_xai_tokens_come_from_events_not_ledger_row(self):
        rollup = build_project_rollup(
            [
                {
                    "id": "xai-tokens",
                    "category": "variable",
                    "amount_usd": 99,
                    "cadence": "usage",
                    "status": "active",
                    "project": "shared",
                }
            ],
            xai_usage={
                "amount": 0.08,
                "by_project": {
                    "memes": {"total_cost_usd": 0.05, "call_count": 2, "total_tokens": 1000},
                    "waiver-wire": {
                        "total_cost_usd": 0.03,
                        "call_count": 1,
                        "total_tokens": 400,
                    },
                },
            },
        )
        by_id = {row["id"]: row for row in rollup["rows"]}
        self.assertAlmostEqual(by_id["memes"]["tokens"], 0.05)
        self.assertAlmostEqual(by_id["waiver-wire"]["tokens"], 0.03)
        self.assertAlmostEqual(by_id["shared"]["tokens"], 0.0)

    def test_cancelled_not_in_monthly_rollup(self):
        rollup = build_project_rollup(
            [
                {
                    "id": "chatgpt-plus",
                    "category": "fixed",
                    "amount_usd": 100,
                    "cadence": "monthly",
                    "status": "cancelled",
                    "project": "unallocated",
                }
            ]
        )
        unallocated = next(row for row in rollup["rows"] if row["id"] == "unallocated")
        self.assertEqual(unallocated["total"], 0)


class SpendProjectPageTests(unittest.TestCase):
    def setUp(self):
        reset_tenant(load_tenant_from_path(_SETH))

    def tearDown(self):
        reset_tenant()

    def test_unallocated_visible_on_spend_page(self):
        app = _spend_app()
        usage = {
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "call_count": 0,
            "by_project": {},
        }
        with patch("src.core.token_tracker.get_month_usage", return_value=usage), patch(
            "web.blueprints.spend._get_aws_current_month_cost", return_value=None
        ):
            response = app.test_client().get("/spend/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("By Project", html)
        self.assertIn("Unallocated", html)
        self.assertIn('data-project="unallocated"', html)
        self.assertIn("sethweiland.com", html)
        self.assertIn("Waiver Wire", html)
        self.assertIn("X / Twitter", html)
        self.assertIn('data-project="x"', html)

    def test_spend_works_with_empty_s3(self):
        tmp = tempfile.TemporaryDirectory()
        store = MemoryS3Store()
        reset_s3_store()
        app = _spend_app()
        try:
            with patch("src.core.token_tracker.get_s3_store", return_value=store), patch(
                "src.core.token_tracker.LOCAL_USAGE_ROOT", Path(tmp.name) / "usage"
            ), patch(
                "src.core.token_tracker.LEGACY_JSONL_PATH", Path(tmp.name) / "token_usage.jsonl"
            ), patch(
                "web.blueprints.spend._get_aws_current_month_cost", return_value=None
            ):
                usage = get_month_usage("xai", 2026, 9)
                self.assertEqual(usage["call_count"], 0)
                response = app.test_client().get("/spend/")
            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            self.assertIn("By Project", html)
            self.assertIn("Unallocated", html)
            self.assertIn("no usage yet", html)
            self.assertIn("xAI / Grok API", html)
            self.assertIn('id="tokens"', html)
            self.assertIn("No token usage recorded this month.", html)
        finally:
            reset_s3_store()
            tmp.cleanup()

    def test_token_row_shows_project_breakdown(self):
        usage = {
            "total_tokens": 12500,
            "total_cost_usd": 0.56,
            "call_count": 7,
            "source": "s3",
            "by_project": {
                "memes": {"total_cost_usd": 0.40, "call_count": 5, "total_tokens": 9000},
                "x": {"total_cost_usd": 0.10, "call_count": 1, "total_tokens": 2000},
                "waiver-wire": {
                    "total_cost_usd": 0.06,
                    "call_count": 1,
                    "total_tokens": 1500,
                },
            },
            "legacy_untagged_xai_as_memes": 0,
        }
        app = _spend_app()
        with patch("src.core.token_tracker.get_month_usage", return_value=usage), patch(
            "web.blueprints.spend._get_aws_current_month_cost", return_value=None
        ):
            response = app.test_client().get("/spend/")
        html = response.get_data(as_text=True)
        self.assertIn("Memes $0.40", html)
        self.assertIn("X / Twitter $0.10", html)
        self.assertIn("Waiver Wire $0.06", html)
        self.assertIn("· S3", html)
        self.assertIn('id="tokens"', html)
        self.assertIn('data-token-project="memes"', html)
        self.assertIn("Missing project tag — shown on purpose.", html)


if __name__ == "__main__":
    unittest.main()
