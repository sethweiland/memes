"""
Secrets adapter for the life-ops shell.

Tenant YAML names the backend (`secrets.backend`) and never stores values.
Only the `env` backend is implemented in this release. `aws` and `bitwarden`
are reserved names — see docs/life-ops.md.
"""

from __future__ import annotations

import os
from typing import Optional, Protocol

from src.core.tenant import load_tenant


class SecretsBackend(Protocol):
    def get(self, name: str, default: str = "") -> str:
        """Return a secret from the configured backend. Never log the value."""


class EnvSecretsBackend:
    """Read process environment (Fly secrets, `.env`, exported vars)."""

    def get(self, name: str, default: str = "") -> str:
        value = os.environ.get(name)
        if value is None or not str(value).strip():
            return default
        return str(value)


class UnimplementedSecretsBackend:
    def __init__(self, backend: str):
        self.backend = backend

    def get(self, name: str, default: str = "") -> str:
        raise NotImplementedError(
            f"secrets.backend={self.backend!r} is documented but not implemented. "
            "Use secrets.backend: env and put credentials in the process environment. "
            "See docs/life-ops.md."
        )


def get_secrets_backend(backend: Optional[str] = None) -> SecretsBackend:
    name = (backend or "").strip().lower()
    if not name:
        try:
            name = load_tenant().secrets_backend
        except Exception:
            name = "env"
    if name == "env":
        return EnvSecretsBackend()
    if name in {"aws", "bitwarden"}:
        return UnimplementedSecretsBackend(name)
    raise ValueError(f"unknown secrets.backend: {name!r}")
