"""
Private X (Twitter) activity queue.

Stevie writes drafts to ``ops/queue/x-activity/{YYYY-MM-DD}.json``.
This module loads/saves that JSON and applies approve / skip / edit.
It never posts to X.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.core.s3_store import BucketLayout, S3Store, get_s3_store


logger = logging.getLogger(__name__)

KINDS = ("follow", "post", "reply")
STATUSES = ("pending", "approved", "skipped", "posted")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

LOCAL_DIR = Path("data/x_activity")


def require_date(date_str: str) -> str:
    if not DATE_RE.fullmatch(date_str or ""):
        raise ValueError(f"invalid date: {date_str!r}")
    return date_str


def summarize(data: Optional[dict], date_str: str) -> dict:
    candidates = list((data or {}).get("candidates") or [])
    pending = sum(1 for c in candidates if c.get("status") == "pending")
    return {
        "date": date_str,
        "total_count": len(candidates),
        "pending_count": pending,
        "approved_count": sum(1 for c in candidates if c.get("status") == "approved"),
        "skipped_count": sum(1 for c in candidates if c.get("status") == "skipped"),
        "posted_count": sum(1 for c in candidates if c.get("status") == "posted"),
        "kind_counts": {
            kind: sum(1 for c in candidates if c.get("kind") == kind) for kind in KINDS
        },
    }


class XActivityQueue:
    """
    S3-backed storage for X activity drafts.

    Reads ``ops/queue/x-activity/{date}.json`` first, then local
    ``data/x_activity/{date}.json``. Writes go to both.
    """

    def __init__(
        self,
        store: Optional[S3Store] = None,
        local_dir: Optional[Path] = None,
    ):
        self.store = store or S3Store()
        self.local_dir = local_dir or LOCAL_DIR
        self.prefix = BucketLayout.X_ACTIVITY_PREFIX

    def s3_key(self, date_str: str) -> str:
        key = BucketLayout.x_activity_key(require_date(date_str))
        BucketLayout.require_ops_key(key)
        if not key.startswith(self.prefix):
            raise ValueError(f"X activity key must stay under {self.prefix}: {key}")
        if key.startswith(BucketLayout.PUBLIC_PREFIX):
            raise ValueError(f"X activity must never be written under public/: {key}")
        return key

    def _local_path(self, date_str: str) -> Path:
        return self.local_dir / f"{require_date(date_str)}.json"

    def save(self, date_str: str, data: dict) -> bool:
        """Save queue JSON to S3 and local cache. Returns True if S3 write succeeded."""
        require_date(date_str)
        json_bytes = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")

        self.local_dir.mkdir(parents=True, exist_ok=True)
        local_path = self._local_path(date_str)
        local_path.write_bytes(json_bytes)
        logger.info(f"Saved X activity to local: {local_path}")

        if not self.store.configured:
            logger.warning("S3 bucket not configured, X activity saved locally only")
            return False

        try:
            s3_key = self.s3_key(date_str)
            self.store.put_object(
                s3_key,
                json_bytes,
                kind="private_ops",
                content_type="application/json",
            )
            logger.info(f"Saved X activity to S3: s3://{self.store.bucket}/{s3_key}")
            return True
        except Exception as e:
            logger.warning(f"Failed to save X activity to S3: {e}")
            return False

    def load(self, date_str: str) -> Optional[dict]:
        """Load queue JSON from S3, with local fallback."""
        require_date(date_str)
        if self.store.configured:
            s3_key = self.s3_key(date_str)
            try:
                result = self.store.get_json(s3_key)
                if result:
                    data, _etag = result
                    logger.info(f"Loaded X activity from S3: s3://{self.store.bucket}/{s3_key}")
                    return data
            except Exception as e:
                logger.warning(f"Failed to load X activity from S3 ({s3_key}): {e}")

        local_path = self._local_path(date_str)
        if local_path.exists():
            try:
                data = json.loads(local_path.read_text(encoding="utf-8"))
                logger.info(f"Loaded X activity from local: {local_path}")
                return data
            except Exception as e:
                logger.error(f"Failed to load local X activity: {e}")

        return None

    def list_dates(self) -> list[dict]:
        dates_map: dict[str, dict] = {}

        if self.store.configured:
            try:
                for key in self.store.list_keys(self.prefix):
                    if not key.endswith(".json"):
                        continue
                    date_str = key[len(self.prefix) :].removeprefix("/").replace(".json", "")
                    if DATE_RE.fullmatch(date_str) and date_str not in dates_map:
                        data = self.load(date_str)
                        if data:
                            dates_map[date_str] = summarize(data, date_str)
            except Exception as e:
                logger.warning(f"Failed to list S3 X activity files: {e}")

        if self.local_dir.exists():
            for file_path in self.local_dir.glob("*.json"):
                date_str = file_path.stem
                if DATE_RE.fullmatch(date_str) and date_str not in dates_map:
                    data = self.load(date_str)
                    if data:
                        dates_map[date_str] = summarize(data, date_str)

        dates = list(dates_map.values())
        dates.sort(key=lambda x: x["date"], reverse=True)
        return dates

    def pending_count(self, date_str: str) -> Optional[int]:
        data = self.load(date_str)
        if not data:
            return None
        return summarize(data, date_str)["pending_count"]

    def _find(self, data: dict, candidate_id: str) -> Optional[dict]:
        for candidate in data.get("candidates") or []:
            if candidate.get("id") == candidate_id:
                return candidate
        return None

    def approve(
        self,
        date_str: str,
        candidate_id: str,
        body: Optional[str] = None,
    ) -> Optional[dict]:
        """Mark a draft approved. Does not post to X."""
        return self._update_candidate(
            date_str,
            candidate_id,
            status="approved",
            body=body,
            stamp_field="approved_at",
        )

    def skip(self, date_str: str, candidate_id: str) -> Optional[dict]:
        return self._update_candidate(
            date_str,
            candidate_id,
            status="skipped",
            stamp_field="skipped_at",
        )

    def update_body(
        self,
        date_str: str,
        candidate_id: str,
        body: str,
    ) -> Optional[dict]:
        return self._update_candidate(
            date_str,
            candidate_id,
            body=body,
            stamp_field="body_updated_at",
        )

    def _update_candidate(
        self,
        date_str: str,
        candidate_id: str,
        *,
        status: Optional[str] = None,
        body: Optional[str] = None,
        stamp_field: str,
    ) -> Optional[dict]:
        if status is not None and status not in STATUSES:
            raise ValueError(f"invalid status: {status}")
        data = self.load(date_str)
        if not data:
            return None
        candidate = self._find(data, candidate_id)
        if not candidate:
            return None
        if body is not None:
            candidate["body"] = body
        if status is not None:
            candidate["status"] = status
        candidate[stamp_field] = datetime.now().isoformat(timespec="seconds")
        self.save(date_str, data)
        return candidate


_queue: Optional[XActivityQueue] = None


def get_x_activity_queue() -> XActivityQueue:
    global _queue
    if _queue is None:
        _queue = XActivityQueue(store=get_s3_store())
    return _queue


def reset_x_activity_queue(queue: Optional[XActivityQueue] = None) -> None:
    """Clear or replace the process-wide queue (tests)."""
    global _queue
    _queue = queue
