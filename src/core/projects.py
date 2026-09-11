"""
Shared project ids for token events and the tech-spend ledger.

Kanban project ids come from tenant config (``config/tenant.yaml``).
``shared`` and ``unallocated`` are Spend-only — never kanban cards.

Token writers default to the tenant ``defaults.usage_project`` (this repo:
``memes``) unless ``USAGE_PROJECT`` or ``MEME_PROJECT`` is set.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from src.core.tenant import SPEND_ONLY_PROJECT_IDS, load_tenant


DEFAULT_PROJECT = "memes"
UNALLOCATED_PROJECT = "unallocated"
SHARED_PROJECT = "shared"

_SPEND_ONLY_META: dict[str, dict[str, str]] = {
    "shared": {
        "name": "Shared",
        "description": "Cursor, Grok Bot / engineering overhead that is not one product",
        "color": "#7c3aed",
    },
    "unallocated": {
        "name": "Unallocated",
        "description": "Missing tag — always shown, never hidden to clean up a chart",
        "color": "#6b7280",
    },
}

_FALLBACK_ORDER = (
    "memes",
    "sethweiland-com",
    "waiver-wire",
    "x",
    "shared",
    "unallocated",
)

_FALLBACK_KNOWN: dict[str, dict[str, str]] = {
    "memes": {
        "name": "Memes",
        "description": "Bluegrass meme pipeline / meme-ops / Imgflip / Fly / xAI from this repo",
        "color": "#2563eb",
    },
    "sethweiland-com": {
        "name": "sethweiland.com",
        "description": "Musician site on Vercel",
        "color": "#059669",
    },
    "waiver-wire": {
        "name": "Waiver Wire",
        "description": "Fantasy-football / Waiver Wire",
        "color": "#d97706",
    },
    "x": {
        "name": "X / Twitter",
        "description": "@SethWeiland1 activity. X-draft xAI calls set USAGE_PROJECT=x.",
        "color": "#111827",
    },
    **_SPEND_ONLY_META,
}


def known_projects() -> dict[str, dict[str, str]]:
    """Spend metadata: tenant kanban projects + shared/unallocated."""
    result: dict[str, dict[str, str]] = {}
    try:
        tenant = load_tenant()
        for project in tenant.kanban_projects():
            result[project.id] = {
                "name": project.name,
                "description": project.description or (project.summary or ""),
                "color": project.color,
            }
    except Exception:
        result = {pid: dict(meta) for pid, meta in _FALLBACK_KNOWN.items()}
    for pid, meta in _SPEND_ONLY_META.items():
        result.setdefault(pid, dict(meta))
    return result


def project_order() -> tuple[str, ...]:
    ids: list[str] = []
    try:
        ids.extend(load_tenant().project_ids())
    except Exception:
        ids.extend(pid for pid in _FALLBACK_ORDER if pid not in SPEND_ONLY_PROJECT_IDS)
    for extra in SPEND_ONLY_PROJECT_IDS:
        if extra not in ids:
            ids.append(extra)
    return tuple(ids)


def default_write_project() -> str:
    try:
        return load_tenant().default_usage_project or DEFAULT_PROJECT
    except Exception:
        return DEFAULT_PROJECT


def __getattr__(name: str):
    """Lazy aliases so ``from src.core.projects import PROJECT_ORDER`` still works."""
    if name == "PROJECT_ORDER":
        return project_order()
    if name == "KNOWN_PROJECTS":
        return known_projects()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


_WRITE_ENV_KEYS = ("USAGE_PROJECT", "MEME_PROJECT")


def normalize_project_id(value: Optional[str], *, missing: str) -> str:
    cleaned = "".join(
        ch for ch in (value or "").strip().lower() if ch.isalnum() or ch in "-_"
    )
    return cleaned or missing


def project_meta(project_id: str) -> dict[str, str]:
    known = known_projects().get(project_id)
    if known:
        return {"id": project_id, **known}
    return {
        "id": project_id,
        "name": project_id,
        "description": "",
        "color": "#9ca3af",
    }


def event_missing_project(event: dict[str, Any]) -> bool:
    raw = event.get("project")
    return not (raw and str(raw).strip())


def resolve_write_project(explicit: Optional[str] = None) -> str:
    """Project id stamped on a new token event."""
    fallback = default_write_project()
    if explicit and str(explicit).strip():
        return normalize_project_id(str(explicit), missing=fallback)
    for key in _WRITE_ENV_KEYS:
        value = (os.environ.get(key) or "").strip()
        if value:
            return normalize_project_id(value, missing=fallback)
    return fallback


def resolve_event_project(event: dict[str, Any]) -> str:
    """
    Project id used when rolling up an existing event.

    Pre-tag xAI rows from this repo's grok.py are counted as ``memes``.
    Anything else without a tag stays ``unallocated``. Historical jsonl is
    not rewritten.
    """
    if not event_missing_project(event):
        return normalize_project_id(str(event.get("project")), missing=UNALLOCATED_PROJECT)
    provider = str(event.get("provider") or "").strip().lower()
    if provider == "xai":
        return DEFAULT_PROJECT
    return UNALLOCATED_PROJECT


def assumed_legacy_xai_memes(event: dict[str, Any]) -> bool:
    return event_missing_project(event) and str(event.get("provider") or "").lower() == "xai"


def monthly_equivalent(amount_usd: Any, cadence: Optional[str]) -> float:
    amount = float(amount_usd or 0)
    cadence = (cadence or "monthly").lower()
    if cadence == "yearly":
        return amount / 12.0
    return amount


def subscription_shares(item: dict[str, Any]) -> dict[str, float]:
    """
    Normalize ``project`` or ``projects`` to shares that sum to 1.0.

    ``projects`` may be ``{"memes": 0.5, "shared": 0.5}`` or
    ``[{"id": "memes", "share": 0.5}, ...]``. Missing tags → unallocated.
    Shares that do not sum to 1.0 put the leftover in unallocated (or scale
    down if they exceed 1).
    """
    raw_projects = item.get("projects")
    shares: dict[str, float] = {}
    if isinstance(raw_projects, dict) and raw_projects:
        for key, value in raw_projects.items():
            pid = normalize_project_id(str(key), missing=UNALLOCATED_PROJECT)
            shares[pid] = shares.get(pid, 0.0) + float(value or 0)
    elif isinstance(raw_projects, list) and raw_projects:
        for entry in raw_projects:
            if not isinstance(entry, dict):
                continue
            pid = normalize_project_id(
                str(entry.get("id") or entry.get("project") or ""),
                missing=UNALLOCATED_PROJECT,
            )
            share = entry.get("share", entry.get("weight", 0))
            shares[pid] = shares.get(pid, 0.0) + float(share or 0)
    elif item.get("project"):
        pid = normalize_project_id(str(item.get("project")), missing=UNALLOCATED_PROJECT)
        shares[pid] = 1.0

    if not shares:
        return {UNALLOCATED_PROJECT: 1.0}

    total = sum(shares.values())
    if total <= 0:
        return {UNALLOCATED_PROJECT: 1.0}
    if abs(total - 1.0) <= 0.001:
        return shares
    if total > 1.0:
        return {pid: value / total for pid, value in shares.items()}
    leftover = round(1.0 - total, 6)
    shares[UNALLOCATED_PROJECT] = shares.get(UNALLOCATED_PROJECT, 0.0) + leftover
    return shares


def allocate_amount(amount: float, shares: dict[str, float]) -> dict[str, float]:
    """Split ``amount`` across shares; last bucket absorbs rounding pennies."""
    amount = round(float(amount or 0), 2)
    items = [(pid, float(share)) for pid, share in shares.items() if float(share) > 0]
    if not items:
        return {UNALLOCATED_PROJECT: amount}
    allocated: dict[str, float] = {}
    remaining = amount
    for index, (pid, share) in enumerate(items):
        if index == len(items) - 1:
            allocated[pid] = remaining
        else:
            part = round(amount * share, 2)
            allocated[pid] = part
            remaining = round(remaining - part, 2)
    return allocated


def format_project_label(item: dict[str, Any]) -> str:
    shares = subscription_shares(item)
    parts: list[str] = []
    for pid, share in shares.items():
        name = project_meta(pid)["name"]
        if abs(share - 1.0) < 0.001:
            parts.append(name)
        else:
            parts.append(f"{name} {int(round(share * 100))}%")
    return " · ".join(parts)


def _empty_row(project_id: str) -> dict[str, Any]:
    meta = project_meta(project_id)
    return {
        "id": project_id,
        "name": meta["name"],
        "description": meta["description"],
        "color": meta["color"],
        "fixed": 0.0,
        "tokens": 0.0,
        "other_variable": 0.0,
        "variable": 0.0,
        "total": 0.0,
        "share_pct": 0.0,
        "token_calls": 0,
        "token_tokens": 0,
        "always_visible": project_id == UNALLOCATED_PROJECT,
    }


def _ensure_row(rows: dict[str, dict[str, Any]], project_id: str) -> dict[str, Any]:
    if project_id not in rows:
        rows[project_id] = _empty_row(project_id)
    return rows[project_id]


def build_project_rollup(
    subscriptions: list[dict[str, Any]],
    *,
    aws_live: Optional[dict[str, Any]] = None,
    xai_usage: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Monthly fixed + variable + token spend grouped by project.

    ``xai-tokens`` ledger rows are ignored (amount is $0; tokens come from
    events). Live AWS replaces the aws ledger amount when present.
    Cancelled items are not included.
    """
    order = project_order()
    rows: dict[str, dict[str, Any]] = {
        pid: _empty_row(pid) for pid in order
    }

    aws_ok = bool(aws_live) and not (aws_live or {}).get("error")
    xai_ok = bool(xai_usage) and not (xai_usage or {}).get("error")

    for item in subscriptions:
        if item.get("status") not in ("active", "cancelling"):
            continue
        item_id = item.get("id")
        if item_id == "xai-tokens":
            continue

        if aws_ok and item_id == "aws":
            amount = float(aws_live.get("amount") or 0)
        else:
            amount = monthly_equivalent(item.get("amount_usd"), item.get("cadence"))

        category = item.get("category") or "fixed"
        for pid, part in allocate_amount(amount, subscription_shares(item)).items():
            row = _ensure_row(rows, pid)
            if category == "variable":
                row["other_variable"] = round(row["other_variable"] + part, 2)
            else:
                row["fixed"] = round(row["fixed"] + part, 2)

    if xai_ok:
        by_project = xai_usage.get("by_project") or {}
        if by_project:
            for pid, bucket in by_project.items():
                row = _ensure_row(rows, str(pid))
                cost = float((bucket or {}).get("total_cost_usd") or 0)
                row["tokens"] = round(row["tokens"] + cost, 2)
                row["token_calls"] += int((bucket or {}).get("call_count") or 0)
                row["token_tokens"] += int((bucket or {}).get("total_tokens") or 0)
        else:
            # Usage total without per-event tags — still show the dollars.
            leftover = float(xai_usage.get("amount") or 0)
            if leftover:
                row = _ensure_row(rows, DEFAULT_PROJECT)
                row["tokens"] = round(row["tokens"] + leftover, 2)

    grand = 0.0
    for row in rows.values():
        row["variable"] = round(row["tokens"] + row["other_variable"], 2)
        row["total"] = round(row["fixed"] + row["variable"], 2)
        grand += row["total"]
    grand = round(grand, 2)
    for row in rows.values():
        row["share_pct"] = round((row["total"] / grand) * 100, 1) if grand else 0.0

    extras = [pid for pid in rows if pid not in order]
    ordered = [rows[pid] for pid in order] + [rows[pid] for pid in extras]

    slices = [row for row in ordered if row["total"] > 0]
    pie_parts: list[str] = []
    cursor = 0.0
    if slices and grand > 0:
        for row in slices:
            start = cursor
            cursor += (row["total"] / grand) * 100.0
            pie_parts.append(f"{row['color']} {start:.2f}% {cursor:.2f}%")

    return {
        "rows": ordered,
        "total": grand,
        "pie_gradient": ", ".join(pie_parts) if pie_parts else "",
        "has_unallocated": any(
            row["id"] == UNALLOCATED_PROJECT for row in ordered
        ),
    }
