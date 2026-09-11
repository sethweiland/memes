"""
Token usage tracking for cost monitoring.

Shared store (when MEME_ASSETS_BUCKET is set):

    s3://{bucket}/ops/usage/{provider}/{YYYY}/{MM}.json

Local fallback / cache:

    data/usage/{provider}/{YYYY}/{MM}.json

Legacy local log (read-only):

    data/token_usage.jsonl

Monthly JSON is rewritten with ETag optimistic concurrency so S3 is not used
as an infinite append log or as one object per API call. Logging never raises
to the caller — meme generation must keep working if S3 is down.

Each event includes ``project`` (string id). This repo defaults to ``memes``
via ``USAGE_PROJECT`` / ``MEME_PROJECT``. One monthly object per provider —
do not split S3 into per-project prefixes. Pre-tag xAI events without
``project`` are read as ``memes``; they are not rewritten.

Cost is a documented heuristic, not xAI billing. The API response only has
token counts; ``estimated_cost_usd`` from grok.py is typically None.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.core.projects import (
    assumed_legacy_xai_memes,
    resolve_event_project,
    resolve_write_project,
)
from src.core.s3_store import (
    BucketLayout,
    PreconditionFailed,
    S3Store,
    get_s3_store,
)


logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
LOCAL_USAGE_ROOT = Path("data/usage")
LEGACY_JSONL_PATH = Path("data/token_usage.jsonl")
S3_WRITE_RETRIES = 5

# Heuristic only — not from the xAI billing API.
# Same blended rate the Spend page used when estimated_cost_usd was unset.
HEURISTIC_USD_PER_MILLION_TOKENS = 0.045


def estimate_cost_usd(
    prompt_tokens: int,
    completion_tokens: int,
    explicit: Optional[float] = None,
) -> Optional[float]:
    """Return an explicit cost, or the documented blended heuristic."""
    if explicit is not None:
        return float(explicit)
    total = int(prompt_tokens or 0) + int(completion_tokens or 0)
    if total <= 0:
        return 0.0
    return round((total / 1_000_000) * HEURISTIC_USD_PER_MILLION_TOKENS, 6)


def empty_month_doc(provider: str, year: int, month: int) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": BucketLayout.safe_provider(provider),
        "year": int(year),
        "month": int(month),
        "totals": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "call_count": 0,
            "estimated_cost_usd": 0.0,
        },
        "events": [],
    }


def local_usage_path(provider: str, year: int, month: int) -> Path:
    provider = BucketLayout.safe_provider(provider)
    return LOCAL_USAGE_ROOT / provider / f"{year:04d}" / f"{month:02d}.json"


def _event_id(event: dict[str, Any]) -> str:
    if event.get("id"):
        return str(event["id"])
    return "|".join(
        [
            str(event.get("timestamp", "")),
            str(event.get("model", "")),
            str(event.get("prompt_tokens", "")),
            str(event.get("completion_tokens", "")),
        ]
    )


def merge_month_docs(*docs: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Union events by id, then recompute totals from the event list."""
    base: Optional[dict[str, Any]] = None
    events_by_id: dict[str, dict[str, Any]] = {}
    for doc in docs:
        if not doc:
            continue
        if base is None:
            base = {
                "schema_version": SCHEMA_VERSION,
                "provider": doc.get("provider"),
                "year": doc.get("year"),
                "month": doc.get("month"),
            }
        for event in doc.get("events") or []:
            if isinstance(event, dict):
                events_by_id[_event_id(event)] = event
    if base is None:
        raise ValueError("merge_month_docs requires at least one document")
    events = sorted(events_by_id.values(), key=lambda item: item.get("timestamp") or "")
    return _with_totals(base, events)


def _with_totals(doc: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    prompt = sum(int(event.get("prompt_tokens") or 0) for event in events)
    completion = sum(int(event.get("completion_tokens") or 0) for event in events)
    cost = 0.0
    for event in events:
        event_cost = event.get("estimated_cost_usd")
        if event_cost is None:
            event_cost = estimate_cost_usd(
                int(event.get("prompt_tokens") or 0),
                int(event.get("completion_tokens") or 0),
            )
        cost += float(event_cost or 0)
    out = dict(doc)
    out["schema_version"] = SCHEMA_VERSION
    out["events"] = events
    out["totals"] = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "call_count": len(events),
        "estimated_cost_usd": round(cost, 6),
    }
    return out


