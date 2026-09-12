"""
Tenant config for the life-ops shell.

Load order (never crash a friend clone):

1. ``TENANT_CONFIG`` if set
2. S3 ``ops/tenant.yaml`` when ``MEME_ASSETS_BUCKET`` is set
3. ``config/tenant.yaml`` if present on disk (gitignored; operator-private)
4. ``config/tenant.example.yaml``

Relative paths resolve from cwd, then the repo root.

No secrets belong in the YAML. Credentials stay in a SecretsBackend.
Folders are navigation config, not a sixth primitive.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import yaml


logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TENANT_PATH = _REPO_ROOT / "config" / "tenant.yaml"
EXAMPLE_TENANT_PATH = _REPO_ROOT / "config" / "tenant.example.yaml"
_S3_TENANT_SENTINEL = Path("__s3__/ops/tenant.yaml")

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
MORE_ACTIVE_SECTIONS = frozenset({"memes", "grok_bot"})
ROUTE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$")

# Project ids that have a dedicated module homepage. Folders themselves
# stay in tenant YAML — this is only "link to the module if it is on."
PROJECT_MODULE_HREFS = {
    "memes": ("memes", "/memes/"),
    "x": ("x", "/x/"),
}

ROUTE_MODULES = {
    "dashboard.index": "memes",
    "generate.start": "memes",
    "gallery.index": "memes",
    "daily_candidates.index": "memes",
    "templates_review.review_page": "memes",
    "video.start": "memes",
    "discovery.dashboard": "memes",
    "grok_bot.index": "grok_bot",
    "x_activity.index": "x",
    "projects.index": "projects",
    "spend.index": "spend",
    "home.index": None,
}

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
class TenantFolderLink:
    """Optional extra bookmark inside a More folder. Not a stored object."""

    label: str
    href: Optional[str] = None
    route: Optional[str] = None
    module: Optional[str] = None
    project_id: Optional[str] = None


@dataclass(frozen=True)
class TenantFolder:
    """Tenant navigation folder. Not a sixth primitive — config only."""

    id: str
    name: str
    project_ids: tuple[str, ...] = ()
    links: tuple[TenantFolderLink, ...] = ()


@dataclass(frozen=True)
class NavChild:
    label: str
    href: str


@dataclass(frozen=True)
class NavItem:
    label: str
    href: str
    id: str = ""
    children: tuple[NavChild, ...] = ()


@dataclass(frozen=True)
class NavFolder:
    id: str
    name: str
    items: tuple[NavItem, ...]


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
    folders: tuple[TenantFolder, ...] = ()

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

    def nav_folders(self, *, url_for: Optional[Callable[..., str]] = None) -> tuple[NavFolder, ...]:
        return present_nav_folders(self, url_for=url_for)


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
    """Resolve a filesystem tenant path (TENANT_CONFIG or an explicit path)."""
    raw = (explicit if explicit is not None else os.environ.get("TENANT_CONFIG", "")).strip()
    if raw:
        path = Path(raw)
        if path.is_absolute():
            return path
        cwd_path = Path.cwd() / path
        if cwd_path.exists():
            return cwd_path
        return _REPO_ROOT / path
    if DEFAULT_TENANT_PATH.exists():
        return DEFAULT_TENANT_PATH
    return EXAMPLE_TENANT_PATH


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


def _safe_href(value: Any) -> Optional[str]:
    text = _blank(value)
    if not text:
        return None
    if text.startswith("/") and not text.startswith("//"):
        return text
    if text.startswith("https://") or text.startswith("http://"):
        return text
    return None


def _parse_folder_link(raw: Any) -> Optional[TenantFolderLink]:
    if not isinstance(raw, dict):
        return None
    label = _blank(raw.get("label"))
    if not label:
        return None
    href = _safe_href(raw.get("href"))
    route = _blank(raw.get("route"))
    if route and not ROUTE_NAME_RE.fullmatch(route):
        route = None
    if not href and not route:
        return None
    module = _blank(raw.get("module"))
    if module and module not in MODULE_NAMES:
        module = None
    project_id = normalize_project_id(raw.get("project_id")) or None
    return TenantFolderLink(
        label=label,
        href=href,
        route=route,
        module=module,
        project_id=project_id,
    )


def _parse_folders(raw: Any) -> tuple[TenantFolder, ...]:
    if not isinstance(raw, list):
        return ()
    folders: list[TenantFolder] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        folder_id = normalize_project_id(entry.get("id"))
        if not folder_id or folder_id in seen:
            continue
        seen.add(folder_id)
        project_ids: list[str] = []
        seen_pids: set[str] = set()
        for pid in entry.get("project_ids") or []:
            cleaned = normalize_project_id(pid)
            if not cleaned or cleaned in seen_pids:
                continue
            seen_pids.add(cleaned)
            project_ids.append(cleaned)
        links: list[TenantFolderLink] = []
        for link_raw in entry.get("links") or []:
            link = _parse_folder_link(link_raw)
            if link:
                links.append(link)
        folders.append(
            TenantFolder(
                id=folder_id,
                name=_blank(entry.get("name")) or folder_id,
                project_ids=tuple(project_ids),
                links=tuple(links),
            )
        )
    return tuple(folders)


def infer_href_module(href: Optional[str]) -> Optional[str]:
    if not href:
        return None
    path = href.split("?", 1)[0]
    if path == "/x" or path.startswith("/x/"):
        return "x"
    if path == "/memes" or path.startswith("/memes/"):
        return "memes"
    if path == "/grok-bot" or path.startswith("/grok-bot/"):
        return "grok_bot"
    if path == "/projects" or path.startswith("/projects/"):
        return "projects"
    if path == "/spend" or path.startswith("/spend/"):
        return "spend"
    return None


def project_nav_href(project_id: str, modules: dict[str, bool]) -> Optional[str]:
    spec = PROJECT_MODULE_HREFS.get(project_id)
    if spec and modules.get(spec[0]):
        return spec[1]
    if modules.get("projects"):
        return "/projects/"
    return None


def more_nav_active(section: Optional[str]) -> bool:
    return (section or "") in MORE_ACTIVE_SECTIONS


def _resolve_folder_href(
    link: TenantFolderLink,
    *,
    url_for: Optional[Callable[..., str]] = None,
) -> Optional[str]:
    if link.route and url_for is not None:
        try:
            return url_for(link.route)
        except Exception:
            pass
    return link.href


def _link_module(link: TenantFolderLink, href: Optional[str]) -> Optional[str]:
    if link.module:
        return link.module
    if link.route and link.route in ROUTE_MODULES:
        return ROUTE_MODULES[link.route]
    return infer_href_module(href)


def present_nav_folders(
    tenant: Tenant,
    *,
    url_for: Optional[Callable[..., str]] = None,
) -> tuple[NavFolder, ...]:
    """
    Folders for the More menu.

    Disabled-module links are omitted so the menu never points at a 404.
    Unknown project ids are skipped. Empty folders are hidden.
    """
    known = {project.id: project for project in tenant.kanban_projects()}
    modules = tenant.modules
    folders: list[NavFolder] = []
    for folder in tenant.folders:
        nested: dict[str, list[NavChild]] = {}
        loose: list[NavItem] = []
        folder_project_ids = set(folder.project_ids)
        for link in folder.links:
            href = _resolve_folder_href(link, url_for=url_for)
            module = _link_module(link, href)
            if not href or (module and not modules.get(module)):
                continue
            if link.project_id and link.project_id in folder_project_ids and link.project_id in known:
                nested.setdefault(link.project_id, []).append(NavChild(label=link.label, href=href))
            else:
                loose.append(NavItem(label=link.label, href=href, id=""))
        items: list[NavItem] = []
        for project_id in folder.project_ids:
            project = known.get(project_id)
            if not project:
                continue
            href = project_nav_href(project_id, modules)
            if not href:
                continue
            items.append(
                NavItem(
                    label=project.name,
                    href=href,
                    id=project.id,
                    children=tuple(nested.get(project_id, ())),
                )
            )
        items.extend(loose)
        if items:
            folders.append(NavFolder(id=folder.id, name=folder.name, items=tuple(items)))
    return tuple(folders)


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
        folders=_parse_folders(data.get("folders")),
    )


def load_tenant_from_path(path: Path) -> Tenant:
    if not path.exists():
        raise FileNotFoundError(f"tenant config not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return normalize_tenant(raw, source_path=str(path))


def load_tenant_from_bytes(body: bytes, *, source_path: str) -> Tenant:
    raw = yaml.safe_load(body.decode("utf-8"))
    return normalize_tenant(raw, source_path=source_path)


def _try_load_s3_tenant(store: Any = None) -> Optional[Tenant]:
    """Load ops/tenant.yaml from S3 when a bucket is configured. Never raises."""
    try:
        from src.core.s3_store import BucketLayout, get_s3_store

        s3 = store if store is not None else get_s3_store()
        if not getattr(s3, "configured", False):
            return None
        key = BucketLayout.tenant_key()
        BucketLayout.require_ops_key(key)
        result = s3.get_object(key)
        if result is None or not result.body:
            return None
        bucket = getattr(s3, "bucket", "") or "bucket"
        return load_tenant_from_bytes(
            result.body,
            source_path=f"s3://{bucket}/{key}",
        )
    except Exception as exc:
        logger.warning("Failed to load tenant from S3; continuing: %s", exc)
        return None


def _load_example_or_empty() -> Tenant:
    if EXAMPLE_TENANT_PATH.exists():
        return load_tenant_from_path(EXAMPLE_TENANT_PATH)
    return normalize_tenant({}, source_path=str(EXAMPLE_TENANT_PATH))


def _resolve_default_tenant(store: Any = None) -> Tenant:
    env_path = os.environ.get("TENANT_CONFIG", "").strip()
    if env_path:
        return load_tenant_from_path(resolve_tenant_path(env_path))
    s3_tenant = _try_load_s3_tenant(store)
    if s3_tenant is not None:
        return s3_tenant
    if DEFAULT_TENANT_PATH.exists():
        return load_tenant_from_path(DEFAULT_TENANT_PATH)
    return _load_example_or_empty()


def load_tenant(
    *,
    path: Optional[Path | str] = None,
    reload: bool = False,
    store: Any = None,
) -> Tenant:
    """Process-wide tenant. Tests should call reset_tenant()."""
    global _tenant, _tenant_path
    if path is not None:
        resolved = Path(path)
        if not resolved.is_absolute():
            resolved = resolve_tenant_path(str(path))
        if reload or _tenant is None or _tenant_path != resolved:
            _tenant = load_tenant_from_path(resolved)
            _tenant_path = resolved
        return _tenant
    if not reload and _tenant is not None:
        return _tenant
    _tenant = _resolve_default_tenant(store)
    if _tenant.source_path.startswith("s3://"):
        _tenant_path = _S3_TENANT_SENTINEL
    else:
        _tenant_path = Path(_tenant.source_path)
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
