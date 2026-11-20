"""Release manifest loading for the read-only update check API.

The manifest is the single source of truth for "what is the latest release and
which artifacts belong to it".  This module only *reads* it: downloading and
installing stay in :mod:`octop.infra.setup.self_update`.

Configuration (environment):

``OCTOP_RELEASE_MANIFEST_FILE``
    Path to a local manifest JSON file (also useful in tests / air-gapped hosts).
``OCTOP_RELEASE_MANIFEST_URL``
    HTTP(S) URL of the manifest. Ignored when the file variable is set.
``OCTOP_RELEASE_MANIFEST_TTL_S``
    In-memory cache TTL in seconds (default 600, clamped to 0..86400).
``OCTOP_RELEASE_MANIFEST_TIMEOUT_S``
    Network timeout in seconds (default 6, clamped to 1..30).

When neither source is configured, callers get ``manifest_not_configured``
instead of an exception that would turn into a 500.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.client import HTTPException

from octop.infra.setup.self_update import is_valid_version

MANIFEST_FILE_ENV = "OCTOP_RELEASE_MANIFEST_FILE"
MANIFEST_URL_ENV = "OCTOP_RELEASE_MANIFEST_URL"
MANIFEST_TTL_ENV = "OCTOP_RELEASE_MANIFEST_TTL_S"
MANIFEST_TIMEOUT_ENV = "OCTOP_RELEASE_MANIFEST_TIMEOUT_S"

DEFAULT_TTL_S = 600.0
DEFAULT_TIMEOUT_S = 6.0
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
CHANNELS: tuple[str, ...] = ("stable", "beta")

_SCHEMA_VERSION = 1
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)


class ManifestError(Exception):
    """A manifest read/parse failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ReleaseArtifact:
    platform: str
    arch: str
    kind: str | None
    filename: str
    url: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class ReleaseManifest:
    version: str
    channel: str
    artifacts: tuple[ReleaseArtifact, ...]
    product: str | None = None
    notes: str | None = None
    published_at: str | None = None
    minimum_supported_version: str | None = None


@dataclass(frozen=True)
class ManifestSnapshot:
    manifest: ReleaseManifest | None
    source: str | None
    cached: bool
    stale: bool
    error_code: str | None = None
    error: str | None = None


_cache_lock = threading.Lock()
_cache: tuple[float, ReleaseManifest, str] | None = None


def clear_manifest_cache() -> None:
    """Drop the in-memory manifest cache (tests and explicit refreshes)."""
    global _cache
    with _cache_lock:
        _cache = None


def manifest_origin() -> tuple[str, str] | None:
    """Return ``("file" | "url", value)`` from the environment, if configured."""
    file_path = (os.environ.get(MANIFEST_FILE_ENV) or "").strip()
    if file_path:
        return ("file", file_path)
    url = (os.environ.get(MANIFEST_URL_ENV) or "").strip()
    if url:
        return ("url", url)
    return None


def _bounded_float(raw: str | None, *, default: float, low: float, high: float) -> float:
    try:
        value = float((raw or "").strip())
    except ValueError:
        return default
    return min(max(value, low), high)


def cache_ttl_seconds() -> float:
    return _bounded_float(
        os.environ.get(MANIFEST_TTL_ENV), default=DEFAULT_TTL_S, low=0.0, high=86400.0
    )


def fetch_timeout_seconds() -> float:
    return _bounded_float(
        os.environ.get(MANIFEST_TIMEOUT_ENV), default=DEFAULT_TIMEOUT_S, low=1.0, high=30.0
    )


