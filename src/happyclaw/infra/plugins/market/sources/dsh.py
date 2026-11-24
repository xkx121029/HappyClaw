"""The DSH (DeepSeek Harness) plugin index as a normalized catalog source.

Format 1 indexes are plain JSON::

    {"format": 1, "title": {...}, "plugins": [
       {"name": "dsh-plugin-foo", "title": ..., "versions": [
          {"version": "1.0.0", "publishTimestamp": 1788000000,
           "source": {"type": "npm"},
           "engines": {"dsh": ">=0.2.0"}}]}]}

Rules enforced here follow the DSH index reference (``docs/user/guide/
plugin-market.zh.md`` and the index-format Agent Note):

* ``format`` is ``1``; ``title`` and every ``LocalizedText`` object carry a
  non-blank ``en`` string.
* ``name`` is a lowercase npm package name, unique inside the index.
* each ``version`` is an exact SemVer string, unique inside the plugin, with an
  integer ``publishTimestamp`` in ``[0, 10^11)``.
* ``source`` is ``{"type": "npm", "registry"?}`` or ``{"type": "git", "url",
  "commit", "path"?}``; other types reject the index.
* ``engines.dsh`` is a non-blank string.

Assumptions (also recorded in ``marketplace.md``):

* npm packages are downloaded from ``<registry>/<name>/-/<base>-<version>.tgz``.
* git releases download a commit archive: GitHub ``/archive/<sha>.zip``, or the
  GitLab ``/-/archive/<sha>/<repo>-<sha>.zip`` pattern for every other host.
* the scoped npm name ``@scope/name`` becomes the native id ``scope__name`` so
  it satisfies the runtime contract's native-id charset; the untouched package
  name is kept in entry metadata.
* ``engines.dsh`` is a runtime constraint, not a plugin dependency: it is
  surfaced in entry metadata and never placed in envelope ``requires``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from happyclaw.infra.plugins.market.download import (
    Transport,
    fetch_bytes,
    require_http_url,
)
from happyclaw.infra.plugins.market.errors import (
    IndexFormatError,
    PayloadError,
    SourceUnreachableError,
)
from happyclaw.infra.plugins.market.models import Artifact, MarketEntry, PluginRelease
from happyclaw.infra.plugins.market.source import Source, manifest_text
from happyclaw.infra.plugins.market.versions import is_exact_semver
from happyclaw.infra.plugins.runtime.contract import (
    InvalidManifestError,
    PluginKind,
    canonical_plugin_id,
)

DEFAULT_NPM_REGISTRY = "https://registry.npmjs.org"

_NPM_NAME_RE = re.compile(r"^(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]{0,213}$")
_HEX40_RE = re.compile(r"^[0-9a-f]{40}$")
_LOCALE_KEY_RE = re.compile(r"^[a-z]{2,8}(?:-[a-z0-9]{1,8})*$")
_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._@+-]+$")
_SEMVER_RANGE_CHARS_RE = re.compile(r"^[0-9A-Za-z.*+<>=|~^ -]+$")


class DshSource(Source):
    """Catalog backed by one DSH market index (URL or offline file)."""

    source_id = PluginKind.DSH
    manifest_names = ("package.json",)

    def __init__(
        self,
        index: str | Path,
        *,
        transport: Transport | None = None,
        language: str = "zh",
        npm_registry: str = DEFAULT_NPM_REGISTRY,
    ) -> None:
        super().__init__(transport=transport or fetch_bytes)
        self._index = index
        self._language = language
        self._npm_registry = npm_registry.rstrip("/")
        self.index_label = str(index) if isinstance(index, Path) else index

    def fetch_index(self) -> list[MarketEntry]:
        body = self._read_index()
        document = _decode(body, idx=self.index_label)
        return _normalize_index(
            document,
            language=self._language,
            npm_registry=self._npm_registry,
            index_label=self.index_label,
        )

    def _read_index(self) -> bytes:
        if isinstance(self._index, Path):
            try:
                return self._index.read_bytes()
            except OSError as exc:
                raise SourceUnreachableError(
                    f"dsh index is unreadable: {self._index}", url=str(self._index)
                ) from exc
        require_http_url(self._index, path="$.index")
        return self._transport(self._index)

    def _validate_manifest(
        self,
        entry: MarketEntry,
        release: PluginRelease,
        manifest: Mapping[str, Any],
        content_root: Path,
    ) -> str | None:
        del content_root
        package_name = _text(entry.extra.get("package_name"))
        name = manifest_text(manifest, "name")
        version = manifest_text(manifest, "version")
        if package_name and name != package_name:
            raise PayloadError(
                f"package name {name!r} does not match catalog name {package_name!r}"
            )
        if version != release.version:
            raise PayloadError(
                f"package version {version!r} does not match catalog version {release.version!r}"
            )
        bundle = manifest.get("dsh")
        if not isinstance(bundle, dict) or not bundle.get("bundle"):
            raise PayloadError("package does not declare dsh.bundle")
        return manifest_text(manifest, "main") or "index.js"

    def _nested_content_root(
        self, wrapper: Path, release: PluginRelease | None
    ) -> Path | None:
        sub_path = release.extra.get("git_path") if release is not None else None
        if isinstance(sub_path, str) and sub_path:
            candidate = wrapper / sub_path
            return candidate if candidate.is_dir() else None
        return None


def _decode(body: bytes, *, idx: str) -> Any:
    import json

    try:
        return json.loads(body.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise IndexFormatError("index is not valid json", path=idx) from exc


def _normalize_index(
    document: Any,
    *,
    language: str,
    npm_registry: str,
    index_label: str,
) -> list[MarketEntry]:
    if not isinstance(document, dict):
        raise IndexFormatError("index is not an object", path="$")
    if document.get("format") != 1:
        raise IndexFormatError("index format must be 1", path="$.format")
    _localized(document.get("title"), "$.title", language, required=True)
    plugins = document.get("plugins")
    if not isinstance(plugins, list):
        raise IndexFormatError("plugins must be an array", path="$.plugins")
    seen_names: set[str] = set()
    entries: list[MarketEntry] = []
    for position, raw in enumerate(plugins):
        path = f"$.plugins[{position}]"
        if not isinstance(raw, dict):
            raise IndexFormatError("plugin is not an object", path=path)
        package_name = _plugin_name(raw.get("name"), f"{path}.name")
        if package_name in seen_names:
            raise IndexFormatError(f"duplicate plugin name {package_name!r}", path=f"{path}.name")
        seen_names.add(package_name)
        plugin_id = _canonical_id(package_name, f"{path}.name")
        releases = _releases(
            raw.get("versions"),
            f"{path}.versions",
            package_name,
            npm_registry,
        )
        metadata = raw.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        labels = _string_list(metadata.get("labels"))
        keywords = _string_list(metadata.get("keywords"))
        category = _text(metadata.get("category"))
        tags = tuple(part for part in (category, *labels, *keywords) if part)
        entries.append(
            MarketEntry(
                plugin_id=plugin_id,
                source=PluginKind.DSH,
                name=_localized(raw.get("title"), f"{path}.title", language) or package_name,
                description=_localized(raw.get("description"), f"{path}.description", language),
                # DSH bundles declare their contributions in ``dsh.bundle`` at
                # install time; the index itself does not map to runtime
                # capabilities, so the envelope fills them from the package.
                capabilities=(),
                releases=tuple(releases),
                homepage=_optional_url(raw.get("homepage"), f"{path}.homepage"),
                icon=_icon(raw.get("icon"), f"{path}.icon"),
                tags=tags,
                extra={
                    "index_url": index_label,
                    "origin": "dsh",
                    "native_id": _native_id(package_name),
                    "package_name": package_name,
                    "metadata": metadata,
                    "runtime": "node",
                },
            )
        )
    return entries


def _releases(raw: Any, path: str, package_name: str, npm_registry: str) -> list[PluginRelease]:
    if not isinstance(raw, list) or not raw:
        raise IndexFormatError("versions must be a non-empty array", path=path)
    releases: list[PluginRelease] = []
    seen: set[str] = set()
    for position, item in enumerate(raw):
        item_path = f"{path}[{position}]"
        if not isinstance(item, dict):
            raise IndexFormatError("version is not an object", path=item_path)
        version = item.get("version")
        if not isinstance(version, str) or not is_exact_semver(version):
            raise IndexFormatError("version must be an exact semver string", path=f"{item_path}.version")
        if version in seen:
            raise IndexFormatError(f"duplicate version {version!r}", path=f"{item_path}.version")
        seen.add(version)
        timestamp = item.get("publishTimestamp")
        if isinstance(timestamp, bool) or not isinstance(timestamp, int) or not 0 <= timestamp < 10**11:
            raise IndexFormatError(
                "publishTimestamp must be an integer in [0, 10^11)",
                path=f"{item_path}.publishTimestamp",
            )
        engines = item.get("engines")
        if not isinstance(engines, dict):
            raise IndexFormatError("engines must be an object", path=f"{item_path}.engines")
        dsh_range = engines.get("dsh")
        if not isinstance(dsh_range, str) or not dsh_range.strip():
            raise IndexFormatError("engines.dsh must be a non-blank string", path=f"{item_path}.engines.dsh")
        if _SEMVER_RANGE_CHARS_RE.fullmatch(dsh_range.strip()) is None:
            raise IndexFormatError("engines.dsh is not a semver range", path=f"{item_path}.engines.dsh")
        artifact, extra = _artifact(
            item.get("source"),
            package_name,
            version,
            f"{item_path}.source",
            npm_registry,
        )
        releases.append(
            PluginRelease(
                version=version,
                artifact=artifact,
                published_at=timestamp,
                requires={"dsh": dsh_range.strip()},
                extra=extra,
            )
        )
    return releases


def _artifact(
    raw: Any,
    package_name: str,
    version: str,
    path: str,
    npm_registry: str,
) -> tuple[Artifact, dict[str, Any]]:
    if not isinstance(raw, dict):
        raise IndexFormatError("source must be an object", path=path)
    kind = raw.get("type")
    if kind == "npm":
        registry = raw.get("registry")
        base = npm_registry
        if registry is not None:
            if not isinstance(registry, str):
                raise IndexFormatError("registry must be a url string", path=f"{path}.registry")
            require_http_url(registry, path=f"{path}.registry")
            base = registry.rstrip("/")
        basename = package_name.rsplit("/", maxsplit=1)[-1]
        return (
            Artifact(
                url=f"{base}/{package_name}/-/{basename}-{version}.tgz",
                media_type="application/gzip",
            ),
            {"npm_registry": base},
        )
    if kind == "git":
        url = raw.get("url")
        commit = raw.get("commit")
        sub_path = raw.get("path")
        if not isinstance(url, str) or urlparse(url).scheme != "https":
            raise IndexFormatError("git url must be an https url", path=f"{path}.url")
        parsed = urlparse(url)
        segments = [part for part in parsed.path.split("/") if part]
        if len(segments) < 2 or parsed.path.endswith("/"):
            raise IndexFormatError("git url must have at least two path segments", path=f"{path}.url")
        if parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise IndexFormatError("git url must not carry credentials, query or fragment", path=f"{path}.url")
        if url.endswith((".tgz", ".tar.gz")):
            raise IndexFormatError("git url must not point at a tarball", path=f"{path}.url")
        if not isinstance(commit, str) or _HEX40_RE.fullmatch(commit) is None:
            raise IndexFormatError("git commit must be a 40-char lowercase sha", path=f"{path}.commit")
        if sub_path is not None:
            if not isinstance(sub_path, str) or not _valid_sub_path(sub_path):
                raise IndexFormatError("git path is not a relative directory", path=f"{path}.path")
        return (
            Artifact(url=_git_archive_url(url, commit), media_type="application/zip"),
            {"git_url": url, "git_commit": commit, "git_path": sub_path},
        )
    raise IndexFormatError("source.type must be npm or git", path=f"{path}.type")


def _git_archive_url(url: str, commit: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    segments = path.split("/")
    if parsed.hostname == "github.com" and len(segments) == 2:
        return f"https://github.com/{path}/archive/{commit}.zip"
    repo = segments[-1].removesuffix(".git")
    return f"{url.rstrip('/').removesuffix('.git')}/-/archive/{commit}/{repo}-{commit}.zip"


def _valid_sub_path(value: str) -> bool:
    segments = value.split("/")
    return bool(segments) and all(
        segment not in {".", ".."} and _PATH_SEGMENT_RE.fullmatch(segment) is not None
        for segment in segments
    )


def _plugin_name(value: Any, path: str) -> str:
    if not isinstance(value, str) or _NPM_NAME_RE.fullmatch(value.strip()) is None:
        raise IndexFormatError("name must be a lowercase npm package name", path=path)
    return value.strip()


def _native_id(package_name: str) -> str:
    """Map an npm name to the contract's native-id charset."""
    return package_name.removeprefix("@").replace("/", "__")


