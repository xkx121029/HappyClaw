"""Profile-specific error types layered on the shared plugin contract."""

from __future__ import annotations

from happyclaw.infra.plugins.runtime.contract import PluginErrorCode, PluginRuntimeError

__all__ = ["ProfileNotFoundError"]


class ProfileNotFoundError(PluginRuntimeError):
    """The requested profile name has no file in the profile store."""

    code = PluginErrorCode.LOAD_FAILED
