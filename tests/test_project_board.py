"""Project board normalize / seed / lane move."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from flask import Blueprint, Flask

import tests.bootstrap  # noqa: F401

from src.core.project_board import (
    ProjectBoard,
    merge_missing_from_tenant,
    normalize_board,
    normalize_project_card,
    reset_project_board,
    seed_projects_from_tenant,
)
from src.core.s3_store import BucketLayout
from src.core.tenant import load_tenant_from_path, reset_tenant
from tests.fakes import MemoryS3Store
from web.blueprints.home import bp as home_bp
from web.blueprints.projects import bp as projects_bp


_ROOT = Path(__file__).resolve().parents[1]
_WEB_ROOT = _ROOT / "web"
_SETH = _ROOT / "config" / "tenant.yaml"
_EXAMPLE = _ROOT / "config" / "tenant.example.yaml"

SETH_IDS = {
    "memes",
    "sethweiland-com",
    "waiver-wire",
    "x",
    "linkmarketcap",
    "whippoorwill",
    "millgrass",
}


def _nav_app():
    app = Flask(
        __name__,
        template_folder=str(_WEB_ROOT / "templates"),
        static_folder=str(_WEB_ROOT / "static"),
    )
    app.secret_key = "test"
    for name, endpoint, path in (
        ("spend", "index", "/spend/"),
        ("x_activity", "index", "/x/"),
        ("grok_bot", "index", "/grok-bot/"),
        ("dashboard", "index", "/memes/"),
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
    app.register_blueprint(projects_bp, url_prefix="/projects")
    return app


class NormalizeTests(unittest.TestCase):
    def test_normalize_project_card_drops_spend_only_and_aliases_lane(self):
        self.assertIsNone(normalize_project_card({"id": "shared", "name": "Shared"}))
        self.assertIsNone(normalize_project_card({"id": "unallocated", "name": "Unallocated"}))
        card = normalize_project_card(
            {
                "id": "Alpha-Bet",
                "name": "Alpha",
                "lane": "waiting_on_seth",
                "owner_agent": "codex",
                "links": {"repo": "https://example.com/r", "prod": ""},
                "summary": "  ",
                "last_done": None,
                "next_steps": "",
            }
        )
        self.assertEqual(card["id"], "alpha-bet")
        self.assertEqual(card["lane"], "waiting_on_you")
        self.assertEqual(card["owner_agent"], "codex")
        self.assertEqual(card["links"]["repo"], "https://example.com/r")
        self.assertIsNone(card["links"]["prod"])
        self.assertIsNone(card["summary"])
        self.assertIsNone(card["last_done"])
        self.assertIsNone(card["next_steps"])

    def test_normalize_board_wraps_bare_array(self):
        board = normalize_board(
            [{"id": "memes", "name": "Memes", "lane": "active"}, {"id": "shared"}]
        )
        self.assertEqual([p["id"] for p in board["projects"]], ["memes"])
        self.assertIsNone(board["updated_at"])

    def test_normalize_board_rejects_junk(self):
        self.assertIsNone(normalize_board("nope"))
        self.assertIsNone(normalize_board({"updated_at": "now"}))


class SeedAndMoveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.local_path = Path(self.tmp.name) / "board.json"
        self.store = MemoryS3Store()
        self.seth = load_tenant_from_path(_SETH)
        self.example = load_tenant_from_path(_EXAMPLE)
        self.board = ProjectBoard(
            store=self.store,
            local_path=self.local_path,
            tenant=self.seth,
        )
        reset_project_board(self.board)
        reset_tenant(self.seth)

    def tearDown(self):
        reset_project_board()
        reset_tenant()
        self.tmp.cleanup()

    def test_s3_key_stays_under_ops_projects(self):
        key = self.board.s3_key()
        self.assertEqual(key, "ops/projects/board.json")
        self.assertTrue(key.startswith("ops/projects/"))
        self.assertFalse(key.startswith("public/"))
        BucketLayout.require_ops_key(key)

    def test_seed_from_seth_tenant_has_seven_ids_no_equinox(self):
        cards = seed_projects_from_tenant(self.seth)
        ids = [c["id"] for c in cards]
        self.assertEqual(set(ids), SETH_IDS)
        self.assertNotIn("equinox", ids)
        self.assertNotIn("shared", ids)
        self.assertNotIn("unallocated", ids)
        for card in cards:
            self.assertIsNone(card["last_done"])
            self.assertIsNone(card["next_steps"])

    def test_example_tenant_seeds_friend_cards(self):
        cards = seed_projects_from_tenant(self.example)
        ids = [c["id"] for c in cards]
        self.assertIn("home-ops", ids)
        self.assertEqual(len(ids), 3)
        self.assertNotIn("memes", ids)

    def test_ensure_seeded_write_through_once(self):
        self.assertFalse(self.local_path.exists())
        first = self.board.ensure_seeded()
        self.assertTrue(self.local_path.exists())
        self.assertIn(BucketLayout.projects_board_key(), self.store.objects)
        self.assertEqual({p["id"] for p in first["projects"]}, SETH_IDS)
        puts = self.store.put_calls
        second = self.board.ensure_seeded()
        self.assertEqual(self.store.put_calls, puts)
        self.assertEqual([p["id"] for p in second["projects"]], [p["id"] for p in first["projects"]])

    def test_seed_local_only_when_bucket_unset(self):
        local_only = ProjectBoard(
            store=MemoryS3Store(configured=False),
            local_path=Path(self.tmp.name) / "local-only.json",
            tenant=self.example,
        )
        data = local_only.ensure_seeded()
        self.assertEqual(len(data["projects"]), 3)
        self.assertTrue((Path(self.tmp.name) / "local-only.json").exists())
        self.assertEqual(len(self.store.objects), 0)

    def test_lane_move(self):
        self.board.ensure_seeded()
        card = self.board.move_lane("memes", "waiting_on_you")
        self.assertEqual(card["lane"], "waiting_on_you")
        reloaded = self.board.load()
        memes = next(p for p in reloaded["projects"] if p["id"] == "memes")
        self.assertEqual(memes["lane"], "waiting_on_you")
        self.assertIsNotNone(memes["updated_at"])

    def test_lane_move_rejects_unknown_project_and_lane(self):
        self.board.ensure_seeded()
        self.assertIsNone(self.board.move_lane("equinox", "active"))
        self.assertIsNone(self.board.move_lane("memes", "sprint-backlog"))

    def test_merge_missing_does_not_overwrite_lane(self):
        board = {
            "updated_at": "2026-09-11T00:00:00+00:00",
            "projects": [
                {
                    "id": "memes",
                    "name": "Memes",
                    "lane": "waiting_on_you",
                    "owner_agent": None,
                    "links": {"repo": None, "prod": None},
                    "summary": None,
                    "last_done": None,
                    "next_steps": None,
                }
            ],
        }
        merged, changed = merge_missing_from_tenant(board, self.seth)
        self.assertTrue(changed)
        by_id = {p["id"]: p for p in merged["projects"]}
        self.assertEqual(by_id["memes"]["lane"], "waiting_on_you")
        self.assertEqual(set(by_id), SETH_IDS)

    def test_save_rejects_bare_array(self):
        with self.assertRaises(TypeError):
            self.board.save([{"id": "memes"}])

    def test_update_card_agent_contract(self):
        self.board.ensure_seeded()
        card = self.board.update_card(
            "waiver-wire",
            lane="blocked",
            last_done="Wrote the tenant seed",
            next_steps="Human: pick a repo URL",
        )
        self.assertEqual(card["lane"], "blocked")
        self.assertEqual(card["last_done"], "Wrote the tenant seed")
        self.assertEqual(card["next_steps"], "Human: pick a repo URL")


class ProjectsPageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.seth = load_tenant_from_path(_SETH)
        self.board = ProjectBoard(
            store=MemoryS3Store(configured=False),
            local_path=Path(self.tmp.name) / "board.json",
            tenant=self.seth,
        )
        reset_project_board(self.board)
        reset_tenant(self.seth)
        self.client = _nav_app().test_client()

    def tearDown(self):
        reset_project_board()
        reset_tenant()
        self.tmp.cleanup()

    def test_seth_projects_page_shows_seven_cards(self):
        response = self.client.get("/projects/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("waiting_on_you", html)
        self.assertIn("Waiting on you", html)
        self.assertNotIn("waiting_on_seth", html)
        self.assertNotIn("Kanban is not built yet", html)
        self.assertNotIn("$", html)
        for name in (
            "Memes",
            "sethweiland.com",
            "Waiver Wire",
            "X / Twitter",
            "Linkmarketcap",
            "Whippoorwill",
            "Millgrass",
        ):
            self.assertIn(name, html)
        self.assertNotIn("Equinox", html)

    def test_lane_move_api(self):
        self.board.ensure_seeded()
        response = self.client.post(
            "/projects/api/projects/memes/lane",
            json={"lane": "blocked"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])
        self.assertEqual(response.get_json()["lane"], "blocked")
        memes = next(p for p in self.board.load()["projects"] if p["id"] == "memes")
        self.assertEqual(memes["lane"], "blocked")

    def test_lane_move_invalid_is_400(self):
        self.board.ensure_seeded()
        response = self.client.post(
            "/projects/api/projects/memes/lane",
            json={"lane": "doing"},
        )
        self.assertEqual(response.status_code, 400)

    def test_example_tenant_board_shows_friend_cards(self):
        example = load_tenant_from_path(_EXAMPLE)
        example_board = ProjectBoard(
            store=MemoryS3Store(configured=False),
            local_path=Path(self.tmp.name) / "example-board.json",
            tenant=example,
        )
        reset_project_board(example_board)
        reset_tenant(example)
        response = self.client.get("/projects/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Home Ops", html)
        self.assertIn("Side Project", html)
        self.assertIn("Writing", html)
        self.assertNotIn("Millgrass", html)
        self.assertNotIn("Linkmarketcap", html)
        self.assertNotIn("waiting_on_seth", html)
        reset_project_board(self.board)
        reset_tenant(self.seth)

    def test_home_lists_waiting_on_you_cards(self):
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
                    },
                    {
                        "id": "memes",
                        "name": "Memes",
                        "lane": "active",
                        "owner_agent": None,
                        "links": {"repo": None, "prod": None},
                        "summary": None,
                        "last_done": None,
                        "next_steps": None,
                    },
                ],
            }
        )
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Waiting on you", html)
        self.assertIn("Needs a call", html)
        self.assertIn("/projects/", html)
        self.assertNotIn("waiting_on_seth", html)
        self.assertNotIn("Nothing queued", html)
