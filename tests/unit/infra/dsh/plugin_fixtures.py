"""On-disk DSH plugin fixtures for S2 discovery tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_PATCH = "- insert:\n    - id: fixture\n      name: fixture-plugin\n"


def write_package(
    package_dir: Path,
    name: str,
    *,
    version: str = "1.0.0",
    capabilities: tuple[str, ...] | None = ("tool",),
    permissions: tuple[str, ...] | None = None,
) -> Path:
    """Write a minimal but valid DSH package at *package_dir*."""
    package_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "name": name,
        "version": version,
        "main": "index.js",
        "dsh": {"bundle": {"patch": "./cordis.patch.yml"}},
    }
    if capabilities is not None:
        manifest["capabilities"] = list(capabilities)
    if permissions is not None:
        manifest["permissions"] = list(permissions)
    (package_dir / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    (package_dir / "cordis.patch.yml").write_text(_PATCH, encoding="utf-8")
    (package_dir / "index.js").write_text("export default {};\n", encoding="utf-8")
    return package_dir


def write_market_plugin(
    dest_root: Path,
    name: str,
    *,
    version: str = "1.0.0",
    slot: str | None = None,
    **package_kwargs: Any,
) -> Path:
    """Write ``<dest_root>/dsh/<name>/index.json`` plus one installed slot."""
    plugin_root = dest_root / "dsh" / name
    package_dir = write_package(plugin_root / version, name, version=version, **package_kwargs)
    (plugin_root / "index.json").write_text(
        json.dumps({"plugin_id": f"dsh:{name}", "current": {"slot": slot or version}}),
        encoding="utf-8",
    )
    return package_dir


__all__ = ["write_market_plugin", "write_package"]
