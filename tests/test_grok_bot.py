import json
import tempfile
import unittest
from pathlib import Path

from flask import Blueprint, Flask

import tests.bootstrap  # noqa: F401

from src.core.grok_bot import (
    GrokBotRoutines,
    format_last_run,
    normalize_loaded,
    normalize_routine,
    reset_grok_bot_routines,
)
from src.core.s3_store import BucketLayout
from tests.fakes import MemoryS3Store
from web.blueprints.grok_bot import bp as grok_bot_bp

_ROOT = Path(__file__).resolve().parents[1]
_WEB_ROOT = _ROOT / "web"
_SEED = _ROOT / "data" / "grok_bot_routines.json"

SEED_IDS = {
    "ceramic-support-thread-watch",
    "fiddle-lab-presets-homework-nudge",
    "ucla-tba-kickoff-watch",
    "x-follow-candidates",
    "x-reply-candidates",
    "x-tweet-drafts",
    "whole-foods-restock",
}
X_IDS = {"x-follow-candidates", "x-reply-candidates", "x-tweet-drafts"}


def _seed():
    return json.loads(_SEED.read_text(encoding="utf-8"))


def _nav_app(*blueprints):
    app = Flask(
        __name__,
        template_folder=str(_WEB_ROOT / "templates"),
        static_folder=str(_WEB_ROOT / "static"),
    )
    nav = [
        ("home", "index", "/"),
        ("projects", "index", "/projects/"),
        ("spend", "index", "/spend/"),
        ("dashboard", "index", "/memes/"),
        ("generate", "start", "/memes/generate/"),
        ("video", "start", "/memes/video/"),
        ("gallery", "index", "/memes/gallery/"),
        ("daily_candidates", "index", "/memes/gallery/daily-candidates/"),
        ("templates_review", "review_page", "/memes/templates/"),
        ("discovery", "dashboard", "/memes/discovery/"),
        ("x_activity", "index", "/x/"),
        ("grok_bot", "index", "/grok-bot/"),
    ]
    registered = {bp.name for bp in blueprints}
    for name, endpoint, path in nav:
        if name in registered:
            continue
        stub = Blueprint(name, name)
        stub.add_url_rule(path, endpoint, lambda: "")
        app.register_blueprint(stub)
    for bp in blueprints:
        if bp.name == "grok_bot":
            app.register_blueprint(bp, url_prefix="/grok-bot")
        elif bp.name == "dashboard":
            app.register_blueprint(bp, url_prefix="/memes")
        else:
            app.register_blueprint(bp)
    return app


class GrokBotNormalizeTests(unittest.TestCase):
    def test_committed_seed_has_seven_live_crons(self):
        normalized = normalize_loaded(_seed())
        self.assertIsNotNone(normalized)
        self.assertEqual(len(normalized["routines"]), 7)
        ids = {r["id"] for r in normalized["routines"]}
        self.assertEqual(ids, SEED_IDS)
        self.assertNotIn("equinox-cancel-reply-watch", ids)
        self.assertTrue(all(r["enabled"] for r in normalized["routines"]))
        x_ids = {r["id"] for r in normalized["routines"] if r["category"] == "x"}
        self.assertEqual(x_ids, X_IDS)
        jeffy = [r for r in normalized["routines"] if r["owner_agent"] == "jeffy"]
        self.assertEqual([r["id"] for r in jeffy], ["whole-foods-restock"])
        for routine in normalized["routines"]:
            if routine["id"] == "whole-foods-restock":
                self.assertEqual(routine["last_run_at"], "2026-09-11T13:27:16Z")
                self.assertEqual(routine["category"], "shopping")
                self.assertEqual(routine["owner_agent"], "jeffy")
            else:
                self.assertIsNone(routine["last_run_at"])

    def test_normalize_loaded_wraps_bare_array(self):
        routines = _seed()["routines"]
        normalized = normalize_loaded(routines)
        self.assertEqual(normalized["updated_at"], None)
        self.assertEqual(len(normalized["routines"]), 7)
        self.assertEqual({r["id"] for r in normalized["routines"]}, SEED_IDS)

    def test_normalize_maps_unknown_category_to_other(self):
        routine = normalize_routine(
            {
                "id": "mystery-job",
                "name": "Mystery",
                "category": "banjo",
                "enabled": "true",
            }
        )
        self.assertEqual(routine["category"], "other")
        self.assertTrue(routine["enabled"])
        self.assertIsNone(routine["last_run_at"])

    def test_normalize_rejects_path_traversal_id(self):
        self.assertIsNone(normalize_routine({"id": "../public/memes/secret"}))
        self.assertIsNone(normalize_loaded("nope"))
        self.assertIsNone(normalize_loaded({"updated_at": "now"}))

    def test_format_last_run_keeps_unconfirmed_blank(self):
        self.assertIsNone(format_last_run(None))
        self.assertEqual(format_last_run("2026-09-11T13:27:16Z"), "Sep 11, 2026 9:27AM ET")


class GrokBotStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.local_path = Path(self.tmp.name) / "grok_bot_routines.json"
        self.store = MemoryS3Store()
        self.catalog = GrokBotRoutines(store=self.store, local_path=self.local_path)
        reset_grok_bot_routines(self.catalog)

    def tearDown(self):
        reset_grok_bot_routines()
        self.tmp.cleanup()

    def test_s3_key_stays_under_ops_grok_bot(self):
        key = self.catalog.s3_key()
        self.assertEqual(key, "ops/grok-bot/routines.json")
        self.assertTrue(key.startswith("ops/grok-bot/"))
        self.assertFalse(key.startswith("public/"))
        self.assertFalse(key.startswith("public/memes/"))
        BucketLayout.require_ops_key(key)

    def test_save_writes_ops_prefix_not_public(self):
        ok = self.catalog.save(_seed())
        self.assertTrue(ok)
        key = BucketLayout.grok_bot_routines_key()
        self.assertIn(key, self.store.objects)
        self.assertTrue(all(k.startswith("ops/grok-bot/") for k in self.store.objects))
        self.assertFalse(any(k.startswith("public/") for k in self.store.objects))

    def test_save_rejects_bare_array(self):
        with self.assertRaises(TypeError):
            self.catalog.save(_seed()["routines"])

    def test_load_prefers_s3_then_local(self):
        local_only = _seed()
        local_only["routines"][0]["blurb"] = "local"
        self.local_path.write_text(json.dumps(local_only), encoding="utf-8")

        remote = _seed()
        remote["routines"][0]["blurb"] = "from-s3"
        self.store.put_json(BucketLayout.grok_bot_routines_key(), remote)

        loaded = self.catalog.load()
        self.assertEqual(loaded["routines"][0]["blurb"], "from-s3")

    def test_load_falls_back_to_local(self):
        self.catalog.save(_seed())
        self.store.objects.clear()
        loaded = self.catalog.load()
        self.assertEqual({r["id"] for r in loaded["routines"]}, SEED_IDS)

    def test_load_wraps_bare_json_array_from_s3(self):
        self.store.put_json(BucketLayout.grok_bot_routines_key(), _seed()["routines"])
        loaded = self.catalog.load()
        self.assertEqual(len(loaded["routines"]), 7)
        raw, _etag = self.store.get_json(BucketLayout.grok_bot_routines_key())
        self.assertIsInstance(raw, list)
        self.catalog.save(loaded)
        stored, _etag = self.store.get_json(BucketLayout.grok_bot_routines_key())
        self.assertIsInstance(stored, dict)
        self.assertIn("routines", stored)

    def test_unconfigured_s3_uses_local_only(self):
        store = MemoryS3Store(configured=False)
        catalog = GrokBotRoutines(store=store, local_path=self.local_path)
        self.assertFalse(catalog.save(_seed()))
        self.assertEqual(len(catalog.load()["routines"]), 7)
        self.assertEqual(store.objects, {})

    def test_s3_down_still_saves_local(self):
        self.store.fail_puts = True
        ok = self.catalog.save(_seed())
        self.assertFalse(ok)
        local = json.loads(self.local_path.read_text(encoding="utf-8"))
        self.assertEqual(len(local["routines"]), 7)

    def test_ensure_seeded_write_through_when_s3_empty(self):
        self.local_path.write_text(json.dumps(_seed()), encoding="utf-8")
        self.assertTrue(self.catalog.ensure_seeded())
        key = BucketLayout.grok_bot_routines_key()
        self.assertEqual(key, "ops/grok-bot/routines.json")
        stored, _etag = self.store.get_json(key)
        self.assertEqual(len(stored["routines"]), 7)
        self.assertTrue(all(k.startswith("ops/grok-bot/") for k in self.store.objects))

    def test_ensure_seeded_does_not_overwrite_s3(self):
        remote = _seed()
        remote["routines"][0]["blurb"] = "live-s3"
        self.store.put_json(BucketLayout.grok_bot_routines_key(), remote)
        self.local_path.write_text(json.dumps(_seed()), encoding="utf-8")
        self.assertTrue(self.catalog.ensure_seeded())
        stored, _etag = self.store.get_json(BucketLayout.grok_bot_routines_key())
        self.assertEqual(stored["routines"][0]["blurb"], "live-s3")


class GrokBotFlaskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.local_path = Path(self.tmp.name) / "grok_bot_routines.json"
        self.store = MemoryS3Store()
        self.catalog = GrokBotRoutines(store=self.store, local_path=self.local_path)
        reset_grok_bot_routines(self.catalog)
        self.app = _nav_app(grok_bot_bp)
        self.client = self.app.test_client()

    def tearDown(self):
        reset_grok_bot_routines()
        self.tmp.cleanup()

    def test_index_empty_state(self):
        response = self.client.get("/grok-bot/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn(
            "No Grok Bot routines file — Jeffy writes to ops/grok-bot/routines.json",
            html,
        )
        self.assertIn("start/stop lives in Grok Bot settings", html)
        self.assertIn('href="/grok-bot/"', html)
        self.assertNotIn("Start routine", html)
        self.assertNotIn("Stop routine", html)

    def test_index_lists_seed_grouped_by_category(self):
        self.catalog.save(_seed())
        html = self.client.get("/grok-bot/").get_data(as_text=True)
        self.assertIn("Whole Foods restock", html)
        self.assertIn("Ceramic support thread watch", html)
        self.assertIn("X follow candidates", html)
        self.assertIn("X reply candidates", html)
        self.assertIn("X tweet drafts", html)
        self.assertNotIn("Equinox cancel-reply watch", html)
        self.assertNotIn("equinox-cancel-reply-watch", html)
        self.assertIn("Fiddle Lab presets homework nudge", html)
        self.assertIn("UCLA TBA kickoff watch", html)
        self.assertIn('data-category="x"', html)
        self.assertIn('data-category="shopping"', html)
        self.assertIn("Every 10 days at 9:00am ET", html)
        self.assertIn("Build WF cart, wait for Seth to checkout", html)
        self.assertIn("Last run", html)
        self.assertIn("Enabled", html)
        self.assertNotIn("Start routine", html)
        self.assertNotIn("Stop routine", html)

        x_section_at = html.find('<section class="grok-bot-section" data-category="x">')
        self.assertGreater(x_section_at, 0)
        next_section = html.find('<section class="grok-bot-section"', x_section_at + 1)
        x_chunk = html[x_section_at:next_section if next_section > 0 else None]
        self.assertIn("X follow candidates", x_chunk)
        self.assertIn("X reply candidates", x_chunk)
        self.assertIn("X tweet drafts", x_chunk)
        self.assertNotIn("Ceramic support thread watch", x_chunk)
        self.assertNotIn("Whole Foods restock", x_chunk)

    def test_index_filters_by_agent_and_enabled(self):
        payload = _seed()
        payload["routines"].append(
            {
                "id": "parked-ops-job",
                "name": "Parked ops job",
                "owner_agent": "jeffy",
                "category": "ops",
                "enabled": False,
                "schedule_human": "Paused",
                "blurb": "Not running",
            }
        )
        self.catalog.save(payload)
        jeffy = self.client.get("/grok-bot/?filter=jeffy").get_data(as_text=True)
        self.assertIn("Whole Foods restock", jeffy)
        self.assertNotIn("Equinox cancel-reply watch", jeffy)
        self.assertIn("Parked ops job", jeffy)
        self.assertNotIn("Ceramic support thread watch", jeffy)

        stevie = self.client.get("/grok-bot/?filter=stevie").get_data(as_text=True)
        self.assertIn("Ceramic support thread watch", stevie)
        self.assertIn("X tweet drafts", stevie)
        self.assertNotIn("Whole Foods restock", stevie)

        enabled = self.client.get("/grok-bot/?filter=enabled").get_data(as_text=True)
        self.assertIn("Whole Foods restock", enabled)
        self.assertIn("X tweet drafts", enabled)
        self.assertNotIn("Parked ops job", enabled)

    def test_grok_bot_sits_next_to_x_in_life_nav(self):
        nav = (_WEB_ROOT / "templates" / "base.html").read_text(encoding="utf-8")
        x_at = nav.find("url_for('x_activity.index')")
        grok_at = nav.find("url_for('grok_bot.index')")
        memes_at = nav.find("url_for('dashboard.index')")
        subnav_at = nav.find('class="subnav"')
        self.assertGreater(x_at, 0)
        self.assertGreater(grok_at, x_at)
        self.assertGreater(memes_at, grok_at)
        self.assertGreater(subnav_at, grok_at)


if __name__ == "__main__":
    unittest.main()
