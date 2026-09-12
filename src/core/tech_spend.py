"""
Operator spend ledger.

Canonical object: ``ops/spend/tech_spend.json`` (never under ``public/``).
Local fallback: ``data/tech_spend.json`` (gitignored).

Load order when ``MEME_ASSETS_BUCKET`` is set: S3, then local, then empty.
Empty is ``{subscriptions: []}``. Do not invent rows.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from src.core.s3_store import BucketLayout, S3Store, get_s3_store


logger = logging.getLogger(__name__)

LOCAL_PATH = Path("data/tech_spend.json")


def empty_ledger() -> dict[str, Any]:
    return {"subscriptions": []}


def normalize_ledger(data: Any) -> Optional[dict[str, Any]]:
    """Keep existing rows only. Reject junk. Do not invent subscriptions."""
    if not isinstance(data, dict):
        return None
    raw_subs = data.get("subscriptions")
    if raw_subs is None:
        raw_subs = []
    if not isinstance(raw_subs, list):
        return None
    subscriptions = [item for item in raw_subs if isinstance(item, dict)]
    out: dict[str, Any] = {"subscriptions": subscriptions}
    raw_cancelled = data.get("cancelled")
    if isinstance(raw_cancelled, list):
        out["cancelled"] = [item for item in raw_cancelled if isinstance(item, dict)]
    if "last_updated" in data:
        out["last_updated"] = data.get("last_updated")
    if "note" in data:
        out["note"] = data.get("note")
    return out


class TechSpendStore:
    """Read-only ledger. Operators upload the JSON; Flask does not invent it."""

    def __init__(
        self,
        store: Optional[S3Store] = None,
        local_path: Optional[Path] = None,
    ):
        self.store = store or get_s3_store()
        self.local_path = local_path or LOCAL_PATH

    def s3_key(self) -> str:
        key = BucketLayout.tech_spend_key()
        BucketLayout.require_ops_key(key)
        if key.startswith(BucketLayout.PUBLIC_PREFIX):
            raise ValueError("Spend ledger must never be written under public/")
        return key

    def _load_local(self) -> Optional[dict[str, Any]]:
        if not self.local_path.exists():
            return None
        try:
            data = json.loads(self.local_path.read_text(encoding="utf-8"))
            return normalize_ledger(data)
        except Exception as exc:
            logger.warning("Failed to load local spend ledger: %s", exc)
            return None

    def load(self) -> dict[str, Any]:
        if self.store.configured:
            try:
                result = self.store.get_json(self.s3_key())
                if result:
                    data, _etag = result
                    normalized = normalize_ledger(data)
                    if normalized is not None:
                        return normalized
            except Exception as exc:
                logger.warning("Failed to load spend ledger from S3: %s", exc)
        local = self._load_local()
        if local is not None:
            return local
        return empty_ledger()


_spend: Optional[TechSpendStore] = None


def get_tech_spend() -> TechSpendStore:
    global _spend
    if _spend is None:
        _spend = TechSpendStore(store=get_s3_store())
    return _spend


def reset_tech_spend(spend: Optional[TechSpendStore] = None) -> None:
    global _spend
    _spend = spend


def load_tech_spend() -> dict[str, Any]:
    return get_tech_spend().load()