def _require_text(entry: dict[str, object], key: str, *, field: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManifestError("manifest_invalid", f"{field}.{key} must be a non-empty string")
    return value.strip()


def _optional_text(entry: dict[str, object], key: str, *, field: str) -> str | None:
    value = entry.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ManifestError("manifest_invalid", f"{field}.{key} must be a string")
    return value.strip() or None


def _parse_artifact(raw: object, index: int) -> ReleaseArtifact:
    field = f"artifacts[{index}]"
    if not isinstance(raw, dict):
        raise ManifestError("manifest_invalid", f"{field} must be an object")
    platform = _require_text(raw, "platform", field=field)
    arch = _require_text(raw, "arch", field=field)
    filename = _require_text(raw, "filename", field=field)
    url = _require_text(raw, "url", field=field)
    if not _SCHEME_RE.match(url):
        raise ManifestError("manifest_invalid", f"{field}.url must be an HTTP(S) URL")
    sha256 = _require_text(raw, "sha256", field=field).lower()
    if not _SHA256_RE.match(sha256):
        raise ManifestError("manifest_invalid", f"{field}.sha256 must be 64 hex characters")
    size_bytes = raw.get("size_bytes")
    if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes <= 0:
        raise ManifestError("manifest_invalid", f"{field}.size_bytes must be a positive integer")
    kind = _optional_text(raw, "kind", field=field)
    return ReleaseArtifact(
        platform=platform,
        arch=arch,
        kind=kind,
        filename=filename,
        url=url,
        sha256=sha256,
        size_bytes=size_bytes,
    )


def validate_manifest(data: object) -> ReleaseManifest:
    """Validate a decoded manifest and return the typed projection.

    Raises :class:`ManifestError` with ``manifest_invalid`` for any missing or
    malformed field.  The release script uses the same rules so the API never
    accepts a manifest the publisher could not build.
    """
    if not isinstance(data, dict):
        raise ManifestError("manifest_invalid", "manifest must be a JSON object")
    schema_version = data.get("schema_version")
    if schema_version != _SCHEMA_VERSION:
        raise ManifestError(
            "manifest_invalid", f"schema_version must be {_SCHEMA_VERSION}"
        )

    version = _require_text(data, "version", field="manifest")
    if not is_valid_version(version):
        raise ManifestError("manifest_invalid", "version must be a PEP 440 version")

    channel = _require_text(data, "channel", field="manifest").lower()
    if channel not in CHANNELS:
        raise ManifestError("manifest_invalid", "channel must be stable or beta")

    raw_artifacts = data.get("artifacts")
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        raise ManifestError("manifest_invalid", "artifacts must be a non-empty list")

    artifacts: list[ReleaseArtifact] = []
    seen_files: set[str] = set()
    seen_urls: set[str] = set()
    for index, raw in enumerate(raw_artifacts):
        artifact = _parse_artifact(raw, index)
        if artifact.filename in seen_files:
            raise ManifestError("manifest_invalid", f"duplicate artifact filename: {artifact.filename}")
        if artifact.url in seen_urls:
            raise ManifestError("manifest_invalid", f"duplicate artifact url: {artifact.url}")
        seen_files.add(artifact.filename)
        seen_urls.add(artifact.url)
        artifacts.append(artifact)

    minimum = _optional_text(data, "minimum_supported_version", field="manifest")
    if minimum is not None and not is_valid_version(minimum):
        raise ManifestError(
            "manifest_invalid", "minimum_supported_version must be a PEP 440 version"
        )

    return ReleaseManifest(
        version=version,
        channel=channel,
        artifacts=tuple(artifacts),
        product=_optional_text(data, "product", field="manifest"),
        notes=_optional_text(data, "notes", field="manifest"),
        published_at=_optional_text(data, "published_at", field="manifest"),
        minimum_supported_version=minimum,
    )


def _decode(payload: bytes) -> ReleaseManifest:
    if len(payload) > MAX_MANIFEST_BYTES:
        raise ManifestError(
            "manifest_invalid", f"manifest exceeds {MAX_MANIFEST_BYTES} bytes"
        )
    try:
        data = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestError("manifest_invalid", f"manifest is not valid JSON: {exc}") from exc
    return validate_manifest(data)


def _read_file(path: str) -> tuple[ReleaseManifest, str]:
    try:
        with open(path, "rb") as handle:
            payload = handle.read(MAX_MANIFEST_BYTES + 1)
    except OSError as exc:
        raise ManifestError("manifest_unreachable", f"cannot read manifest file: {exc}") from exc
    return _decode(payload), "local-file"


def _is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    name = host.strip("[]").lower()
    if name in {"localhost", "::1"}:
        return True
    parts = name.split(".")
    return len(parts) == 4 and parts[0] == "127" and all(p.isdigit() for p in parts)


def _read_url(url: str) -> tuple[ReleaseManifest, str]:
    if not _SCHEME_RE.match(url):
        raise ManifestError(
            "manifest_invalid", "OCTOP_RELEASE_MANIFEST_URL must be an HTTP(S) URL"
        )
    parsed = urllib.parse.urlsplit(url)
    # Local manifests must bypass the system proxy, same rule as local models.
    handlers: list[urllib.request.BaseHandler] = []
    if _is_loopback_host(parsed.hostname):
        handlers.append(urllib.request.ProxyHandler({}))
    opener = urllib.request.build_opener(*handlers)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "octop-release-check/1.0", "Accept": "application/json"},
    )
    try:
        with opener.open(request, timeout=fetch_timeout_seconds()) as response:
            payload = response.read(MAX_MANIFEST_BYTES + 1)
    except (urllib.error.URLError, HTTPException, TimeoutError, OSError) as exc:
        raise ManifestError("manifest_unreachable", f"cannot reach manifest: {exc}") from exc
    return _decode(payload), parsed.hostname or "remote"


def _read_manifest(origin: tuple[str, str]) -> tuple[ReleaseManifest, str]:
    kind, value = origin
    if kind == "file":
        return _read_file(value)
    return _read_url(value)


def load_manifest(*, force: bool = False) -> ManifestSnapshot:
    """Return the cached manifest, refreshing it when the TTL expires.

    Network/file failures never raise when a cached copy exists: the stale copy
    is returned with ``stale=True`` plus the failure code so the UI can explain
    why the data may be old.
    """
    global _cache
    origin = manifest_origin()
    if origin is None:
        raise ManifestError(
            "manifest_not_configured",
            f"set {MANIFEST_FILE_ENV} or {MANIFEST_URL_ENV} to enable release checks",
        )

    with _cache_lock:
        now = time.monotonic()
        if not force and _cache is not None:
            cached_at, cached_manifest, cached_source = _cache
            if now - cached_at < cache_ttl_seconds():
                return ManifestSnapshot(
                    manifest=cached_manifest,
                    source=cached_source,
                    cached=True,
                    stale=False,
                )
        try:
            manifest, source = _read_manifest(origin)
        except ManifestError as exc:
            if _cache is not None:
                _cached_at, cached_manifest, cached_source = _cache
                return ManifestSnapshot(
                    manifest=cached_manifest,
                    source=cached_source,
                    cached=True,
                    stale=True,
                    error_code=exc.code,
                    error=exc.message,
                )
            raise
        _cache = (now, manifest, source)
        return ManifestSnapshot(manifest=manifest, source=source, cached=False, stale=False)
