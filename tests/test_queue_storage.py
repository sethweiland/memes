import json
import tempfile
import unittest
from pathlib import Path

import tests.bootstrap  # noqa: F401

from src.core.meme_assets import MemeAssetUploader, QueueStorage
from src.core.s3_store import BucketLayout
from tests.fakes import MemoryS3Store


class QueueStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.local_dir = Path(self.tmp.name)
        self.store = MemoryS3Store()
        self.queue = QueueStorage(store=self.store, local_dir=self.local_dir)

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_writes_ops_prefix_not_public(self):
        ok = self.queue.save("2026-09-11", {"date": "2026-09-11", "candidates": []})
        self.assertTrue(ok)
        key = BucketLayout.queue_key("2026-09-11")
        self.assertIn(key, self.store.objects)
        self.assertTrue(key.startswith("ops/"))
        self.assertFalse(key.startswith("public/"))

    def test_load_falls_back_to_legacy_prefix(self):
        legacy_key = BucketLayout.queue_legacy_key("2026-09-10")
        payload = {"date": "2026-09-10", "topic": "legacy", "candidates": []}
        self.store.put_json(legacy_key, payload)
        loaded = self.queue.load("2026-09-10")
        self.assertEqual(loaded["topic"], "legacy")

    def test_load_prefers_ops_over_legacy(self):
        self.store.put_json(
            BucketLayout.queue_legacy_key("2026-09-11"),
            {"date": "2026-09-11", "topic": "old", "candidates": []},
        )
        self.store.put_json(
            BucketLayout.queue_key("2026-09-11"),
            {"date": "2026-09-11", "topic": "new", "candidates": []},
        )
        loaded = self.queue.load("2026-09-11")
        self.assertEqual(loaded["topic"], "new")

    def test_s3_down_still_saves_local(self):
        self.store.fail_puts = True
        ok = self.queue.save("2026-09-11", {"date": "2026-09-11", "candidates": [1]})
        self.assertFalse(ok)
        local = json.loads((self.local_dir / "2026-09-11.json").read_text(encoding="utf-8"))
        self.assertEqual(local["candidates"], [1])

    def test_generated_uploads_use_public_generated_prefix(self):
        uploader = MemeAssetUploader(
            store=self.store,
            public_prefix=None,
        )
        # Force the documented default even if the env overrides it.
        uploader.public_prefix = BucketLayout.GENERATED_PREFIX
        key = uploader._generate_key("banjo_joke.png")
        self.assertTrue(key.startswith("public/memes/generated/"))
        self.assertTrue(key.endswith(".jpg"))
        BucketLayout.require_public_meme_key(key)

    def test_unconfigured_s3_uses_local_only(self):
        store = MemoryS3Store(configured=False)
        queue = QueueStorage(store=store, local_dir=self.local_dir)
        self.assertFalse(queue.save("2026-09-11", {"date": "2026-09-11", "candidates": []}))
        self.assertEqual(queue.load("2026-09-11")["date"], "2026-09-11")


if __name__ == "__main__":
    unittest.main()
