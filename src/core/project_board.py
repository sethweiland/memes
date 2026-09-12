"""
Private project board.

Canonical object: ``ops/projects/board.json`` (never under ``public/``).
Local fallback: ``data/projects/board.json``.

If no board file exists, seed from tenant.yaml projects and write through
once. ``shared`` / ``unallocated`` are Spend-only and never become cards.

The UI is a sorted list. ``lane`` is still the status enum (idea / active /
blocked / waiting_on_you / parked) — not a sixth primitive.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.core.s3_store import BucketLayout, S3Store, get_s3_store
from src.core.tenant import (
    LANES,
    LANE_LABELS,
    SPEND_ONLY_PROJECT_IDS,
    Tenant,
    load_tenant,
    normalize_lane,
    normalize_project_id,
)


logger = logging.getLogger(__name__)

LOCAL_PATH = Path("data/projects/board.json")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _blank(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_project_card(raw: Any) -> Optional[dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    project_id = normalize_project_id(raw.get("id"))
    if not project_id or project_id in SPEND_ONLY_PROJECT_IDS:
        return None

    links_raw = raw.get("links") if isinstance(raw.get("links"), dict) else {}
    name = _blank(raw.get("name")) or project_id
    updated_at = _blank(raw.get("updated_at"))

    return {
        "id": project_id,
        "name": name,
        "lane": normalize_lane(raw.get("lane")),
        "owner_agent": _blank(raw.get("owner_agent")),
        "updated_at": updated_at,
        "links": {
            "repo": _blank(links_raw.get("repo")),
            "prod": _blank(links_raw.get("prod")),
        },
        "summary": _blank(raw.get("summary")),
        "last_done": _blank(raw.get("last_done")),
        "next_steps": _blank(raw.get("next_steps")),
    }


def normalize_board(data: Any) -> Optional[dict[str, Any]]:
    """
    Canonical shape is ``{updated_at, projects}``.

    On READ only: a bare JSON array is treated as ``projects``.
    Writes stay an object — never persist a list.
    """
    if isinstance(data, list):
        projects_raw = data
        updated_at = None
    elif isinstance(data, dict):
        if "projects" not in data:
            return None
        projects_raw = data.get("projects")
        updated_at = data.get("updated_at")
    else:
        return None

    if not isinstance(projects_raw, list):
        return None

    projects: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in projects_raw:
        card = normalize_project_card(raw)
        if not card or card["id"] in seen:
            continue
        seen.add(card["id"])
        projects.append(card)

    return {
        "updated_at": _blank(updated_at),
        "projects": projects,
    }


def seed_projects_from_tenant(tenant: Optional[Tenant] = None) -> list[dict[str, Any]]:
    tenant = tenant or load_tenant()
    cards = []
    for project in tenant.kanban_projects():
        card = normalize_project_card(project.as_card())
        if card:
            cards.append(card)
    return cards


def merge_missing_from_tenant(
    board: dict[str, Any],
    tenant: Optional[Tenant] = None,
) -> tuple[dict[str, Any], bool]:
    """Add tenant projects that are not on the board. Do not overwrite lanes."""
    existing = {card["id"] for card in board.get("projects") or []}
    added = False
    projects = list(board.get("projects") or [])
    for card in seed_projects_from_tenant(tenant):
        if card["id"] in existing:
            continue
        projects.append(card)
        existing.add(card["id"])
        added = True
    if not added:
        return board, False
    merged = {"updated_at": utc_now(), "projects": projects}
    return merged, True


# Default list order: attention first, then name. Parked last.
LANE_SORT_ORDER = ("waiting_on_you", "blocked", "active", "idea", "parked")
LANE_SORT_INDEX = {lane: index for index, lane in enumerate(LANE_SORT_ORDER)}


def group_by_lane(projects: list[dict[str, Any]]) -> list[tuple[str, str, list[dict[str, Any]]]]:
    grouped = []
    for lane in LANES:
        cards = [p for p in projects if p.get("lane") == lane]
        grouped.append((lane, LANE_LABELS[lane], cards))
    return grouped


def sort_projects(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """waiting_on_you, blocked, active, idea, parked — then name."""

    def key(card: dict[str, Any]) -> tuple[int, str]:
        lane = str(card.get("lane") or "")
        rank = LANE_SORT_INDEX.get(lane, len(LANE_SORT_ORDER))
        name = str(card.get("name") or card.get("id") or "").casefold()
        return (rank, name)

    return sorted(projects, key=key)


def project_owners(projects: list[dict[str, Any]]) -> list[str]:
    owners: list[str] = []
    seen: set[str] = set()
    for card in projects:
        owner = (card.get("owner_agent") or "").strip()
        if not owner or owner in seen:
            continue
        seen.add(owner)
        owners.append(owner)
    return sorted(owners, key=str.casefold)


def clip_one_line(value: Any, limit: int = 120) -> Optional[str]:
    """Collapse whitespace and truncate. Used for list secondary lines."""
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    if not cleaned:
        return None
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(1, limit - 1)].rstrip() + "…"


def line_is_clipped(value: Any, short: Optional[str]) -> bool:
    """True when the preview is shorter than the collapsed source text."""
    if not short or value is None:
        return False
    cleaned = " ".join(str(value).split())
    return bool(cleaned) and short != cleaned


def present_project(card: dict[str, Any]) -> dict[str, Any]:
    """View model: stored fields plus clipped secondary lines. Not persisted."""
    shown = dict(card)
    shown["summary_short"] = clip_one_line(card.get("summary"), 140)
    shown["last_done_short"] = clip_one_line(card.get("last_done"), 120)
    shown["next_steps_short"] = clip_one_line(card.get("next_steps"), 120)
    shown["summary_clipped"] = line_is_clipped(card.get("summary"), shown["summary_short"])
    shown["last_done_clipped"] = line_is_clipped(card.get("last_done"), shown["last_done_short"])
    shown["next_steps_clipped"] = line_is_clipped(
        card.get("next_steps"), shown["next_steps_short"]
    )
    return shown


def waiting_on_you(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [p for p in projects if p.get("lane") == "waiting_on_you"]


class ProjectBoard:
    """
    S3-backed project board.

    Reads ``ops/projects/board.json`` first, then local
    ``data/projects/board.json``. Writes go to both when the bucket is set.
    """

    def __init__(
        self,
        store: Optional[S3Store] = None,
        local_path: Optional[Path] = None,
        tenant: Optional[Tenant] = None,
    ):
        self.store = store or S3Store()
        self.local_path = local_path or LOCAL_PATH
        self.tenant = tenant
        self.prefix = BucketLayout.PROJECTS_PREFIX

    def _tenant(self) -> Tenant:
        return self.tenant or load_tenant()

    def s3_key(self) -> str:
        key = BucketLayout.projects_board_key()
        BucketLayout.require_ops_key(key)
        if not key.startswith(self.prefix):
            raise ValueError(f"Projects key must stay under {self.prefix}: {key}")
        if key.startswith(BucketLayout.PUBLIC_PREFIX):
            raise ValueError("Projects data must never be written under public/")
        return key

    def save(self, data: dict) -> bool:
        if not isinstance(data, dict):
            raise TypeError(
                "Project board writes must be {updated_at, projects}, not a bare array"
            )
        normalized = normalize_board(data)
        if normalized is None:
            raise ValueError("Project board must contain a projects list")
        if not normalized.get("updated_at"):
            normalized["updated_at"] = utc_now()
        json_bytes = json.dumps(normalized, indent=2, ensure_ascii=False).encode("utf-8")

        self.local_path.parent.mkdir(parents=True, exist_ok=True)
        self.local_path.write_bytes(json_bytes)
        logger.info("Saved project board to local: %s", self.local_path)

        if not self.store.configured:
            logger.warning("S3 bucket not configured, project board saved locally only")
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
                "Saved project board to S3: s3://%s/%s",
                self.store.bucket,
                s3_key,
            )
            return True
        except Exception as e:
            logger.warning("Failed to save project board to S3: %s", e)
            return False

    def _load_local(self) -> Optional[dict]:
        if not self.local_path.exists():
            return None
        try:
            data = json.loads(self.local_path.read_text(encoding="utf-8"))
            normalized = normalize_board(data)
            if normalized is not None:
                logger.info("Loaded project board from local: %s", self.local_path)
                return normalized
        except Exception as e:
            logger.error("Failed to load local project board: %s", e)
        return None

    def load(self) -> Optional[dict]:
        if self.store.configured:
            s3_key = self.s3_key()
            try:
                result = self.store.get_json(s3_key)
                if result:
                    data, _etag = result
                    normalized = normalize_board(data)
                    if normalized is not None:
                        logger.info(
                            "Loaded project board from S3: s3://%s/%s",
                            self.store.bucket,
                            s3_key,
                        )
                        return normalized
            except Exception as e:
                logger.warning("Failed to load project board from S3 (%s): %s", s3_key, e)

        return self._load_local()

    def ensure_seeded(self) -> dict:
        """
        Seed from tenant.yaml when no board file exists (write-through once).

        Existing cards keep their lane / last_done / next_steps. New tenant
        project ids are merged in.
        """
        data = self.load()
        tenant = self._tenant()
        if data is None:
            seeded = {
                "updated_at": utc_now(),
                "projects": seed_projects_from_tenant(tenant),
            }
            self.save(seeded)
            return seeded

        merged, changed = merge_missing_from_tenant(data, tenant)
        if changed:
            self.save(merged)
            return merged
        return data

    def move_lane(self, project_id: str, lane: str) -> Optional[dict]:
        project_id = normalize_project_id(project_id)
        lane = normalize_lane(lane, missing="")
        if not project_id or lane not in LANES:
            return None
        data = self.ensure_seeded()
        for card in data.get("projects") or []:
            if card.get("id") != project_id:
                continue
            now = utc_now()
            card["lane"] = lane
            card["updated_at"] = now
            data["updated_at"] = now
            self.save(data)
            return card
        return None

    def update_card(
        self,
        project_id: str,
        *,
        lane: Optional[str] = None,
        summary: Optional[str] = None,
        last_done: Optional[str] = None,
        next_steps: Optional[str] = None,
        owner_agent: Optional[str] = None,
        name: Optional[str] = None,
    ) -> Optional[dict]:
        """Agent contract: patch one card and persist the board."""
        project_id = normalize_project_id(project_id)
        if not project_id:
            return None
        data = self.ensure_seeded()
        for card in data.get("projects") or []:
            if card.get("id") != project_id:
                continue
            if lane is not None:
                resolved = normalize_lane(lane, missing="")
                if resolved not in LANES:
                    return None
                card["lane"] = resolved
            if summary is not None:
                card["summary"] = _blank(summary)
            if last_done is not None:
                card["last_done"] = _blank(last_done)
            if next_steps is not None:
                card["next_steps"] = _blank(next_steps)
            if owner_agent is not None:
                card["owner_agent"] = _blank(owner_agent)
            if name is not None:
                card["name"] = _blank(name) or card["name"]
            now = utc_now()
            card["updated_at"] = now
            data["updated_at"] = now
            self.save(data)
            return card
        return None


_board: Optional[ProjectBoard] = None


def get_project_board() -> ProjectBoard:
    global _board
    if _board is None:
        _board = ProjectBoard(store=get_s3_store())
    return _board


def reset_project_board(board: Optional[ProjectBoard] = None) -> None:
    """Clear or replace the process-wide board (tests)."""
    global _board
    _board = board
