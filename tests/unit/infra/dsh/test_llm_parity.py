"""S8 parity: harness ``ChatModelFactory`` vs the DSH LangChain adapter.

The same fixed wire payloads are fed to both sides. The reference side calls
LangChain OpenAI's own parsing helpers (the exact code the harness model uses
after the HTTP layer); the adapter side runs the real ``LlmRuntime`` over a
scripted transport. Projections are compared field by field, and a missing
field is reported as ``<missing>`` instead of being defaulted away.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from langchain_core.messages import AIMessageChunk, HumanMessage
from happyclaw_harness.config import ModelConfig, ProviderConfig
from happyclaw_harness.llm.factory import ChatModelFactory

from octop.infra.dsh.llm.langchain_model import build_dsh_chat_model

MISSING = "<missing>"

COMPLETION: dict[str, Any] = {
    "id": "chatcmpl-parity",
    "object": "chat.completion",
    "created": 1,
    "model": "m",
    "system_fingerprint": "fp_parity",
    "choices": [
        {
            "index": 0,
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "content": "hello",
                "reasoning_content": "think",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "search", "arguments": '{"q":"x"}'},
                    }
                ],
            },
        }
    ],
    "usage": {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
        "prompt_tokens_details": {"cached_tokens": 3},
        "completion_tokens_details": {"reasoning_tokens": 2},
    },
}

STREAM_CHUNKS: list[dict[str, Any]] = [
    {
        "id": "chatcmpl-parity",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "m",
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "reasoning_content": "thi"},
                "finish_reason": None,
            }
        ],
    },
    {
        "choices": [
            {
                "index": 0,
                "delta": {"reasoning_content": "nk", "content": "hel"},
                "finish_reason": None,
            }
        ]
    },
    {
        "choices": [
            {"index": 0, "delta": {"content": "lo"}, "finish_reason": None}
        ]
    },
    {
        "choices": [
            {
                "index": 0,
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "search", "arguments": '{"q":'},
                        }
                    ]
                },
                "finish_reason": None,
            }
        ]
    },
    {
        "choices": [
            {
                "index": 0,
                "delta": {
                    "tool_calls": [{"index": 0, "function": {"arguments": '"x"}'}}]
                },
                "finish_reason": "tool_calls",
            }
        ],
        "model": "m",
    },
    {"choices": [], "usage": copy.deepcopy(COMPLETION["usage"])},
]


class _ScriptedStream:
    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        self._chunks = chunks

    def __aiter__(self):
        async def generate():
            for chunk in self._chunks:
                yield copy.deepcopy(chunk)

        return generate()

    async def aclose(self) -> None:
        return None


class ScriptedTransport:
    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        self.chunks = chunks
        self.requests: list[dict[str, Any]] = []

    def stream(self, request):
        self.requests.append(copy.deepcopy(dict(request)))
        return _ScriptedStream(self.chunks)


def _provider() -> ProviderConfig:
    return ProviderConfig(
        id="p",
        base_url="https://example.invalid/v1",
        api_key="k",
        models=[ModelConfig(id="m")],
    )


def _reference_model() -> Any:
    provider = _provider()
    return ChatModelFactory([provider]).get_chat_model("p/m")


def _adapter_model(transport: ScriptedTransport) -> Any:
    provider = _provider()
    return build_dsh_chat_model(provider, provider.models[0], transport)


def _project_usage(usage: Any) -> Any:
    if usage is None:
        return None
    return {
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "input_token_details": dict(usage.get("input_token_details") or {}),
        "output_token_details": dict(usage.get("output_token_details") or {}),
    }


def _project_message(message: Any) -> dict[str, Any]:
    kwargs = message.additional_kwargs or {}
    return {
        "type": message.type,
        "content": message.content,
        "reasoning": kwargs.get("reasoning_content", MISSING),
        "tool_calls": [
            {key: call.get(key) for key in ("name", "args", "id", "type")}
            for call in message.tool_calls
        ],
        "invalid_tool_calls": [
            {key: call.get(key) for key in ("name", "args", "id", "error")}
            for call in message.invalid_tool_calls
        ],
        "usage": _project_usage(message.usage_metadata),
        "response_metadata": dict(message.response_metadata),
    }


def _project_stream(chunks: list[Any]) -> dict[str, Any]:
    text: list[str] = []
    reasoning: list[str] = []
    tool_call_chunks: list[dict[str, Any]] = []
    usage = None
    finish_reason = None
    response_metadata: dict[str, Any] = {}
    for chunk in chunks:
        message = chunk.message
        if message.content:
            text.append(str(message.content))
        if (message.additional_kwargs or {}).get("reasoning_content"):
            reasoning.append(str(message.additional_kwargs["reasoning_content"]))
        for entry in message.tool_call_chunks or ():
            tool_call_chunks.append(
                {key: entry.get(key) for key in ("name", "args", "id", "index", "type")}
            )
        if message.usage_metadata:
            usage = _project_usage(message.usage_metadata)
        if chunk.generation_info and "finish_reason" in chunk.generation_info:
            finish_reason = chunk.generation_info["finish_reason"]
        response_metadata.update(message.response_metadata or {})
    return {
        "text": "".join(text),
        "reasoning": "".join(reasoning),
        "tool_call_chunks": tool_call_chunks,
        "usage": usage,
        "finish_reason": finish_reason,
        "response_metadata": response_metadata,
    }


def assert_parity(reference: dict[str, Any], actual: dict[str, Any]) -> None:
    """Fail with an explicit field list instead of a defaulted value."""
    missing = sorted(set(reference) - set(actual))
    extra = sorted(set(actual) - set(reference))
    assert not missing, f"adapter is missing fields: {missing}"
    assert not extra, f"adapter produced unexpected fields: {extra}"
    for key in reference:
        assert actual[key] == reference[key], (
            f"field {key!r} differs: reference={reference[key]!r} adapter={actual[key]!r}"
        )


def test_non_stream_message_matches_harness_field_by_field() -> None:
    reference = _reference_model()
    reference_message = reference._create_chat_result(copy.deepcopy(COMPLETION)).generations[0].message

    transport = ScriptedTransport(STREAM_CHUNKS)
    adapter = _adapter_model(transport)
    adapter_message = adapter._generate([HumanMessage(content="hi")]).generations[0].message

    assert_parity(_project_message(reference_message), _project_message(adapter_message))


async def test_stream_chunks_match_harness_field_by_field() -> None:
    reference = _reference_model()
    reference_chunks = []
    for raw in copy.deepcopy(STREAM_CHUNKS):
        chunk = reference._convert_chunk_to_generation_chunk(raw, AIMessageChunk, None)
        if chunk is not None:
            reference_chunks.append(chunk)

    transport = ScriptedTransport(STREAM_CHUNKS)
    adapter = _adapter_model(transport)
    adapter_chunks = [chunk async for chunk in adapter._astream([HumanMessage(content="hi")])]

    assert_parity(_project_stream(reference_chunks), _project_stream(adapter_chunks))


async def test_accumulated_stream_message_matches_harness() -> None:
    reference = _reference_model()
    reference_chunks = []
    for raw in copy.deepcopy(STREAM_CHUNKS):
        chunk = reference._convert_chunk_to_generation_chunk(raw, AIMessageChunk, None)
        if chunk is not None:
            reference_chunks.append(chunk)
    reference_message = sum(reference_chunks[1:], reference_chunks[0]).message

    transport = ScriptedTransport(STREAM_CHUNKS)
    adapter = _adapter_model(transport)
    chunks = [chunk async for chunk in adapter._astream([HumanMessage(content="hi")])]
    adapter_message = sum(chunks[1:], chunks[0]).message

    assert_parity(_project_message(reference_message), _project_message(adapter_message))


def test_missing_field_is_reported_not_defaulted() -> None:
    reference = _reference_model()
    reference_message = reference._create_chat_result(copy.deepcopy(COMPLETION)).generations[0].message
    projected = _project_message(reference_message)
    projected.pop("reasoning")

    with pytest.raises(AssertionError, match="missing fields: \\['reasoning'\\]"):
        assert_parity(_project_message(reference_message), projected)


def test_reasoning_and_usage_are_present_without_fallback_defaults() -> None:
    reference = _reference_model()
    message = reference._create_chat_result(copy.deepcopy(COMPLETION)).generations[0].message
    projected = _project_message(message)

    assert projected["reasoning"] == "think"
    assert projected["usage"] == {
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
        "input_token_details": {"cache_read": 3},
        "output_token_details": {"reasoning": 2},
    }
