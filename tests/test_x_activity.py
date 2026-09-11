import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from flask import Blueprint, Flask

import tests.bootstrap  # noqa: F401

from src.core.s3_store import BucketLayout
from src.core.x_activity import (
    XActivityQueue,
    require_date,
    reset_x_activity_queue,
    summarize,
)
from tests.fakes import MemoryS3Store
from web.blueprints.dashboard import bp as dashboard_bp
from web.blueprints.x_activity import bp as x_activity_bp

_WEB_ROOT = Path(__file__).resolve().parents[1] / "web"
DATE = "2026-09-11"
FOLLOW_ID = "11111111-1111-1111-1111-111111111111"
POST_ID = "22222222-2222-2222-2222-222222222222"
REPLY_ID = "33333333-3333-3333-3333-333333333333"


def _fixture(date=DATE):
    return {
        "date": date,
        "candidates": [
            {
                "id": FOLLOW_ID,
                "kind": "follow",
                "status": "pending",
                "body": "Follow this banjo account",
                "target": {"handle": "@highlonesome"},
                "media_urls": [],
                "created_at": "2026-09-11T12:00:00",
                "source": "stevie",
                "project": "x",
            },
            {
                "id": POST_ID,
                "kind": "post",
                "status": "pending",
                "body": "New meme drop",
                "target": {"handle": "@memes851988"},
                "media_urls": ["https://example.com/m.jpg"],
                "created_at": "2026-09-11T12:01:00",
                "source": "stevie",
                "project": "x",
            },
            {
                "id": REPLY_ID,
                "kind": "reply",
                "status": "pending",
                "body": "this riff slaps",
                "target": {"handle": "@foo", "tweet_id": "12345"},
                "media_urls": [],
                "created_at": "2026-09-11T12:02:00",
                "source": "stevie",
                "project": "x",
            },
        ],
    }


def _nav_app(*blueprints):
    app = Flask(
        __name__,
        template_folder=str(_WEB_ROOT / "templates"),
        static_folder=str(_WEB_ROOT / "static"),
    )
    nav = [
        ("dashboard", "index", "/"),
        ("spend", "index", "/spend/"),
        ("generate", "start", "/generate/"),
        ("video", "start", "/video/"),
        ("gallery", "index", "/gallery/"),
        ("daily_candidates", "index", "/gallery/daily-candidates/"),
        ("templates_review", "review_page", "/templates/"),
        ("discovery", "dashboard", "/discovery/"),
        ("x_activity", "index", "/x/"),
    ]
    registered = {bp.name for bp in blueprints}
    for name, endpoint, path in nav:
        if name in registered:
            continue
        stub = Blueprint(name, name)
        stub.add_url_rule(path, endpoint, lambda: "")
        app.register_blueprint(stub)
    for bp in blueprints:
        app.register_blueprint(bp)
    return app


class XActivityQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.local_dir = Path(self.tmp.name)
        self.store = MemoryS3Store()
        self.queue = XActivityQueue(store=self.store, local_dir=self.local_dir)
        reset_x_activity_queue(self.queue)

    def tearDown(self):
        reset_x_activity_queue()
        self.tmp.cleanup()

    def test_s3_key_stays_under_ops_queue_x_activity(self):
        key = self.queue.s3_key(DATE)
        self.assertEqual(key, "ops/queue/x-activity/2026-09-11.json")
        self.assertTrue(key.startswith("ops/queue/x-activity/"))
        self.assertFalse(key.startswith("public/"))
        self.assertFalse(key.startswith("public/memes/"))
        BucketLayout.require_ops_key(key)

    def test_require_date_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            require_date("../public/memes/secret")
        with self.assertRaises(ValueError):
            self.queue.s3_key("not-a-date")

    def test_save_writes_ops_prefix_not_public(self):
        ok = self.queue.save(DATE, _fixture())
        self.assertTrue(ok)
        key = BucketLayout.x_activity_key(DATE)
        self.assertIn(key, self.store.objects)
        self.assertTrue(all(k.startswith("ops/queue/x-activity/") for k in self.store.objects))
        self.assertFalse(any(k.startswith("public/") for k in self.store.objects))

    def test_load_prefers_s3_then_local(self):
        local_only = _fixture()
        local_only["candidates"][0]["body"] = "local"
        (self.local_dir).mkdir(parents=True, exist_ok=True)
        (self.local_dir / f"{DATE}.json").write_text(json.dumps(local_only), encoding="utf-8")

        remote = _fixture()
        remote["candidates"][0]["body"] = "from-s3"
        self.store.put_json(BucketLayout.x_activity_key(DATE), remote)

        loaded = self.queue.load(DATE)
        self.assertEqual(loaded["candidates"][0]["body"], "from-s3")

    def test_load_falls_back_to_local(self):
        self.queue.save(DATE, _fixture())
        self.store.objects.clear()
        loaded = self.queue.load(DATE)
        self.assertEqual(loaded["candidates"][0]["id"], FOLLOW_ID)

    def test_unconfigured_s3_uses_local_only(self):
        store = MemoryS3Store(configured=False)
        queue = XActivityQueue(store=store, local_dir=self.local_dir)
        self.assertFalse(queue.save(DATE, _fixture()))
        self.assertEqual(queue.load(DATE)["date"], DATE)
        self.assertEqual(store.objects, {})

    def test_s3_down_still_saves_local(self):
        self.store.fail_puts = True
        ok = self.queue.save(DATE, _fixture())
        self.assertFalse(ok)
        local = json.loads((self.local_dir / f"{DATE}.json").read_text(encoding="utf-8"))
        self.assertEqual(local["candidates"][0]["id"], FOLLOW_ID)

    def test_approve_updates_status_in_s3(self):
        self.queue.save(DATE, _fixture())
        updated = self.queue.approve(DATE, FOLLOW_ID, body="Follow @highlonesome please")
        self.assertEqual(updated["status"], "approved")
        self.assertEqual(updated["body"], "Follow @highlonesome please")

        stored, _etag = self.store.get_json(BucketLayout.x_activity_key(DATE))
        follow = next(c for c in stored["candidates"] if c["id"] == FOLLOW_ID)
        self.assertEqual(follow["status"], "approved")
        self.assertEqual(follow["body"], "Follow @highlonesome please")
        self.assertIn("approved_at", follow)
        self.assertEqual(follow["source"], "stevie")
        self.assertEqual(follow["project"], "x")

    def test_skip_updates_status_in_s3(self):
        self.queue.save(DATE, _fixture())
        updated = self.queue.skip(DATE, POST_ID)
        self.assertEqual(updated["status"], "skipped")
        stored, _etag = self.store.get_json(BucketLayout.x_activity_key(DATE))
        post = next(c for c in stored["candidates"] if c["id"] == POST_ID)
        self.assertEqual(post["status"], "skipped")
        self.assertIn("skipped_at", post)

    def test_update_body_keeps_pending(self):
        self.queue.save(DATE, _fixture())
        updated = self.queue.update_body(DATE, REPLY_ID, "edited reply")
        self.assertEqual(updated["status"], "pending")
        self.assertEqual(updated["body"], "edited reply")

    def test_approve_missing_returns_none(self):
        self.assertIsNone(self.queue.approve(DATE, FOLLOW_ID))
        self.queue.save(DATE, _fixture())
        self.assertIsNone(self.queue.skip(DATE, "missing"))

    def test_summarize_counts(self):
        data = _fixture()
        data["candidates"][0]["status"] = "approved"
        data["candidates"][1]["status"] = "skipped"
        summary = summarize(data, DATE)
        self.assertEqual(summary["pending_count"], 1)
        self.assertEqual(summary["approved_count"], 1)
        self.assertEqual(summary["skipped_count"], 1)
        self.assertEqual(summary["kind_counts"]["reply"], 1)


class XActivityFlaskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = MemoryS3Store()
        self.queue = XActivityQueue(store=self.store, local_dir=Path(self.tmp.name))
        reset_x_activity_queue(self.queue)
        self.app = _nav_app(x_activity_bp)
        self.client = self.app.test_client()

    def tearDown(self):
        reset_x_activity_queue()
        self.tmp.cleanup()

    def test_index_empty_state(self):
        response = self.client.get("/x/?date=2026-09-11")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn(
            "No pending X drafts for this date — Stevie writes to ops/queue/x-activity/",
            html,
        )
        self.assertIn("this app never posts to X", html)
        self.assertIn('href="/x/"', html)

    def test_index_renders_fixture_and_filters(self):
        self.queue.save(DATE, _fixture())
        response = self.client.get("/x/?date=2026-09-11")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("@highlonesome", html)
        self.assertIn("New meme drop", html)
        self.assertIn("this riff slaps", html)
        self.assertIn("Follow", html)
        self.assertIn("Post", html)
        self.assertIn("Reply", html)

        follow_only = self.client.get("/x/?date=2026-09-11&kind=follow").get_data(as_text=True)
        self.assertIn("@highlonesome", follow_only)
        self.assertNotIn("New meme drop", follow_only)

    def test_approve_updates_s3_json_status(self):
        self.queue.save(DATE, _fixture())
        response = self.client.post(
            f"/x/api/candidates/{DATE}/approve/{FOLLOW_ID}",
            json={"body": "Approved follow copy"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])

        key = BucketLayout.x_activity_key(DATE)
        self.assertEqual(key, "ops/queue/x-activity/2026-09-11.json")
        stored, _etag = self.store.get_json(key)
        follow = next(c for c in stored["candidates"] if c["id"] == FOLLOW_ID)
        self.assertEqual(follow["status"], "approved")
        self.assertEqual(follow["body"], "Approved follow copy")
        self.assertTrue(all(k.startswith("ops/queue/x-activity/") for k in self.store.objects))

    def test_skip_updates_s3_json_status(self):
        self.queue.save(DATE, _fixture())
        response = self.client.post(f"/x/api/candidates/{DATE}/skip/{POST_ID}")
        self.assertEqual(response.status_code, 200)
        stored, _etag = self.store.get_json(BucketLayout.x_activity_key(DATE))
        post = next(c for c in stored["candidates"] if c["id"] == POST_ID)
        self.assertEqual(post["status"], "skipped")

    def test_update_body(self):
        self.queue.save(DATE, _fixture())
        response = self.client.post(
            f"/x/api/candidates/{DATE}/update-body/{REPLY_ID}",
            json={"body": "rewritten"},
        )
        self.assertEqual(response.status_code, 200)
        stored, _etag = self.store.get_json(BucketLayout.x_activity_key(DATE))
        reply = next(c for c in stored["candidates"] if c["id"] == REPLY_ID)
        self.assertEqual(reply["body"], "rewritten")
        self.assertEqual(reply["status"], "pending")

    def test_invalid_date_is_400(self):
        response = self.client.get("/x/api/candidates/../public")
        self.assertEqual(response.status_code, 404)
        response = self.client.post("/x/api/candidates/not-a-date/approve/abc")
        self.assertEqual(response.status_code, 400)

    def test_approve_missing_is_404(self):
        response = self.client.post(f"/x/api/candidates/{DATE}/approve/{FOLLOW_ID}")
        self.assertEqual(response.status_code, 404)


class DashboardXBadgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = MemoryS3Store()
        self.queue = XActivityQueue(store=self.store, local_dir=Path(self.tmp.name))
        reset_x_activity_queue(self.queue)
        self.app = _nav_app(dashboard_bp)
        self.client = self.app.test_client()

    def tearDown(self):
        reset_x_activity_queue()
        self.tmp.cleanup()

    def test_home_shows_x_pending_badge(self):
        today = datetime.now().strftime("%Y-%m-%d")
        self.queue.save(today, _fixture(today))
        with patch("web.blueprints.dashboard._get_daily_candidates_count", return_value=None):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("X Pending", html)
        self.assertIn("3", html)
        self.assertIn("Review X", html)
        self.assertIn("/x/", html)


if __name__ == "__main__":
    unittest.main()
