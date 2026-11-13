"""Failures raised by the unified plugin market pipeline.

Error codes reuse the runtime contract wherever a matching code exists:
manifest/validation failures are ``PLUGIN_MANIFEST_INVALID`` and downgrade
refusals are ``PLUGIN_VERSION_CONFLICT``. The market
adds stable codes the contract does not define yet so callers can separate a
transient outage from a tampered package:

* ``PLUGIN_SOURCE_UNREACHABLE`` -- catalog or artifact could not be read.
* ``PLUGIN_CHECKSUM_MISMATCH`` -- bytes do not match the published digest.
* ``PLUGIN_RELEASE_NOT_FOUND`` -- requested version is not listed.
* ``PLUGIN_MARKET_UNAVAILABLE`` -- the octop portal call failed.
* ``PLUGIN_DEPENDENCY_IN_USE`` -- an uninstall would break an installed plugin.
* ``PLUGIN_CONFIG_SCHEMA_CHANGED`` -- a downgrade would strand stored config.
* ``PLUGIN_CAPABILITY_EXPANSION`` -- an upgrade grants capabilities the
  installed version did not declare and the caller did not confirm it.
* ``PLUGIN_INDEX_UNUSABLE`` -- a catalog's structure is broken, or every row in
  it was rejected, so the index lists nothing. Single bad rows never raise:
  they are collected by the source as ``RejectedEntry`` diagnostics.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Mapping, cast

from octop.infra.plugins.runtime.contract import (
    InvalidManifestError,
    PluginErrorCode,
    PluginRuntimeError,
    VersionConflictError,
)

if TYPE_CHECKING:
    from octop.infra.plugins.market.models import RejectedEntry

__all__ = [
    "CapabilityExpansionError",
    "ChecksumMismatchError",
    "ConfigSchemaChangedError",
    "DependencyConstraintError",
    "DependencyInUseError",
    "IndexFormatError",
    "IndexUnusableError",
    "InstallConflictError",
    "MarketError",
    "MarketErrorCode",
    "PayloadError",
    "ReleaseNotFound",
    "SourceUnreachableError",
    "UnsupportedSourceError",
]


class MarketErrorCode(StrEnum):
    """Stable market-side codes that are not part of the runtime contract yet."""

    MARKET_UNAVAILABLE = "PLUGIN_MARKET_UNAVAILABLE"
    SOURCE_UNREACHABLE = "PLUGIN_SOURCE_UNREACHABLE"
    CHECKSUM_MISMATCH = "PLUGIN_CHECKSUM_MISMATCH"
    RELEASE_NOT_FOUND = "PLUGIN_RELEASE_NOT_FOUND"
    DEPENDENCY_IN_USE = "PLUGIN_DEPENDENCY_IN_USE"
    CONFIG_SCHEMA_CHANGED = "PLUGIN_CONFIG_SCHEMA_CHANGED"
    CAPABILITY_EXPANSION = "PLUGIN_CAPABILITY_EXPANSION"
    INDEX_UNUSABLE = "PLUGIN_INDEX_UNUSABLE"


MarketCode = PluginErrorCode | MarketErrorCode


class MarketError(PluginRuntimeError):
    """Base class for market failures with an optional market-specific code."""

    code = PluginErrorCode.LOAD_FAILED

    def __init__(
        self,
        message: str,
        *,
        code: MarketCode | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        payload = dict(details or {})
        if code is not None:
            payload.setdefault("market_code", code.value)
            self.code = cast(PluginErrorCode, code)
        super().__init__(message, details=payload)


class IndexFormatError(InvalidManifestError):
    """A catalog does not follow the format documented for its source."""

    def __init__(self, message: str, *, path: str = "") -> None:
        payload: dict[str, Any] = {"path": path} if path else {}
        super().__init__(f"{message} at {path}" if path else message, details=payload)
        self.path = path


class IndexUnusableError(MarketError):
    """One catalog lists nothing: its structure is broken or every row was rejected.

    ``rejected`` holds one :class:`~octop.infra.plugins.market.models.RejectedEntry`
    per refused row. The message lists the first few with their reason and fix so
    the failure is actionable without a debugger; ``details["rejected"]`` keeps
    the full report for machines.
    """

    _MAX_LISTED = 10

    def __init__(
        self,
        source: str,
        *,
        reason: str = "",
        rejected: Sequence["RejectedEntry"] = (),
    ) -> None:
        if rejected:
            header = f"索引 {source} 的 {len(rejected)} 个条目全部被拒绝，市场无法使用"
        else:
            header = f"索引 {source} 无法使用：{reason or '结构损坏'}"
        lines = [header]
        for entry in rejected[: self._MAX_LISTED]:
            label = entry.plugin_id or "<无 id>"
            lines.append(f"- [{label}] {entry.error_code}: {entry.reason}")
            lines.append(f"  建议：{entry.suggestion}")
        if len(rejected) > self._MAX_LISTED:
            lines.append(f"…还有 {len(rejected) - self._MAX_LISTED} 个被拒条目")
        super().__init__(
            "\n".join(lines),
            code=MarketErrorCode.INDEX_UNUSABLE,
            details={
                "source": source,
                "rejected": [
                    {
                        "plugin_id": entry.plugin_id,
                        "error_code": entry.error_code,
                        "reason": entry.reason,
                        "suggestion": entry.suggestion,
                        "raw": entry.raw,
                    }
                    for entry in rejected
                ],
            },
        )
        self.source = source
        self.rejected = tuple(rejected)


class ReleaseNotFound(MarketError):
    """The requested release is not listed by the catalog."""

    def __init__(self, plugin_id: str, version: str) -> None:
        super().__init__(
            f"plugin {plugin_id!r} does not list release {version!r}",
            code=MarketErrorCode.RELEASE_NOT_FOUND,
            details={"plugin_id": plugin_id, "version": version},
        )
        self.plugin_id = plugin_id
        self.version = version


class SourceUnreachableError(MarketError):
    """The catalog or the release archive could not be read."""

    def __init__(self, message: str, *, url: str = "") -> None:
        super().__init__(
            message,
            code=MarketErrorCode.SOURCE_UNREACHABLE,
            details={"url": url} if url else None,
        )
        self.url = url


class UnsupportedSourceError(SourceUnreachableError):
    """A release has no archive this pipeline can download."""


class PayloadError(InvalidManifestError):
    """Downloaded bytes are not a usable plugin payload."""


class ChecksumMismatchError(MarketError):
    """Downloaded bytes do not match the checksum published by the catalog."""

    def __init__(self, expected: str, actual: str) -> None:
        super().__init__(
            f"checksum mismatch: expected {expected}, got {actual}",
            code=MarketErrorCode.CHECKSUM_MISMATCH,
            details={"expected": expected, "actual": actual},
        )
        self.expected = expected
        self.actual = actual


class InstallConflictError(VersionConflictError):
    """An install would downgrade without an explicit force."""

    def __init__(
        self,
        message: str,
        *,
        plugin_id: str,
        installed_version: str,
        incoming_version: str,
    ) -> None:
        super().__init__(
            message,
            details={
                "plugin_id": plugin_id,
                "installed_version": installed_version,
                "incoming_version": incoming_version,
            },
        )
        self.plugin_id = plugin_id
        self.installed_version = installed_version
        self.incoming_version = incoming_version


class DependencyInUseError(MarketError):
    """Uninstalling this version would break another installed plugin."""

    def __init__(
        self,
        plugin_id: str,
        version: str,
        dependents: tuple[tuple[str, str, str], ...],
    ) -> None:
        """``dependents`` holds ``(plugin_id, version, constraint)`` triples."""
        listed = "、".join(
            f"{dep_id} {dep_version}（约束 {constraint}）"
            for dep_id, dep_version, constraint in dependents
        )
        super().__init__(
            f"无法卸载 {plugin_id} {version}：已安装的 {listed} 依赖它，"
            "请先卸载依赖方",
            code=MarketErrorCode.DEPENDENCY_IN_USE,
            details={
                "plugin_id": plugin_id,
                "version": version,
                "dependents": [
                    {
                        "plugin_id": dep_id,
                        "version": dep_version,
                        "constraint": constraint,
                    }
                    for dep_id, dep_version, constraint in dependents
                ],
            },
        )
        self.plugin_id = plugin_id
        self.version = version
        self.dependents = dependents


class DependencyConstraintError(VersionConflictError):
    """An upgrade would make another installed plugin's constraint fail."""

    def __init__(
        self,
        plugin_id: str,
        version: str,
        mismatched: tuple[tuple[str, str, str], ...],
    ) -> None:
        """``mismatched`` holds ``(plugin_id, version, constraint)`` triples."""
        listed = "、".join(
            f"{dep_id} {dep_version} 要求 {constraint}"
            for dep_id, dep_version, constraint in mismatched
        )
        super().__init__(
            f"无法升级 {plugin_id} 到 {version}：已安装的 {listed}，"
            "升级后不再满足，请先升级依赖方",
            details={
                "plugin_id": plugin_id,
                "version": version,
                "dependents": [
                    {
                        "plugin_id": dep_id,
                        "version": dep_version,
                        "constraint": constraint,
                    }
                    for dep_id, dep_version, constraint in mismatched
                ],
            },
        )
        self.plugin_id = plugin_id
        self.version = version
        self.mismatched = mismatched


