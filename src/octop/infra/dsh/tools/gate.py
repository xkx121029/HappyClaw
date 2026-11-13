"""Read-only admission rules for DSH plugin tools (S2).

Admission is decided from the manifest-derived envelope only: a plugin must
declare the ``tool`` capability, and must not declare any write or egress
permission. Nothing here inspects tool bodies or guesses permissions.

The blocking set is deliberately small and explicit. Anything that needs a real
execution backend (``fs.write`` / ``exec`` / ``network``) is excluded at
discovery time, not filtered after mounting, so a provider is never even asked
for such a plugin.
"""

from __future__ import annotations

from octop.infra.plugins.runtime.contract import (
    CapabilityKind,
    PermissionKind,
    PluginEnvelope,
)

# Skip reasons. Stable strings: the status query and tests both read them.
SKIP_NOT_TOOL = "not_tool_capability"
SKIP_UNSAFE_PERMISSION = "unsafe_permission"
SKIP_NO_PROVIDER = "no_tool_provider"
SKIP_PROVIDER_FAILED = "tool_provider_failed"
SKIP_DEFINITION_INVALID = "tool_definition_invalid"
SKIP_NAME_CONFLICT = "name_conflict"
SKIP_INSTALL_BROKEN = "install_broken"
SKIP_MARKET_ROOT_MISSING = "market_root_missing"
SKIP_MARKET_SLOT_UNREADABLE = "market_slot_unreadable"
SKIP_DUPLICATE = "duplicate_plugin_id"
SKIP_DISCOVERY_FAILED = "discovery_failed"

BLOCKING_PERMISSIONS: tuple[PermissionKind, ...] = (
    PermissionKind.FS_WRITE,
    PermissionKind.EXEC,
    PermissionKind.NETWORK,
)


def permission_name(kind: PermissionKind) -> str:
    """Manifest spelling of a permission (``fs.write``, ``exec``, ...)."""
    return kind.value


def is_tool_plugin(envelope: PluginEnvelope) -> bool:
    return CapabilityKind.TOOL in envelope.capabilities


def blocking_permissions(envelope: PluginEnvelope) -> tuple[PermissionKind, ...]:
    """Declared permissions that make a plugin unsafe to mount in S2."""
    declared = set(envelope.permissions)
    return tuple(kind for kind in BLOCKING_PERMISSIONS if kind in declared)


__all__ = [
    "BLOCKING_PERMISSIONS",
    "SKIP_DEFINITION_INVALID",
    "SKIP_DISCOVERY_FAILED",
    "SKIP_DUPLICATE",
    "SKIP_INSTALL_BROKEN",
    "SKIP_MARKET_ROOT_MISSING",
    "SKIP_MARKET_SLOT_UNREADABLE",
    "SKIP_NAME_CONFLICT",
    "SKIP_NOT_TOOL",
    "SKIP_NO_PROVIDER",
    "SKIP_PROVIDER_FAILED",
    "SKIP_UNSAFE_PERMISSION",
    "blocking_permissions",
    "is_tool_plugin",
    "permission_name",
]
