"""DSH tool execution pipeline: snapshot, policy, dispatch, validation, result.

The pipeline preserves the DSH semantics Octop needs for a local single-user
agent:

* parameters are losslessly snapshotted before anything runs;
* pre-execute hooks and monotonic guards can deny / cancel / ask;
* a failing pre-execution checkpoint aborts *before* dispatch (no side effects);
* ``timeoutMs`` is enforced per call;
* success values are validated against ``output.schema`` before rendering;
* post-execute hooks may accept (replacing content/value) or block;
* every invocation emits exactly one ``tool/call`` and one ``tool/result``;
* results are capped by ``max_result_bytes``.
"""

from __future__ import annotations

import asyncio
import copy
import inspect
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from octop.infra.plugins.bridge.approval import Guardrail, GuardrailContext
from octop.infra.plugins.bridge.contract import (
    ApprovalOutcome,
    ApprovalRequest,
    Approver,
    CheckpointHook,
    PostToolDecision,
    PreToolDecision,
    ToolDefinition,
    ToolExecutionContext,
)
from octop.infra.plugins.bridge.contract_types import AbortSignal, ContentBlocks, text_content
from octop.infra.plugins.bridge.errors import (
    DshToolError,
    DshToolErrorCode,
    describe_exception,
    tool_error_content,
)
from octop.infra.plugins.bridge.schema import validate_json_schema

DEFAULT_MAX_RESULT_BYTES = 256 * 1024


@dataclass(frozen=True)
class ToolCall:
    """An inbound model tool call (``tool/call``)."""

    call_id: str
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True)
class ToolCallRecord:
    """The recorded form of a call, emitted as the ``tool/call`` event."""

    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolResultRecord:
    """The recorded result, emitted as the ``tool/result`` event."""

    call_id: str
    name: str
    content: ContentBlocks
    is_error: bool
    error: dict[str, Any] | None
    source_call_id: str


@dataclass(frozen=True)
class ToolInvocation:
    """A settled call/result pair."""

    call: ToolCallRecord
    result: ToolResultRecord

    @property
    def text(self) -> str:
        return "\n".join(
            str(block.get("text", ""))
            for block in self.result.content
            if block.get("type") == "text"
        )


ToolEvent = ToolCallRecord | ToolResultRecord
EventHandler = Callable[[str, "ToolEvent"], None]


@dataclass(frozen=True)
class _PostOutcome:
    """Internal result of the post-execute chain."""

    error: tuple[DshToolErrorCode, str] | None = None
    value: Any = None
    content: ContentBlocks = field(default_factory=list)


