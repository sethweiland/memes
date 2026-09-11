import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import tests.bootstrap  # noqa: F401

from src.core.s3_store import BucketLayout, reset_s3_store
from src.core.token_tracker import (
    estimate_cost_usd,
    get_month_usage,
    log_token_usage,
    merge_month_docs,
)
from tests.fakes import MemoryS3Store


class _FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 9, 11, 18, 0, 0, tzinfo=tz or timezone.utc)


class TokenTrackerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = MemoryS3Store()
        reset_s3_store()
        self.patches = [
            patch("src.core.token_tracker.LOCAL_USAGE_ROOT", self.root / "usage"),
            patch("src.core.token_tracker.LEGACY_JSONL_PATH", self.root / "token_usage.jsonl"),
            patch("src.core.token_tracker.get_s3_store", return_value=self.store),
            patch("src.core.token_tracker.datetime", _FrozenDateTime),
            patch.dict("os.environ", {"USAGE_HOST": "test-host"}),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()
        reset_s3_store()
        self.tmp.cleanup()

    def test_local_fallback_when_s3_unset(self):
        self.store.configured = False
        log_token_usage("xai", "grok-4.6", 800_000, 200_000)
        usage = get_month_usage("xai", 2026, 9)
        self.assertEqual(usage["call_count"], 1)
        self.assertEqual(usage["total_tokens"], 1_000_000)
        self.assertEqual(usage["source"], "local")
        self.assertAlmostEqual(usage["total_cost_usd"], 0.045)

    def test_s3_write_is_readable_without_local_file(self):
        log_token_usage("xai", "grok-4.6", 200, 50)
        key = BucketLayout.usage_key("xai", 2026, 9)
        self.assertIn(key, self.store.objects)

        # Spend on Fly has no local jsonl — only the shared S3 object.
        for path in (self.root / "usage").rglob("*.json"):
            path.unlink()
        usage = get_month_usage("xai", 2026, 9)
        self.assertEqual(usage["source"], "s3")
        self.assertEqual(usage["call_count"], 1)
        self.assertEqual(usage["total_tokens"], 250)

    def test_s3_outage_does_not_raise_and_keeps_local(self):
        self.store.fail_puts = True
        log_token_usage("xai", "grok-4.6", 10, 5)  # must not raise
        usage = get_month_usage("xai", 2026, 9)
        self.assertEqual(usage["call_count"], 1)
        self.assertEqual(usage["source"], "local")

    def test_monthly_object_accumulates_events(self):
        log_token_usage("xai", "grok-4.6", 10, 1)
        log_token_usage("xai", "grok-4.6", 20, 2)
        raw, _etag = self.store.get_json(BucketLayout.usage_key("xai", 2026, 9))
        self.assertEqual(len(raw["events"]), 2)
        self.assertEqual(raw["totals"]["call_count"], 2)
        self.assertEqual(raw["totals"]["total_tokens"], 33)

    def test_legacy_jsonl_still_read(self):
        self.store.configured = False
        legacy = self.root / "token_usage.jsonl"
        legacy.write_text(
            json.dumps(
                {
                    "timestamp": "2026-09-02T00:00:00Z",
                    "provider": "xai",
                    "model": "grok-4.6",
                    "prompt_tokens": 8,
                    "completion_tokens": 2,
                    "total_tokens": 10,
                    "estimated_cost_usd": None,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        usage = get_month_usage("xai", 2026, 9)
        self.assertEqual(usage["source"], "local_legacy_jsonl")
        self.assertEqual(usage["call_count"], 1)
        self.assertEqual(usage["total_tokens"], 10)

    def test_merge_unions_events_by_id(self):
        merged = merge_month_docs(
            {
                "provider": "xai",
                "year": 2026,
                "month": 9,
                "events": [{"id": "a", "timestamp": "2026-09-01T00:00:00Z", "prompt_tokens": 1, "completion_tokens": 0}],
            },
            {
                "provider": "xai",
                "year": 2026,
                "month": 9,
                "events": [
                    {"id": "a", "timestamp": "2026-09-01T00:00:00Z", "prompt_tokens": 1, "completion_tokens": 0},
                    {"id": "b", "timestamp": "2026-09-02T00:00:00Z", "prompt_tokens": 2, "completion_tokens": 0},
                ],
            },
        )
        self.assertEqual(merged["totals"]["call_count"], 2)
        self.assertEqual(merged["totals"]["prompt_tokens"], 3)

    def test_heuristic_cost_is_documented_blend(self):
        cost = estimate_cost_usd(500_000, 500_000)
        self.assertAlmostEqual(cost, 0.045, places=6)

    def test_s3_get_failure_during_spend_falls_back_to_local(self):
        log_token_usage("xai", "grok-4.6", 40, 10)
        self.store.fail_gets = True
        usage = get_month_usage("xai", 2026, 9)
        self.assertEqual(usage["source"], "local")
        self.assertEqual(usage["call_count"], 1)


if __name__ == "__main__":
    unittest.main()
