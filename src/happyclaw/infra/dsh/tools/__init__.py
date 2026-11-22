"""S2: read-only DSH plugin tools in the agent tool list.

Importing this package has no side effects: nothing is discovered, imported
from a plugin, or written at import time. Callers check
``happyclaw.infra.dsh.switches.stage_enabled("tools")`` first and only then import
``build_dsh_plugin_tools``.
"""

from __future__ import annotations

from .catalog import DshToolBuild, ToolProvider, build_dsh_plugin_tools
from .discovery import DiscoveredPlugin, DshToolSkip, discover_dsh_plugins
from .gate import (
    BLOCKING_PERMISSIONS,
    SKIP_DEFINITION_INVALID,
    SKIP_DISCOVERY_FAILED,
    SKIP_DUPLICATE,
    SKIP_INSTALL_BROKEN,
    SKIP_MARKET_ROOT_MISSING,
    SKIP_MARKET_SLOT_UNREADABLE,
    SKIP_NAME_CONFLICT,
    SKIP_NOT_TOOL,
    SKIP_NO_PROVIDER,
    SKIP_PROVIDER_FAILED,
    SKIP_UNSAFE_PERMISSION,
    blocking_permissions,
    is_tool_plugin,
)
from .sandbox import (
    ENV_SANDBOX_ABSENCE,
    DshSandboxState,
    SandboxProbe,
    build_capability_probe,
    resolve_absence_mode_strict,
)

__all__ = [
    "BLOCKING_PERMISSIONS",
    "DiscoveredPlugin",
    "DshSandboxState",
    "DshToolBuild",
    "DshToolSkip",
    "ENV_SANDBOX_ABSENCE",
    "SandboxProbe",
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
    "ToolProvider",
    "blocking_permissions",
    "build_capability_probe",
    "build_dsh_plugin_tools",
    "discover_dsh_plugins",
    "is_tool_plugin",
    "resolve_absence_mode_strict",
]