class ToolPipeline:
    """Runs one DSH tool call through the guard-railed pipeline."""

    def __init__(
        self,
        *,
        lookup: Callable[[str], ToolDefinition | None],
        scope: str = "global",
        max_result_bytes: int = DEFAULT_MAX_RESULT_BYTES,
        checkpoint: CheckpointHook | None = None,
        approver: Approver | None = None,
        guardrail: Guardrail | None = None,
        on_event: EventHandler | None = None,
        default_timeout_ms: float | None = None,
    ) -> None:
        self.lookup = lookup
        self.scope = scope
        self.max_result_bytes = max_result_bytes
        self.checkpoint = checkpoint
        self.approver = approver
        self.guardrail = guardrail
        self.on_event = on_event
        self.default_timeout_ms = default_timeout_ms

    def _passthrough_exceptions(self) -> tuple[type[BaseException], ...]:
        """收集必须原样抛给运行时的暂停异常（HITL 中断等）。"""
        for source in (self.guardrail, self.approver):
            # 兼容 bound method（如 channel.request）：到实例上找声明。
            for owner in (source, getattr(source, "__self__", None)):
                if owner is None:
                    continue
                pause = getattr(owner, "passthrough_exceptions", None)
                if pause is None:
                    pause = getattr(owner, "pause_exceptions", None)
                if pause:
                    return tuple(pause)
        return ()

    async def invoke(
        self,
        call: ToolCall,
        *,
        signal: AbortSignal | None = None,
    ) -> ToolInvocation:
        snapshot, snapshot_error = snapshot_arguments(call.arguments)
        call_record = ToolCallRecord(
            call_id=call.call_id or new_call_id(),
            name=call.name,
            arguments=snapshot,
        )
        self._emit("tool/call", call_record)

        if snapshot_error is not None:
            return self._fail(
                call_record,
                DshToolErrorCode.TOOL_INVALID_ARGUMENTS,
                snapshot_error,
            )

        definition = self.lookup(call.name)
        if definition is None:
            return self._fail(
                call_record,
                DshToolErrorCode.TOOL_UNKNOWN,
                f"unknown tool {call.name!r}",
            )

        violations = validate_json_schema(snapshot, definition.parameters)
        if violations:
            return self._fail(
                call_record,
                DshToolErrorCode.TOOL_INVALID_ARGUMENTS,
                "invalid arguments: " + "; ".join(violations[:5]),
            )

        context = ToolExecutionContext(call_id=call_record.call_id, signal=signal)

        if self.guardrail is not None:
            decision = await self.guardrail.evaluate(
                GuardrailContext(
                    call_id=call_record.call_id,
                    tool_name=call.name,
                    arguments=snapshot,
                    signal=signal,
                )
            )
            if decision.action == "deny":
                return self._fail(
                    call_record,
                    decision.code or DshToolErrorCode.TOOL_DENIED,
                    decision.reason or "denied by guardrail",
                )

        blocked = await self._run_pre_hooks(definition, context, snapshot)
        if blocked is not None:
            return self._fail(call_record, blocked[0], blocked[1])

        if context.aborted():
            return self._abort_result(call_record, "aborted before dispatch")

        checkpoint_failure = await self._run_checkpoint(context)
        if checkpoint_failure is not None:
            return self._abort_result(call_record, checkpoint_failure)

        try:
            value = await self._dispatch(definition, snapshot, context)
        except DshToolError as exc:
            return self._fail(call_record, exc.code, exc.message)

        violations = validate_json_schema(value, definition.output.schema)
        if violations:
            return self._fail(
                call_record,
                DshToolErrorCode.TOOL_OUTPUT_INVALID,
                "output does not match output.schema: " + "; ".join(violations[:5]),
            )

        try:
            content = definition.output.render_content(dict(snapshot), value)
        except DshToolError as exc:
            return self._fail(call_record, exc.code, exc.message)

        settled = await self._run_post_hooks(definition, context, snapshot, value, content)
        if settled.error is not None:
            return self._fail(call_record, settled.error[0], settled.error[1])
        value, content = settled.value, settled.content

        limit = definition.max_result_bytes or self.max_result_bytes
        size = content_size(content)
        if size > limit:
            return self._fail(
                call_record,
                DshToolErrorCode.TOOL_RESULT_TOO_LARGE,
                f"tool result is {size} bytes, above the {limit} byte limit",
            )

        return self._success(call_record, content)

    def abort_before_dispatch(
        self,
        call: ToolCall,
        *,
        reason: str = "aborted before dispatch",
    ) -> ToolInvocation:
        """Emit a paired call/result for a call that never started."""
        snapshot, _ = snapshot_arguments(call.arguments)
        call_record = ToolCallRecord(
            call_id=call.call_id or new_call_id(),
            name=call.name,
            arguments=snapshot,
        )
        self._emit("tool/call", call_record)
        return self._abort_result(call_record, reason)

    async def _run_pre_hooks(
        self,
        definition: ToolDefinition,
        context: ToolExecutionContext,
        args: Mapping[str, Any],
    ) -> tuple[DshToolErrorCode, str] | None:
        for hook in definition.pre_execute:
            try:
                decision = await _resolve(hook(context, dict(args)))
            except Exception as exc:
                return (
                    DshToolErrorCode.TOOL_EXECUTION_FAILED,
                    f"pre-execute hook failed: {describe_exception(exc)}",
                )
            if not isinstance(decision, PreToolDecision):
                return (
                    DshToolErrorCode.TOOL_EXECUTION_FAILED,
                    "pre-execute hook returned an invalid decision",
                )
            if decision.action == "allow":
                continue
            if decision.action == "deny":
                return (DshToolErrorCode.TOOL_DENIED, decision.reason or "denied by policy")
            if decision.action == "cancel":
                return (
                    DshToolErrorCode.TOOL_ABORTED,
                    decision.reason or "cancelled by policy",
                )
            approval = await self._request_approval(context, decision.reason)
            if approval is not None:
                return approval

        for guard in definition.guards:
            try:
                reason = await _resolve(guard(context, dict(args)))
            except Exception as exc:
                return (
                    DshToolErrorCode.TOOL_EXECUTION_FAILED,
                    f"tool guard failed: {describe_exception(exc)}",
                )
            if isinstance(reason, str) and reason:
                return (DshToolErrorCode.TOOL_DENIED, reason)
        return None

    async def _request_approval(
        self,
        context: ToolExecutionContext,
        reason: str,
    ) -> tuple[DshToolErrorCode, str] | None:
        if self.approver is None:
            return (
                DshToolErrorCode.TOOL_DENIED,
                f"approval unavailable: {reason or 'approval required'}",
            )
        request = ApprovalRequest(
            call_id=context.call_id,
            reason=reason,
            signal=context.signal,
        )
        try:
            raw = await _resolve(self.approver(request))
        except Exception as exc:
            # 暂停异常必须穿透，不能被记成一次审批拒绝。
            if isinstance(exc, self._passthrough_exceptions()):
                raise
            return (
                DshToolErrorCode.TOOL_DENIED,
                f"approval failed: {describe_exception(exc)}",
            )
        try:
            outcome = raw if isinstance(raw, ApprovalOutcome) else ApprovalOutcome(str(raw))
        except ValueError:
            return (DshToolErrorCode.TOOL_DENIED, f"approval rejected: {reason}")
        if outcome is ApprovalOutcome.ALLOWED_ONCE:
            return None
        if outcome is ApprovalOutcome.CANCELLED:
            return (DshToolErrorCode.TOOL_ABORTED, reason or "cancelled by user")
        return (DshToolErrorCode.TOOL_DENIED, f"approval {outcome.value}: {reason}")

    async def _run_checkpoint(self, context: ToolExecutionContext) -> str | None:
        if self.checkpoint is None:
            return None
        try:
            await _resolve(self.checkpoint())
        except Exception as exc:
            return f"pre-execution checkpoint failed: {describe_exception(exc)}"
        if context.aborted():
            return "aborted before dispatch"
        return None

    async def _dispatch(
        self,
        definition: ToolDefinition,
        args: Mapping[str, Any],
        context: ToolExecutionContext,
    ) -> Any:
        timeout_ms = (
            definition.timeout_ms if definition.timeout_ms is not None else self.default_timeout_ms
        )
        timeout_s = None if timeout_ms is None else timeout_ms / 1000.0

        async def runner() -> Any:
            if inspect.iscoroutinefunction(definition.execute):
                return await _resolve(definition.execute(copy.deepcopy(dict(args)), context))
            outcome = await asyncio.to_thread(
                definition.execute,
                copy.deepcopy(dict(args)),
                context,
            )
            return await _resolve(outcome)

        try:
            if timeout_s is None:
                return await runner()
            return await asyncio.wait_for(runner(), timeout_s)
        except TimeoutError:
            raise DshToolError(
                DshToolErrorCode.TOOL_TIMEOUT,
                f"tool {definition.name!r} exceeded {int(timeout_ms or 0)} ms",
            ) from None
        except asyncio.CancelledError:
            if context.aborted():
                raise DshToolError(
                    DshToolErrorCode.TOOL_ABORTED,
                    f"tool {definition.name!r} was aborted",
                ) from None
            raise
        except DshToolError:
            raise
        except Exception as exc:
            raise DshToolError(
                DshToolErrorCode.TOOL_EXECUTION_FAILED,
                describe_exception(exc),
            ) from None

    async def _run_post_hooks(
        self,
        definition: ToolDefinition,
        context: ToolExecutionContext,
        args: Mapping[str, Any],
        value: Any,
        content: ContentBlocks,
    ) -> _PostOutcome:
        for hook in definition.post_execute:
            try:
                decision = await _resolve(
                    hook(context, dict(args), value, list(content)),
                )
            except Exception as exc:
                return _PostOutcome(
                    error=(
                        DshToolErrorCode.TOOL_EXECUTION_FAILED,
                        f"post-execute hook failed: {describe_exception(exc)}",
                    )
                )
            if not isinstance(decision, PostToolDecision):
                return _PostOutcome(
                    error=(
                        DshToolErrorCode.TOOL_EXECUTION_FAILED,
                        "post-execute hook returned an invalid decision",
                    )
                )
            if decision.action == "block":
                return _PostOutcome(
                    error=(
                        DshToolErrorCode.TOOL_DENIED,
                        decision.reason or "blocked by post-execute policy",
                    )
                )
            if decision.has_value():
                value = decision.value
                violations = validate_json_schema(value, definition.output.schema)
                if violations:
                    return _PostOutcome(
                        error=(
                            DshToolErrorCode.TOOL_OUTPUT_INVALID,
                            "post-execute value does not match output.schema: "
                            + "; ".join(violations[:5]),
                        )
                    )
                try:
                    content = definition.output.render_content(dict(args), value)
                except DshToolError as exc:
                    return _PostOutcome(error=(exc.code, exc.message))
            elif decision.content is not None:
                content = decision.content
        return _PostOutcome(value=value, content=content)

    def _success(self, call_record: ToolCallRecord, content: ContentBlocks) -> ToolInvocation:
        result = ToolResultRecord(
            call_id=call_record.call_id,
            name=call_record.name,
            content=content,
            is_error=False,
            error=None,
            source_call_id=call_record.call_id,
        )
        self._emit("tool/result", result)
        return ToolInvocation(call=call_record, result=result)

    def _fail(
        self,
        call_record: ToolCallRecord,
        code: DshToolErrorCode,
        message: str,
    ) -> ToolInvocation:
        error = DshToolError(code, message)
        result = ToolResultRecord(
            call_id=call_record.call_id,
            name=call_record.name,
            content=tool_error_content(error.message),
            is_error=True,
            error=error.error_info(),
            source_call_id=call_record.call_id,
        )
        self._emit("tool/result", result)
        return ToolInvocation(call=call_record, result=result)

    def _abort_result(self, call_record: ToolCallRecord, reason: str) -> ToolInvocation:
        return self._fail(
            call_record,
            DshToolErrorCode.TOOL_ABORTED_BEFORE_DISPATCH,
            reason,
        )

    def _emit(self, event: str, record: ToolEvent) -> None:
        if self.on_event is not None:
            self.on_event(event, record)


