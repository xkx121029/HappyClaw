"""Per-plugin enable flags stored in config.json."""

from __future__ import annotations

import json
from pathlib import Path

from octop.infra.errors import corrupt_config_error
from octop.infra.utils.json_file import (
    JsonFileCorruptError,
    read_json_object,
    write_json_atomic,
)


def _read_global_plugins(config_path: Path) -> dict[str, bool]:
    if not config_path.is_file():
        return {}
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    plugins = raw.get("plugins")
    if not isinstance(plugins, dict):
        return {}
    out: dict[str, bool] = {}
    for plugin_id, entry in plugins.items():
        if isinstance(entry, dict):
            out[str(plugin_id)] = bool(entry.get("enabled", True))
        else:
            out[str(plugin_id)] = True
    return out


def _write_global_plugin_enabled(config_path: Path, plugin_id: str, enabled: bool) -> None:
    """Merge ``plugins.<id>.enabled`` into ``config.json`` without dropping other keys.

    A corrupt config.json raises instead of being treated as empty: merging into
    ``{}`` and writing back destroys every other setting, including the
    ``database`` section (issue #730).
    """
    try:
        data = read_json_object(config_path)
    except JsonFileCorruptError as exc:
        raise corrupt_config_error(exc.path, exc.detail) from exc
    if data is None:
        data = {}
    plugins = data.get("plugins")
    if not isinstance(plugins, dict):
        plugins = {}
        data["plugins"] = plugins
    entry = plugins.get(plugin_id)
    if not isinstance(entry, dict):
        entry = {}
    entry["enabled"] = bool(enabled)
    plugins[plugin_id] = entry
    write_json_atomic(config_path, data)
