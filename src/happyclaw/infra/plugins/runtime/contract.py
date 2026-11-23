"""Unified plugin runtime shared by the Octop and DSH adapters.

The contract in this module is deliberately stdlib-only: the Octop host, the
DSH manifest adapters, and the integration API layer all import it, so it must
not depend on ``happyclaw-harness``, PyYAML, or the DSH TypeScript runtime.

Design notes
------------
* ``PluginEnvelope.id`` is the canonical, globally unique id. Adapters prefix
  the ecosystem-native id (``octop:demo-toolkit``, ``dsh:tool-bash``) because
  both ecosystems use short, collision-prone ids. The native id stays available
  through ``PluginEnvelope.native_id`` and ``metadata["native_id"]``.
* ``requires`` describes *plugin* dependencies (id + version constraint), not
  Python/npm packages. Package requirements stay in the ecosystem-specific
  manifest and are surfaced through ``metadata`` when needed.
* Error codes are local to this package on purpose. Mapping them to the host's
  ``happyclaw.infra.errors.ErrorCode``/i18n happens at the API boundary, so adding
  a plugin error never changes unrelated locales.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "CAPABILITY_KINDS",
    "PERMISSION_KINDS",
    "ActivationContext",
    "CapabilityKind",
    "InvalidManifestError",
    "MissingDependencyError",
    "PermissionKind",
    "PluginEnvelope",
    "PluginErrorCode",
    "PluginHandle",
    "PluginKind",
    "PluginLoadError",
    "PluginLoader",
    "PluginRequirement",
    "PluginRuntimeError",
    "PluginSource",
    "PluginSourceKind",
    "SandboxDeniedError",
    "VersionConflictError",
    "canonical_plugin_id",
    "parse_permission_list",
    "split_plugin_id",
    "version_satisfies",
]


class PluginKind(StrEnum):
    """Ecosystem a plugin comes from."""

    OCTOP = "octop"
    DSH = "dsh"


class PluginSourceKind(StrEnum):
    """Where an envelope was discovered."""

    LOCAL = "local"
    MARKET = "market"


class CapabilityKind(StrEnum):
    """What a plugin contributes to the host."""

    TOOL = "tool"
    SKILL = "skill"
    PROVIDER = "provider"
    PANEL = "panel"
    CHANNEL = "channel"
    HOOK = "hook"
    SERVICE = "service"


CAPABILITY_KINDS: frozenset[str] = frozenset(kind.value for kind in CapabilityKind)


class PermissionKind(StrEnum):
    """What a plugin may touch outside its own state.

    This is deliberately *not* the capability vocabulary above. Capabilities say
    what a plugin contributes to the host (a tool, a panel, a provider); these
    permissions say what the sandbox may let it touch. One is never derived from
    the other: a ``tool`` capability implies no filesystem or network access,
    and a declared ``network`` permission does not make the plugin a provider.
    """

    FS_READ = "fs.read"
    FS_WRITE = "fs.write"
    EXEC = "exec"
    NETWORK = "network"


PERMISSION_KINDS: frozenset[str] = frozenset(kind.value for kind in PermissionKind)


class PluginErrorCode(StrEnum):
    """Stable error codes for the plugin runtime.

    These strings are part of the cross-line contract; do not rename them
    without coordinating with the adapters and the API layer.
    """

    MANIFEST_INVALID = "PLUGIN_MANIFEST_INVALID"
    DEPENDENCY_MISSING = "PLUGIN_DEPENDENCY_MISSING"
    VERSION_CONFLICT = "PLUGIN_VERSION_CONFLICT"
    LOAD_FAILED = "PLUGIN_LOAD_FAILED"
    SANDBOX_DENIED = "PLUGIN_SANDBOX_DENIED"


class PluginRuntimeError(Exception):
    """Base exception carrying a stable code plus structured details."""

    code: PluginErrorCode = PluginErrorCode.LOAD_FAILED

    def __init__(
        self,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "details": dict(self.details),
        }

    def __str__(self) -> str:
        return self.message


class InvalidManifestError(PluginRuntimeError):
    """A manifest/row is missing required fields or is malformed."""

    code = PluginErrorCode.MANIFEST_INVALID


class MissingDependencyError(PluginRuntimeError):
    """A required plugin id is not present in the discovered graph."""

    code = PluginErrorCode.DEPENDENCY_MISSING


class VersionConflictError(PluginRuntimeError):
    """A discovered plugin version does not satisfy a requirement."""

    code = PluginErrorCode.VERSION_CONFLICT


class PluginLoadError(PluginRuntimeError):
    """Discovery/activation/deactivation failed for a valid envelope."""

    code = PluginErrorCode.LOAD_FAILED


class SandboxDeniedError(PluginRuntimeError):
    """Activation was refused by the sandbox/permission policy."""

    code = PluginErrorCode.SANDBOX_DENIED


_ID_RE = re.compile(r"^(?P<kind>octop|dsh):(?P<native>[A-Za-z0-9][A-Za-z0-9._-]*)$")
_CONSTRAINT_RE = re.compile(
    r"^(?P<op>==|!=|>=|<=|>|<|~=)?\s*(?P<version>[0-9][0-9A-Za-z.+-]*)$",
)
_PRE_RANK = {
    "dev": 0,
    "a": 1,
    "alpha": 1,
    "b": 2,
    "beta": 2,
    "pre": 3,
    "preview": 3,
    "rc": 3,
}


def canonical_plugin_id(kind: PluginKind, native_id: str) -> str:
    """Return ``<kind>:<native_id>`` after validating both parts."""

    native = str(native_id or "").strip()
    if not native:
        raise InvalidManifestError("plugin id must not be empty", details={"kind": kind.value})
    return _validate_plugin_id(f"{kind.value}:{native}")


def split_plugin_id(plugin_id: str) -> tuple[PluginKind, str]:
    """Split a canonical id into ``(kind, native_id)``."""

    match = _ID_RE.match(_validate_plugin_id(plugin_id))
    assert match is not None
    return PluginKind(match.group("kind")), match.group("native")


def _validate_plugin_id(plugin_id: str) -> str:
    if not plugin_id or not str(plugin_id).strip():
        raise InvalidManifestError("plugin id must not be empty")
    if not _ID_RE.match(plugin_id):
        raise InvalidManifestError(
            "plugin id must be '<octop|dsh>:<native-id>' using letters, digits, '.', '_' or '-'",
            details={"id": plugin_id},
        )
    return plugin_id


def _version_key(version: str) -> tuple[tuple[int, ...], int, int]:
    """Convert a version string to a comparable key.

    Supports the subset used by Octop and DSH: dotted numeric releases with an
    optional ``-rc.N`` / ``-beta.N`` suffix and optional ``+build`` metadata.
    Build metadata is ignored, and release segments are zero-padded to at least
    three components so ``1.2``, ``1.2.0`` and ``1.2.0.0`` compare naturally.
    """

    cleaned = str(version or "").strip()
    if not cleaned:
        raise InvalidManifestError("version must not be empty")
    if cleaned.endswith("+unknown"):
        cleaned = cleaned[: -len("+unknown")]
    cleaned = cleaned.split("+", 1)[0]
    release, _, prerelease = cleaned.partition("-")

    release_parts: list[int] = []
    for part in release.split("."):
        if not part.isdigit():
            raise InvalidManifestError(
                "version release segments must be numeric",
                details={"version": version},
            )
        release_parts.append(int(part))
    if not release_parts:
        raise InvalidManifestError("version must not be empty", details={"version": version})

    width = max(3, len(release_parts))
    release_parts.extend([0] * (width - len(release_parts)))

    if not prerelease:
        return tuple(release_parts), 4, 0

    match = re.match(r"^(?P<label>[A-Za-z]+)(?:[._-]?(?P<num>\d+))?$", prerelease)
    if match is None:
        raise InvalidManifestError(
            "unsupported prerelease segment",
            details={"version": version},
        )
    label = match.group("label").lower()
    rank = _PRE_RANK.get(label)
    if rank is None:
        raise InvalidManifestError(
            "unsupported prerelease label",
            details={"version": version, "label": label},
        )
    return tuple(release_parts), rank, int(match.group("num") or 0)


def _validate_constraint_syntax(constraint: str) -> None:
    expression = str(constraint or "").strip()
    if not expression or expression == "*":
        return
    for part in expression.split(","):
        if _CONSTRAINT_RE.match(part.strip()) is None:
            raise InvalidManifestError(
                "version constraint must look like '>=1.2,<2' or '*'",
                details={"constraint": constraint},
            )


def _constraint_matches(version: str, constraint: str) -> bool:
    expression = str(constraint or "").strip()
    if not expression or expression == "*":
        return True

    match = _CONSTRAINT_RE.match(expression)
    if match is None:
        raise InvalidManifestError(
            "version constraint must look like '>=1.2,<2' or '*'",
            details={"constraint": constraint},
        )

    operator = match.group("op") or "=="
    target = match.group("version")
    left = _version_key(version)
    right = _version_key(target)

    if operator == "==":
        return left == right
    if operator == "!=":
        return left != right
    if operator == ">=":
        return left >= right
    if operator == "<=":
        return left <= right
    if operator == ">":
        return left > right
    if operator == "<":
        return left < right

    # ``~=X.Y`` means ``>=X.Y`` and the same ``X`` prefix; ``~=X.Y.Z`` keeps
    # ``X.Y``. Release segments were normalized to at least three entries, so
    # the prefix is always ``len(release) - 1``.
    if operator == "~=":
        release = target.split("-", 1)[0].split("+", 1)[0].split(".")
        if len(release) < 2:
            raise InvalidManifestError(
                "'~=' requires at least a major.minor version",
                details={"constraint": constraint},
            )
        prefix_len = len(release) - 1
        prefix = tuple(int(part) for part in release[:prefix_len])
        normalized = _version_key(version)[0]
        return left >= right and normalized[:prefix_len] == prefix

    raise InvalidManifestError(
        "unsupported version constraint operator",
        details={"constraint": constraint, "operator": operator},
    )


def version_satisfies(version: str, constraint: str) -> bool:
    """Return whether ``version`` satisfies a constraint expression.

    Shared by plugin requirements and host-runtime checks (e.g. the Node engine
    floor recorded in ``metadata.required_engines``).
    """

    text = str(constraint or "").strip()
    if text in {"", "*"}:
        return True
    return all(
        _constraint_matches(version, part)
        for part in text.split(",")
        if part.strip()
    )


def parse_permission_list(raw: object) -> tuple[tuple[PermissionKind, ...], bool]:
    """Parse a manifest ``permissions`` value into sandbox permissions.

    ``None`` or an empty list means "declared nothing", which is the
    least-privilege default and never "everything is allowed". Unknown names are
    a manifest error rather than being dropped: silently ignoring ``fs.*`` would
    look safer while making the plugin impossible to diagnose.
    """

    if raw is None:
        return (), False
    if isinstance(raw, str):
        values = [part.strip() for part in raw.split(",") if part.strip()]
    elif isinstance(raw, (list, tuple)):
        values = [str(part).strip() for part in raw if str(part).strip()]
    else:
        raise InvalidManifestError(
            "permissions must be a name or a list of names",
            details={"permissions": repr(raw)},
        )
    if not values:
        return (), False
    try:
        parsed = tuple(dict.fromkeys(PermissionKind(value) for value in values))
    except ValueError:
        raise InvalidManifestError(
            "unsupported plugin permission",
            details={"permissions": values, "valid": sorted(PERMISSION_KINDS)},
        ) from None
    return parsed, True


@dataclass(frozen=True, slots=True)
class PluginRequirement:
    """A dependency on another plugin id with an optional version range."""

    plugin_id: str
    constraint: str = "*"

    def __post_init__(self) -> None:
        _validate_plugin_id(self.plugin_id)
        _validate_constraint_syntax(self.constraint)

    def matches(self, version: str) -> bool:
        return version_satisfies(version, self.constraint)

    def to_dict(self) -> dict[str, str]:
        return {"plugin_id": self.plugin_id, "constraint": self.constraint}


@dataclass(frozen=True, slots=True)
class PluginSource:
    """Where the plugin came from."""

    kind: PluginSourceKind
    reference: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", PluginSourceKind(self.kind))
        reference = str(self.reference or "").strip()
        if not reference:
            raise InvalidManifestError("plugin source reference must not be empty")
        object.__setattr__(self, "reference", reference)

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind.value, "reference": self.reference}


@dataclass(frozen=True, slots=True)
class PluginEnvelope:
    """Ecosystem-neutral description of a plugin, before activation."""

    id: str
    kind: PluginKind
    version: str
    entry: str
    source: PluginSource
    capabilities: tuple[CapabilityKind, ...] = ()
    permissions: tuple[PermissionKind, ...] = ()
    config_schema: Mapping[str, Any] = field(default_factory=dict)
    requires: tuple[PluginRequirement, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_plugin_id(self.id)
        object.__setattr__(self, "kind", PluginKind(self.kind))
        plugin_kind, _native_id = split_plugin_id(self.id)
        if plugin_kind is not self.kind:
            raise InvalidManifestError(
                "envelope kind does not match the id prefix",
                details={"id": self.id, "kind": self.kind.value},
            )
        _version_key(self.version)
        if not str(self.entry or "").strip():
            raise InvalidManifestError(
                "plugin entry must not be empty",
                details={"id": self.id},
            )
        if not isinstance(self.source, PluginSource):
            raise InvalidManifestError(
                "plugin source must be a PluginSource",
                details={"id": self.id},
            )

        capabilities = tuple(CapabilityKind(item) for item in self.capabilities)
        if len(set(capabilities)) != len(capabilities):
            raise InvalidManifestError(
                "duplicate capability kind",
                details={"id": self.id},
            )

        try:
            permissions = tuple(PermissionKind(item) for item in self.permissions)
        except ValueError:
            raise InvalidManifestError(
                "unsupported plugin permission",
                details={
                    "id": self.id,
                    "permissions": [str(item) for item in self.permissions],
                    "valid": sorted(PERMISSION_KINDS),
                },
            ) from None
        if len(set(permissions)) != len(permissions):
            raise InvalidManifestError(
                "duplicate plugin permission",
                details={"id": self.id},
            )

        requirements = tuple(self.requires)
        seen: set[str] = set()
        for requirement in requirements:
            if not isinstance(requirement, PluginRequirement):
                raise InvalidManifestError(
                    "requires entries must be PluginRequirement instances",
                    details={"id": self.id},
                )
            if requirement.plugin_id == self.id:
                raise InvalidManifestError(
                    "plugin must not depend on itself",
                    details={"id": self.id},
                )
            if requirement.plugin_id in seen:
                raise InvalidManifestError(
                    "duplicate requirement",
                    details={"id": self.id, "requires": requirement.plugin_id},
                )
            seen.add(requirement.plugin_id)

        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "permissions", permissions)
        object.__setattr__(self, "requires", requirements)
        object.__setattr__(self, "config_schema", dict(self.config_schema))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def native_id(self) -> str:
        return split_plugin_id(self.id)[1]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "version": self.version,
            "entry": self.entry,
            "capabilities": [capability.value for capability in self.capabilities],
            "permissions": {
                "declared": bool(self.permissions),
                "items": [
                    permission.value
                    for permission in PermissionKind
                    if permission in set(self.permissions)
                ],
                "policy": "declared" if self.permissions else "least_privilege",
            },
            "config_schema": dict(self.config_schema),
            "source": self.source.to_dict(),
            "requires": [requirement.to_dict() for requirement in self.requires],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class ActivationContext:
    """Host-provided values handed to ``PluginLoader.activate``."""

    config: Mapping[str, Any] = field(default_factory=dict)
    data_dir: Path | None = None
    services: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PluginHandle:
    """Opaque activation handle returned by a loader."""

    plugin_id: str
    kind: PluginKind
    activation_id: str
    payload: Any = None

    def __post_init__(self) -> None:
        _validate_plugin_id(self.plugin_id)
        object.__setattr__(self, "kind", PluginKind(self.kind))
        if not str(self.activation_id or "").strip():
            raise PluginLoadError("activation id must not be empty")


@runtime_checkable
class PluginLoader(Protocol):
    """Adapter implemented once per ecosystem."""

    @property
    def kind(self) -> PluginKind:
        """Ecosystem handled by this loader."""

    def discover(
        self,
        roots: Sequence[str | Path] | None = None,
        *,
        strict: bool = False,
    ) -> list[PluginEnvelope]:
        """Return envelopes without activating anything.

        ``roots`` limits discovery to those directories (``None`` means each
        loader's own defaults); ``strict`` re-raises manifest errors instead of
        reporting them through logging.
        """

    def activate(self, envelope: PluginEnvelope, ctx: ActivationContext) -> PluginHandle:
        """Activate one envelope or raise a ``PluginRuntimeError``."""

    def deactivate(self, handle: PluginHandle) -> None:
        """Release everything acquired by ``activate``."""
