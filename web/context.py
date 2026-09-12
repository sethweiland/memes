"""Shared Jinja context for the life-ops shell."""

from __future__ import annotations

from typing import Any


def life_ops_context() -> dict[str, Any]:
    tenant = None
    modules = None
    nav_folders: tuple = ()
    try:
        from src.core.tenant import load_tenant

        tenant = load_tenant()
        modules = tenant.modules
    except Exception:
        return {"tenant": None, "modules": None, "nav_folders": ()}

    try:
        from flask import url_for

        from src.core.tenant import present_nav_folders

        nav_folders = present_nav_folders(tenant, url_for=url_for)
    except Exception:
        from src.core.tenant import present_nav_folders

        nav_folders = present_nav_folders(tenant)
    return {"tenant": tenant, "modules": modules, "nav_folders": nav_folders}


def register_life_ops_context(app) -> None:
    app.context_processor(life_ops_context)
