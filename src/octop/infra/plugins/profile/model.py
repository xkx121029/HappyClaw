"""Profile data model: a named plugin composition, ready to persist as JSON.

A profile is deliberately declarative. It names the plugins a local owner wants
active, the per-plugin configuration handed to ``PluginLoader.activate``, the
capability switches applied on top of the envelope, and whether a plugin has to
load at startup (``eager``) or on first use (``lazy``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from octop.infra.plugins.runtime.contract import (
    CapabilityKind,
    InvalidManifestError,
    PermissionKind,
    split_plugin_id,
)

__all__ = [
    "LoadMode",
    "Profile",
    "ProfileEntry",
    "validate_profile_name",
]

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class LoadMode(StrEnum):
    """When a plugin is activated."""

    EAGER = "eager"
    LAZY = "lazy"


def validate_profile_name(name: str) -> str:
    """Return a cleaned profile name, rejecting anything unsafe as a filename.

    Names become ``profiles/<name>.json``, so path separators and traversal
    segments are refused at this boundary instead of reaching the filesystem.
    """

    cleaned = str(name or "").strip()
    if not cleaned:
        raise InvalidManifestError("组合名称不能为空", details={"profile": name})
    if _NAME_RE.match(cleaned) is None:
        raise InvalidManifestError(
            "组合名称只能包含字母、数字、点、下划线和连字符，且不超过 64 个字符",
            details={"profile": name},
        )
    return cleaned


def _capability_tuple(raw: Any) -> tuple[CapabilityKind, ...]:
    try:
        capabilities = tuple(CapabilityKind(str(item)) for item in raw)
    except ValueError as exc:
        raise InvalidManifestError(
            "组合条目里的能力开关不受支持",
            details={"capabilities": [str(item) for item in raw]},
        ) from exc
    if len(set(capabilities)) != len(capabilities):
        raise InvalidManifestError(
            "组合条目里的能力开关重复",
            details={"capabilities": [item.value for item in capabilities]},
        )
    return capabilities


def _permission_tuple(raw: Any) -> tuple[PermissionKind, ...]:
    try:
        permissions = tuple(PermissionKind(str(item)) for item in raw)
    except ValueError as exc:
        raise InvalidManifestError(
            "组合条目里的权限开关不受支持",
            details={"permissions": [str(item) for item in raw]},
        ) from exc
    if len(set(permissions)) != len(permissions):
        raise InvalidManifestError(
            "组合条目里的权限开关重复",
            details={"permissions": [item.value for item in permissions]},
        )
    return permissions


@dataclass(frozen=True, slots=True)
class ProfileEntry:
    """One plugin row inside a profile."""

    plugin_id: str
    config: Mapping[str, Any] = field(default_factory=dict)
    load: LoadMode = LoadMode.EAGER
    enabled: bool = True
    capabilities: tuple[CapabilityKind, ...] | None = None
    permissions: tuple[PermissionKind, ...] | None = None

    def __post_init__(self) -> None:
        try:
            split_plugin_id(self.plugin_id)
        except InvalidManifestError as exc:
            raise InvalidManifestError(
                "组合条目里的插件 id 不合法",
                details={"plugin_id": self.plugin_id},
            ) from exc
        if not isinstance(self.config, Mapping):
            raise InvalidManifestError(
                "插件配置必须是映射",
                details={"plugin_id": self.plugin_id},
            )
        if not isinstance(self.enabled, bool):
            raise InvalidManifestError(
                "enabled 必须是布尔值",
                details={"plugin_id": self.plugin_id},
            )
        object.__setattr__(self, "load", LoadMode(self.load))
        if self.capabilities is not None:
            object.__setattr__(self, "capabilities", _capability_tuple(self.capabilities))
        if self.permissions is not None:
            object.__setattr__(self, "permissions", _permission_tuple(self.permissions))
        object.__setattr__(self, "config", dict(self.config))

    @property
    def is_eager(self) -> bool:
        return self.enabled and self.load is LoadMode.EAGER

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "config": dict(self.config),
            "load": self.load.value,
            "enabled": self.enabled,
            "capabilities": (
                None
                if self.capabilities is None
                else [capability.value for capability in self.capabilities]
            ),
            "permissions": (
                None
                if self.permissions is None
                else [permission.value for permission in self.permissions]
            ),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ProfileEntry:
        plugin_id = str(raw.get("plugin_id") or "").strip()
        if not plugin_id:
            raise InvalidManifestError("组合条目缺少 plugin_id", details={"entry": dict(raw)})
        config = raw.get("config") or {}
        if not isinstance(config, Mapping):
            raise InvalidManifestError(
                "插件配置必须是映射",
                details={"plugin_id": plugin_id},
            )
        capabilities = raw.get("capabilities")
        if capabilities is not None and not isinstance(capabilities, (list, tuple)):
            raise InvalidManifestError(
                "能力开关必须是列表",
                details={"plugin_id": plugin_id},
            )
        permissions = raw.get("permissions")
        if permissions is not None and not isinstance(permissions, (list, tuple)):
            raise InvalidManifestError(
                "权限开关必须是列表",
                details={"plugin_id": plugin_id},
            )
        return cls(
            plugin_id=plugin_id,
            config=dict(config),
            load=LoadMode(str(raw.get("load") or LoadMode.EAGER.value)),
            enabled=bool(raw.get("enabled", True)),
            capabilities=None if capabilities is None else _capability_tuple(capabilities),
            permissions=None if permissions is None else _permission_tuple(permissions),
        )


@dataclass(frozen=True, slots=True)
class Profile:
    """A named, persistable plugin composition."""

    name: str
    entries: tuple[ProfileEntry, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", validate_profile_name(self.name))
        entries = tuple(self.entries)
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, ProfileEntry):
                raise InvalidManifestError(
                    "组合条目必须是 ProfileEntry",
                    details={"profile": self.name},
                )
            if entry.plugin_id in seen:
                raise InvalidManifestError(
                    "组合里出现重复插件",
                    details={"profile": self.name, "plugin_id": entry.plugin_id},
                )
            seen.add(entry.plugin_id)
        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "description", str(self.description or ""))

    def entry(self, plugin_id: str) -> ProfileEntry | None:
        for entry in self.entries:
            if entry.plugin_id == plugin_id:
                return entry
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "entries": [entry.to_dict() for entry in self.entries],
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Profile:
        name = str(raw.get("name") or "").strip()
        if not name:
            raise InvalidManifestError("组合文件缺少 name", details={"profile": raw.get("name")})
        rows = raw.get("entries") or []
        if not isinstance(rows, (list, tuple)):
            raise InvalidManifestError("组合的 entries 必须是列表", details={"profile": name})
        return cls(
            name=name,
            entries=tuple(ProfileEntry.from_dict(row) for row in rows),
            description=str(raw.get("description") or ""),
        )
