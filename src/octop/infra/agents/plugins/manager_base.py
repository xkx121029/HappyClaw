"""Attribute contract shared by the plugin manager mixins."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from octop_harness.plugins import LoadedPlugin

    from octop.infra.db.repos.control_files import ControlFileRepo
    from octop.infra.db.repos.settings import SettingsRepo


class PluginManagerBase:
    """Declares the state and cross-mixin calls :class:`PluginManager` owns."""

    _plugins_dir: Path
    _config_path: Path
    _control_files: ControlFileRepo | None
    _plugin_settings: SettingsRepo | None
    _tool_catalog: dict[str, list[dict[str, Any]]]
    _skill_catalog: dict[str, set[str]]
    _dsh_market_cache: dict[str, Any] | None
    _dsh_market_cache_key: tuple[tuple[str, ...], str] | None
    _dsh_market_cache_at: float
    _dsh_market_lock: Any
    _dsh_source_health: dict[str, dict[str, Any]]
    _dsh_sources_checked_at: str | None
    _dsh_progress: dict[str, dict[str, Any]]
    _dsh_progress_lock: Any
    _dsh_refresh_lock: Any
    _dsh_refresh_inflight: set[str]

    # Cross-mixin calls: the concrete implementation lives on a sibling mixin
    # of the composed PluginManager, so the contract is declared here.
    def install_path(
        self,
        source: Path,
        *,
        force: bool = False,
        expect_id: str | None = None,
        expect_version: str | None = None,
    ) -> LoadedPlugin:
        raise NotImplementedError

    def install_url(
        self,
        url: str,
        *,
        force: bool = False,
        expect_id: str | None = None,
        expect_version: str | None = None,
    ) -> LoadedPlugin:
        raise NotImplementedError

    def global_enabled_map(self) -> dict[str, bool]:
        raise NotImplementedError

    def _set_enabled_flag(self, plugin_id: str, enabled: bool) -> None: ...

    def _ensure_plugin_cache(self) -> None: ...

    def _persist_plugin_tree(self, plugin_id: str) -> None: ...

    def dsh_source_urls(self) -> list[str]:
        raise NotImplementedError

    def dsh_market_root(self) -> Path:
        raise NotImplementedError

    def _dsh_snapshot(
        self, urls: list[str], *, language: str, refresh: bool
    ) -> tuple[dict[str, Any], bool]:
        raise NotImplementedError

    def list_dsh_installed(self) -> dict[str, Any]:
        raise NotImplementedError

    def _dsh_runtime_status(self, plugin_id: str, *, probe: bool = False) -> dict[str, Any]:
        raise NotImplementedError
