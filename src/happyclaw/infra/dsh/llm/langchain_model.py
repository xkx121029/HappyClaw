"""LangChain ``BaseChatModel`` adapter over the DSH LLM seam.

This is the S8 bridge: it lets ``happyclaw_harness`` keep its own routing,
middleware and graph while a single, explicitly listed ``provider/model`` ref
is served by :class:`~happyclaw.infra.dsh.llm.runtime.LlmRuntime`.

The adapter declares the harness version it was written against. A mismatch is
reported by :func:`harness_version_warning` at install time; it is never
silently ignored.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from importlib.metadata import PackageNotFoundError, version
from typing import Any, cast

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    ToolCallChunk,
    UsageMetadata,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from happyclaw.infra.dsh.llm.adapter import adapter_for
from happyclaw.infra.dsh.llm.assembly import AssistantTurnBuilder
from happyclaw.infra.dsh.llm.retry import RetryPolicy
from happyclaw.infra.dsh.llm.runtime import LlmRuntime
from happyclaw.infra.dsh.llm.types import (
    AssistantTurn,
    BlockEnd,
    BlockStart,
    FinishChunk,
    FinishReason,
    LlmRequest,
    Message,
    ReasoningBlock,
    ReasoningDelta,
    Role,
    StepRestart,
    TextBlock,
    TextDelta,
    TokenUsage,
    ToolCallBlock,
    ToolCallDelta,
    ToolResultBlock,
    ToolSchema,
    UsageChunk,
    UsageDrift,
)

__all__ = [
    "REQUIRED_HARNESS_VERSION",
    "DshChatModel",
    "DshModelError",
    "build_dsh_chat_model",
    "harness_version_warning",
    "installed_harness_version",
]

#: The ``happyclaw_harness`` release this adapter was implemented and verified
#: against. Bump only together with the parity fixtures in
#: ``tests/unit/infra/dsh/test_llm_parity.py``.
REQUIRED_HARNESS_VERSION = "1.0.14"

# OpenAI wire vocabulary for the reasons DSH normalizes.
_FINISH_TO_WIRE = {
    FinishReason.STOP: "stop",
    FinishReason.TOOL_CALLS: "tool_calls",
    FinishReason.MAX_TOKENS: "length",
    FinishReason.ABORTED: "aborted",
    FinishReason.ERROR: "error",
}


class DshModelError(RuntimeError):
    """The DSH runtime could not produce a usable assistant turn."""


def installed_harness_version() -> str | None:
    """Return the installed ``happyclaw-harness`` version, or ``None`` when absent."""
    try:
        return version("happyclaw-harness")
    except PackageNotFoundError:
        return None


def harness_version_warning() -> str | None:
    """Return a warning when the installed harness is not the verified one."""
    installed = installed_harness_version()
    if installed is None:
        return "happyclaw-harness is not installed; the DSH LLM adapter cannot be verified"
    if installed != REQUIRED_HARNESS_VERSION:
        return (
            f"happyclaw-harness {installed} differs from the verified "
            f"{REQUIRED_HARNESS_VERSION}; re-run the LLM parity fixtures before enabling"
        )
    return None


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, Mapping) and block.get("type") in {"text", "text_delta"}:
                parts.append(str(block.get("text") or ""))
        return "".join(parts)
    return ""


def _arguments_json(arguments: Any) -> str:
    if isinstance(arguments, str):
        return arguments or "{}"
    return json.dumps(arguments if arguments is not None else {}, ensure_ascii=False)


def _message_blocks(message: BaseMessage) -> tuple[Role, list[Any]]:
    kind = getattr(message, "type", "")
    if kind == "system":
        return Role.SYSTEM, [TextBlock(_text_of(message.content))]
    if kind == "tool":
        tool_call_id = str(getattr(message, "tool_call_id", "") or "")
        return Role.TOOL, [ToolResultBlock(tool_call_id, _text_of(message.content))]
    if kind == "ai":
        blocks: list[Any] = []
        reasoning = (getattr(message, "additional_kwargs", None) or {}).get("reasoning_content")
        if reasoning:
            blocks.append(ReasoningBlock(str(reasoning)))
        text = _text_of(message.content)
        if text:
            blocks.append(TextBlock(text))
        for call in getattr(message, "tool_calls", None) or ():
            raw = call if isinstance(call, Mapping) else call.model_dump()
            blocks.append(
                ToolCallBlock(
                    id=str(raw.get("id") or ""),
                    name=str(raw.get("name") or ""),
                    arguments=_arguments_json(raw.get("args")),
                )
            )
        return Role.ASSISTANT, blocks
    return Role.USER, [TextBlock(_text_of(message.content))]


def _tool_schema(raw: Mapping[str, Any]) -> ToolSchema | None:
    function = raw.get("function")
    if not isinstance(function, Mapping):
        function = raw
    name = str(function.get("name") or "")
    if not name:
        return None
    parameters = function.get("parameters")
    return ToolSchema(
        name=name,
        description=str(function.get("description") or ""),
        parameters=parameters if isinstance(parameters, Mapping) else {},
    )


def _usage_metadata(usage: TokenUsage) -> dict[str, Any]:
    input_details: dict[str, int] = {}
    if "cache_read" in usage.reported_details:
        input_details["cache_read"] = usage.cache_read_tokens
    if "cache_write" in usage.reported_details:
        input_details["cache_write"] = usage.cache_write_tokens
    output_details: dict[str, int] = {}
    if "reasoning" in usage.reported_details:
        output_details["reasoning"] = usage.reasoning_tokens
    return {
        # LangChain's ``input_tokens`` is the billed prompt count, i.e. cache
        # reads/writes included. DSH keeps them disjoint.
        "input_tokens": usage.billed_input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.resolved_total(),
        "input_token_details": input_details,
        "output_token_details": output_details,
    }


def _wire_finish(reason: FinishReason | None) -> str | None:
    return None if reason is None else _FINISH_TO_WIRE.get(reason, str(reason))


def _tool_call_parts(block: ToolCallBlock) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return ``(tool_call, invalid_tool_call)`` exactly like LangChain does."""
    try:
        parsed = json.loads(block.arguments or "{}")
    except ValueError as exc:
        return None, {
            "name": block.name,
            "args": block.arguments,
            "id": block.id,
            "error": str(exc),
        }
    if not isinstance(parsed, dict):
        return None, {
            "name": block.name,
            "args": block.arguments,
            "id": block.id,
            "error": "arguments must decode to a JSON object",
        }
    return {"name": block.name, "args": parsed, "id": block.id, "type": "tool_call"}, None


