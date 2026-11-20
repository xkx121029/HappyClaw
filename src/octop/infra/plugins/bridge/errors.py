"""Stable error codes and readable error results for the DSH tool bridge.

Every failure crossing the bridge becomes a :class:`DshToolError` carrying one
of the stable codes below. Raw exception text is flattened into a single line
and never includes a traceback, so tool results stay safe to hand back to the
model.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from octop.infra.plugins.bridge.contract_types import ContentBlocks, text_content


class DshToolErrorCode(StrEnum):
    """Stable, machine-readable failure codes (DSH compatible where applicable)."""

    TOOL_DEFINITION_INVALID = "TOOL_DEFINITION_INVALID"
    TOOL_UNKNOWN = "TOOL_UNKNOWN"
    TOOL_INVALID_ARGUMENTS = "TOOL_INVALID_ARGUMENTS"
    TOOL_DENIED = "TOOL_DENIED"
    TOOL_CAPABILITY_UNAVAILABLE = "TOOL_CAPABILITY_UNAVAILABLE"
    TOOL_APPROVAL_UNAVAILABLE = "TOOL_APPROVAL_UNAVAILABLE"
    TOOL_APPROVAL_DENIED = "TOOL_APPROVAL_DENIED"
    TOOL_APPROVAL_TIMEOUT = "TOOL_APPROVAL_TIMEOUT"
    TOOL_APPROVAL_CLOSED = "TOOL_APPROVAL_CLOSED"
    TOOL_APPROVAL_DISCONNECTED = "TOOL_APPROVAL_DISCONNECTED"
    TOOL_SANDBOX_BACKING_MISSING = "TOOL_SANDBOX_BACKING_MISSING"
    TOOL_SANDBOX_DENIED = "TOOL_SANDBOX_DENIED"
    TOOL_SANDBOX_NOT_ASSEMBLED = "TOOL_SANDBOX_NOT_ASSEMBLED"
    TOOL_RISK_ESCALATION_INVALID = "TOOL_RISK_ESCALATION_INVALID"
    TOOL_ABORTED = "TOOL_ABORTED"
    TOOL_ABORTED_BEFORE_DISPATCH = "TOOL_ABORTED_BEFORE_DISPATCH"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    TOOL_EXECUTION_FAILED = "TOOL_EXECUTION_FAILED"
    TOOL_OUTPUT_INVALID = "TOOL_OUTPUT_INVALID"
    TOOL_RENDER_FAILED = "TOOL_RENDER_FAILED"
    TOOL_RESULT_TOO_LARGE = "TOOL_RESULT_TOO_LARGE"
    # S10 runtime invocation: the bundle entry is executed in a Node child
    # process. Each failure mode gets its own code so the UI never has to guess
    # whether the plugin is missing, its entry is gone, or the host runtime is
    # too old.
    TOOL_RUNTIME_PLUGIN_NOT_LOADED = "TOOL_RUNTIME_PLUGIN_NOT_LOADED"
    TOOL_RUNTIME_ENTRY_MISSING = "TOOL_RUNTIME_ENTRY_MISSING"
    TOOL_RUNTIME_ENGINE_UNSATISFIED = "TOOL_RUNTIME_ENGINE_UNSATISFIED"
    TOOL_RUNTIME_SERVICE_MISSING = "TOOL_RUNTIME_SERVICE_MISSING"
    TOOL_RUNTIME_FAILED = "TOOL_RUNTIME_FAILED"


_MAX_MESSAGE_CHARS = 1000


def _flatten(message: str) -> str:
    text = " ".join(str(message).split())
    if len(text) > _MAX_MESSAGE_CHARS:
        return text[: _MAX_MESSAGE_CHARS - 3] + "..."
    return text


def describe_exception(exc: BaseException) -> str:
    """Return ``ExcType: message`` without leaking a traceback.

    Hostile ``__str__`` implementations fall back to a fixed placeholder, which
    mirrors DSH's ``<unprintable thrown value>`` behaviour.
    """
    try:
        type_name = type(exc).__name__
        text = str(exc)
    except Exception:
        return "<unprintable thrown value>"
    text = _flatten(text)
    return f"{type_name}: {text}" if text else type_name


class DshToolError(Exception):
    """A bridge failure that maps to a stable code and a readable result."""

    def __init__(
        self,
        code: DshToolErrorCode,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = _flatten(message)
        self.details: dict[str, Any] = dict(details or {})
        super().__init__(self.message)

    def error_info(self) -> dict[str, Any]:
        return {
            "name": type(self).__name__,
            "code": self.code.value,
            "message": self.message,
        }


def tool_error_content(message: str) -> ContentBlocks:
    """DSH-shaped error content: a single ``Error: <reason>`` text block."""
    return text_content(f"Error: {_flatten(message)}")


__all__ = [
    "DshToolError",
    "DshToolErrorCode",
    "describe_exception",
    "tool_error_content",
]
