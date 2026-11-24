"""Unit tests for the DSH LLM seam: adapter translation and fake-provider e2e."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any

import pytest

from happyclaw.infra.dsh.llm import (
    AnthropicAdapter,
    AssistantTurnBuilder,
    CancellationToken,
    FailureCode,
    FinishChunk,
    FinishReason,
    LlmRequest,
    LlmRuntime,
    Message,
    OpenAICompatibleAdapter,
    ReasoningBlock,
    Role,
    StepRestart,
    TextBlock,
    TokenAuditPolicy,
    ToolSchema,
    UsageDrift,
    adapter_for,
    text_message,
)


class _RawStream:
    def __init__(self, items: list[Any]) -> None:
        self._items = items
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[Mapping[str, Any]]:
        for item in self._items:
            if isinstance(item, Exception):
                raise item
            yield item

    async def aclose(self) -> None:
        self.closed = True


class ScriptedTransport:
    """In-memory wire transport: one script of decoded JSON frames per request."""

    def __init__(self, scripts: list[list[Any]]) -> None:
        self.scripts = list(scripts)
        self.requests: list[Mapping[str, Any]] = []
        self.streams: list[_RawStream] = []

    def stream(self, request: Mapping[str, Any]) -> _RawStream:
        self.requests.append(request)
        stream = _RawStream(self.scripts.pop(0))
        self.streams.append(stream)
        return stream


async def _collect(
    runtime: LlmRuntime,
    request: LlmRequest,
    *,
    cancel: CancellationToken | None = None,
) -> tuple[list[Any], Any]:
    events: list[Any] = []
    builder = AssistantTurnBuilder()
    async for event in runtime.stream(request, cancel=cancel):
        events.append(event)
        if isinstance(event, StepRestart):
            builder.reset()
        elif isinstance(event, UsageDrift):
            continue
        else:
            builder.push(event)
    return events, builder.build()


def _request(**overrides: Any) -> LlmRequest:
    base: dict[str, Any] = {
        "provider": "openai",
        "model": "test-model",
        "system": "Be terse.",
        "messages": (text_message(Role.USER, "你好"),),
        "tools": (ToolSchema("read_file", "Read a file", {"type": "object"}),),
        "temperature": 0.2,
        "max_tokens": 64,
    }
    base.update(overrides)
    return LlmRequest(**base)


async def test_openai_fake_provider_end_to_end() -> None:
    transport = ScriptedTransport(
        [
            [
                {"choices": [{"delta": {"role": "assistant"}}]},
                {"choices": [{"delta": {"content": "你好"}}]},
                {"choices": [{"delta": {"content": " world"}}]},
                {"choices": [{"delta": {}, "finish_reason": "stop"}]},
                {
                    "choices": [],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 7, "total_tokens": 107},
                },
            ]
        ]
    )
    runtime = LlmRuntime(OpenAICompatibleAdapter(transport, name="openai"))

    events, turn = await _collect(runtime, _request())

    payload = transport.requests[0]
    assert payload["model"] == "test-model"
    assert payload["stream"] is True
    assert payload["messages"] == [
        {"role": "system", "content": "Be terse."},
        {"role": "user", "content": "你好"},
    ]
    assert payload["tools"][0]["function"]["name"] == "read_file"

    assert isinstance(turn.content[0], TextBlock)
    assert turn.content[0].text == "你好 world"
    assert turn.finish_reason is FinishReason.STOP
    assert turn.incomplete is False
    assert turn.usage is not None
    assert turn.usage.input_tokens == 100
    assert turn.usage.output_tokens == 7
    assert turn.usage.resolved_total() == 107
    assert isinstance(events[-1], FinishChunk)
    assert transport.streams[0].closed is True


async def test_openai_tool_call_stream_normalizes_to_one_block() -> None:
    transport = ScriptedTransport(
        [
            [
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_1",
                                        "function": {"name": "read_file", "arguments": '{"pa'},
                                    }
                                ]
                            }
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {"index": 0, "function": {"arguments": 'th":"a.txt"}'}}
                                ]
                            }
                        }
                    ]
                },
                {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
            ]
        ]
    )
    runtime = LlmRuntime(OpenAICompatibleAdapter(transport))

    _, turn = await _collect(runtime, _request())

    assert turn.finish_reason is FinishReason.TOOL_CALLS
    assert len(turn.tool_calls) == 1
    call = turn.tool_calls[0]
    assert (call.id, call.name) == ("call_1", "read_file")
    assert call.parsed_arguments() == {"path": "a.txt"}


async def test_anthropic_fake_provider_end_to_end() -> None:
    transport = ScriptedTransport(
        [
            [
                {
                    "type": "message_start",
                    "message": {
                        "usage": {
                            "input_tokens": 40,
                            "output_tokens": 1,
                            "cache_read_input_tokens": 10,
                        }
                    },
                },
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "thinking", "thinking": ""},
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "thinking_delta", "thinking": "plan"},
                },
                {"type": "content_block_stop", "index": 0},
                {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {"type": "text", "text": ""},
                },
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {"type": "text_delta", "text": "hi"},
                },
                {"type": "content_block_stop", "index": 1},
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn"},
                    "usage": {"output_tokens": 5},
                },
                {"type": "message_stop"},
            ]
        ]
    )
    runtime = LlmRuntime(AnthropicAdapter(transport))

    _, turn = await _collect(
        runtime,
        _request(provider="anthropic", system="sys", max_tokens=32),
    )

    payload = transport.requests[0]
    assert payload["system"] == "sys"
    assert payload["max_tokens"] == 32
    assert payload["messages"][0]["role"] == "user"

    assert isinstance(turn.content[0], ReasoningBlock)
    assert turn.content[0].text == "plan"
    assert isinstance(turn.content[1], TextBlock)
    assert turn.content[1].text == "hi"
    assert turn.finish_reason is FinishReason.STOP
    assert turn.usage is not None
    assert turn.usage.input_tokens == 40
    assert turn.usage.cache_read_tokens == 10
    assert turn.usage.billed_input_tokens == 50
    assert turn.usage.output_tokens == 5


async def test_anthropic_missing_max_tokens_fails_without_retry() -> None:
    transport = ScriptedTransport([])
    runtime = LlmRuntime(AnthropicAdapter(transport))

    events, turn = await _collect(
        runtime,
        _request(provider="anthropic", max_tokens=None),
        cancel=None,
    )

    assert transport.requests == []
    assert turn.finish_reason is FinishReason.ERROR
    assert turn.failure is not None
    assert turn.failure.code == FailureCode.INVALID_REQUEST
    assert not any(isinstance(event, StepRestart) for event in events)


def test_adapter_for_routes_known_kinds() -> None:
    transport = ScriptedTransport([])
    assert isinstance(adapter_for("anthropic", transport), AnthropicAdapter)
    assert isinstance(adapter_for("OpenAI", transport), OpenAICompatibleAdapter)
    assert isinstance(adapter_for("custom-gateway", transport), OpenAICompatibleAdapter)


def test_token_audit_policy_rejects_bad_threshold() -> None:
    with pytest.raises(ValueError):
        TokenAuditPolicy(ratio_threshold=0.0)


def test_message_requires_explicit_role() -> None:
    message = Message(role=Role.USER, content=(TextBlock("x"),))
    assert message.role is Role.USER