def _turn_to_message(turn: AssistantTurn) -> AIMessage:
    text = "".join(block.text for block in turn.content if isinstance(block, TextBlock))
    reasoning = "".join(block.text for block in turn.content if isinstance(block, ReasoningBlock))
    tool_calls: list[dict[str, Any]] = []
    invalid_tool_calls: list[dict[str, Any]] = []
    for block in turn.content:
        if not isinstance(block, ToolCallBlock):
            continue
        call, invalid = _tool_call_parts(block)
        if call is not None:
            tool_calls.append(call)
        if invalid is not None:
            invalid_tool_calls.append(invalid)
    additional_kwargs: dict[str, Any] = {}
    if reasoning:
        additional_kwargs["reasoning_content"] = reasoning
    return AIMessage(
        content=text,
        additional_kwargs=additional_kwargs,
        tool_calls=tool_calls,
        invalid_tool_calls=invalid_tool_calls,
        usage_metadata=cast("UsageMetadata", _usage_metadata(turn.usage))
        if turn.usage is not None
        else None,
    )


def _event_to_chunk(event: Any, *, provider: str) -> ChatGenerationChunk | None:
    meta = {"model_provider": provider}
    if isinstance(event, BlockStart | BlockEnd):
        return None
    if isinstance(event, TextDelta):
        return ChatGenerationChunk(
            message=AIMessageChunk(content=event.text, response_metadata=dict(meta))
        )
    if isinstance(event, ReasoningDelta):
        return ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                additional_kwargs={"reasoning_content": event.text},
                response_metadata=dict(meta),
            )
        )
    if isinstance(event, ToolCallDelta):
        entry = ToolCallChunk(
            name=event.name,
            args=event.arguments_delta,
            id=event.wire_id,
            index=event.slot if event.slot is not None else event.index,
            type="tool_call_chunk",
        )
        return ChatGenerationChunk(
            message=AIMessageChunk(
                content="", tool_call_chunks=[entry], response_metadata=dict(meta)
            )
        )
    if isinstance(event, UsageChunk):
        return ChatGenerationChunk(
            message=AIMessageChunk(
                content="", usage_metadata=cast("UsageMetadata", _usage_metadata(event.usage))
            )
        )
    if isinstance(event, FinishChunk):
        if event.failure is not None:
            raise DshModelError(f"provider failure {event.failure.code}: {event.failure.message}")
        return ChatGenerationChunk(
            message=AIMessageChunk(content=""),
            generation_info={"finish_reason": _wire_finish(event.reason)},
        )
    return None