def new_call_id() -> str:
    return uuid4().hex


def snapshot_arguments(raw: Mapping[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Return a lossless JSON snapshot, or an error message when that is impossible."""
    try:
        if not isinstance(raw, Mapping):
            raise TypeError("tool arguments must be a mapping")
        if _contains_non_string_key(raw):
            raise TypeError("tool argument keys must be strings")
        dumped = json.dumps(dict(raw), ensure_ascii=False, allow_nan=False)
        snapshot = json.loads(dumped)
    except (TypeError, ValueError) as exc:
        return {}, f"arguments are not losslessly JSON-serializable: {exc}"
    if not isinstance(snapshot, dict):
        return {}, "arguments must serialize to a JSON object"
    return snapshot, None


def content_size(content: ContentBlocks) -> int:
    try:
        return len(json.dumps(content, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        return len(json.dumps(text_content("<unserializable content>")).encode("utf-8"))


def _contains_non_string_key(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or _contains_non_string_key(item):
                return True
        return False
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_non_string_key(item) for item in value)
    return False


async def _resolve(value: object) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


__all__ = [
    "DEFAULT_MAX_RESULT_BYTES",
    "ToolCall",
    "ToolCallRecord",
    "ToolInvocation",
    "ToolPipeline",
    "ToolResultRecord",
    "content_size",
    "new_call_id",
    "snapshot_arguments",
]