def _event_cost(event: dict[str, Any]) -> float:
    event_cost = event.get("estimated_cost_usd")
    if event_cost is None:
        event_cost = estimate_cost_usd(
            int(event.get("prompt_tokens") or 0),
            int(event.get("completion_tokens") or 0),
        )
    return float(event_cost or 0)


def _project_breakdown(events: list[dict[str, Any]]) -> tuple[dict[str, Any], int]:
    buckets: dict[str, dict[str, Any]] = {}
    legacy_assumed = 0
    for event in events:
        if not isinstance(event, dict):
            continue
        if assumed_legacy_xai_memes(event):
            legacy_assumed += 1
        project_id = resolve_event_project(event)
        bucket = buckets.setdefault(
            project_id,
            {
                "total_tokens": 0,
                "total_cost_usd": 0.0,
                "call_count": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
            },
        )
        prompt = int(event.get("prompt_tokens") or 0)
        completion = int(event.get("completion_tokens") or 0)
        bucket["prompt_tokens"] += prompt
        bucket["completion_tokens"] += completion
        bucket["total_tokens"] += int(event.get("total_tokens") or (prompt + completion))
        bucket["total_cost_usd"] += _event_cost(event)
        bucket["call_count"] += 1
    for bucket in buckets.values():
        bucket["total_cost_usd"] = round(float(bucket["total_cost_usd"]), 4)
    return buckets, legacy_assumed


def _build_event(
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    estimated_cost_usd: Optional[float],
    project: Optional[str] = None,
) -> dict[str, Any]:
    prompt_tokens = int(prompt_tokens or 0)
    completion_tokens = int(completion_tokens or 0)
    return {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "provider": BucketLayout.safe_provider(provider),
        "model": model,
        "project": resolve_write_project(project),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "estimated_cost_usd": estimate_cost_usd(
            prompt_tokens, completion_tokens, estimated_cost_usd
        ),
        "host": os.environ.get("USAGE_HOST") or socket.gethostname()[:64],
    }


def _read_local_month(provider: str, year: int, month: int) -> Optional[dict[str, Any]]:
    path = local_usage_path(provider, year, month)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read local usage %s: %s", path, exc)
        return None


