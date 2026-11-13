"""Anthropic Messages adapter.

Anthropic differs from chat-completions in three places the seam must absorb:
the system prompt is a top-level field, tools carry ``input_schema``, and the
stream is an event protocol rather than choice deltas. Everything above this
file sees the same canonical chunks.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Mapping
from dataclasses import dataclass, field
from typing import Any

from octop.infra.dsh.llm.adapter import ChunkStream, RawChunkStream, Transport
from octop.infra.dsh.llm.errors import (
    FailureCode,
    ProviderFailure,
    failure_from_error_payload,
)
from octop.infra.dsh.llm.types import (
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

__all__ = ["AnthropicAdapter", "build_payload"]

_STOP_REASONS: dict[str, FinishReason] = {
    "end_turn": FinishReason.STOP,
    "stop_sequence": FinishReason.STOP,
    "pause_turn": FinishReason.STOP,
    "tool_use": FinishReason.TOOL_CALLS,
    "max_tokens": FinishReason.MAX_TOKENS,
}

_BLOCK_KINDS: dict[str, BlockKind] = {
    "text": BlockKind.TEXT,
    "thinking": BlockKind.REASONING,
    "tool_use": BlockKind.TOOL_CALL,
}


def _int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        return max(int(value), 0)
    return 0


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _sequence(value: Any) -> list[Any] | None:
    return value if isinstance(value, list) else None


def _message_payload(message: Message) -> dict[str, Any]:
    if message.role is Role.TOOL:
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": block.tool_call_id,
                    "content": block.content,
                    "is_error": block.is_error,
                }
                for block in message.content
                if isinstance(block, ToolResultBlock)
            ],
        }
    content: list[dict[str, Any]] = []
    for block in message.content:
        if isinstance(block, TextBlock):
            content.append({"type": "text", "text": block.text})
        elif isinstance(block, ToolResultBlock):
            content.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.tool_call_id,
                    "content": block.content,
                    "is_error": block.is_error,
                }
            )
        elif isinstance(block, ToolCallBlock):
            try:
                arguments = block.parsed_arguments()
            except ValueError as exc:
                raise ProviderFailure(
                    FailureCode.INVALID_REQUEST,
                    f"assistant tool call {block.name!r} has non-object arguments",
                ) from exc
            content.append(
                {
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": arguments,
                }
            )
        # Reasoning blocks are provider-signed state; replaying them without
        # the signature is invalid, so they are intentionally dropped.
    return {"role": message.role.value, "content": content}


def build_payload(request: LlmRequest) -> dict[str, Any]:
    """Translate one canonical request into a Messages payload.

    ``max_tokens`` is required by Anthropic; a missing value fails as an
    invalid request instead of silently picking a truncation point.
    """
    if request.max_tokens is None:
        raise ProviderFailure(
            FailureCode.INVALID_REQUEST,
            "anthropic requests require max_tokens",
        )
    payload: dict[str, Any] = {
        "model": request.model,
        "max_tokens": request.max_tokens,
        "messages": [
            _message_payload(message)
            for message in request.messages
            if message.role in (Role.USER, Role.ASSISTANT, Role.TOOL)
        ],
        "stream": True,
    }
    if request.system:
        payload["system"] = request.system
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.stop:
        payload["stop_sequences"] = list(request.stop)
    if request.tools:
        payload["tools"] = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": dict(tool.parameters),
            }
            for tool in request.tools
        ]
    return payload


@dataclass(slots=True)
class _BlockState:
    index: int
    kind: BlockKind
    parts: list[str] = field(default_factory=list)
    call_id: str = ""
    name: str = ""


@dataclass(slots=True)
class _StreamState:
    blocks: dict[int, _BlockState] = field(default_factory=dict)
    open_blocks: set[int] = field(default_factory=set)
    finish_reason: FinishReason | None = None
    usage: TokenUsage | None = None
    stopped: bool = False


class AnthropicAdapter:
    """Translates one Anthropic Messages route."""

    name = "anthropic"

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def start(self, request: LlmRequest) -> ChunkStream:
        return self._translate(self._transport.stream(build_payload(request)))

    async def _translate(self, raw: RawChunkStream) -> AsyncGenerator[StreamChunk, None]:
        state = _StreamState()
        try:
            async for event in raw:
                event_type = _str(event.get("type"))
                if event_type == "error":
                    raise failure_from_error_payload(event)
                if event_type == "message_start":
                    self._record_message_usage(state, event)
                elif event_type == "content_block_start":
                    for chunk in self._start_block(state, event):
                        yield chunk
                elif event_type == "content_block_delta":
                    for chunk in self._translate_delta(state, event):
                        yield chunk
                elif event_type == "content_block_stop":
                    for chunk in self._close_block(state, _int(event.get("index"))):
                        yield chunk
                elif event_type == "message_delta":
                    self._record_message_delta(state, event)
                elif event_type == "message_stop":
                    state.stopped = True

            if not state.stopped:
                raise ProviderFailure(
                    FailureCode.TRANSPORT,
                    "anthropic stream ended before message_stop",
                )
            finish_reason = state.finish_reason
            if finish_reason is None:
                raise ProviderFailure(
                    FailureCode.TRANSPORT,
                    "anthropic stream ended before stop_reason",
                )
            if state.usage is not None:
                yield UsageChunk(state.usage)
            for index in sorted(state.open_blocks):
                for chunk in self._close_block(state, index):
                    yield chunk
            yield FinishChunk(finish_reason)
        finally:
            await raw.aclose()

    def _record_message_usage(self, state: _StreamState, event: Mapping[str, Any]) -> None:
        message = _mapping(event.get("message")) or {}
        usage = _mapping(message.get("usage"))
        if usage is None:
            return
        reported = set()
        if usage.get("cache_read_input_tokens") is not None:
            reported.add("cache_read")
        if usage.get("cache_creation_input_tokens") is not None:
            reported.add("cache_write")
        state.usage = TokenUsage(
            input_tokens=_int(usage.get("input_tokens")),
            output_tokens=_int(usage.get("output_tokens")),
            cache_read_tokens=_int(usage.get("cache_read_input_tokens")),
            cache_write_tokens=_int(usage.get("cache_creation_input_tokens")),
            reported_details=frozenset(reported),
        )

    def _record_message_delta(self, state: _StreamState, event: Mapping[str, Any]) -> None:
        delta = _mapping(event.get("delta")) or {}
        stop_reason = _str(delta.get("stop_reason"))
        if stop_reason:
            state.finish_reason = _STOP_REASONS.get(stop_reason, FinishReason.STOP)
        usage = _mapping(event.get("usage"))
        if usage is not None and state.usage is not None:
            output = _int(usage.get("output_tokens"))
            if output:
                state.usage = TokenUsage(
                    input_tokens=state.usage.input_tokens,
                    output_tokens=output,
                    cache_read_tokens=state.usage.cache_read_tokens,
                    cache_write_tokens=state.usage.cache_write_tokens,
                    reasoning_tokens=state.usage.reasoning_tokens,
                    reported_details=state.usage.reported_details,
                )

    def _start_block(self, state: _StreamState, event: Mapping[str, Any]) -> list[StreamChunk]:
        index = _int(event.get("index"))
        block = _mapping(event.get("content_block")) or {}
        kind = _BLOCK_KINDS.get(_str(block.get("type")), BlockKind.TEXT)
        current = _BlockState(
            index=index,
            kind=kind,
            call_id=_str(block.get("id")),
            name=_str(block.get("name")),
        )
        state.blocks[index] = current
        state.open_blocks.add(index)
        events: list[StreamChunk] = [BlockStart(index, kind)]
        initial = _str(block.get("text"))
        if initial:
            current.parts.append(initial)
            events.append(TextDelta(index, initial))
        return events

    def _translate_delta(
        self, state: _StreamState, event: Mapping[str, Any]
    ) -> list[StreamChunk]:
        index = _int(event.get("index"))
        current = state.blocks.get(index)
        delta = _mapping(event.get("delta")) or {}
        if current is None:
            return []
        delta_type = _str(delta.get("type"))
        if delta_type == "text_delta":
            text = _str(delta.get("text"))
            if not text:
                return []
            current.parts.append(text)
            return [TextDelta(index, text)]
        if delta_type == "thinking_delta":
            text = _str(delta.get("thinking"))
            if not text:
                return []
            current.parts.append(text)
            return [ReasoningDelta(index, text)]
        if delta_type == "input_json_delta":
            fragment = _str(delta.get("partial_json"))
            if not fragment:
                return []
            current.parts.append(fragment)
            return [
                ToolCallDelta(
                    index=index,
                    tool_call_id=current.call_id,
                    arguments_delta=fragment,
                )
            ]
        return []

    def _close_block(self, state: _StreamState, index: int) -> list[StreamChunk]:
        current = state.blocks.get(index)
        if current is None or index not in state.open_blocks:
            return []
        state.open_blocks.discard(index)
        text = "".join(current.parts)
        if current.kind is BlockKind.TOOL_CALL:
            block = ToolCallBlock(current.call_id, current.name, text)
        elif current.kind is BlockKind.REASONING:
            block = ReasoningBlock(text)
        else:
            block = TextBlock(text)
        return [BlockEnd(index, block)]
