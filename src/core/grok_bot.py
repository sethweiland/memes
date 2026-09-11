"""
Private Grok Bot routine catalog.

Canonical object: ``ops/grok-bot/routines.json`` (never under ``public/``).
Local seed / fallback: ``data/grok_bot_routines.json``.

Reads S3 first, then local. Writes go to both when the bucket is set.
This module catalogs routines only — it never starts or stops them.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from src.core.s3_store import BucketLayout, S3Store, get_s3_store


logger = logging.getLogger(__name__)

CATEGORIES = (
    "shopping",
    "health",
    "x",
    "music",
    "support",
    "sports",
    "ops",
    "other",
)
CATEGORY_LABELS = {
    "shopping": "Shopping",
    "health": "Health",
    "x": "X",
    "music": "Music",
    "support": "Support",
    "sports": "Sports",
    "ops": "Ops",
    "other": "Other",
}
FILTERS = ("all", "enabled", "jeffy", "stevie")
AGENTS = ("jeffy", "stevie")
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LOCAL_PATH = Path("data/grok_bot_routines.json")
ET = ZoneInfo("America/New_York")


def normalize_routine(raw) -> Optional[dict]:
    """Coerce one routine into the catalog shape. Unknown categories become other."""
    if not isinstance(raw, dict):
        return None
    routine_id = str(raw.get("id") or "").strip().lower()
    if not ID_RE.fullmatch(routine_id):
        return None

    category = str(raw.get("category") or "").strip().lower()
    if category not in CATEGORIES:
        category = "other"

    owner = str(raw.get("owner_agent") or "").strip().lower() or "unknown"

    enabled = raw.get("enabled")
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() in {"1", "true", "yes", "on"}
    elif enabled is None:
        enabled = True
    else:
        enabled = bool(enabled)

    last_run = raw.get("last_run_at")
    if last_run is not None:
        last_run = str(last_run).strip() or None

    links = raw.get("links")
    ops_link = links.get("ops") if isinstance(links, dict) else None
    if ops_link is not None:
        ops_link = str(ops_link).strip() or None

    schedule = str(raw.get("schedule") or "").strip() or None
    schedule_human = str(raw.get("schedule_human") or "").strip() or None
    status = str(raw.get("status") or "").strip() or None
    blurb = str(raw.get("blurb") or "").strip() or None
    name = str(raw.get("name") or routine_id).strip()

    project_raw = raw.get("project_id", raw.get("project"))
    project_id = None
    if project_raw is not None and str(project_raw).strip():
        cleaned = "".join(
            ch for ch in str(project_raw).strip().lower() if ch.isalnum() or ch in "-_"
        )
        project_id = cleaned or None

    return {
        "id": routine_id,
        "name": name,
        "owner_agent": owner,
        "project_id": project_id,
        "category": category,
        "enabled": enabled,
        "schedule": schedule,
        "schedule_human": schedule_human,
        "last_run_at": last_run,
        "status": status,
        "blurb": blurb,
        "links": {"ops": ops_link},
    }


def normalize_loaded(data) -> Optional[dict]:
    """
    Canonical shape is ``{updated_at, routines}``.

    On READ only: a bare JSON array is treated as ``routines``.
    Writes stay an object — never persist a list.
    """
    if isinstance(data, list):
        routines_raw = data
        updated_at = None
    elif isinstance(data, dict):
        if "routines" not in data:
            return None
        routines_raw = data.get("routines")
        updated_at = data.get("updated_at")
    else:
        return None

    if not isinstance(routines_raw, list):
        return None

    routines = []
    seen: set[str] = set()
    for raw in routines_raw:
        routine = normalize_routine(raw)
        if not routine or routine["id"] in seen:
            continue
        seen.add(routine["id"])
        routines.append(routine)

    if updated_at is not None:
        updated_at = str(updated_at).strip() or None

    return {"updated_at": updated_at, "routines": routines}


def filter_routines(routines: list[dict], filter_name: str) -> list[dict]:
    if filter_name == "enabled":
        return [r for r in routines if r.get("enabled")]
    if filter_name in AGENTS:
        return [r for r in routines if r.get("owner_agent") == filter_name]
    return list(routines)


def group_by_category(routines: list[dict]) -> list[tuple[str, str, list[dict]]]:
    grouped = []
    for category in CATEGORIES:
        items = [r for r in routines if r.get("category") == category]
        if items:
            grouped.append((category, CATEGORY_LABELS[category], items))
    return grouped


def format_last_run(iso_str: Optional[str]) -> Optional[str]:
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ET).strftime("%b %d, %Y %-I:%M%p ET")
    except (ValueError, TypeError, OSError):
        return iso_str


def summarize(data: Optional[dict]) -> dict:
    routines = list((data or {}).get("routines") or [])
    return {
        "total_count": len(routines),
        "enabled_count": sum(1 for r in routines if r.get("enabled")),
        "agent_counts": {
            agent: sum(1 for r in routines if r.get("owner_agent") == agent)
            for agent in AGENTS
        },
        "updated_at": (data or {}).get("updated_at"),
    }


class GrokBotRoutines:
    """
    S3-backed catalog of Grok Bot cron/event routines.

    Reads ``ops/grok-bot/routines.json`` first, then local
    ``data/grok_bot_routines.json``. Writes go to both when the bucket is set.
    """

    def __init__(
        self,
        store: Optional[S3Store] = None,
        local_path: Optional[Path] = None,
    ):
        self.store = store or S3Store()
        self.local_path = local_path or LOCAL_PATH
        self.prefix = BucketLayout.GROK_BOT_PREFIX

    def s3_key(self) -> str:
        key = BucketLayout.grok_bot_routines_key()
        BucketLayout.require_ops_key(key)
        if not key.startswith(self.prefix):
            raise ValueError(f"Grok Bot key must stay under {self.prefix}: {key}")
        if key.startswith(BucketLayout.PUBLIC_PREFIX):
            raise ValueError(f"Grok Bot data must never be written under public/: {key}")
        return key

    def save(self, data: dict) -> bool:
        """Save catalog JSON to local + S3. Returns True if S3 write succeeded."""
        if not isinstance(data, dict):
            raise TypeError(
                "Grok Bot writes must be {updated_at, routines}, not a bare array"
            )
        normalized = normalize_loaded(data)
        if normalized is None:
            raise ValueError("Grok Bot catalog must contain a routines list")
        json_bytes = json.dumps(normalized, indent=2, ensure_ascii=False).encode("utf-8")

        self.local_path.parent.mkdir(parents=True, exist_ok=True)
        self.local_path.write_bytes(json_bytes)
        logger.info("Saved Grok Bot routines to local: %s", self.local_path)

        if not self.store.configured:
            logger.warning("S3 bucket not configured, Grok Bot routines saved locally only")
            return False

        try:
            s3_key = self.s3_key()
            self.store.put_object(
                s3_key,
                json_bytes,
                kind="private_ops",
                content_type="application/json",
            )
            logger.info(
                "Saved Grok Bot routines to S3: s3://%s/%s",
                self.store.bucket,
                s3_key,
            )
            return True
        except Exception as e:
            logger.warning("Failed to save Grok Bot routines to S3: %s", e)
            return False

    def _load_local(self) -> Optional[dict]:
        if not self.local_path.exists():
            return None
        try:
            data = json.loads(self.local_path.read_text(encoding="utf-8"))
            normalized = normalize_loaded(data)
            if normalized is not None:
                logger.info("Loaded Grok Bot routines from local: %s", self.local_path)
                return normalized
        except Exception as e:
            logger.error("Failed to load local Grok Bot routines: %s", e)
        return None

    def load(self) -> Optional[dict]:
        """Load catalog JSON from S3, with local fallback."""
        if self.store.configured:
            s3_key = self.s3_key()
            try:
                result = self.store.get_json(s3_key)
                if result:
                    data, _etag = result
                    normalized = normalize_loaded(data)
                    if normalized is not None:
                        logger.info(
                            "Loaded Grok Bot routines from S3: s3://%s/%s",
                            self.store.bucket,
                            s3_key,
                        )
                        return normalized
            except Exception as e:
                logger.warning("Failed to load Grok Bot routines from S3 (%s): %s", s3_key, e)

        return self._load_local()

    def ensure_seeded(self) -> bool:
        """
        Write the local seed through to S3 when the bucket is set and empty.

        Never overwrites an existing S3 catalog. Returns True if S3 has data
        after this call.
        """
        if not self.store.configured:
            return False

        s3_key = self.s3_key()
        try:
            existing = self.store.get_json(s3_key)
        except Exception as e:
            logger.warning("Failed to check Grok Bot S3 seed (%s): %s", s3_key, e)
            return False

        if existing:
            data, _etag = existing
            return normalize_loaded(data) is not None

        local = self._load_local()
        if not local:
            return False
        return self.save(local)


_catalog: Optional[GrokBotRoutines] = None


def get_grok_bot_routines() -> GrokBotRoutines:
    global _catalog
    if _catalog is None:
        _catalog = GrokBotRoutines(store=get_s3_store())
    return _catalog


def reset_grok_bot_routines(catalog: Optional[GrokBotRoutines] = None) -> None:
    """Clear or replace the process-wide catalog (tests)."""
    global _catalog
    _catalog = catalog
