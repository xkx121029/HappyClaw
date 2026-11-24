"""OpenAI-compatible chat-completions adapter.

Covers OpenAI itself and every gateway that speaks the same wire protocol
(Ollama, Azure, most relays). The adapter only translates; auth headers,
base URLs, and proxies belong to the injected transport.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Mapping
from dataclasses import dataclass, field
from typing import Any

from happyclaw.infra.dsh.llm.adapter import ChunkStream, RawChunkStream, Transport
from happyclaw.infra.dsh.llm.errors import (
    FailureCode,
    ProviderFailure,
    failure_from_error_payload,
)
from happyclaw.infra.dsh.llm.types import (
    BlockEnd,
    BlockKind,
    BlockStart,
    FinishChunk,
    FinishReason,
    LlmRequest,
    Message,
    ReasoningBlock,
    ReasoningDelta,
    Role,
    StreamChunk,
    TextBlock,
    TextDelta,
    TokenUsage,
    ToolCallBlock,
    ToolCallDelta,
    ToolResultBlock,
    UsageChunk,
)

__all__ = ["OpenAICompatibleAdapter", "build_payload", "parse_usage"]

_FINISH_REASONS: dict[str, FinishReason] = {
    "stop": FinishReason.STOP,
    "end_turn": FinishReason.STOP,
    "stop_sequence": FinishReason.STOP,
    "tool_calls": FinishReason.TOOL_CALLS,
    "function_call": FinishReason.TOOL_CALLS,
    "length": FinishReason.MAX_TOKENS,
    "max_tokens": FinishReason.MAX_TOKENS,
}


def _int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        return max(int(value), 0)
    if isinstance(value, str):
        try:
            return max(int(value), 0)
        except ValueError:
            return 0
    return 0


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _sequence(value: Any) -> list[Any] | None:
    return value if isinstance(value, list) else None


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    parts = _sequence(content)
    if parts is None:
        return ""
    chunks: list[str] = []
    for part in parts:
        item = _mapping(part)
        if item is not None and item.get("type") in (None, "text"):
            chunks.append(_str(item.get("text")))
    return "".join(chunks)


def _message_payload(message: Message) -> list[dict[str, Any]]:
    if message.role is Role.TOOL:
        payloads: list[dict[str, Any]] = []
        for block in message.content:
            if isinstance(block, ToolResultBlock):
                tool_payload: dict[str, Any] = {
                    "role": "tool",
                    "tool_call_id": block.tool_call_id,
                    "content": block.content,
                }
                payloads.append(tool_payload)
        return payloads

    text = "".join(
        block.text for block in message.content if isinstance(block, (TextBlock, ReasoningBlock))
    )
    payload: dict[str, Any] = {"role": message.role.value, "content": text}
    calls = [block for block in message.content if isinstance(block, ToolCallBlock)]
    if calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in calls
        ]
    return [payload]


def build_payload(request: LlmRequest) -> dict[str, Any]:
    """Translate one canonical request into a chat-completions payload.

    Usage is requested inside the stream because the runtime audits estimates
    against provider numbers; a vendor that rejects ``stream_options`` omits
    usage instead and the audit stays silent.
    """
    messages: list[dict[str, Any]] = []
    if request.system:
        messages.append({"role": "system", "content": request.system})
    for message in request.messages:
        messages.extend(_message_payload(message))

    payload: dict[str, Any] = {
        "model": request.model,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.max_tokens is not None:
        payload["max_tokens"] = request.max_tokens
    if request.stop:
        payload["stop"] = list(request.stop)
    if request.tools:
        payload["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": dict(tool.parameters),
                },
            }
            for tool in request.tools
        ]
    return payload


def parse_usage(value: Mapping[str, Any]) -> TokenUsage:
    """Normalize prompt/completion counters into disjoint cache-aware counts."""
    prompt = _int(value.get("prompt_tokens"))
    prompt_details = _mapping(value.get("prompt_tokens_details")) or {}
    cached = min(_int(prompt_details.get("cached_tokens")), prompt)
    completion_details = _mapping(value.get("completion_tokens_details")) or {}
    total = value.get("total_tokens")
    reported = set()
    if prompt_details.get("cached_tokens") is not None:
        reported.add("cache_read")
    if completion_details.get("reasoning_tokens") is not None:
        reported.add("reasoning")
    return TokenUsage(
        input_tokens=prompt - cached,
        output_tokens=_int(value.get("completion_tokens")),
        total_tokens=_int(total) if total is not None else None,
        cache_read_tokens=cached,
        reasoning_tokens=_int(completion_details.get("reasoning_tokens")),
        reported_details=frozenset(reported),
    )


@dataclass(slots=True)
class _TextState:
    index: int
    parts: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _ToolState:
    index: int
    call_id: str
    name: str
    parts: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _StreamState:
    next_index: int = 0
    text: _TextState | None = None
    reasoning: _TextState | None = None
    tools: dict[int, _ToolState] = field(default_factory=dict)
    finish_reason: FinishReason | None = None
    usage: TokenUsage | None = None

    def allocate(self) -> int:
        index = self.next_index
        self.next_index += 1
        return index


class OpenAICompatibleAdapter:
    """Translates one OpenAI-compatible route."""

    def __init__(self, transport: Transport, *, name: str = "openai") -> None:
        self.name = name
        self._transport = transport

    def start(self, request: LlmRequest) -> ChunkStream:
        return self._translate(self._transport.stream(build_payload(request)))

    async def _translate(self, raw: RawChunkStream) -> AsyncGenerator[StreamChunk, None]:
        state = _StreamState()
        try:
            async for chunk in raw:
                if "error" in chunk:
                    raise failure_from_error_payload(chunk)
                usage = _mapping(chunk.get("usage"))
                if usage is not None:
                    state.usage = parse_usage(usage)
                choices = _sequence(chunk.get("choices"))
                if not choices:
                    continue
                for choice in choices:
                    entry = _mapping(choice)
                    if entry is None:
                        continue
                    delta = _mapping(entry.get("delta")) or {}
                    for event in self._translate_delta(state, delta):
                        yield event
                    finish = entry.get("finish_reason")
                    if isinstance(finish, str) and finish:
                        state.finish_reason = _FINISH_REASONS.get(finish, FinishReason.STOP)

            finish_reason = state.finish_reason
            if finish_reason is None:
                raise ProviderFailure(
                    FailureCode.TRANSPORT,
                    "provider stream ended before finish_reason",
                )
            if state.usage is not None:
                yield UsageChunk(state.usage)
            for event in self._close_blocks(state):
                yield event
            yield FinishChunk(finish_reason)
        finally:
            await raw.aclose()

    def _translate_delta(self, state: _StreamState, delta: Mapping[str, Any]) -> list[StreamChunk]:
        events: list[StreamChunk] = []

        reasoning = _str(delta.get("reasoning_content")) or _str(delta.get("reasoning"))
        if reasoning:
            if state.reasoning is None:
                state.reasoning = _TextState(state.allocate())
                events.append(BlockStart(state.reasoning.index, BlockKind.REASONING))
            state.reasoning.parts.append(reasoning)
            events.append(ReasoningDelta(state.reasoning.index, reasoning))

        content = _content_text(delta.get("content"))
        if content:
            if state.text is None:
                state.text = _TextState(state.allocate())
                events.append(BlockStart(state.text.index, BlockKind.TEXT))
            state.text.parts.append(content)
            events.append(TextDelta(state.text.index, content))

        calls = _sequence(delta.get("tool_calls"))
        if calls is not None:
            for position, candidate in enumerate(calls):
                call = _mapping(candidate)
                if call is None:
                    continue
                slot = _int(call.get("index")) if call.get("index") is not None else position
                function = _mapping(call.get("function")) or {}
                current = state.tools.get(slot)
                if current is None:
                    call_id = _str(call.get("id")) or f"tool_call_{slot}"
                    name = _str(function.get("name"))
                    current = _ToolState(state.allocate(), call_id, name)
                    state.tools[slot] = current
                    events.append(BlockStart(current.index, BlockKind.TOOL_CALL))
                arguments = _str(function.get("arguments"))
                if arguments:
                    current.parts.append(arguments)
                events.append(
                    ToolCallDelta(
                        index=current.index,
                        tool_call_id=current.call_id,
                        arguments_delta=arguments,
                        name=_str(function.get("name")) or None,
                        wire_id=_str(call.get("id")) or None,
                        slot=slot,
                    )
                )
        return events

    def _close_blocks(self, state: _StreamState) -> list[StreamChunk]:
        events: list[StreamChunk] = []
        blocks: list[tuple[int, TextBlock | ReasoningBlock | ToolCallBlock]] = []
        if state.reasoning is not None:
            blocks.append((state.reasoning.index, ReasoningBlock("".join(state.reasoning.parts))))
        if state.text is not None:
            blocks.append((state.text.index, TextBlock("".join(state.text.parts))))
        for tool in state.tools.values():
            blocks.append((tool.index, ToolCallBlock(tool.call_id, tool.name, "".join(tool.parts))))
        for index, block in sorted(blocks, key=lambda item: item[0]):
            events.append(BlockEnd(index, block))
        return events
