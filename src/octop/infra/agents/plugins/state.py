"""Control-plane state: shared plugin store, revision, tool cache."""

from __future__ import annotations

import json
import logging
import shutil
import threading
from pathlib import Path
from typing import Any

from octop.infra.agents.plugins.constants import (
    PLUGINS_ENABLED,
    PLUGINS_REVISION,
)
from octop.infra.agents.plugins.global_flags import (
    _read_global_plugins,
    _write_global_plugin_enabled,
)
from octop.infra.agents.plugins.manager_base import PluginManagerBase
from octop.infra.agents.plugins.metadata import (
    _read_tree,
)
from octop.infra.db.repos.control_files import ControlFileRepo
from octop.infra.db.repos.settings import SettingsRepo

logger = logging.getLogger(__name__)


class PluginStateMixin(PluginManagerBase):
    def __init__(self, *, plugins_dir: Path, config_path: Path) -> None:
        self._plugins_dir = plugins_dir
        self._config_path = config_path
        self._control_files: ControlFileRepo | None = None
        self._plugin_settings: SettingsRepo | None = None
        self._plugins_dir.mkdir(parents=True, exist_ok=True)
        # Last-known tool metadata so Admin / Experts can still list tools after
        # a global disable unloads the plugin from the process registry.
        self._tool_catalog: dict[str, list[dict[str, Any]]] = {}
        self._skill_catalog: dict[str, set[str]] = {}
        # Aggregated DSH index cache: rebuilding it re-downloads every source.
        self._dsh_market_cache: dict[str, Any] | None = None
        self._dsh_market_cache_key: tuple[tuple[str, ...], str] | None = None
        self._dsh_market_cache_at = 0.0
        self._dsh_market_lock = threading.Lock()
        self._dsh_source_health: dict[str, dict[str, Any]] = {}
        self._dsh_sources_checked_at: str | None = None
        # Install progress per plugin, polled by the DSH page while a load runs.
        self._dsh_progress: dict[str, dict[str, Any]] = {}
        self._dsh_progress_lock = threading.Lock()
        self._dsh_refresh_lock = threading.Lock()
        self._dsh_refresh_inflight: set[str] = set()

    @property
    def plugins_dir(self) -> Path:
        return self._plugins_dir

    def global_enabled_map(self) -> dict[str, bool]:
        settings = self._plugin_settings
        if settings is not None:
            raw = settings.get(PLUGINS_ENABLED)
            if raw:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    data = None
                if isinstance(data, dict):
                    return {str(key): bool(value) for key, value in data.items()}
            return {}
        return _read_global_plugins(self._config_path)

    def attach_control_plane(self, files: ControlFileRepo, settings: SettingsRepo) -> None:
        """Use the shared file table as the plugin source of truth."""
        self._control_files = files
        self._plugin_settings = settings
        self._adopt_local_plugins()
        self._ensure_plugin_cache()

    def _adopt_local_plugins(self) -> None:
        """Copy this machine's plugin trees once, before the revision marker exists."""
        files = self._control_files
        settings = self._plugin_settings
        if files is None or settings is None:
            return
        if settings.get(PLUGINS_REVISION) is not None:
            return
        for child in self._plugins_dir.iterdir():
            if not child.is_dir() or child.name.startswith(".") or child.is_symlink():
                continue
            if not (child / "plugin.yaml").is_file():
                continue
            if files.has_owner(ControlFileRepo.PLUGIN, child.name):
                continue
            payloads = _read_tree(child)
            if payloads:
                files.replace_tree(ControlFileRepo.PLUGIN, child.name, payloads)
        if settings.get(PLUGINS_ENABLED) is None:
            flags = _read_global_plugins(self._config_path)
            settings.set(PLUGINS_ENABLED, json.dumps(flags, sort_keys=True))
        owners = files.owners(ControlFileRepo.PLUGIN)
        settings.set(PLUGINS_REVISION, "1" if owners else "0")

    def _set_enabled_flag(self, plugin_id: str, enabled: bool) -> None:
        settings = self._plugin_settings
        if settings is None:
            _write_global_plugin_enabled(self._config_path, plugin_id, enabled)
            return
        current = self.global_enabled_map()
        current[plugin_id] = bool(enabled)
        settings.set(PLUGINS_ENABLED, json.dumps(current, sort_keys=True))

    def _revision_marker(self) -> Path:
        return self._plugins_dir / ".control-revision"

    def _ensure_plugin_cache(self) -> None:
        files = self._control_files
        settings = self._plugin_settings
        if files is None or settings is None:
            return
        revision = settings.get(PLUGINS_REVISION) or "0"
        marker = self._revision_marker()
        try:
            current = marker.read_text(encoding="utf-8") if marker.is_file() else None
        except OSError:
            current = None
        if current == revision:
            return
        self._plugins_dir.mkdir(parents=True, exist_ok=True)
        owners = set(files.owners(ControlFileRepo.PLUGIN))
        if not owners and revision == "0":
            marker.write_text(revision, encoding="utf-8")
            return
        for child in list(self._plugins_dir.iterdir()):
            if child.name == ".control-revision" or not child.is_dir():
                continue
            if child.name not in owners:
                shutil.rmtree(child, ignore_errors=True)
        for owner in owners:
            dest = self._plugins_dir / owner
            if dest.exists():
                shutil.rmtree(dest)
            dest.mkdir(parents=True)
            for relative, content in files.list_files(ControlFileRepo.PLUGIN, owner):
                target = dest / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        marker.write_text(revision, encoding="utf-8")

    def _bump_plugin_revision(self) -> None:
        settings = self._plugin_settings
        if settings is None:
            return
        raw = settings.get(PLUGINS_REVISION) or "0"
        try:
            revision = str(int(raw) + 1)
        except ValueError:
            revision = "1"
        settings.set(PLUGINS_REVISION, revision)
        try:
            self._revision_marker().write_text(revision, encoding="utf-8")
        except OSError:
            logger.warning("failed to record plugin cache revision")

    def _persist_plugin_tree(self, plugin_id: str) -> None:
        files = self._control_files
        if files is None:
            return
        files.replace_tree(
            ControlFileRepo.PLUGIN,
            plugin_id,
            _read_tree(self._plugins_dir / plugin_id),
        )
        self._bump_plugin_revision()