def _canonical_id(package_name: str, path: str) -> str:
    try:
        return canonical_plugin_id(PluginKind.DSH, _native_id(package_name))
    except InvalidManifestError as exc:
        raise IndexFormatError(str(exc), path=path) from exc


def _localized(value: Any, path: str, language: str, *, required: bool = False) -> str:
    if value is None:
        if required:
            raise IndexFormatError("localized text is required", path=path)
        return ""
    if isinstance(value, str):
        if not value.strip():
            if required:
                raise IndexFormatError("localized text is blank", path=path)
            return ""
        return value.strip()
    if not isinstance(value, dict):
        raise IndexFormatError("localized text must be a string or object", path=path)
    for key, text in value.items():
        if not isinstance(key, str) or _LOCALE_KEY_RE.fullmatch(key) is None:
            raise IndexFormatError(f"invalid locale key {key!r}", path=f"{path}.{key}")
        if not isinstance(text, str) or not text.strip():
            raise IndexFormatError("localized strings must be non-blank", path=f"{path}.{key}")
    english = value.get("en")
    if not isinstance(english, str) or not english.strip():
        raise IndexFormatError("localized text requires en", path=path)
    if language.lower().startswith("zh"):
        chinese = value.get("zh")
        if isinstance(chinese, str) and chinese.strip():
            return chinese.strip()
    return english.strip()


def _optional_url(value: Any, path: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise IndexFormatError("url must be a string", path=path)
    require_http_url(value, path=path)
    return value.strip()


def _icon(value: Any, path: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    if value.startswith("data:"):
        return value
    require_http_url(value, path=path)
    return value.strip()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""
