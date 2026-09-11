"""
Tenant config for the life-ops shell.

Load path: TENANT_CONFIG if set, else config/tenant.yaml.
Relative paths resolve from cwd, then the repo root.

No secrets belong in the YAML. credentials stay in a SecretsBackend.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TENANT_PATH = _REPO_ROOT / "config" / "tenant.yaml"

PROJECT_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

LANES = ("idea", "active", "blocked", "waiting_on_you", "parked")
LANE_ALIASES = {"waiting_on_seth": "waiting_on_you"}
LANE_LABELS = {
    "idea": "Idea",
    "active": "Active",
    "blocked": "Blocked",
    "waiting_on_you": "Waiting on you",
    "parked": "Parked",
}

MODULE_NAMES = ("projects", "spend", "x", "grok_bot", "memes", "calendar")
SECRET_BACKENDS = ("env", "aws", "bitwarden")
SPEND_ONLY_PROJECT_IDS = ("shared", "unallocated")

_FALLBACK_COLORS = {
    "memes": "#2563eb",
    "sethweiland-com": "#059669",
    "waiver-wire": "#d97706",
    "x": "#111827",
    "shared": "#7c3aed",
    "unallocated": "#6b7280",
}


@dataclass(frozen=True)
class TenantProject:
    id: str
    name: str
    lane: str
    owner_agent: Optional[str] = None
    color: str = "#9ca3af"
    description: str = ""
    links: dict[str, Optional[str]] = field(default_factory=dict)
    summary: Optional[str] = None
    last_done: Optional[str] = None
    next_steps: Optional[str] = None

    def as_card(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "lane": self.lane,
            "owner_agent": self.owner_agent,
            "updated_at": None,
            "links": {
                "repo": (self.links or {}).get("repo"),
                "prod": (self.links or {}).get("prod"),
            },
            "summary": self.summary,
            "last_done": self.last_done,
            "next_steps": self.next_steps,
            "color": self.color,
            "description": self.description,
        }


@dataclass(frozen=True)
class Tenant:
    human_name: str
    timezone: str
    handle: Optional[str]
    site_title: str
    site_domain: str
    modules: dict[str, bool]
    secrets_backend: str
    agents: list[dict[str, str]]
    projects: tuple[TenantProject, ...]
    calendar_enabled: bool
    default_usage_project: str
    source_path: str

    def module_enabled(self, name: str) -> bool:
        return bool(self.modules.get(name))

    def kanban_projects(self) -> tuple[TenantProject, ...]:
        return tuple(p for p in self.projects if p.id not in SPEND_ONLY_PROJECT_IDS)

    def project_ids(self) -> tuple[str, ...]:
        return tuple(p.id for p in self.kanban_projects())

    def project_by_id(self, project_id: str) -> Optional[TenantProject]:
        for project in self.projects:
            if project.id == project_id:
                return project
        return None


_tenant: Optional[Tenant] = None
_tenant_path: Optional[Path] = None


def normalize_lane(value: Optional[str], *, missing: str = "idea") -> str:
    cleaned = (value or "").strip().lower()
    cleaned = LANE_ALIASES.get(cleaned, cleaned)
    if cleaned in LANES:
        return cleaned
    return missing


def normalize_project_id(value: Optional[str], *, missing: str = "") -> str:
    cleaned = "".join(
        ch for ch in (value or "").strip().lower() if ch.isalnum() or ch in "-_"
    )
    if cleaned and PROJECT_ID_RE.fullmatch(cleaned):
        return cleaned
    return missing


def _blank(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _link(value: Any) -> Optional[str]:
    return _blank(value)


def resolve_tenant_path(explicit: Optional[str] = None) -> Path:
    raw = (explicit if explicit is not None else os.environ.get("TENANT_CONFIG", "")).strip()
    if raw:
        path = Path(raw)
        if path.is_absolute():
            return path
        cwd_path = Path.cwd() / path
        if cwd_path.exists():
            return cwd_path
        return _REPO_ROOT / path
    return DEFAULT_TENANT_PATH


def _default_modules() -> dict[str, bool]:
    return {
        "projects": True,
        "spend": True,
        "x": False,
        "grok_bot": False,
        "memes": False,
        "calendar": False,
    }


def _parse_modules(raw: Any) -> dict[str, bool]:
    modules = _default_modules()
    if isinstance(raw, dict):
        for name in MODULE_NAMES:
            if name in raw:
                modules[name] = bool(raw[name])
    calendar = modules.get("calendar", False)
    return modules | {"calendar": calendar}


def _parse_project(raw: Any) -> Optional[TenantProject]:
    if not isinstance(raw, dict):
        return None
    project_id = normalize_project_id(raw.get("id"))
    if not project_id or project_id in SPEND_ONLY_PROJECT_IDS:
        return None
    links_raw = raw.get("links") if isinstance(raw.get("links"), dict) else {}
    color = _blank(raw.get("color")) or _FALLBACK_COLORS.get(project_id, "#9ca3af")
    name = _blank(raw.get("name")) or project_id
    return TenantProject(
        id=project_id,
        name=name,
        lane=normalize_lane(raw.get("lane")),
        owner_agent=_blank(raw.get("owner_agent")),
        color=color,
        description=_blank(raw.get("description")) or "",
        links={"repo": _link(links_raw.get("repo")), "prod": _link(links_raw.get("prod"))},
        summary=_blank(raw.get("summary")),
        last_done=_blank(raw.get("last_done")),
        next_steps=_blank(raw.get("next_steps")),
    )


def _parse_agents(raw: Any) -> list[dict[str, str]]:
    agents: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return agents
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        agent_id = normalize_project_id(entry.get("id"))
        if not agent_id or agent_id in seen:
            continue
        seen.add(agent_id)
        agents.append({"id": agent_id, "name": _blank(entry.get("name")) or agent_id})
    return agents


def normalize_tenant(raw: Any, *, source_path: str) -> Tenant:
    data = raw if isinstance(raw, dict) else {}
    human = data.get("human") if isinstance(data.get("human"), dict) else {}
    site = data.get("site") if isinstance(data.get("site"), dict) else {}
    secrets = data.get("secrets") if isinstance(data.get("secrets"), dict) else {}
    calendar = data.get("calendar") if isinstance(data.get("calendar"), dict) else {}
    defaults = data.get("defaults") if isinstance(data.get("defaults"), dict) else {}

    backend = str(secrets.get("backend") or "env").strip().lower()
    if backend not in SECRET_BACKENDS:
        backend = "env"

    modules = _parse_modules(data.get("modules"))
    calendar_enabled = bool(calendar.get("enabled", modules.get("calendar", False)))
    modules["calendar"] = calendar_enabled

    projects: list[TenantProject] = []
    seen: set[str] = set()
    for entry in data.get("projects") or []:
        project = _parse_project(entry)
        if not project or project.id in seen:
            continue
        seen.add(project.id)
        projects.append(project)

    default_usage = normalize_project_id(defaults.get("usage_project"))
    if not default_usage:
        default_usage = projects[0].id if projects else "unallocated"

    return Tenant(
        human_name=_blank(human.get("name")) or "You",
        timezone=_blank(human.get("timezone")) or "America/New_York",
        handle=_blank(human.get("handle")),
        site_title=_blank(site.get("title")) or "Ops",
        site_domain=_blank(site.get("domain")) or "localhost",
        modules=modules,
        secrets_backend=backend,
        agents=_parse_agents(data.get("agents")),
        projects=tuple(projects),
        calendar_enabled=calendar_enabled,
        default_usage_project=default_usage,
        source_path=source_path,
    )


def load_tenant_from_path(path: Path) -> Tenant:
    if not path.exists():
        raise FileNotFoundError(f"tenant config not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return normalize_tenant(raw, source_path=str(path))


def load_tenant(*, path: Optional[Path | str] = None, reload: bool = False) -> Tenant:
    """Process-wide tenant. Tests should call reset_tenant()."""
    global _tenant, _tenant_path
    resolved = Path(path) if path is not None else resolve_tenant_path()
    if path is not None and not resolved.is_absolute():
        resolved = resolve_tenant_path(str(path))
    if reload or _tenant is None or _tenant_path != resolved:
        _tenant = load_tenant_from_path(resolved)
        _tenant_path = resolved
    return _tenant


def reset_tenant(tenant: Optional[Tenant] = None) -> None:
    """Clear or replace the process-wide tenant (tests)."""
    global _tenant, _tenant_path
    _tenant = tenant
    _tenant_path = Path(tenant.source_path) if tenant is not None else None


def module_enabled(name: str) -> bool:
    try:
        return load_tenant().module_enabled(name)
    except Exception:
        return name in {"projects", "spend"}
