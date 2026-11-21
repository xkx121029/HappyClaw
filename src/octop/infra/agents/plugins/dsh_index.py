"""DSH index sources: fetch, disk cache, tolerant aggregation."""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from octop.infra.agents.plugins.constants import (
    DSH_INDEX_FETCH_TIMEOUT_SECONDS,
    DSH_SOURCE_ATTEMPTS,
    DSH_SOURCE_BUDGET_SECONDS,
    DSH_SOURCE_RETRY_BACKOFF_SECONDS,
    DSH_SOURCES_LIMIT,
)
from octop.infra.errors import ErrorCode, OctopError, corrupt_config_error
from octop.infra.plugins.market.source import Source
from octop.infra.plugins.runtime.contract import PluginKind
from octop.infra.utils.json_file import (
    JsonFileCorruptError,
    read_json_object,
    write_json_atomic,
)

logger = logging.getLogger(__name__)


def dsh_source_budget(url: str) -> float:
    """Whole-read budget for one index; slow operators get more time."""

    return DSH_SOURCE_BUDGET_SECONDS.get(url, DSH_INDEX_FETCH_TIMEOUT_SECONDS)


def _fetch_index_bytes(url: str, *, budget: float) -> bytes:
    """Read one index, retrying transient failures with a short backoff.

    A read that exhausted its whole budget is not retried in the foreground:
    the next attempt costs the same again, so the caller falls back to the
    cached body and refreshes it in the background instead.
    """

    from octop.infra.plugins.market.download import MAX_INDEX_BYTES, fetch_bytes
    from octop.infra.plugins.market.errors import SourceUnreachableError

    delay = DSH_SOURCE_RETRY_BACKOFF_SECONDS
    last: Exception | None = None
    for attempt in range(max(1, DSH_SOURCE_ATTEMPTS)):
        try:
            return fetch_bytes(url, limit=MAX_INDEX_BYTES, total_timeout=budget)
        except SourceUnreachableError as exc:
            last = exc
            if "timeout" in str(exc):
                break
            if attempt + 1 < DSH_SOURCE_ATTEMPTS:
                time.sleep(delay)
                delay *= 2
    assert last is not None
    raise last


