"""Python mirror of the DSH ``ToolDefinition`` contract.

The bridge adapts DSH's TypeScript tool contract to Octop's Python tool
registry. A definition must declare ``parameters`` and ``output.schema`` as
JSON Schema; ``execute`` returns a canonical JSON value which the pipeline
validates against ``output.schema`` before rendering.

Deliberately omitted (see ``2026-11-12/dsh-integration/outputs/tool-bridge.md``):
DSH's five-layer scope stack, PTC, MCP two-phase swap, multi-route answerers.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from octop.infra.plugins.bridge.contract_types import (
    AbortSignal,
    ContentBlocks,
    normalize_content,
)
from octop.infra.plugins.bridge.errors import DshToolError, DshToolErrorCode
from octop.infra.plugins.bridge.schema import assert_json_schema

_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass(frozen=True)
class PreToolDecision:
    """DSH ``PreToolDecision``: allow / deny / cancel / ask.

    Parameters are never rewritable here, matching DSH: the call has already
    been recorded and shown to the user.
    """

    action: Literal["allow", "deny", "cancel", "ask"]
    reason: str = ""

    @classmethod
    def allow(cls) -> PreToolDecision:
        return cls("allow")

    @classmethod
    def deny(cls, reason: str) -> PreToolDecision:
        return cls("deny", reason)

    @classmethod
    def cancel(cls, reason: str = "cancelled by policy") -> PreToolDecision:
        return cls("cancel", reason)

    @classmethod
    def ask(cls, reason: str) -> PreToolDecision:
        return cls("ask", reason)


_UNSET: Any = object()


@dataclass(frozen=True)
class PostToolDecision:
    """DSH ``PostToolDecision``: accept (optionally replacing content/value) or block."""

    action: Literal["accept", "block"]
    reason: str = ""
    content: ContentBlocks | None = None
    value: Any = _UNSET

    @classmethod
    def accept(
        cls,
        *,
        content: ContentBlocks | None = None,
        value: Any = _UNSET,
    ) -> PostToolDecision:
        return cls("accept", content=content, value=value)

    @classmethod
    def block(cls, feedback: str) -> PostToolDecision:
        return cls("block", reason=feedback)

    def has_value(self) -> bool:
        return self.value is not _UNSET


class ApprovalOutcome(StrEnum):
    """Single-approver outcome closed set (DSH compatible)."""

    ALLOWED_ONCE = "allowed-once"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ApprovalRequest:
    call_id: str
    reason: str
    signal: AbortSignal | None = None
    tool_name: str = ""
    arguments: Mapping[str, Any] = field(default_factory=dict)
    # What the sandbox actually inspected for this call. Kept on the request so
    # an approval transport can show it and an audit sink can record it.
    sandbox_backed: bool = False
    sandbox_coverage: str = "unknown"


@dataclass(frozen=True)
class ToolExecutionContext:
    """Per-call context handed to execute and policy hooks."""

    call_id: str
    signal: AbortSignal | None = None

    def aborted(self) -> bool:
        return self.signal is not None and self.signal.is_set()


@dataclass(frozen=True)
class ToolOutputSpec:
    """DSH ``output``: schema validates the success value, render builds content."""

    schema: dict[str, Any]
    render: Callable[[Mapping[str, Any], Any], object]

    def render_content(self, args: Mapping[str, Any], value: Any) -> ContentBlocks:
        try:
            return normalize_content(self.render(args, value))
        except Exception as exc:
            raise DshToolError(
                DshToolErrorCode.TOOL_RENDER_FAILED,
                f"output render failed: {type(exc).__name__}: {exc}",
            ) from None


ToolExecute = Callable[[Mapping[str, Any], ToolExecutionContext], object]
ConcurrencyClassifier = Callable[[Mapping[str, Any]], object]
PreHook = Callable[[ToolExecutionContext, Mapping[str, Any]], object]
GuardHook = Callable[[ToolExecutionContext, Mapping[str, Any]], object]
PostHook = Callable[[ToolExecutionContext, Mapping[str, Any], Any, ContentBlocks], object]
CheckpointHook = Callable[[], object]
Approver = Callable[[ApprovalRequest], object]


@dataclass(frozen=True)
class ToolDefinition:
    """A DSH-compatible tool declaration ready for the Octop agent runtime."""

    name: str
    description: str
    parameters: dict[str, Any]
    output: ToolOutputSpec
    execute: ToolExecute
    timeout_ms: float | None = None
    is_concurrency_safe: ConcurrencyClassifier | None = None
    pre_execute: tuple[PreHook, ...] = ()
    guards: tuple[GuardHook, ...] = ()
    post_execute: tuple[PostHook, ...] = ()
    max_result_bytes: int | None = None

    def __post_init__(self) -> None:
        if not _TOOL_NAME_RE.match(self.name):
            raise DshToolError(
                DshToolErrorCode.TOOL_DEFINITION_INVALID,
                f"tool name {self.name!r} must match {_TOOL_NAME_RE.pattern}",
            )
        if not self.description.strip():
            raise DshToolError(
                DshToolErrorCode.TOOL_DEFINITION_INVALID,
                f"tool {self.name!r} requires a description",
            )
        if not isinstance(self.parameters, dict):
            raise DshToolError(
                DshToolErrorCode.TOOL_DEFINITION_INVALID,
                f"tool {self.name!r} parameters must be a JSON Schema object",
            )
        try:
            assert_json_schema(self.parameters, label=f"{self.name}.parameters")
        except ValueError as exc:
            raise DshToolError(
                DshToolErrorCode.TOOL_DEFINITION_INVALID,
                str(exc),
            ) from exc
        if not isinstance(self.output, ToolOutputSpec):
            raise DshToolError(
                DshToolErrorCode.TOOL_DEFINITION_INVALID,
                f"tool {self.name!r} requires an output spec",
            )
        try:
            assert_json_schema(self.output.schema, label=f"{self.name}.output.schema")
        except ValueError as exc:
            raise DshToolError(
                DshToolErrorCode.TOOL_DEFINITION_INVALID,
                str(exc),
            ) from exc
        if not callable(self.execute):
            raise DshToolError(
                DshToolErrorCode.TOOL_DEFINITION_INVALID,
                f"tool {self.name!r} execute must be callable",
            )
        if not callable(self.output.render):
            raise DshToolError(
                DshToolErrorCode.TOOL_DEFINITION_INVALID,
                f"tool {self.name!r} output.render must be callable",
            )
        if self.timeout_ms is not None and (
            not math.isfinite(self.timeout_ms) or self.timeout_ms <= 0
        ):
            raise DshToolError(
                DshToolErrorCode.TOOL_DEFINITION_INVALID,
                f"tool {self.name!r} timeout_ms must be a positive finite number",
            )
        if self.max_result_bytes is not None and self.max_result_bytes <= 0:
            raise DshToolError(
                DshToolErrorCode.TOOL_DEFINITION_INVALID,
                f"tool {self.name!r} max_result_bytes must be positive",
            )

    def schema_projection(self) -> dict[str, Any]:
        """Model-facing projection: name / description / parameters only."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    def classify_concurrency(self, args: Mapping[str, Any]) -> bool:
        """Only an exact ``True`` allows parallel execution (DSH semantics)."""
        classifier = self.is_concurrency_safe
        if classifier is None:
            return False
        try:
            return classifier(args) is True
        except Exception:
            return False


__all__ = [
    "ApprovalOutcome",
    "ApprovalRequest",
    "Approver",
    "CheckpointHook",
    "ConcurrencyClassifier",
    "PostHook",
    "PostToolDecision",
    "PreHook",
    "PreToolDecision",
    "ToolDefinition",
    "ToolExecutionContext",
    "ToolOutputSpec",
]
