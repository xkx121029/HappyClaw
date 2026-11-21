"""The remote market portal as a normalized catalog source.

The portal returns ``{"success": true, "data": {"items": [...]}}`` from
``/api/market/plugins``. Each item already carries the newest release of one
plugin id::

    {"id", "version", "name", "description", "kind", "icon", "group",
     "requires", "download_url", "updated_at", "sha256"?}

Rows are normalized to canonical ``octop:<native-id>`` ids so an installed
envelope loads without rewriting. Reading the live catalog reuses
:mod:`octop.infra.market` unchanged; tests pass ``loader`` for offline use.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Mapping

from octop.infra.plugins.market.download import Transport, fetch_bytes
from octop.infra.plugins.market.errors import (
    IndexUnusableError,
    PayloadError,
    SourceUnreachableError,
)
from octop.infra.plugins.market.models import (
    Artifact,
    MarketEntry,
    PluginRelease,
    RejectedEntry,
)
from octop.infra.plugins.market.source import Source, manifest_text
from octop.infra.plugins.runtime.contract import (
    CapabilityKind,
    InvalidManifestError,
    PluginKind,
    PluginRequirement,
    canonical_plugin_id,
)

_INDEX_LABEL = "portal:/api/market/plugins"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_KIND_CAPABILITIES: dict[str, CapabilityKind] = {
    "tool": CapabilityKind.TOOL,
    "skill": CapabilityKind.SKILL,
    "hook": CapabilityKind.HOOK,
    "channel": CapabilityKind.CHANNEL,
    "provider": CapabilityKind.PROVIDER,
    "panel": CapabilityKind.PANEL,
    "service": CapabilityKind.SERVICE,
}

Loader = Callable[[], list[dict[str, Any]]]


def _default_loader() -> list[dict[str, Any]]:
    from octop.infra.market.errors import PortalMarketError
    from octop.infra.market.plugins import list_market_plugins

    try:
        return list_market_plugins()
    except PortalMarketError as exc:
        raise SourceUnreachableError(f"octop market unavailable: {exc}") from exc


class OctopSource(Source):
    """Catalog backed by the octop portal plugin index."""

    source_id = PluginKind.OCTOP
    manifest_names = ("plugin.yaml", "plugin.yml")

    def __init__(
        self,
        *,
        loader: Loader | None = None,
        transport: Transport | None = None,
        language: str = "zh",
    ) -> None:
        super().__init__(transport=transport or fetch_bytes)
        self._loader = loader
        self._language = language
        self._rejected: tuple[RejectedEntry, ...] = ()
        self.index_label = _INDEX_LABEL

    def fetch_index(self) -> list[MarketEntry]:
        """Normalize every portal row, isolating failures per row.

        One malformed row is recorded as a ``RejectedEntry`` and never hides the
        other plugins; the index only fails as a whole when its structure is
        broken or when every row was rejected (``IndexUnusableError``, with a
        readable per-row diagnosis).
        """
        items = self._loader() if self._loader is not None else _default_loader()
        if not isinstance(items, list):
            raise IndexUnusableError(
                self.index_label,
                reason=f"返回结构损坏：items 应为数组，实际是 {type(items).__name__}",
            )
        entries: list[MarketEntry] = []
        rejected: list[RejectedEntry] = []
        for item in items:
            try:
                entries.append(_normalize(item, self._language, self.index_label))
            except InvalidManifestError as exc:
                rejected.append(_rejection(item, exc))
        self._rejected = tuple(rejected)
        if not entries and rejected:
            raise IndexUnusableError(self.index_label, rejected=self._rejected)
        return entries

    @property
    def rejected(self) -> tuple[RejectedEntry, ...]:
        return self._rejected

    def _validate_manifest(
        self,
        entry: MarketEntry,
        release: PluginRelease,
        manifest: Mapping[str, Any],
        content_root: Path,
    ) -> str | None:
        plugin_id = manifest_text(manifest, "id")
        version = manifest_text(manifest, "version")
        if plugin_id != entry.native_id:
            raise PayloadError(
                f"package id {plugin_id!r} does not match catalog id {entry.native_id!r}"
            )
        if version != release.version:
            raise PayloadError(
                f"package version {version!r} does not match catalog version {release.version!r}"
            )
        declared = manifest_text(manifest, "entry")
        if declared:
            return declared
        if manifest_text(manifest, "kind") == "skill" and (content_root / "SKILL.md").is_file():
            return "SKILL.md"
        # The runtime contract requires a non-empty entry; octop skill-style
        # packages may omit it, so fall back to the manifest itself.
        return self.manifest_names[0]


def _normalize(item: Any, language: str, index_label: str) -> MarketEntry:
    """Turn one portal row into an entry; every refusal raises with a reason."""
    if not isinstance(item, Mapping):
        raise InvalidManifestError(
            "索引条目不是对象，无法解析",
            details={"field": "$", "type": type(item).__name__},
        )
    native_id = _text(item.get("id"))
    if not native_id:
        raise InvalidManifestError(
            "索引条目缺少 id", details={"field": "id", "raw": item.get("id")}
        )
    version = _text(item.get("version"))
    if not version:
        raise InvalidManifestError(
            f"索引条目 {native_id!r} 缺少 version", details={"field": "version"}
        )
    url = _text(item.get("download_url"))
    if not url:
        raise InvalidManifestError(
            f"索引条目 {native_id!r} 缺少 download_url", details={"field": "download_url"}
        )
    try:
        plugin_id = canonical_plugin_id(PluginKind.OCTOP, native_id)
    except InvalidManifestError as exc:
        raise InvalidManifestError(
            f"索引条目 id {native_id!r} 不是合法的插件 id：{exc.message}",
            details={"field": "id", "id": native_id},
        ) from exc
    kind = _text(item.get("kind")) or "tool"
    raw_requires = tuple(
        str(name).strip()
        for name in _as_list(item.get("requires"))
        if str(name).strip()
    )
    requirements = _requirements(raw_requires)
    ui = item.get("ui") if isinstance(item.get("ui"), dict) else None
    group = _text(item.get("group"))
    return MarketEntry(
        plugin_id=plugin_id,
        source=PluginKind.OCTOP,
        name=_pick_localized(item.get("name"), language) or native_id,
        description=_pick_localized(item.get("description"), language),
        capabilities=_capabilities(kind, ui),
        releases=(
            PluginRelease(
                version=version,
                artifact=Artifact(
                    url=url,
                    sha256=_checksum(item),
                    size=_size(item.get("size")),
                ),
                published_at=_published_at(item.get("updated_at")),
            ),
        ),
        requires=requirements,
        homepage=_text(item.get("homepage")) or None,
        icon=_text(item.get("icon")) or None,
        tags=tuple(part for part in (group,) if part),
        extra={
            "index_url": index_label,
            "origin": "happyclaw",
            "native_id": native_id,
            "group": group or None,
            "requires_raw": list(raw_requires),
            "python_requires": _python_requirements(item),
            "ui": ui,
            "runtime": "python",
        },
    )


def _rejection(item: Any, exc: InvalidManifestError) -> RejectedEntry:
    """Describe one refused row: who it was, why it failed, and how to fix it."""
    native_id = _text(item.get("id")) if isinstance(item, Mapping) else ""
    plugin_id: str | None = native_id or None
    if native_id:
        try:
            plugin_id = canonical_plugin_id(PluginKind.OCTOP, native_id)
        except InvalidManifestError:
            plugin_id = native_id
    raw: Any = dict(item) if isinstance(item, Mapping) else item
    return RejectedEntry(
        plugin_id=plugin_id,
        raw=raw,
        error_code=exc.code.value,
        reason=exc.message,
        suggestion=_suggestion(exc),
    )


def _suggestion(exc: InvalidManifestError) -> str:
    """A concrete repair hint in Chinese, derived from the rejection details."""
    details = exc.details
    spec = details.get("requires")
    if isinstance(spec, str):
        if isinstance(details.get("constraint"), str):
            return (
                f"把 requires 条目 {spec!r} 的版本约束改成 >=1.0.0、<2 或 "
                ">=1.0.0,<2.0.0 这类写法"
            )
        valid = details.get("valid")
        if isinstance(valid, list):
            prefixes = " / ".join(str(value) for value in valid)
            return (
                f"把 requires 条目 {spec!r} 的生态前缀改成 {prefixes} 之一"
                "（插件依赖必须带生态前缀）"
            )
        if "缺少生态前缀" in exc.message:
            return (
                f"把 {spec!r} 移到 python_requires（或 dependencies）；"
                "插件依赖写成 octop:<id> / dsh:<id>"
            )
        return f"把 requires 条目 {spec!r} 写成 octop:<id> 或 dsh:<id>，可带版本约束"
    field = details.get("field")
    if field == "id":
        return "把 id 改成只含字母、数字、_、-、. 的名称；确有缺失就补齐 id"
    if field == "version":
        return "补齐 version 字段（每行都要有该插件的最新版本号）"
    if field == "download_url":
        return "补齐 download_url 字段（指向该版本 zip 包的下载地址）"
    return (
        "按门户清单格式检查该条目：id / version / download_url 必填，"
        "requires 必须带生态前缀"
    )


def _python_requirements(item: Mapping[str, Any]) -> tuple[str, ...]:
    """Python package deps from the catalog; they never enter plugin ``requires``."""
    for key in ("python_requires", "dependencies"):
        raw = item.get(key)
        if isinstance(raw, str) and raw.strip():
            return (raw.strip(),)
        if isinstance(raw, list):
            values = tuple(str(value).strip() for value in raw if str(value).strip())
            if values:
                return values
    return ()


def _requirements(names: tuple[str, ...]) -> tuple[PluginRequirement, ...]:
    """Parse catalog ``requires`` entries; unparseable ones raise, never vanish.

    Every entry is a plugin dependency and must carry an ecosystem prefix:
    ``octop:mkt-base`` or ``dsh:weather``, optionally followed by a constraint
    (``octop:mkt-base>=1.0.0``). Bare names are rejected because the package
    manifest uses them for Python dependencies, not plugin ids.
    """
    requirements: list[PluginRequirement] = []
    seen: set[str] = set()
    for spec in names:
        requirement = _parse_requirement(spec)
        if requirement.plugin_id in seen:
            continue
        seen.add(requirement.plugin_id)
        requirements.append(requirement)
    return tuple(requirements)


def _parse_requirement(spec: str) -> PluginRequirement:
    text = spec.strip()
    name, constraint = _split_constraint(text)
    if ":" not in name:
        raise InvalidManifestError(
            f"requires 条目 {spec!r} 缺少生态前缀：插件依赖需要写成 octop:<id> 或 "
            "dsh:<id>；Python 依赖请写在 python_requires（或 dependencies）里",
            details={"requires": spec, "field": "requires"},
        )
    prefix, native = name.split(":", 1)
    try:
        kind = PluginKind(prefix)
    except ValueError:
        raise InvalidManifestError(
            f"requires 条目 {spec!r} 的生态前缀 {prefix!r} 不认识",
            details={"requires": spec, "valid": [item.value for item in PluginKind]},
        ) from None
    try:
        plugin_id = canonical_plugin_id(kind, native)
    except InvalidManifestError as exc:
        raise InvalidManifestError(
            f"requires 条目 {spec!r} 不是合法的插件 id：{exc.message}",
            details={"requires": spec},
        ) from exc
    try:
        return PluginRequirement(plugin_id, constraint)
    except InvalidManifestError as exc:
        raise InvalidManifestError(
            f"requires 条目 {spec!r} 的版本约束不合法：{exc.message}",
            details={"requires": spec, "constraint": constraint},
        ) from exc


def _split_constraint(text: str) -> tuple[str, str]:
    for index, char in enumerate(text):
        if char in "<>=^~!":
            return text[:index].strip(), text[index:].strip()
    return text, "*"



def _capabilities(kind: str, ui: Mapping[str, Any] | None) -> tuple[CapabilityKind, ...]:
    capabilities: list[CapabilityKind] = []
    mapped = _KIND_CAPABILITIES.get(kind)
    if mapped is not None:
        capabilities.append(mapped)
    if ui is not None and _text(ui.get("entry")):
        capabilities.append(CapabilityKind.PANEL)
    return tuple(dict.fromkeys(capabilities))


def _pick_localized(value: Any, language: str) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        zh = _text(value.get("zh"))
        en = _text(value.get("en"))
        return (zh or en) if language.lower().startswith("zh") else (en or zh)
    return ""


def _checksum(item: Mapping[str, Any]) -> str | None:
    for key in ("sha256", "checksum"):
        value = item.get(key)
        if isinstance(value, str):
            candidate = value.strip().lower().removeprefix("sha256:")
        elif isinstance(value, dict):
            algorithm = _text(value.get("algorithm") or value.get("type")).lower()
            if algorithm != "sha256":
                continue
            candidate = _text(value.get("value")).lower()
        else:
            continue
        if _SHA256_RE.fullmatch(candidate):
            return candidate
    return None


def _size(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def _published_at(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


__all__ = ["OctopSource"]
