"""Read the build stamp that packaging embeds next to the dashboard assets.

``scripts/packaging/build_dashboard.py`` writes ``dashboard/version.json``
(git commit, dashboard build time, sha256 of ``index.html``) into the build
output, which ``octop.spec`` collects as data. Health reports it so an installed
bundle can be traced back to the exact frontend that was packaged.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def dashboard_dir() -> Path | None:
    """Directory that holds the built dashboard inside this installation."""
    package = sys.modules.get("octop")
    location = getattr(package, "__file__", None) if package is not None else None
    if not location:
        return None
    return Path(location).parent / "dashboard"


def dashboard_build_info() -> dict[str, Any] | None:
    """Parsed ``version.json`` (``None`` when the bundle has no stamp)."""
    root = dashboard_dir()
    if root is None:
        return None
    stamp = root / "version.json"
    if not stamp.is_file():
        return None
    try:
        payload = json.loads(stamp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None
