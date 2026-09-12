"""Spend ledger: S3 ops/spend/tech_spend.json, else local, else empty. No invented rows."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import tests.bootstrap  # noqa: F401

from src.core.s3_store import BucketLayout
from src.core.tech_spend import (
    TechSpendStore,
    empty_ledger,
    normalize_ledger,
    reset_tech_spend,
)
from tests.fakes import MemoryS3Store


_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "tech_spend.json"


class NormalizeLedgerTests(unittest.TestCase):
    def test_empty_has_no_invented_rows(self):
        ledger = empty_ledger()
        self.assertEqual(ledger, {"subscriptions": []})
        self.assertNotIn("Imgflip", json.dumps(ledger))
        self.assertNotIn("Cursor", json.dumps(ledger))

    def test_normalize_drops_junk_and_keeps_existing_rows(self):
        self.assertIsNone(normalize_ledger(["not", "an", "object"]))
        self.assertIsNone(normalize_ledger({"subscriptions": "nope"}))
        data = normalize_ledger(
            {
                "subscriptions": [
                    {"id": "hosting-pro", "name": "Example Hosting", "amount_usd": 20},
                    "skip-me",
                ],
                "cancelled": [{"id": "old-saas", "name": "Old SaaS"}],
            }
        )
        self.assertEqual(len(data["subscriptions"]), 1)
        self.assertEqual(data["subscriptions"][0]["id"], "hosting-pro")
        self.assertEqual(data["cancelled"][0]["id"], "old-saas")


class TechSpendStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.local_path = Path(self.tmp.name) / "tech_spend.json"
        reset_tech_spend()

    def tearDown(self):
        reset_tech_spend()
        self.tmp.cleanup()

    def test_s3_key_stays_under_ops_spend(self):
        store = TechSpendStore(store=MemoryS3Store(), local_path=self.local_path)
        key = store.s3_key()
        self.assertEqual(key, "ops/spend/tech_spend.json")
        BucketLayout.require_ops_key(key)
        self.assertFalse(key.startswith("public/"))

    def test_s3_wins_over_local(self):
        self.local_path.write_text(
            json.dumps({"subscriptions": [{"id": "local-only", "name": "Local Only"}]}),
            encoding="utf-8",
        )
        memory = MemoryS3Store()
        memory.put_json(
            BucketLayout.tech_spend_key(),
            {"subscriptions": [{"id": "s3-row", "name": "From S3"}]},
        )
        ledger = TechSpendStore(store=memory, local_path=self.local_path).load()
        ids = [item["id"] for item in ledger["subscriptions"]]
        self.assertEqual(ids, ["s3-row"])
        self.assertNotIn("local-only", ids)

    def test_local_used_when_s3_unset(self):
        self.local_path.write_bytes(_FIXTURE.read_bytes())
        ledger = TechSpendStore(
            store=MemoryS3Store(configured=False),
            local_path=self.local_path,
        ).load()
        ids = [item["id"] for item in ledger["subscriptions"]]
        self.assertIn("hosting-pro", ids)
        self.assertNotIn("vercel-pro", ids)
        self.assertNotIn("cursor", ids)

    def test_empty_when_s3_and_local_missing(self):
        ledger = TechSpendStore(
            store=MemoryS3Store(),
            local_path=self.local_path,
        ).load()
        self.assertEqual(ledger["subscriptions"], [])
        blob = json.dumps(ledger)
        self.assertNotIn("Imgflip", blob)
        self.assertNotIn("Cursor", blob)
        self.assertNotIn("vercel-pro", blob)
        self.assertNotIn("Invented", blob)
