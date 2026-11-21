"""DSH market: sources, listing, install/upgrade/uninstall."""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from octop.infra.agents.plugins.constants import (
    DSH_DEFAULT_SOURCES,
    DSH_INDEX_CACHE_DIRNAME,
    DSH_MARKET_CACHE_TTL_SECONDS,
    DSH_MARKET_MAX_PAGE_SIZE,
    DSH_MARKET_PAGE_SIZE,
    DSH_MARKET_SNAPSHOT_DEADLINE_SECONDS,
    DSH_PROGRESS_HISTORY,
    DSH_SOURCE_BACKGROUND_BUDGET_SECONDS,
    DSH_SOURCE_FETCH_WORKERS,
    DSH_SOURCES_LIMIT,
)
from octop.infra.agents.plugins.dsh_index import (
    _cached_dsh_index_entries,
    _dsh_entry_matches,
    _dsh_source,
    _read_dsh_index_cache,
    _read_dsh_sources,
    _TolerantDshSource,
    _write_dsh_sources,
    dsh_source_budget,
    normalize_dsh_source,
)
from octop.infra.agents.plugins.manager_base import PluginManagerBase
from octop.infra.agents.plugins.market_errors import (
    _market_error_payload,
    _market_octop_error,
)
from octop.infra.agents.plugins.node_deps import (
    _install_dsh_dependencies,
)
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.utils.json_file import (
    JsonFileCorruptError,
    read_json_object,
)

logger = logging.getLogger(__name__)


