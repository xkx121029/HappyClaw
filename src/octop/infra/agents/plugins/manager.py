"""Plugin manager: bundled/portal market, DSH market, install pipeline.

The class is assembled from mixins by responsibility. Archive validation,
download and the install entry points stay in this module because tests
patch its limits and ``urllib.request.urlopen``.
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from octop_harness.plugins import (
    LoadedPlugin,
    PluginManifest,
    unload_plugin,
)

from octop.infra.agents.plugins.catalog import PluginCatalogMixin
from octop.infra.agents.plugins.dsh_catalog import DshCatalogMixin
from octop.infra.agents.plugins.dsh_status import DshStatusMixin
from octop.infra.agents.plugins.loader import (
    _load_plugin_dir,
)
from octop.infra.agents.plugins.manager_base import PluginManagerBase
from octop.infra.agents.plugins.state import PluginStateMixin
from octop.infra.db.repos.control_files import ControlFileRepo
from octop.infra.errors import ErrorCode, OctopError

logger = logging.getLogger(__name__)


_MAX_PLUGIN_ARCHIVE_BYTES = 100 * 1024 * 1024

_MAX_PLUGIN_ZIP_ENTRIES = 2_000

_MAX_PLUGIN_UNCOMPRESSED_BYTES = 64 * 1024 * 1024

_MAX_PLUGIN_MEMBER_BYTES = 64 * 1024 * 1024

_MAX_PLUGIN_COMPRESSION_RATIO = 100.0

_DOWNLOAD_CHUNK = 64 * 1024

_GITHUB_BLOB_RE = re.compile(
    r"^https?://(?:www\.)?github\.com/"
    r"(?P<owner>[^/]+)/(?P<repo>[^/]+)/(?:blob|raw)/"
    r"(?P<ref>[^/]+)/(?P<path>.+)$",
    re.IGNORECASE,
)


class PluginManager(
    PluginStateMixin,
    PluginCatalogMixin,
    DshCatalogMixin,
    DshStatusMixin,
    PluginManagerBase,
):
    """One plugin store: catalog, DSH market and install pipeline."""

    def install_path(
        self,
        source: Path,
        *,
        force: bool = False,
        expect_id: str | None = None,
        expect_version: str | None = None,
    ) -> LoadedPlugin:
        self._ensure_plugin_cache()
        source = source.resolve()
        if not source.is_dir():
            raise OctopError(
                ErrorCode.PLUGIN_INVALID_ARCHIVE,
                f"plugin directory not found: {source}",
            )
        try:
            manifest = PluginManifest.load(source / "plugin.yaml")
        except Exception as exc:
            raise OctopError(
                ErrorCode.PLUGIN_INVALID_ARCHIVE,
                f"invalid plugin manifest: {exc}",
            ) from exc
        if expect_id is not None and manifest.id != expect_id:
            raise OctopError(
                ErrorCode.PLUGIN_INVALID_ARCHIVE,
                f"plugin id {manifest.id!r} does not match {expect_id!r}",
            )
        if expect_version is not None and manifest.version != expect_version:
            raise OctopError(
                ErrorCode.PLUGIN_INVALID_ARCHIVE,
                f"plugin version {manifest.version!r} does not match {expect_version!r}",
            )
        dest = self._plugins_dir / manifest.id
        if dest.exists():
            if not force:
                raise OctopError(
                    ErrorCode.PLUGIN_ALREADY_EXISTS,
                    f"plugin already installed: {manifest.id}",
                    details={"id": manifest.id},
                )
            shutil.rmtree(dest)
        shutil.copytree(source, dest)
        self._persist_plugin_tree(manifest.id)
        unload_plugin(manifest.id)
        try:
            return _load_plugin_dir(dest, install_deps=True)
        except Exception as exc:
            raise OctopError(
                ErrorCode.PLUGIN_INSTALL_FAILED,
                f"failed to load plugin: {exc}",
                details={"reason": str(exc)},
            ) from exc

    def install_archive(
        self,
        archive: Path,
        *,
        force: bool = False,
        expect_id: str | None = None,
        expect_version: str | None = None,
    ) -> LoadedPlugin:
        """Install a plugin from a local ZIP archive.

        The archive must contain exactly one plugin directory (at the zip root
        or in a single top-level folder) with a ``plugin.yaml`` manifest.
        """
        _assert_zip_magic(archive)
        try:
            if archive.stat().st_size > _MAX_PLUGIN_ARCHIVE_BYTES:
                raise _archive_error("plugin ZIP exceeds 100 MiB")
        except OSError as exc:
            raise _archive_error(f"cannot inspect plugin ZIP: {exc}") from exc
        with tempfile.TemporaryDirectory() as tmp:
            extract_to = Path(tmp) / "extract"
            extract_to.mkdir()
            try:
                with zipfile.ZipFile(archive) as zf:
                    infos = _validate_plugin_zip(zf)
                    extract_root = extract_to.resolve()
                    for member in infos:
                        target = (extract_to / member.filename).resolve()
                        try:
                            target.relative_to(extract_root)
                        except ValueError as exc:
                            raise _archive_error("zip path traversal detected") from exc
                    total_written = 0
                    for member in infos:
                        target = (extract_to / member.filename).resolve()
                        if member.is_dir():
                            target.mkdir(parents=True, exist_ok=True)
                            continue
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(member) as source, target.open("wb") as destination:
                            while True:
                                chunk = source.read(1024 * 1024)
                                if not chunk:
                                    break
                                total_written += len(chunk)
                                if total_written > _MAX_PLUGIN_UNCOMPRESSED_BYTES:
                                    raise _archive_error("plugin ZIP expands beyond 64 MiB")
                                destination.write(chunk)
            except OctopError:
                raise
            except zipfile.BadZipFile as exc:
                raise OctopError(
                    ErrorCode.PLUGIN_INVALID_ARCHIVE,
                    "file is not a valid ZIP archive",
                ) from exc

            # Support zip root being the plugin dir or containing one subdir
            candidates = [p for p in extract_to.iterdir() if (p / "plugin.yaml").is_file()]
            if not candidates and (extract_to / "plugin.yaml").is_file():
                candidates = [extract_to]
            if len(candidates) != 1:
                raise OctopError(
                    ErrorCode.PLUGIN_INVALID_ARCHIVE,
                    "zip must contain exactly one plugin directory with plugin.yaml",
                )
            return self.install_path(
                candidates[0],
                force=force,
                expect_id=expect_id,
                expect_version=expect_version,
            )

    def install_url(
        self,
        url: str,
        *,
        force: bool = False,
        expect_id: str | None = None,
        expect_version: str | None = None,
    ) -> LoadedPlugin:
        resolved = normalize_plugin_download_url(url)
        _assert_http_url(resolved)
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "plugin.zip"
            _download_plugin_archive(resolved, archive)
            try:
                return self.install_archive(
                    archive,
                    force=force,
                    expect_id=expect_id,
                    expect_version=expect_version,
                )
            except OctopError as exc:
                if exc.code is not ErrorCode.PLUGIN_INVALID_ARCHIVE:
                    raise
                raise OctopError(
                    ErrorCode.PLUGIN_INVALID_ARCHIVE,
                    f"{exc.message} (GitHub /blob/ pages return HTML — use a raw .zip URL)",
                    details=exc.details,
                ) from exc

    def uninstall(self, plugin_id: str) -> None:
        unload_plugin(plugin_id)
        self._tool_catalog.pop(plugin_id, None)
        self._skill_catalog.pop(plugin_id, None)
        dest = self._plugins_dir / plugin_id
        if dest.is_dir():
            shutil.rmtree(dest)
        if self._control_files is not None:
            self._control_files.delete_owner(ControlFileRepo.PLUGIN, plugin_id)
            self._bump_plugin_revision()


def _assert_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise OctopError(
            ErrorCode.PLUGIN_INVALID_ARCHIVE,
            "plugin URL must be an http(s) address to a ZIP archive",
        )


def _assert_zip_magic(archive: Path) -> None:
    with archive.open("rb") as source:
        head = source.read(4)
    if len(head) < 2 or head[:2] != b"PK":
        raise OctopError(
            ErrorCode.PLUGIN_INVALID_ARCHIVE,
            "file is not a valid ZIP archive",
        )


def _archive_error(message: str) -> OctopError:
    return OctopError(ErrorCode.PLUGIN_INVALID_ARCHIVE, message)


def _validate_plugin_zip(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = zf.infolist()
    if len(infos) > _MAX_PLUGIN_ZIP_ENTRIES:
        raise _archive_error("plugin ZIP contains too many entries")

    total_uncompressed = 0
    for member in infos:
        if member.file_size < 0 or member.file_size > _MAX_PLUGIN_MEMBER_BYTES:
            raise _archive_error(f"plugin ZIP member is too large: {member.filename}")
        total_uncompressed += member.file_size
        if total_uncompressed > _MAX_PLUGIN_UNCOMPRESSED_BYTES:
            raise _archive_error("plugin ZIP expands beyond 64 MiB")
        compressed = member.compress_size or 0
        if (
            compressed > 0
            and member.file_size > 1024 * 1024
            and member.file_size / compressed > _MAX_PLUGIN_COMPRESSION_RATIO
        ):
            raise _archive_error(f"plugin ZIP compression ratio is too high: {member.filename}")
    return infos


def _download_plugin_archive(url: str, archive: Path) -> None:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
            content_length = response.headers.get("Content-Length")
            if content_length is not None:
                try:
                    if int(content_length) > _MAX_PLUGIN_ARCHIVE_BYTES:
                        raise _archive_error("plugin ZIP download exceeds the configured limit")
                except ValueError:
                    pass
            total = 0
            with archive.open("wb") as target:
                while True:
                    chunk = response.read(_DOWNLOAD_CHUNK)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > _MAX_PLUGIN_ARCHIVE_BYTES:
                        raise _archive_error("plugin ZIP download exceeds the configured limit")
                    target.write(chunk)
    except OctopError:
        raise
    except urllib.error.HTTPError as exc:
        raise OctopError(
            ErrorCode.PLUGIN_INSTALL_FAILED,
            f"download failed with HTTP {exc.code}",
            details={"reason": f"HTTP {exc.code}"},
        ) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None) or str(exc)
        raise OctopError(
            ErrorCode.PLUGIN_INSTALL_FAILED,
            f"download failed: {reason}",
            details={"reason": str(reason)},
        ) from exc
    except OSError as exc:
        raise OctopError(
            ErrorCode.PLUGIN_INSTALL_FAILED, f"download failed: {exc}", details={"reason": str(exc)}
        ) from exc


def normalize_plugin_download_url(url: str) -> str:
    """Rewrite GitHub ``/blob/`` (and ``/raw/``) page URLs to raw content URLs.

    ``https://github.com/org/repo/blob/main/plugin.zip`` returns HTML, not the
    archive — that is the common cause of ``BadZipFile`` during install.
    """
    cleaned = url.strip()
    match = _GITHUB_BLOB_RE.match(cleaned)
    if match is None:
        return cleaned
    owner = match.group("owner")
    repo = match.group("repo")
    ref = match.group("ref")
    path = match.group("path").lstrip("/")
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"


# --- historical import surface -------------------------------------------
# Callers and tests import these from this module; they now live in the
# responsibility-specific sibling modules.
__all__ = [
    "PluginManager",
    "normalize_plugin_download_url",
    "DSH_DEFAULT_SOURCES",
    "DSH_DEP_INSTALL_TIMEOUT_SECONDS",
    "DSH_INDEX_CACHE_DIRNAME",
    "DSH_INDEX_FETCH_TIMEOUT_SECONDS",
    "DSH_MARKET_CACHE_TTL_SECONDS",
    "DSH_MARKET_MAX_PAGE_SIZE",
    "DSH_MARKET_PAGE_SIZE",
    "DSH_MARKET_SNAPSHOT_DEADLINE_SECONDS",
    "DSH_PROBE_TIMEOUT_SECONDS",
    "DSH_PROGRESS_HISTORY",
    "DSH_SOURCE_ATTEMPTS",
    "DSH_SOURCE_BACKGROUND_BUDGET_SECONDS",
    "DSH_SOURCE_BUDGET_SECONDS",
    "DSH_SOURCE_FETCH_WORKERS",
    "DSH_SOURCE_RETRY_BACKOFF_SECONDS",
    "DSH_SOURCES_LIMIT",
    "DSH_STATUS_SCHEMA_VERSION",
    "DSH_UI_SURFACE_REASON",
    "DSH_UI_SURFACE_REASON_CODE",
    "PLUGIN_UI_API_VERSION",
    "PLUGIN_UI_DATA_DOMAINS",
    "PLUGIN_UI_EVENTS",
    "PLUGIN_UI_HOST_SERVICES",
    "PLUGIN_UI_SLOTS",
    "PLUGIN_UI_SURFACE_REASON_DUPLICATE",
    "PLUGIN_UI_SURFACE_REASON_SLOT",
    "PLUGINS_ENABLED",
    "PLUGINS_REVISION",
    "_TolerantDshSource",
    "_cached_dsh_index_entries",
    "_dsh_entry_matches",
    "_dsh_source",
    "_fetch_index_bytes",
    "_read_dsh_index_cache",
    "_read_dsh_sources",
    "_write_dsh_index_cache",
    "_write_dsh_sources",
    "dsh_source_budget",
    "normalize_dsh_source",
    "_read_global_plugins",
    "_write_global_plugin_enabled",
    "_channel_fingerprint",
    "_market_error_payload",
    "_market_octop_error",
    "PLUGIN_GROUPS",
    "_parse_ui_surfaces",
    "_read_installed_version",
    "_read_plugin_yaml",
    "_read_tree",
    "_version_tuple",
    "parse_plugin_group",
    "parse_plugin_icon",
    "parse_plugin_requires",
    "parse_plugin_ui_meta",
    "_classify_dependency_failure",
    "_install_dsh_dependencies",
    "_node_dependency_gaps",
    "_node_engine_problem",
    "_node_range_satisfied",
    "_node_version_tuple",
    "_probe_dsh_entry",
]

from octop.infra.agents.plugins.constants import (  # noqa: E402
    DSH_DEFAULT_SOURCES,
    DSH_DEP_INSTALL_TIMEOUT_SECONDS,
    DSH_INDEX_CACHE_DIRNAME,
    DSH_INDEX_FETCH_TIMEOUT_SECONDS,
    DSH_MARKET_CACHE_TTL_SECONDS,
    DSH_MARKET_MAX_PAGE_SIZE,
    DSH_MARKET_PAGE_SIZE,
    DSH_MARKET_SNAPSHOT_DEADLINE_SECONDS,
    DSH_PROBE_TIMEOUT_SECONDS,
    DSH_PROGRESS_HISTORY,
    DSH_SOURCE_ATTEMPTS,
    DSH_SOURCE_BACKGROUND_BUDGET_SECONDS,
    DSH_SOURCE_BUDGET_SECONDS,
    DSH_SOURCE_FETCH_WORKERS,
    DSH_SOURCE_RETRY_BACKOFF_SECONDS,
    DSH_SOURCES_LIMIT,
    DSH_STATUS_SCHEMA_VERSION,
    DSH_UI_SURFACE_REASON,
    DSH_UI_SURFACE_REASON_CODE,
    PLUGIN_UI_API_VERSION,
    PLUGIN_UI_DATA_DOMAINS,
    PLUGIN_UI_EVENTS,
    PLUGIN_UI_HOST_SERVICES,
    PLUGIN_UI_SLOTS,
    PLUGIN_UI_SURFACE_REASON_DUPLICATE,
    PLUGIN_UI_SURFACE_REASON_SLOT,
    PLUGINS_ENABLED,
    PLUGINS_REVISION,
)
from octop.infra.agents.plugins.dsh_index import (  # noqa: E402
    _cached_dsh_index_entries,
    _dsh_entry_matches,
    _dsh_source,
    _fetch_index_bytes,
    _read_dsh_index_cache,
    _read_dsh_sources,
    _TolerantDshSource,
    _write_dsh_index_cache,
    _write_dsh_sources,
    dsh_source_budget,
    normalize_dsh_source,
)
from octop.infra.agents.plugins.global_flags import (  # noqa: E402
    _read_global_plugins,
    _write_global_plugin_enabled,
)
from octop.infra.agents.plugins.loader import (  # noqa: E402
    _channel_fingerprint,
)
from octop.infra.agents.plugins.market_errors import (  # noqa: E402
    _market_error_payload,
    _market_octop_error,
)
from octop.infra.agents.plugins.metadata import (  # noqa: E402
    PLUGIN_GROUPS,
    _parse_ui_surfaces,
    _read_installed_version,
    _read_plugin_yaml,
    _read_tree,
    _version_tuple,
    parse_plugin_group,
    parse_plugin_icon,
    parse_plugin_requires,
    parse_plugin_ui_meta,
)
from octop.infra.agents.plugins.node_deps import (  # noqa: E402
    _classify_dependency_failure,
    _install_dsh_dependencies,
    _node_dependency_gaps,
    _node_engine_problem,
    _node_range_satisfied,
    _node_version_tuple,
    _probe_dsh_entry,
)
