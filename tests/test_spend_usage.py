import unittest
from unittest.mock import patch

import tests.bootstrap  # noqa: F401

from web.blueprints.spend import _get_xai_token_usage


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