def _write_local_month(doc: dict[str, Any]) -> None:
    path = local_usage_path(doc["provider"], int(doc["year"]), int(doc["month"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _event_month(event: dict[str, Any]) -> tuple[int, int]:
    timestamp = event.get("timestamp") or ""
    try:
        return int(timestamp[0:4]), int(timestamp[5:7])
    except (TypeError, ValueError):
        now = datetime.now(timezone.utc)
        return now.year, now.month


def _read_legacy_jsonl(provider: str, year: int, month: int) -> dict[str, Any]:
    """Read the original local jsonl so existing Mac logs are not dropped."""
    if not LEGACY_JSONL_PATH.exists():
        return empty_month_doc(provider, year, month)
    prefix = f"{year:04d}-{month:02d}"
    events: list[dict[str, Any]] = []
    try:
        with LEGACY_JSONL_PATH.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("provider") != provider:
                    continue
                if not str(entry.get("timestamp", "")).startswith(prefix):
                    continue
                events.append(entry)
    except OSError as exc:
        logger.warning("Failed to read legacy token log: %s", exc)
        return empty_month_doc(provider, year, month)
    return _with_totals(empty_month_doc(provider, year, month), events)


def _append_s3(
    store: S3Store,
    event: dict[str, Any],
    local_doc: dict[str, Any],
) -> Optional[dict[str, Any]]:
    provider = event["provider"]
    year, month = _event_month(event)
    key = BucketLayout.usage_key(provider, year, month)
    BucketLayout.require_ops_key(key)

    last_error: Optional[BaseException] = None
    for attempt in range(S3_WRITE_RETRIES):
        try:
            remote = store.get_json(key)
        except Exception as exc:
            last_error = exc
            logger.warning("Failed to read S3 usage %s: %s", key, exc)
            return None

        if remote:
            remote_doc, etag = remote
        else:
            remote_doc, etag = empty_month_doc(provider, year, month), None

        merged = merge_month_docs(remote_doc, local_doc)
        try:
            if etag:
                store.put_json(key, merged, if_match=etag)
            else:
                store.put_json(key, merged, if_none_match="*")
            logger.info("Saved usage to S3: s3://%s/%s", store.bucket, key)
            return merged
        except PreconditionFailed as exc:
            last_error = exc
            logger.info(
                "S3 usage write conflict on %s (attempt %s/%s); retrying",
                key,
                attempt + 1,
                S3_WRITE_RETRIES,
            )
            continue
        except Exception as exc:
            last_error = exc
            logger.warning("Failed to write S3 usage %s: %s", key, exc)
            return None

    logger.warning("S3 usage write gave up after retries: %s", last_error)
    return None


def log_token_usage(
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    estimated_cost_usd: Optional[float] = None,
    project: Optional[str] = None,
) -> None:
    """
    Record one API call. Never raises — generation must not fail if S3 is down.

    ``project`` is a string id (see ``src.core.projects``). Default is
    ``USAGE_PROJECT`` or ``MEME_PROJECT``, else ``memes``.
    """
    try:
        event = _build_event(
            provider,
            model,
            prompt_tokens,
            completion_tokens,
            estimated_cost_usd,
            project=project,
        )
        year, month = _event_month(event)
        local_doc = merge_month_docs(
            _read_local_month(event["provider"], year, month)
            or empty_month_doc(event["provider"], year, month),
            {"events": [event], "provider": event["provider"], "year": year, "month": month},
        )

        persisted = None
        try:
            store = get_s3_store()
            if store.configured:
                persisted = _append_s3(store, event, local_doc)
        except Exception as exc:
            logger.warning("S3 token usage write skipped: %s", exc)

        _write_local_month(persisted or local_doc)
    except Exception:
        logger.exception("token usage logging failed")


def _summarize(doc: dict[str, Any], source: str) -> dict[str, Any]:
    totals = doc.get("totals") or {}
    events = [event for event in (doc.get("events") or []) if isinstance(event, dict)]
    by_project, legacy_assumed = _project_breakdown(events)
    return {
        "total_tokens": int(totals.get("total_tokens") or 0),
        "total_cost_usd": round(float(totals.get("estimated_cost_usd") or 0), 4),
        "call_count": int(totals.get("call_count") or 0),
        "prompt_tokens": int(totals.get("prompt_tokens") or 0),
        "completion_tokens": int(totals.get("completion_tokens") or 0),
        "source": source,
        "by_project": by_project,
        "legacy_untagged_xai_as_memes": legacy_assumed,
    }


def get_month_usage(provider: str, year: int, month: int) -> dict[str, Any]:
    """
    Month totals for Spend. Prefers the shared S3 object, then local monthly
    JSON, then the legacy jsonl file.
    """
    empty = {
        "total_tokens": 0,
        "total_cost_usd": 0.0,
        "call_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "source": None,
        "by_project": {},
        "legacy_untagged_xai_as_memes": 0,
    }
    provider = BucketLayout.safe_provider(provider)

    try:
        store = get_s3_store()
        if store.configured:
            key = BucketLayout.usage_key(provider, year, month)
            remote = store.get_json(key)
            if remote:
                doc, _etag = remote
                summary = _summarize(doc, "s3")
                if summary["call_count"]:
                    return summary
    except Exception as exc:
        logger.warning("Failed to read S3 usage for Spend: %s", exc)

    local = _read_local_month(provider, year, month)
    if local:
        summary = _summarize(local, "local")
        if summary["call_count"]:
            return summary

    legacy = _read_legacy_jsonl(provider, year, month)
    summary = _summarize(legacy, "local_legacy_jsonl")
    if summary["call_count"]:
        return summary

    return empty
