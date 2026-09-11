"""Register src/web as namespace packages so tests avoid heavy package __init__ imports."""

from __future__ import annotations

import sys
import types
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _ensure_pkg(name: str, path: Path) -> None:
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    module.__package__ = name
    sys.modules[name] = module


_ensure_pkg("src", _ROOT / "src")
_ensure_pkg("src.core", _ROOT / "src" / "core")
_ensure_pkg("src.config", _ROOT / "src" / "config")
_ensure_pkg("web", _ROOT / "web")
_ensure_pkg("web.blueprints", _ROOT / "web" / "blueprints")
