"""Stable error codes and readable Chinese messages for the plugin sandbox.

Codes are local to :mod:`happyclaw.infra.plugins.sandbox` on purpose, mirroring the
plugin runtime contract: the host maps them to ``happyclaw.infra.errors.ErrorCode``
and i18n bundles at the API boundary, so a new sandbox denial never changes
unrelated locale files.

Every failure carries a message that is safe to show to the local owner:
no traceback, no host paths beyond the workspace root the owner configured.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

__all__ = [
    "SandboxConfigError",
    "SandboxDeniedError",
    "SandboxError",
    "SandboxErrorCode",
    "describe_exception",
]


class SandboxErrorCode(StrEnum):
    """Stable, machine-readable sandbox failure codes."""

    DECLARATION_INVALID = "SANDBOX_DECLARATION_INVALID"
    CAPABILITY_UNDECLARED = "SANDBOX_CAPABILITY_UNDECLARED"
    PERMISSION_UNDECLARED = "SANDBOX_PERMISSION_UNDECLARED"
    PERMISSION_OUT_OF_SCOPE = "SANDBOX_PERMISSION_OUT_OF_SCOPE"
    WORKSPACE_UNAVAILABLE = "SANDBOX_WORKSPACE_UNAVAILABLE"
    PATH_INVALID = "SANDBOX_PATH_INVALID"
    PATH_OUTSIDE_WORKSPACE = "SANDBOX_PATH_OUTSIDE_WORKSPACE"
    COMMAND_INVALID = "SANDBOX_COMMAND_INVALID"
    COMMAND_TIMEOUT = "SANDBOX_COMMAND_TIMEOUT"
    EXECUTOR_UNAVAILABLE = "SANDBOX_EXECUTOR_UNAVAILABLE"
    EXECUTOR_FAILED = "SANDBOX_EXECUTOR_FAILED"
    LIMITS_INVALID = "SANDBOX_LIMITS_INVALID"
    EARLY_CHECK_MISS = "SANDBOX_EARLY_CHECK_MISS"
    NOT_ASSEMBLED = "SANDBOX_NOT_ASSEMBLED"


class SandboxError(Exception):
    """Base sandbox failure carrying a stable code plus structured details."""

    code: SandboxErrorCode = SandboxErrorCode.PATH_INVALID

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


class SandboxConfigError(SandboxError):
    """The sandbox was configured with data that cannot be interpreted.

    Raised while constructing the sandbox or a limit value, never in response to
    a plugin request: a manifest that declares an unknown capability fails loud
    instead of being silently widened or narrowed.
    """

    code = SandboxErrorCode.DECLARATION_INVALID


class SandboxDeniedError(SandboxError):
    """A plugin request was refused by the sandbox.

    ``code`` is set per denial (path escape, undeclared capability, timeout, …)
    and the same instance is what the audit ledger sees.
    """

    def __init__(
        self,
        code: SandboxErrorCode,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.code = code


def describe_exception(exc: BaseException) -> str:
    """Return ``ExcType: message`` flattened to one line, without a traceback."""

    try:
        type_name = type(exc).__name__
        text = " ".join(str(exc).split())
    except Exception:
        return "<unprintable thrown value>"
    return f"{type_name}: {text}" if text else type_name
