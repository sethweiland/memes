import unittest

import tests.bootstrap  # noqa: F401

from src.core.s3_store import BucketLayout, S3Store


class BucketLayoutTests(unittest.TestCase):
    def test_usage_key_is_monthly_under_ops(self):
        key = BucketLayout.usage_key("xAI", 2026, 9)
        self.assertEqual(key, "ops/usage/xai/2026/09.json")
        BucketLayout.require_ops_key(key)

    def test_queue_key_is_private_ops(self):
        key = BucketLayout.queue_key("2026-09-11")
        self.assertEqual(key, "ops/queue/daily-candidates/2026-09-11.json")
        BucketLayout.require_ops_key(key)

    def test_ops_key_rejects_public_prefix(self):
        with self.assertRaises(ValueError):
            BucketLayout.require_ops_key("public/memes/usage/xai/2026/09.json")

    def test_public_key_rejects_ops(self):
        with self.assertRaises(ValueError):
            BucketLayout.require_public_meme_key("ops/usage/xai/2026/09.json")

    def test_generated_prefix_stays_public(self):
        key = f"{BucketLayout.GENERATED_PREFIX}abc_meme.jpg"
        BucketLayout.require_public_meme_key(key)
        self.assertTrue(key.startswith(BucketLayout.PUBLIC_PREFIX))
        self.assertFalse(key.startswith(BucketLayout.TEMPLATES_PREFIX))


class S3StoreSafetyTests(unittest.TestCase):
    def test_put_json_defaults_to_private_ops(self):
        store = S3Store(bucket="test-bucket")
        store._client = object()
        with self.assertRaises(ValueError):
            store.put_json("public/memes/secret.json", {"nope": True})

    def test_unconfigured_store(self):
        store = S3Store(bucket="")
        self.assertFalse(store.configured)
        self.assertIsNone(store.get_object("ops/usage/xai/2026/09.json"))
        self.assertEqual(store.list_keys("ops/"), [])


if __name__ == "__main__":
    unittest.main()
