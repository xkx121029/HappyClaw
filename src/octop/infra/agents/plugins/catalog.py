"""Bundled and portal market: rows, install, load, enable."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from octop_harness.plugins import (
    LoadedPlugin,
    PluginManifest,
    PluginRegistry,
    discover_plugin_dirs,
    unload_plugin,
)

from octop.infra.agents.plugins.bundled import default_bundled_plugins_root
from octop.infra.agents.plugins.loader import (
    _CHANNEL_FINGERPRINTS,
    _channel_fingerprint,
    _load_plugin_dir,
)
from octop.infra.agents.plugins.manager_base import PluginManagerBase
from octop.infra.agents.plugins.metadata import (
    _MARKET_ASSET_SUFFIXES,
    _read_installed_version,
    _read_plugin_yaml,
    _version_tuple,
    parse_plugin_group,
    parse_plugin_icon,
    parse_plugin_requires,
    parse_plugin_ui_meta,
)
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.market import (
    PortalMarketError,
    get_market_plugin,
    is_market_archive_url,
    list_market_plugins,
    pick_localized,
)
from octop.infra.market.errors import local_network_error

logger = logging.getLogger(__name__)


class PluginCatalogMixin(PluginManagerBase):
    def seed_bundled(self) -> list[str]:
        """Upgrade already-installed bundled plugins when catalog versions are newer."""
        from octop.infra.agents.plugins.bundled import default_bundled_plugins_root
        from octop.infra.agents.plugins.seed import seed_bundled_plugins

        copied = seed_bundled_plugins(
            bundled_root=default_bundled_plugins_root(),
            plugins_dir=self._plugins_dir,
            config_path=self._config_path,
        )
        for plugin_id in copied:
            self._persist_plugin_tree(plugin_id)
        return copied

    def market_root(self) -> Path:
        from octop.infra.agents.plugins.bundled import default_bundled_plugins_root

        return default_bundled_plugins_root()

    def market_plugin_dir(self, plugin_id: str) -> Path | None:
        """Return a catalog plugin directory when it exists under the market root."""
        cleaned = plugin_id.strip()
        if not cleaned or ".." in cleaned or "/" in cleaned or "\\" in cleaned:
            return None
        dest = self.market_root() / cleaned
        if dest.is_dir() and (dest / "plugin.yaml").is_file():
            return dest
        return None

    def list_market(self, language: str = "zh") -> list[dict[str, Any]]:
        """List marketplace plugins from the bundled catalog and the portal.

        Bundled plugins ship with the product, so they stay browsable even when
        the portal is unreachable. ``source`` tells the Dashboard which install
        endpoint to call; the remote shape keeps its old fields.
        """
        bundled = self._bundled_plugin_rows(language)
        try:
            remote = list_market_plugins()
        except PortalMarketError as exc:
            logger.warning("remote plugin market unavailable: %s", exc)
            if bundled:
                return bundled
            network_error = local_network_error(exc)
            if network_error is not None:
                raise network_error from exc
            raise OctopError(
                ErrorCode.PLUGIN_MARKET_FAILED,
                "plugin market failed: upstream request failed",
                details={"reason": "upstream request failed"},
            ) from exc
        return bundled + [self._remote_plugin_row(item, language) for item in remote]

    def _bundled_plugin_rows(self, language: str) -> list[dict[str, Any]]:
        """Describe every in-package catalog plugin, installed or not."""
        root = default_bundled_plugins_root()
        if not root.is_dir():
            return []
        rows: list[dict[str, Any]] = []
        for plugin_dir in sorted(root.iterdir(), key=lambda item: item.name):
            if not plugin_dir.is_dir() or not (plugin_dir / "plugin.yaml").is_file():
                continue
            try:
                manifest = _read_plugin_yaml(plugin_dir)
            except Exception as exc:
                logger.warning("skip bundled plugin %s: %s", plugin_dir.name, exc)
                continue
            plugin_id = str(manifest.get("id") or plugin_dir.name).strip()
            if not plugin_id:
                continue
            version = str(manifest.get("version") or "")
            installed_dir = self.plugin_dir(plugin_id)
            installed_version = (
                None if installed_dir is None else _read_installed_version(installed_dir)
            )
            ui = parse_plugin_ui_meta(plugin_dir)
            icon = manifest.get("icon")
            group = manifest.get("group")
            rows.append(
                {
                    "id": plugin_id,
                    "version": version,
                    "name": pick_localized(manifest.get("name"), language) or plugin_id,
                    "kind": str(manifest.get("kind") or "tool"),
                    "description": pick_localized(manifest.get("description"), language),
                    "icon": icon.strip() if isinstance(icon, str) and icon.strip() else None,
                    "group": (group.strip() if isinstance(group, str) and group.strip() else None),
                    "requires": [],
                    "installed": installed_dir is not None,
                    "installed_version": installed_version,
                    "update_available": (
                        installed_dir is not None
                        and _version_tuple(version) > _version_tuple(installed_version)
                    ),
                    "source": "bundled",
                    "install_kind": "bundled",
                    "ui": ui,
                }
            )
        return rows

    def install_bundled(self, plugin_id: str, *, force: bool = False) -> LoadedPlugin:
        """Install one in-package catalog plugin without touching the network."""
        cleaned = plugin_id.strip()
        if not cleaned or cleaned in {".", ".."} or "/" in cleaned or "\\" in cleaned:
            raise OctopError(ErrorCode.NOT_FOUND, f"bundled plugin {plugin_id!r} not found")
        source = default_bundled_plugins_root() / cleaned
        if not source.is_dir() or not (source / "plugin.yaml").is_file():
            raise OctopError(ErrorCode.NOT_FOUND, f"bundled plugin {plugin_id!r} not found")
        return self.install_path(source, force=force, expect_id=cleaned)

    def _remote_plugin_row(self, item: dict[str, Any], language: str) -> dict[str, Any]:
        plugin_id = str(item.get("id") or "").strip()
        version = str(item.get("version") or "")
        installed_dir = self.plugin_dir(plugin_id) if plugin_id else None
        installed_version = (
            None if installed_dir is None else _read_installed_version(installed_dir)
        )
        icon = item.get("icon")
        group = item.get("group")
        raw_requires = item.get("requires")
        requires = raw_requires if isinstance(raw_requires, list) else []
        return {
            "id": plugin_id,
            "version": version,
            "name": pick_localized(item.get("name"), language) or plugin_id,
            "kind": str(item.get("kind") or "tool"),
            "description": pick_localized(item.get("description"), language),
            "icon": icon.strip() if isinstance(icon, str) and icon.strip() else None,
            "group": group.strip() if isinstance(group, str) and group.strip() else None,
            "requires": [
                str(item_name).strip() for item_name in requires if str(item_name).strip()
            ],
            "installed": installed_dir is not None,
            "installed_version": installed_version,
            "update_available": (
                installed_dir is not None
                and _version_tuple(version) > _version_tuple(installed_version)
            ),
            "source": "portal",
            "install_kind": "archive",
        }

    def install_from_market(
        self,
        plugin_id: str,
        *,
        version: str | None = None,
        force: bool = False,
    ) -> LoadedPlugin:
        """Install one marketplace release from its CDN archive.

        ``version`` selects the catalog release. ``latest`` means the release
        currently listed for that id. A different release already on disk is
        replaced. ``force`` replaces the same release.
        """
        requested = version.strip() if version else None
        if requested == "latest":
            requested = None
        try:
            remote = get_market_plugin(plugin_id)
        except PortalMarketError as exc:
            logger.warning("remote plugin market unavailable: %s", exc)
            network_error = local_network_error(exc)
            if network_error is not None:
                raise network_error from exc
            raise OctopError(
                ErrorCode.PLUGIN_MARKET_FAILED,
                "plugin market failed: upstream request failed",
                details={"reason": "upstream request failed"},
            ) from exc
        if remote is None:
            raise OctopError(
                ErrorCode.NOT_FOUND,
                f"marketplace plugin {plugin_id!r} not found",
            )
        catalog_version = str(remote.get("version") or "")
        if requested and catalog_version != requested:
            raise OctopError(
                ErrorCode.NOT_FOUND,
                f"marketplace plugin {plugin_id!r} version {requested!r} not found",
            )
        url = remote.get("download_url")
        if not isinstance(url, str) or not is_market_archive_url(url):
            raise OctopError(
                ErrorCode.PLUGIN_INSTALL_FAILED,
                f"marketplace plugin {plugin_id!r} has no archive",
            )
        loaded = self.install_url(
            url,
            force=self._replace_market_release(
                plugin_id,
                requested or catalog_version,
                force=force,
            ),
            expect_id=plugin_id,
            expect_version=catalog_version or None,
        )
        self._set_enabled_flag(loaded.manifest.id, True)
        return loaded

    def _replace_market_release(self, plugin_id: str, version: str, *, force: bool) -> bool:
        """Replace disk contents when installing a different catalog release."""
        if force:
            return True
        installed_dir = self.plugin_dir(plugin_id)
        if installed_dir is None or not version:
            return False
        return _read_installed_version(installed_dir) != version

    def resolve_market_ui_file(self, plugin_id: str, rel_path: str) -> Path:
        """Resolve a marketplace catalog asset (icons only)."""
        plugin_dir = self.market_plugin_dir(plugin_id)
        if plugin_dir is None:
            raise OctopError(
                ErrorCode.NOT_FOUND,
                f"marketplace plugin {plugin_id!r} not found",
            )
        cleaned = rel_path.strip().lstrip("/").replace("\\", "/")
        suffix = Path(cleaned).suffix.lower()
        if suffix not in _MARKET_ASSET_SUFFIXES:
            raise OctopError(ErrorCode.NOT_FOUND, "invalid marketplace asset path")
        return self._resolve_plugin_asset(plugin_dir, cleaned)

    def load_installed(self, *, install_deps: bool = True) -> list[LoadedPlugin]:
        self._ensure_plugin_cache()
        enabled = self.global_enabled_map()
        previous = {plugin.manifest.id: plugin for plugin in PluginRegistry().all_loaded()}
        PluginRegistry().clear()
        loaded: list[LoadedPlugin] = []
        for plugin_dir in discover_plugin_dirs(self._plugins_dir):
            try:
                manifest = PluginManifest.load(plugin_dir / "plugin.yaml")
            except Exception as exc:
                logger.error("skip plugin dir %s: %s", plugin_dir, exc)
                continue
            if enabled.get(manifest.id, True) is False:
                continue
            try:
                fingerprint = (
                    _channel_fingerprint(plugin_dir) if str(manifest.kind) == "channel" else ""
                )
                old = previous.get(manifest.id)
                if (
                    str(manifest.kind) == "channel"
                    and old is not None
                    and _CHANNEL_FINGERPRINTS.get(manifest.id) == fingerprint
                ):
                    PluginRegistry().register(old)
                    loaded.append(old)
                else:
                    loaded.append(_load_plugin_dir(plugin_dir, install_deps=install_deps))
                if str(manifest.kind) == "channel":
                    _CHANNEL_FINGERPRINTS[manifest.id] = fingerprint
            except Exception as exc:
                logger.error(
                    "failed to load plugin from %s: %s",
                    plugin_dir,
                    exc,
                    exc_info=True,
                )
        for plugin_id, is_on in enabled.items():
            if not is_on:
                unload_plugin(plugin_id)
        return [p for p in loaded if enabled.get(p.manifest.id, True) is not False]

    def load_missing(self, *, install_deps: bool = False) -> list[LoadedPlugin]:
        """Load any on-disk plugins that are not yet in the process registry.

        Used after CLI ``octop plugin install`` while ``octop run`` is already
        up — unlike ``load_installed``, this does not clear already-loaded
        plugins.
        """
        self._ensure_plugin_cache()
        enabled = self.global_enabled_map()
        newly: list[LoadedPlugin] = []
        for plugin_dir in discover_plugin_dirs(self._plugins_dir):
            try:
                manifest = PluginManifest.load(plugin_dir / "plugin.yaml")
            except Exception as exc:
                logger.error("skip plugin dir %s: %s", plugin_dir, exc)
                continue
            if enabled.get(manifest.id) is False:
                continue
            if PluginRegistry().get(manifest.id) is not None:
                continue
            try:
                newly.append(_load_plugin_dir(plugin_dir, install_deps=install_deps))
                logger.info(
                    "loaded missing plugin %s v%s",
                    manifest.id,
                    manifest.version,
                )
            except Exception as exc:
                logger.error(
                    "failed to load plugin from %s: %s",
                    plugin_dir,
                    exc,
                    exc_info=True,
                )
        return newly

    @staticmethod
    def _channel_registration_error(plugin_id: str) -> str | None:
        from octop.infra.gateway.plugin_channels import registration_errors

        return registration_errors().get(plugin_id)

    def list_installed(self) -> list[dict[str, Any]]:
        self._ensure_plugin_cache()
        out: list[dict[str, Any]] = []
        enabled_map = self.global_enabled_map()
        for plugin_dir in discover_plugin_dirs(self._plugins_dir):
            try:
                manifest = PluginManifest.load(plugin_dir / "plugin.yaml")
            except Exception as exc:
                out.append(
                    {
                        "id": plugin_dir.name,
                        "error": str(exc),
                        "path": str(plugin_dir),
                        "enabled": enabled_map.get(plugin_dir.name, True),
                    },
                )
                continue
            loaded = PluginRegistry().get(manifest.id)
            ui_meta = parse_plugin_ui_meta(plugin_dir)
            if loaded is not None:
                tools_meta = [
                    {
                        "name": t.name,
                        "description": t.description,
                        "config_fields": t.config_fields,
                    }
                    for t in loaded.tools
                ]
                self._tool_catalog[manifest.id] = tools_meta
                if loaded.skills_dir is not None:
                    self._skill_catalog[manifest.id] = {
                        path.name
                        for path in loaded.skills_dir.iterdir()
                        if path.is_dir() and (path / "SKILL.md").is_file()
                    }
            else:
                tools_meta = list(self._tool_catalog.get(manifest.id) or [])
            out.append(
                {
                    "id": manifest.id,
                    "version": manifest.version,
                    "name": manifest.name,
                    "kind": manifest.kind,
                    "description": manifest.description,
                    "icon": parse_plugin_icon(plugin_dir),
                    "group": parse_plugin_group(plugin_dir),
                    "requires": parse_plugin_requires(plugin_dir),
                    "path": str(plugin_dir),
                    "loaded": loaded is not None,
                    "registration_error": self._channel_registration_error(manifest.id),
                    "enabled": enabled_map.get(manifest.id, True),
                    "ui": ui_meta,
                    "tools": tools_meta,
                },
            )
        return out

    def set_enabled(self, plugin_id: str, enabled: bool) -> dict[str, Any]:
        """Toggle global plugin enablement in ``config.json`` and load/unload registry."""
        plugin_dir = self.plugin_dir(plugin_id)
        if plugin_dir is None:
            raise OctopError(ErrorCode.NOT_FOUND, f"plugin {plugin_id!r} not found")
        try:
            PluginManifest.load(plugin_dir / "plugin.yaml")
        except Exception as exc:
            raise OctopError(
                ErrorCode.PLUGIN_INVALID_ARCHIVE,
                f"invalid plugin manifest: {exc}",
            ) from exc

        self._set_enabled_flag(plugin_id, enabled)
        if enabled:
            if PluginRegistry().get(plugin_id) is None:
                try:
                    _load_plugin_dir(plugin_dir, install_deps=False)
                except Exception as exc:
                    raise OctopError(
                        ErrorCode.PLUGIN_INSTALL_FAILED,
                        f"failed to load plugin: {exc}",
                        details={"reason": str(exc)},
                    ) from exc
        else:
            loaded = PluginRegistry().get(plugin_id)
            if loaded is not None:
                self._tool_catalog[plugin_id] = [
                    {
                        "name": t.name,
                        "description": t.description,
                        "config_fields": t.config_fields,
                    }
                    for t in loaded.tools
                ]
                if loaded.skills_dir is not None:
                    self._skill_catalog[plugin_id] = {
                        path.name
                        for path in loaded.skills_dir.iterdir()
                        if path.is_dir() and (path / "SKILL.md").is_file()
                    }
            unload_plugin(plugin_id)

        for item in self.list_installed():
            if item.get("id") == plugin_id:
                return item
        return {"id": plugin_id, "enabled": enabled}

    def plugin_dir(self, plugin_id: str) -> Path | None:
        """Return the on-disk plugin directory when it exists."""
        self._ensure_plugin_cache()
        dest = self._plugins_dir / plugin_id
        if dest.is_dir() and (dest / "plugin.yaml").is_file():
            return dest
        return None

    def resolve_ui_file(self, plugin_id: str, rel_path: str) -> Path:
        """Resolve a UI asset under the plugin tree with path-traversal checks.

        ``rel_path`` is typically relative to ``<plugin>/ui/`` (e.g. ``dist/index.js``)
        as served by ``GET /api/plugins/{id}/ui/{path}``. Full paths from the
        plugin root (``ui/dist/index.js``) are also accepted.
        """
        plugin_dir = self.plugin_dir(plugin_id)
        if plugin_dir is None:
            raise OctopError(
                ErrorCode.NOT_FOUND,
                f"plugin {plugin_id!r} not found",
            )
        return self._resolve_plugin_asset(plugin_dir, rel_path)

    @staticmethod
    def _resolve_plugin_asset(plugin_dir: Path, rel_path: str) -> Path:
        cleaned = rel_path.strip().lstrip("/").replace("\\", "/")
        if not cleaned or any(part == ".." for part in cleaned.split("/")):
            raise OctopError(ErrorCode.NOT_FOUND, "invalid plugin UI path")
        candidates = [
            plugin_dir / "ui" / cleaned,
            plugin_dir / cleaned,
        ]
        if not cleaned.startswith("ui/") and not cleaned.startswith("dist/"):
            candidates.append(plugin_dir / "ui" / "dist" / cleaned)
        for target in candidates:
            resolved = target.resolve()
            try:
                resolved.relative_to(plugin_dir.resolve())
            except ValueError as exc:
                raise OctopError(ErrorCode.NOT_FOUND, "invalid plugin UI path") from exc
            if resolved.is_file():
                return resolved
        raise OctopError(
            ErrorCode.NOT_FOUND,
            f"plugin UI file not found: {cleaned}",
        )

    def plugin_skill_names(self, plugin_id: str) -> set[str]:
        """Return skill directory names registered by one loaded plugin."""
        plugin = PluginRegistry().get(plugin_id)
        if plugin is None or plugin.skills_dir is None:
            return set(self._skill_catalog.get(plugin_id) or ())
        names = {
            path.name
            for path in plugin.skills_dir.iterdir()
            if path.is_dir() and (path / "SKILL.md").is_file()
        }
        self._skill_catalog[plugin_id] = names
        return set(names)

    def sync_skills_to_workspace(
        self,
        workspace: Any,
        *,
        agent_plugins: object = None,
    ) -> None:
        from octop_harness.backends.workspace import BackendWorkspace

        from octop.infra.agents.plugins.plugin_tool_defaults import agent_plugin_enabled

        if not isinstance(workspace, BackendWorkspace):
            return
        enabled = self.global_enabled_map()
        pairs: list[tuple[str, bytes]] = []
        for plugin in PluginRegistry().list_plugins():
            if enabled.get(plugin.manifest.id) is False:
                continue
            if not agent_plugin_enabled(agent_plugins, plugin.manifest.id):
                continue
            if plugin.skills_dir is None:
                continue
            for skill_dir in plugin.skills_dir.iterdir():
                if not skill_dir.is_dir():
                    continue
                if not (skill_dir / "SKILL.md").is_file():
                    continue
                dest = f"skills/{skill_dir.name}"
                if workspace.exists(f"{dest}/SKILL.md"):
                    continue
                for path in skill_dir.rglob("*"):
                    if not path.is_file():
                        continue
                    rel = path.relative_to(skill_dir).as_posix()
                    pairs.append((f"{dest}/{rel}", path.read_bytes()))
        if pairs:
            workspace.upload_many(pairs)