def _dsh_index_cache_path(cache_dir: Path, url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return cache_dir / f"{digest}.json"


def _read_dsh_index_cache(cache_dir: Path, url: str) -> bytes | None:
    path = _dsh_index_cache_path(cache_dir, url)
    try:
        return path.read_bytes()
    except OSError:
        return None


def _write_dsh_index_cache(cache_dir: Path, url: str, body: bytes) -> None:
    path = _dsh_index_cache_path(cache_dir, url)
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{threading.get_ident()}.tmp")
        tmp.write_bytes(body)
        os.replace(tmp, path)
    except OSError as exc:  # a cache miss must never fail the read
        logger.debug("could not write DSH index cache for %s: %s", url, exc)


def _cached_dsh_index_entries(url: str, body: bytes, *, language: str) -> list[Any]:
    """Rebuild catalog rows from a cached index body."""

    from octop.infra.plugins.market import DshSource

    return DshSource(url, language=language, transport=lambda _target: body).fetch_index()


def _dsh_source(
    url: str,
    *,
    language: str,
    cache_dir: Path | None = None,
    budget: float | None = None,
    allow_cache: bool = False,
) -> Any:
    """Build a ``DshSource``; the npm registry is overridable for fixtures.

    ``cache_dir`` stores the raw index body of a successful read. With
    ``allow_cache`` a failed read falls back to that body, which is what keeps
    install/upgrade working while a mirror is slow; the catalog listing asks for
    live reads instead so it can report the source as ``stale``.
    """

    from octop.infra.plugins.market import DshSource
    from octop.infra.plugins.market.download import fetch_bytes

    # ``DshSource`` treats a ``Path`` as an offline file and a string as a URL,
    # so an absolute path must not be passed through as a string.
    index: str | Path = url
    if urlparse(url).scheme not in {"http", "https"}:
        index = Path(url)

    def transport(target: str) -> bytes:
        # Only the index itself gets a total budget: a public index can weigh
        # several megabytes, and one slow host must not stall a page load.
        if target != url:
            return fetch_bytes(target)
        try:
            body = _fetch_index_bytes(url, budget=budget or dsh_source_budget(url))
        except Exception:
            if not allow_cache or cache_dir is None:
                raise
            # Installing from a cached catalog beats failing because a mirror
            # is slow right now; the background refresh updates the cache.
            cached = _read_dsh_index_cache(cache_dir, url)
            if cached is None:
                raise
            logger.warning("DSH index %s unreadable; serving cached body", url)
            return cached
        if cache_dir is not None:
            _write_dsh_index_cache(cache_dir, url, body)
        return body

    registry = os.environ.get("OCTOP_DSH_NPM_REGISTRY", "").strip()
    if registry:
        return DshSource(index, language=language, npm_registry=registry, transport=transport)
    return DshSource(index, language=language, transport=transport)


class _TolerantDshSource(Source):
    """A DSH source whose read failure means "no rows", not "abort".

    ``MarketplaceIndex.fetch`` already skips a source whose rows were all
    rejected, but a transport failure escapes and aborts install/upgrade. A
    slow mirror must not block installing from a healthy one, so the failure is
    recorded here and the source simply contributes nothing.
    """

    # Only DshSource instances are wrapped; keep the kind visible to the
    # marketplace pipeline (``Source.source_id`` is a ClassVar).
    source_id = PluginKind.DSH

    def __init__(self, source: Any, failures: list[Exception]) -> None:
        super().__init__()
        self._source = source
        self._failures = failures
        self.index_label = source.index_label

    @property
    def manifest_names(self) -> tuple[str, ...]:
        return tuple(self._source.manifest_names)

    def fetch_index(self) -> list[Any]:
        try:
            return list(self._source.fetch_index())
        except Exception as exc:  # one slow mirror is not a broken mirror
            self._failures.append(exc)
            return []

    def _validate_manifest(
        self,
        entry: Any,
        release: Any,
        manifest: Any,
        content_root: Path,
    ) -> str | None:
        result = self._source._validate_manifest(entry, release, manifest, content_root)
        return None if result is None else str(result)

    def install(self, entry: Any, dest: Path, *, release: Any = None) -> Any:
        return self._source.install(entry, dest, release=release)

    def verify(self, entry: Any, payload: Any, *, release: Any = None) -> None:
        self._source.verify(entry, payload, release=release)


def normalize_dsh_source(raw: str) -> str:
    """Validate one user-supplied DSH index address.

    Accepts ``http(s)://`` URLs and existing absolute local paths (offline
    fixtures). Everything else is refused with a typed error instead of being
    stored and failing later during a background refresh.
    """

    value = str(raw or "").strip()
    if not value:
        raise OctopError(
            ErrorCode.PLUGIN_MARKET_SOURCE_INVALID,
            "DSH 索引地址不能为空",
            details={"url": value},
        )
    parsed = urlparse(value)
    if parsed.scheme in ("http", "https"):
        if not parsed.netloc:
            raise OctopError(
                ErrorCode.PLUGIN_MARKET_SOURCE_INVALID,
                f"DSH 索引地址缺少主机名：{value}",
                details={"url": value},
            )
        return value
    path = Path(value).expanduser()
    if not path.is_absolute() or not path.is_file():
        raise OctopError(
            ErrorCode.PLUGIN_MARKET_SOURCE_INVALID,
            "DSH 索引地址必须是 http(s) URL 或存在的绝对文件路径",
            details={"url": value},
        )
    return str(path)


def _read_dsh_sources(config_path: Path) -> list[str] | None:
    """Read ``plugin_market.dsh_sources`` without dropping unrelated keys.

    ``None`` means the user never configured the section, which is what lets
    :meth:`PluginManager.dsh_source_urls` fall back to the built-in indexes. An
    explicitly stored list (including ``[]``) is authoritative.
    """

    try:
        data = read_json_object(config_path)
    except JsonFileCorruptError as exc:
        raise corrupt_config_error(exc.path, exc.detail) from exc
    if not isinstance(data, dict):
        return None
    section = data.get("plugin_market")
    raw = section.get("dsh_sources") if isinstance(section, dict) else None
    if not isinstance(raw, list):
        return None
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip() and item.strip() not in out:
            out.append(item.strip())
    return out[:DSH_SOURCES_LIMIT]


def _write_dsh_sources(config_path: Path, urls: list[str]) -> None:
    """Merge ``plugin_market.dsh_sources`` into ``config.json`` atomically."""

    try:
        data = read_json_object(config_path)
    except JsonFileCorruptError as exc:
        raise corrupt_config_error(exc.path, exc.detail) from exc
    payload = dict(data or {})
    section = payload.get("plugin_market")
    merged = dict(section) if isinstance(section, dict) else {}
    merged["dsh_sources"] = list(urls)
    payload["plugin_market"] = merged
    write_json_atomic(config_path, payload)


def _dsh_entry_matches(entry: Any, needle: str) -> bool:
    """Case-insensitive substring match over name, description and id."""

    return any(
        needle in str(value or "").casefold()
        for value in (
            getattr(entry, "name", ""),
            getattr(entry, "description", ""),
            getattr(entry, "plugin_id", ""),
        )
    )