class DshChatModel(BaseChatModel):
    """One provider route served by ``LlmRuntime`` instead of the harness SDK."""

    provider_spec: Any
    model_spec: Any
    transport: Any
    dsh_protocol: str = "openai"
    dsh_max_attempts: int = 1

    @property
    def _llm_type(self) -> str:
        return f"dsh-{self.dsh_protocol}"

    def _build_request(
        self,
        messages: Sequence[BaseMessage],
        stop: Sequence[str] | None,
        kwargs: Mapping[str, Any],
    ) -> LlmRequest:
        system_parts: list[str] = []
        converted: list[Message] = []
        for message in messages:
            role, blocks = _message_blocks(message)
            if role is Role.SYSTEM:
                system_parts.extend(block.text for block in blocks if isinstance(block, TextBlock))
                continue
            converted.append(Message(role=role, content=tuple(blocks)))
        tools: list[ToolSchema] = []
        for raw in kwargs.get("tools") or ():
            if isinstance(raw, Mapping):
                schema = _tool_schema(raw)
                if schema is not None:
                    tools.append(schema)
        stop_values = stop if stop is not None else kwargs.get("stop")
        return LlmRequest(
            provider=str(getattr(self.provider_spec, "id", "")),
            model=str(getattr(self.model_spec, "id", "")),
            messages=tuple(converted),
            system="\n\n".join(part for part in system_parts if part) or None,
            tools=tuple(tools),
            temperature=kwargs.get("temperature"),
            max_tokens=kwargs.get("max_tokens")
            or getattr(self.model_spec, "max_output_tokens", None),
            stop=tuple(stop_values or ()),
        )

    def _runtime(self) -> LlmRuntime:
        return LlmRuntime(
            adapter_for(self.dsh_protocol, self.transport),
            policy=RetryPolicy(max_attempts=max(1, int(self.dsh_max_attempts)), max_compressions=0),
        )

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._agenerate(messages, stop, run_manager, **kwargs))
        raise DshModelError("DshChatModel is async-only; use ainvoke/astream inside a running loop")

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        request = self._build_request(messages, stop, kwargs)
        builder = AssistantTurnBuilder()
        async for event in self._runtime().stream(request):
            if isinstance(event, StepRestart):
                builder.reset()
            elif isinstance(event, UsageDrift):
                continue
            else:
                builder.push(event)
        turn = builder.build()
        if turn.failure is not None:
            raise DshModelError(f"provider failure {turn.failure.code}: {turn.failure.message}")
        generation = ChatGeneration(
            message=_turn_to_message(turn),
            generation_info={"finish_reason": _wire_finish(turn.finish_reason)},
        )
        return ChatResult(generations=[generation])

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        request = self._build_request(messages, stop, kwargs)
        async for event in self._runtime().stream(request):
            if isinstance(event, StepRestart):
                raise DshModelError("DSH runtime restarted the step mid-stream")
            if isinstance(event, UsageDrift):
                continue
            chunk = _event_to_chunk(event, provider=self.dsh_protocol)
            if chunk is not None:
                yield chunk


def build_dsh_chat_model(
    provider: Any,
    model: Any,
    transport: Any,
    *,
    max_attempts: int = 1,
) -> DshChatModel:
    """Build one adapter for an explicitly selected ``provider/model`` ref."""
    protocol = str(getattr(provider, "protocol", "") or "openai").strip().lower()
    if protocol not in {"openai", "anthropic"}:
        raise DshModelError(f"protocol {protocol!r} has no DSH adapter")
    return DshChatModel(
        provider_spec=provider,
        model_spec=model,
        transport=transport,
        dsh_protocol=protocol,
        dsh_max_attempts=max_attempts,
    )