class DshCatalogMixin(PluginManagerBase):
    def dsh_source_urls(self) -> list[str]:
        """Configured DSH index addresses, in user order.

        Until the user saves ``plugin_market.dsh_sources`` the built-in indexes
        are used. An explicit list replaces them entirely, so removing every
        built-in source sticks across restarts.
        """

        stored = _read_dsh_sources(self._config_path)
        if stored is None:
            return list(DSH_DEFAULT_SOURCES)
        return stored

    def add_dsh_source(self, url: str) -> list[str]:
        """Persist one DSH index address; idempotent for duplicates."""

        value = normalize_dsh_source(url)
        urls = self.dsh_source_urls()
        if value in urls:
            return urls
        if len(urls) >= DSH_SOURCES_LIMIT:
            raise OctopError(
                ErrorCode.PLUGIN_MARKET_SOURCE_INVALID,
                f"最多可添加 {DSH_SOURCES_LIMIT} 条 DSH 索引源",
                details={"url": value, "limit": DSH_SOURCES_LIMIT},
            )
        urls.append(value)
        _write_dsh_sources(self._config_path, urls)
        self._invalidate_dsh_market_cache()
        return urls

    def remove_dsh_source(self, url: str) -> list[str]:
        """Drop one DSH index address; unknown values are a no-op."""

        value = str(url or "").strip()
        current = self.dsh_source_urls()
        urls = [item for item in current if item != value]
        if urls != current:
            _write_dsh_sources(self._config_path, urls)
            self._invalidate_dsh_market_cache()
        return urls

    def _invalidate_dsh_market_cache(self) -> None:
        """Forget the aggregated index after a source or install change."""

        with self._dsh_market_lock:
            self._dsh_market_cache = None
            self._dsh_market_cache_key = None
            self._dsh_market_cache_at = 0.0

    def dsh_market_root(self) -> Path:
        """Catalog install root for DSH plugins."""

        from octop.infra.plugins.market import default_market_root

        return default_market_root()

    def _dsh_index(self, *, language: str = "zh") -> tuple[Any, list[Exception]]:
        """Marketplace index over every configured source, plus read failures.

        Sources are wrapped so a slow or broken mirror contributes no rows
        instead of aborting install/upgrade. The failures come back to the
        caller, which explains a total miss in terms of the source error.
        """
        from octop.infra.plugins.market import MarketplaceIndex

        urls = self.dsh_source_urls()
        if not urls:
            raise OctopError(
                ErrorCode.PLUGIN_MARKET_SOURCE_INVALID,
                "尚未配置 DSH 索引源，请先添加一个静态 JSON 索引地址",
                details={"sources": []},
            )
        cache_dir = self._dsh_index_cache_dir()
        failures: list[Exception] = []
        index = MarketplaceIndex(
            [
                _TolerantDshSource(
                    _dsh_source(
                        url,
                        language=language,
                        cache_dir=cache_dir,
                        allow_cache=True,
                    ),
                    failures,
                )
                for url in urls
            ]
        )
        return index, failures

    def _dsh_index_cache_dir(self) -> Path:
        return self.dsh_market_root() / DSH_INDEX_CACHE_DIRNAME

    def _fetch_dsh_source(
        self, url: str, *, language: str, fetched_at: str
    ) -> tuple[list[Any] | None, dict[str, Any]]:
        """Fetch one index; failures stay on that source instead of raising.

        A timeout is not the same as a broken source: when the body was cached
        from an earlier successful read, those rows are served (``status:
        "stale"``) and a background thread refreshes the cache. Only a source
        with no usable copy at all reports ``error`` and drops its entries.
        """

        cache_dir = self._dsh_index_cache_dir()
        source = _dsh_source(url, language=language, cache_dir=cache_dir)
        started = time.monotonic()
        try:
            rows = source.fetch_index()
        except Exception as exc:  # one source must not hide the others
            elapsed_ms = round((time.monotonic() - started) * 1000, 1)
            cached_body = _read_dsh_index_cache(cache_dir, url)
            error = _market_error_payload(exc)
            slow = "timeout" in str(exc).lower()
            if cached_body is not None:
                try:
                    rows = _cached_dsh_index_entries(url, cached_body, language=language)
                except Exception:
                    rows = None
                if rows is not None:
                    self._schedule_dsh_source_refresh(url, language=language)
                    return rows, {
                        "url": url,
                        "status": "stale",
                        "error": error,
                        "entry_count": len(rows),
                        "diagnostics": "",
                        "fetched_at": fetched_at,
                        "stale": True,
                        "budget_seconds": dsh_source_budget(url),
                        "elapsed_ms": elapsed_ms,
                    }
            if slow:
                # No cache yet and the read ran out of budget: the source is
                # slow today, not broken. Warm its cache off the request path
                # and keep every other source in the catalog.
                self._schedule_dsh_source_refresh(url, language=language)
            return None, {
                "url": url,
                "status": "slow" if slow else "error",
                "error": error,
                "entry_count": 0,
                "diagnostics": "",
                "fetched_at": fetched_at,
                "stale": False,
                "budget_seconds": dsh_source_budget(url),
                "elapsed_ms": elapsed_ms,
            }
        return rows, {
            "url": url,
            "status": "ok",
            "error": None,
            "entry_count": len(rows),
            "diagnostics": source.diagnostics(),
            "fetched_at": fetched_at,
            "stale": False,
            "budget_seconds": dsh_source_budget(url),
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
        }

    def _schedule_dsh_source_refresh(self, url: str, *, language: str) -> None:
        """Refresh a slow source off the request path; never raises."""

        with self._dsh_refresh_lock:
            if url in self._dsh_refresh_inflight:
                return
            self._dsh_refresh_inflight.add(url)

        def run() -> None:
            try:
                _dsh_source(
                    url,
                    language=language,
                    cache_dir=self._dsh_index_cache_dir(),
                    budget=DSH_SOURCE_BACKGROUND_BUDGET_SECONDS,
                ).fetch_index()
            except Exception as exc:  # the visible status already carries the error
                logger.info("background DSH source refresh failed for %s: %s", url, exc)
            finally:
                with self._dsh_refresh_lock:
                    self._dsh_refresh_inflight.discard(url)

        threading.Thread(target=run, daemon=True, name="dsh-source-refresh").start()

    def _dsh_snapshot(
        self, urls: list[str], *, language: str, refresh: bool
    ) -> tuple[dict[str, Any], bool]:
        """Aggregated index (one winning entry per plugin id) plus source health.

        The snapshot is cached for a short window: three public indexes weigh
        several megabytes, and paging/searching must not re-download them on
        every keystroke. ``refresh`` forces a rebuild; source and install
        changes invalidate the cache explicitly.
        """

        from datetime import datetime

        from octop.infra.plugins.market.versions import compare_versions

        key = (tuple(urls), language)
        with self._dsh_market_lock:
            started = time.monotonic()
            if (
                not refresh
                and self._dsh_market_cache is not None
                and self._dsh_market_cache_key == key
                and started - self._dsh_market_cache_at < DSH_MARKET_CACHE_TTL_SECONDS
            ):
                return self._dsh_market_cache, True

            fetched_at = datetime.now(UTC).isoformat()
            source_rows: list[dict[str, Any]] = []
            winners: dict[str, Any] = {}
            pending_urls: list[str] = []
            # Sources are independent; fetching them in parallel keeps the
            # first page bounded by the slowest operator, not their sum.
            if urls:
                from concurrent.futures import ThreadPoolExecutor, as_completed

                pool = ThreadPoolExecutor(max_workers=min(DSH_SOURCE_FETCH_WORKERS, len(urls)))
                futures = {
                    pool.submit(
                        self._fetch_dsh_source,
                        url,
                        language=language,
                        fetched_at=fetched_at,
                    ): url
                    for url in urls
                }
                results: list[tuple[list[Any] | None, dict[str, Any]]] = []
                try:
                    for future in as_completed(
                        futures, timeout=DSH_MARKET_SNAPSHOT_DEADLINE_SECONDS
                    ):
                        try:
                            results.append(future.result())
                        except Exception as exc:  # never expected; stay honest
                            url = futures[future]
                            results.append(
                                (
                                    None,
                                    {
                                        "url": url,
                                        "status": "error",
                                        "error": _market_error_payload(exc),
                                        "entry_count": 0,
                                        "diagnostics": "",
                                        "fetched_at": fetched_at,
                                        "stale": False,
                                        "budget_seconds": dsh_source_budget(url),
                                        "elapsed_ms": None,
                                    },
                                )
                            )
                except TimeoutError:
                    # A slow source must not hold the whole catalog hostage:
                    # render what is ready and let the reader finish in the
                    # background, where it fills the disk cache.
                    pending_urls = [url for future, url in futures.items() if not future.done()]
                finally:
                    pool.shutdown(wait=False)
                for url in pending_urls:
                    results.append(
                        (
                            None,
                            {
                                "url": url,
                                "status": "slow",
                                "error": {
                                    "code": "PLUGIN_SOURCE_PENDING",
                                    "message": "索引仍在读取，已转入后台并会缓存",
                                    "details": {},
                                },
                                "entry_count": 0,
                                "diagnostics": "",
                                "fetched_at": fetched_at,
                                "stale": False,
                                "budget_seconds": dsh_source_budget(url),
                                "elapsed_ms": None,
                            },
                        )
                    )
            else:
                results = []
            # ``as_completed`` yields in completion order. Health rows are
            # reported in the configured order so callers can index by
            # position instead of matching URLs.
            order = {url: index for index, url in enumerate(urls)}
            results.sort(key=lambda item: order.get(item[1]["url"], len(order)))
            for rows, health in results:
                source_rows.append(health)
                self._dsh_source_health[health["url"]] = health
                for entry in rows or []:
                    current = winners.get(entry.plugin_id)
                    if current is None:
                        winners[entry.plugin_id] = entry
                        continue
                    comparison = compare_versions(entry.version, current.version)
                    if comparison is not None and comparison > 0:
                        winners[entry.plugin_id] = entry

            self._dsh_sources_checked_at = fetched_at
            snapshot = {
                "sources": source_rows,
                "winners": winners,
                "fetched_at": fetched_at,
            }
            self._dsh_market_cache = snapshot
            self._dsh_market_cache_key = key
            self._dsh_market_cache_at = started
            return snapshot, False

    def list_dsh_market(
        self,
        language: str = "zh",
        *,
        query: str = "",
        page: int = 1,
        page_size: int = DSH_MARKET_PAGE_SIZE,
        refresh: bool = False,
    ) -> dict[str, Any]:
        """Return one page of the DSH catalog, with source health and paging.

        Filtering is a case-insensitive substring match over the plugin name,
        description and canonical id. Paging happens after filtering, so
        ``total`` always describes the query. The full index stays on the
        server: the UI only receives the rows it renders.
        """

        urls = self.dsh_source_urls()
        root = self.dsh_market_root()
        snapshot, cached = self._dsh_snapshot(urls, language=language, refresh=refresh)
        needle = str(query or "").strip().casefold()

        winners = snapshot["winners"]
        matched = [
            entry
            for _plugin_id, entry in sorted(winners.items())
            if not needle or _dsh_entry_matches(entry, needle)
        ]
        total = len(matched)
        size = max(1, min(int(page_size or DSH_MARKET_PAGE_SIZE), DSH_MARKET_MAX_PAGE_SIZE))
        current = max(1, int(page or 1))
        start = (current - 1) * size
        entries = [self._dsh_entry_row(entry, root=root) for entry in matched[start : start + size]]
        builtin = set(DSH_DEFAULT_SOURCES)
        return {
            "market_root": str(root),
            "sources": [{**row, "builtin": row["url"] in builtin} for row in snapshot["sources"]],
            "entries": entries,
            "total": total,
            "page": current,
            "page_size": size,
            "total_pages": (total + size - 1) // size,
            "query": str(query or "").strip(),
            "fetched_at": snapshot["fetched_at"],
            "cached": cached,
        }

    def _dsh_entry_row(self, entry: Any, *, root: Path) -> dict[str, Any]:
        from functools import cmp_to_key

        from octop.infra.plugins.market.versions import compare_versions

        def _newest_first(left: Any, right: Any) -> int:
            return compare_versions(right.version, left.version) or 0

        releases = sorted(entry.releases, key=cmp_to_key(_newest_first))
        installed, installed_version = self._dsh_install_state(entry.plugin_id)
        runtime = self._dsh_runtime_status(entry.plugin_id)
        return {
            "plugin_id": entry.plugin_id,
            "package_name": entry.extra.get("package_name"),
            "name": entry.name,
            "description": entry.description,
            "icon": entry.icon,
            "homepage": entry.homepage,
            "tags": list(entry.tags),
            "source_url": entry.extra.get("index_url"),
            "versions": [release.version for release in releases],
            "recommended_version": entry.version,
            "installed": installed,
            "installed_version": installed_version,
            "update_available": bool(
                installed
                and installed_version
                and (compare_versions(entry.version, installed_version) or 0) > 0
            ),
            "runtime": runtime,
        }

    def _dsh_install_state(self, plugin_id: str) -> tuple[bool, str | None]:
        """Read the ledger's ``current`` version without trusting the slot."""

        native = plugin_id.split(":", 1)[1] if ":" in plugin_id else plugin_id
        ledger_path = self.dsh_market_root() / "dsh" / native / "index.json"
        try:
            ledger = read_json_object(ledger_path)
        except JsonFileCorruptError:
            return True, None
        if not isinstance(ledger, dict):
            return False, None
        current = ledger.get("current")
        if not isinstance(current, dict):
            return True, None
        return True, str(current.get("version") or "") or None

    def list_dsh_installed(self) -> dict[str, Any]:
        """Return DSH bundles installed from the market, read from disk only.

        ``list_installed`` scans ``~/.octop/plugins`` (host plugin directories),
        while DSH market installs live under ``<market_root>/dsh`` and are
        tracked by their own ledger. The installed tab therefore has to read
        that ledger directly; resolving it through the remote index would make
        an offline catalog look like an uninstalled plugin. Nothing is imported
        or executed here, and no network request is made.
        """

        from octop.infra.plugins.market import ENVELOPE_FILENAME

        root = self.dsh_market_root()
        dsh_root = root / "dsh"
        rows: list[dict[str, Any]] = []
        if not dsh_root.is_dir():
            return {"market_root": str(root), "plugins": rows}

        for plugin_root in sorted(path for path in dsh_root.iterdir() if path.is_dir()):
            plugin_id = f"dsh:{plugin_root.name}"
            row: dict[str, Any] = {
                "plugin_id": plugin_id,
                "name": plugin_root.name,
                "description": "",
                "version": None,
                "versions": [],
                "installed_at": None,
                "install_dir": None,
                "entry": None,
                "source_url": None,
                "runtime": self._dsh_runtime_status(plugin_id),
                "error": None,
            }
            try:
                ledger = read_json_object(plugin_root / "index.json")
            except JsonFileCorruptError as exc:
                row["error"] = f"安装账本无法解析：{exc.detail}"
                rows.append(row)
                continue
            if not isinstance(ledger, dict):
                row["error"] = "未找到安装账本"
                rows.append(row)
                continue

            plugin_id = str(ledger.get("plugin_id") or plugin_id)
            row["plugin_id"] = plugin_id
            records = [item for item in ledger.get("installs", []) if isinstance(item, dict)]
            row["versions"] = [
                str(item.get("version") or "") for item in records if item.get("version")
            ]
            current = ledger.get("current")
            record = current if isinstance(current, dict) else (records[-1] if records else None)
            if record is None:
                row["error"] = "安装账本没有可读的版本记录"
                rows.append(row)
                continue

            row["version"] = str(record.get("version") or "") or None
            row["installed_at"] = record.get("installed_at")
            slot = plugin_root / str(record.get("slot") or "")
            row["install_dir"] = str(slot)
            try:
                envelope = read_json_object(slot / ENVELOPE_FILENAME)
            except JsonFileCorruptError:
                envelope = None
            if isinstance(envelope, dict):
                metadata = envelope.get("metadata")
                metadata = metadata if isinstance(metadata, dict) else {}
                package = metadata.get("package")
                package = package if isinstance(package, dict) else {}
                market = metadata.get("market")
                market = market if isinstance(market, dict) else {}
                source = envelope.get("source")
                source = source if isinstance(source, dict) else {}
                row["name"] = str(
                    package.get("package_name") or metadata.get("native_id") or row["name"]
                )
                row["description"] = str(metadata.get("description") or "")
                row["entry"] = envelope.get("entry")
                row["source_url"] = (
                    str(market.get("index") or source.get("reference") or "") or None
                )
            row["runtime"] = self._dsh_runtime_status(plugin_id)
            rows.append(row)

        return {"market_root": str(root), "plugins": rows}

    def _dsh_progress_start(self, plugin_id: str, *, action: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._dsh_progress_lock:
            self._dsh_progress[plugin_id] = {
                "plugin_id": plugin_id,
                "action": action,
                "phase": "download",
                "status": "running",
                "progress": 0.05,
                "message": "正在下载并解包发布包",
                "detail": "",
                "error_code": None,
                "started_at": now,
                "updated_at": now,
                "finished_at": None,
            }
            self._prune_dsh_progress_locked()

    def _prune_dsh_progress_locked(self) -> None:
        overflow = len(self._dsh_progress) - DSH_PROGRESS_HISTORY
        if overflow <= 0:
            return
        finished = sorted(
            (
                (key, record["finished_at"])
                for key, record in self._dsh_progress.items()
                if record.get("finished_at")
            ),
            key=lambda item: item[1],
        )
        for key, _finished_at in finished[:overflow]:
            self._dsh_progress.pop(key, None)

    def _dsh_progress_update(self, plugin_id: str, **fields: Any) -> None:
        with self._dsh_progress_lock:
            record = self._dsh_progress.get(plugin_id)
            if record is None:
                return
            record.update(fields)
            record["updated_at"] = datetime.now(UTC).isoformat()

    def _dsh_progress_finish(
        self, plugin_id: str, *, status: str, error_code: str | None = None
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self._dsh_progress_lock:
            record = self._dsh_progress.get(plugin_id)
            if record is None:
                return
            record.update(
                phase="done",
                status=status,
                progress=1.0,
                error_code=error_code,
                updated_at=now,
                finished_at=now,
            )

    def dsh_install_progress(self, plugin_id: str) -> dict[str, Any]:
        """Last known load progress for one plugin (``__missing__`` is null).

        Returned separately from the install response so the page can show a
        phase while the install request itself is still running.
        """

        with self._dsh_progress_lock:
            record = self._dsh_progress.get(plugin_id)
            return {
                "plugin_id": plugin_id,
                "progress": dict(record) if record is not None else None,
            }

    def _dsh_install_dependencies(self, plugin_id: str, install_dir: Path) -> dict[str, Any]:
        """Run the dependency install for one slot and stream its progress."""

        try:
            package = read_json_object(install_dir / "package.json") or {}
        except JsonFileCorruptError as exc:
            return {
                "status": "failed",
                "manager": None,
                "missing": [],
                "code": "DSH_DEP_RESOLVE",
                "cause": "resolve",
                "message": f"package.json 无法解析：{exc.detail}",
                "output_tail": "",
                "duration_ms": 0,
            }
        self._dsh_progress_update(
            plugin_id,
            phase="dependencies",
            progress=0.45,
            message="正在安装依赖闭包（pnpm/npm）",
        )

        def on_output(line: str) -> None:
            self._dsh_progress_update(plugin_id, detail=line[:300], progress=0.6)

        report = _install_dsh_dependencies(install_dir, package, on_output=on_output)
        self._dsh_progress_update(
            plugin_id,
            detail=report["message"],
            progress=0.8,
            error_code=report.get("code"),
        )
        return report

    def install_dsh_market(
        self,
        plugin_id: str,
        *,
        version: str | None = None,
        force: bool = False,
        language: str = "zh",
    ) -> dict[str, Any]:
        """Install one DSH release, then its dependency closure and a probe.

        The market pipeline only unpacks the tarball. A bundle that declares
        npm dependencies is therefore loaded-but-broken unless the closure is
        installed here. Dependency failure is reported, not raised: the files
        did install, and the UI distinguishes "依赖装不上" from "装上了但运行时
        不可用".
        """

        self._dsh_progress_start(plugin_id, action="install")
        index, source_failures = self._dsh_index(language=language)
        if not index.fetch() and source_failures:
            self._dsh_progress_finish(
                plugin_id,
                status="failed",
                error_code=_market_error_payload(source_failures[0])["code"],
            )
            raise _market_octop_error(source_failures[0]) from source_failures[0]
        try:
            result = index.install(
                plugin_id,
                self.dsh_market_root(),
                version=version,
                force=force,
            )
        except Exception as exc:
            # "not listed" is misleading when a source was simply unreachable:
            # report the read failure so the UI can say the source is down
            # instead of claiming the plugin does not exist.
            failure = exc
            if source_failures and "is not listed" in str(exc):
                failure = source_failures[0]
            self._dsh_progress_finish(
                plugin_id,
                status="failed",
                error_code=_market_error_payload(failure)["code"],
            )
            self._dsh_progress_update(plugin_id, detail=str(failure)[:400])
            raise _market_octop_error(failure) from failure

        dependency = self._dsh_install_dependencies(plugin_id, result.install_dir)
        self._dsh_progress_update(
            plugin_id, phase="probe", progress=0.9, message="正在做运行时能力探针"
        )
        runtime = self._dsh_runtime_status(plugin_id, probe=True)
        if dependency["status"] == "failed":
            status = "installed_dependency_failed"
        elif runtime["status"] == "visible":
            status = "installed"
        else:
            status = "installed_not_ready"
        self._dsh_progress_finish(
            plugin_id,
            status="ok" if status == "installed" else "not_ready",
            error_code=dependency.get("code") or runtime.get("error_code"),
        )
        return {
            "plugin_id": result.plugin_id,
            "version": result.version,
            "source": result.source,
            "install_dir": str(result.install_dir),
            "status": status,
            "dependency": dependency,
            "runtime": runtime,
        }

    def upgrade_dsh_market(
        self,
        plugin_id: str,
        *,
        version: str | None = None,
        allow_capability_expansion: bool = False,
        language: str = "zh",
    ) -> dict[str, Any]:
        """Move an installed DSH plugin to another catalog version."""

        self._dsh_progress_start(plugin_id, action="upgrade")
        index, source_failures = self._dsh_index(language=language)
        if not index.fetch() and source_failures:
            self._dsh_progress_finish(
                plugin_id,
                status="failed",
                error_code=_market_error_payload(source_failures[0])["code"],
            )
            raise _market_octop_error(source_failures[0]) from source_failures[0]
        try:
            result = index.upgrade(
                plugin_id,
                self.dsh_market_root(),
                version=version,
                allow_capability_expansion=allow_capability_expansion,
            )
        except Exception as exc:
            failure = exc
            if source_failures and "is not listed" in str(exc):
                failure = source_failures[0]
            self._dsh_progress_finish(
                plugin_id,
                status="failed",
                error_code=_market_error_payload(failure)["code"],
            )
            self._dsh_progress_update(plugin_id, detail=str(failure)[:400])
            raise _market_octop_error(failure) from failure

        dependency = self._dsh_install_dependencies(plugin_id, result.install_dir)
        self._dsh_progress_update(
            plugin_id, phase="probe", progress=0.9, message="正在做运行时能力探针"
        )
        runtime = self._dsh_runtime_status(plugin_id, probe=True)
        if dependency["status"] == "failed":
            status = "upgraded_dependency_failed"
        elif runtime["status"] == "visible":
            status = "upgraded"
        else:
            status = "upgraded_not_ready"
        self._dsh_progress_finish(
            plugin_id,
            status="ok" if status == "upgraded" else "not_ready",
            error_code=dependency.get("code") or runtime.get("error_code"),
        )
        return {
            "plugin_id": result.plugin_id,
            "version": result.version,
            "previous_version": result.previous_version,
            "source": result.source,
            "install_dir": str(result.install_dir),
            "status": status,
            "dependency": dependency,
            "runtime": runtime,
        }

    def uninstall_dsh_market(
        self,
        plugin_id: str,
        *,
        version: str | None = None,
    ) -> dict[str, Any]:
        """Uninstall one DSH slot and report whether the tree is gone."""

        from octop.infra.plugins.market import uninstall as uninstall_entry

        root = self.dsh_market_root()
        try:
            result = uninstall_entry(plugin_id, root, version=version)
        except Exception as exc:
            raise _market_octop_error(exc) from exc
        native = plugin_id.split(":", 1)[1] if ":" in plugin_id else plugin_id
        plugin_root = root / "dsh" / native
        return {
            "plugin_id": result.plugin_id,
            "version": result.version,
            "install_dir": str(result.install_dir),
            "cleaned": not plugin_root.exists(),
            "remaining_versions": list(result.remaining_versions),
        }
