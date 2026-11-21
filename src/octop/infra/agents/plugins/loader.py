"""Loading plugin directories from disk."""

from __future__ import annotations

import hashlib
from pathlib import Path

from octop_harness.plugins import (
    LoadedPlugin,
    load_plugin_dir,
)

from octop.infra.agents.plugins.legacy_imports import ensure_legacy_harness_agent_alias

_CHANNEL_FINGERPRINTS: dict[str, str] = {}


def _channel_fingerprint(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or any(
            part in {"__pycache__", ".git"} for part in path.relative_to(directory).parts
        ):
            continue
        digest.update(str(path.relative_to(directory)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _load_plugin_dir(plugin_dir: Path, *, install_deps: bool) -> LoadedPlugin:
    """Load one plugin, accepting the pre-rename ``harness_agent`` import."""
    ensure_legacy_harness_agent_alias()
    return load_plugin_dir(plugin_dir, install_deps=install_deps)