class ConfigSchemaChangedError(MarketError):
    """A downgrade would replace the config schema and strand stored config."""

    def __init__(
        self,
        plugin_id: str,
        from_version: str,
        to_version: str,
        added: tuple[str, ...],
        removed: tuple[str, ...],
    ) -> None:
        changes: list[str] = []
        if added:
            changes.append("新增 " + "、".join(added))
        if removed:
            changes.append("移除 " + "、".join(removed))
        detail = "；".join(changes) or "结构不同"
        super().__init__(
            f"降级 {plugin_id} {from_version} → {to_version} 会改变配置 schema"
            f"（{detail}），为避免静默丢配置已拒绝；请先迁移配置再重试",
            code=MarketErrorCode.CONFIG_SCHEMA_CHANGED,
            details={
                "plugin_id": plugin_id,
                "from_version": from_version,
                "to_version": to_version,
                "added": list(added),
                "removed": list(removed),
            },
        )
        self.plugin_id = plugin_id
        self.from_version = from_version
        self.to_version = to_version
        self.added = added
        self.removed = removed


class CapabilityExpansionError(MarketError):
    """An upgrade grants capabilities the installed version did not declare."""

    def __init__(
        self,
        plugin_id: str,
        from_version: str,
        to_version: str,
        added: tuple[str, ...],
    ) -> None:
        listed = "、".join(added)
        super().__init__(
            f"升级 {plugin_id} {from_version} → {to_version} 会扩大能力（新增 {listed}），"
            "需要显式确认：allow_capability_expansion=True",
            code=MarketErrorCode.CAPABILITY_EXPANSION,
            details={
                "plugin_id": plugin_id,
                "from_version": from_version,
                "to_version": to_version,
                "added": list(added),
            },
        )
        self.plugin_id = plugin_id
        self.from_version = from_version
        self.to_version = to_version
        self.added = added
