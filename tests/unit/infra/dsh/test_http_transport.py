"""Real-socket tests for the httpx transports.

Everything runs against an ``asyncio`` HTTP server on ``127.0.0.1`` with a
random port; no external network is touched.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from langchain_core.messages import HumanMessage
from happyclaw_harness.config import ModelConfig, ProviderConfig
from happyclaw_harness.llm.factory import ChatModelFactory

from happyclaw.infra.dsh.llm.errors import FailureCode, ProviderFailure
from happyclaw.infra.dsh.llm.factory import DshModelFactory
from happyclaw.infra.dsh.llm.http_transport import (
    build_http_transport,
    is_loopback_url,
)
from happyclaw.infra.dsh.llm.langchain_model import DshChatModel

Handler = Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]]

OPENAI_FRAMES: list[dict[str, Any]] = [
    {
        "id": "chatcmpl-real",
        "object": "chat.completion.chunk",
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
    {"choices": [{"index": 0, "delta": {"content": "lo"}, "finish_reason": None}]},
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
        ]
    },
    {
        "choices": [],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "prompt_tokens_details": {"cached_tokens": 3},
            "completion_tokens_details": {"reasoning_tokens": 2},
        },
    },
]

ANTHROPIC_FRAMES: list[dict[str, Any]] = [
    {
        "type": "message_start",
        "message": {
            "id": "msg_1",
            "role": "assistant",
            "content": [],
            "usage": {
                "input_tokens": 4,
                "output_tokens": 1,
                "cache_read_input_tokens": 2,
                "cache_creation_input_tokens": 0,
            },
        },
    },
    {
        "type": "content_block_start",
        "index": 0,
        "content_block": {"type": "text", "text": ""},
    },
    {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "text_delta", "text": "hi"},
    },
    {"type": "content_block_stop", "index": 0},
    {
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn"},
        "usage": {"output_tokens": 2},
    },
    {"type": "message_stop"},
]


def _enable(monkeypatch: pytest.MonkeyPatch, refs: str = "p/m") -> None:
    monkeypatch.setenv("OCTOP_DSH_RUNTIME", "1")
    monkeypatch.setenv("OCTOP_DSH_LLM", "1")
    monkeypatch.setenv("OCTOP_DSH_LLM_REFS", refs)


def _provider(port: int, *, protocol: str = "openai") -> ProviderConfig:
    return ProviderConfig(
        id="p",
        base_url=f"http://127.0.0.1:{port}/v1",
        api_key="k",
        protocol=protocol,
        models=[ModelConfig(id="m", max_output_tokens=64)],
    )


async def _serve(handler: Handler) -> tuple[asyncio.AbstractServer, int]:
    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port


async def _read_request(
    reader: asyncio.StreamReader,
) -> tuple[str, dict[str, str], bytes]:
    raw = await reader.readuntil(b"\r\n\r\n")
    lines = raw.decode("latin-1").split("\r\n")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line:
            continue
        key, _, value = line.partition(":")
        headers[key.strip().lower()] = value.strip()
    length = int(headers.get("content-length", "0") or 0)
    body = await reader.readexactly(length) if length else b""
    return lines[0], headers, body


def _sse_head(*, chunked: bool = False) -> bytes:
    encoding = "Transfer-Encoding: chunked\r\n" if chunked else ""
    return (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: text/event-stream\r\n"
        "Cache-Control: no-cache\r\n"
        "Connection: close\r\n"
        f"{encoding}"
        "\r\n"
    ).encode()


async def _write_frames(
    writer: asyncio.StreamWriter, frames: list[dict[str, Any]]
) -> None:
    for frame in frames:
        writer.write(f"data: {json.dumps(frame)}\n\n".encode())
        await writer.drain()


async def _finish(writer: asyncio.StreamWriter, *, done: bool = True) -> None:
    if done:
        writer.write(b"data: [DONE]\n\n")
        await writer.drain()
    writer.close()
    await writer.wait_closed()


async def test_fixture_ref_streams_through_a_real_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        line, headers, body = await _read_request(reader)
        captured.update(
            line=line, headers=headers, body=json.loads(body.decode("utf-8"))
        )
        writer.write(_sse_head())
        await writer.drain()
        await _write_frames(writer, OPENAI_FRAMES)
        await _finish(writer)

    server, port = await _serve(handler)
    try:
        _enable(monkeypatch)
        provider = _provider(port)
        wrapper = DshModelFactory(
            ChatModelFactory([provider]),
            refs={"p/m"},
            transport_factory=build_http_transport,
        )
        model = wrapper.get_chat_model("p/m")
        assert isinstance(model, DshChatModel)
        chunks = [chunk async for chunk in model._astream([HumanMessage(content="hi")])]
    finally:
        server.close()
        await server.wait_closed()

    text = "".join(str(chunk.message.content) for chunk in chunks)
    reasoning = "".join(
        str(chunk.message.additional_kwargs.get("reasoning_content") or "")
        for chunk in chunks
    )
    tool_parts = [
        part for chunk in chunks for part in chunk.message.tool_call_chunks
    ]
    usage = next(
        chunk.message.usage_metadata
        for chunk in chunks
        if chunk.message.usage_metadata is not None
    )
    finish = next(
        chunk.generation_info["finish_reason"]
        for chunk in chunks
        if chunk.generation_info
    )

    assert text == "hello"
    assert reasoning == "think"
    assert [part["name"] for part in tool_parts] == ["search", None]
    assert [part["args"] for part in tool_parts] == ['{"q":', '"x"}']
    assert [part["id"] for part in tool_parts] == ["call_1", None]
    assert tool_parts[0]["index"] == 0
    assert usage == {
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
        "input_token_details": {"cache_read": 3},
        "output_token_details": {"reasoning": 2},
    }
    assert finish == "tool_calls"

    assert captured["line"].startswith("POST /v1/chat/completions HTTP/1.1")
    assert captured["headers"]["authorization"] == "Bearer k"
    assert captured["body"]["model"] == "m"
    assert captured["body"]["stream"] is True


async def test_anthropic_transport_speaks_the_messages_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        line, headers, body = await _read_request(reader)
        captured.update(
            line=line, headers=headers, body=json.loads(body.decode("utf-8"))
        )
        writer.write(_sse_head())
        await writer.drain()
        await _write_frames(writer, ANTHROPIC_FRAMES)
        await _finish(writer, done=False)

    server, port = await _serve(handler)
    try:
        _enable(monkeypatch)
        wrapper = DshModelFactory(
            ChatModelFactory([_provider(port, protocol="anthropic")]),
            refs={"p/m"},
            transport_factory=build_http_transport,
        )
        model = wrapper.get_chat_model("p/m")
        assert isinstance(model, DshChatModel)
        chunks = [chunk async for chunk in model._astream([HumanMessage(content="hi")])]
    finally:
        server.close()
        await server.wait_closed()

    text = "".join(str(chunk.message.content) for chunk in chunks)
    usage = next(
        chunk.message.usage_metadata
        for chunk in chunks
        if chunk.message.usage_metadata is not None
    )
    finish = next(
        chunk.generation_info["finish_reason"]
        for chunk in chunks
        if chunk.generation_info
    )

    assert text == "hi"
    assert usage["input_tokens"] == 6
    assert usage["output_tokens"] == 2
    assert usage["total_tokens"] == 8
    assert usage["input_token_details"] == {"cache_read": 2, "cache_write": 0}
    assert finish == "stop"

    assert captured["line"].startswith("POST /v1/messages HTTP/1.1")
    assert captured["headers"]["x-api-key"] == "k"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    assert captured["body"]["max_tokens"] == 64
    assert captured["body"]["stream"] is True


async def test_mid_stream_disconnect_reports_transport_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await _read_request(reader)
        # Chunked body that never terminates: the peer sees an abrupt close.
        writer.write(_sse_head(chunked=True))
        payload = f"data: {json.dumps(OPENAI_FRAMES[0])}\n\n".encode()
        writer.write(f"{len(payload):x}\r\n".encode() + payload + b"\r\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server, port = await _serve(handler)
    try:
        transport = build_http_transport(_provider(port), ModelConfig(id="m"))
        assert transport is not None
        raw = transport.stream({"model": "m", "stream": True, "messages": []})
        with pytest.raises(ProviderFailure) as info:
            async for _frame in raw:
                pass
        assert info.value.code == FailureCode.TRANSPORT
        assert raw.closed is True
    finally:
        server.close()
        await server.wait_closed()


async def test_cancellation_closes_the_underlying_connection() -> None:
    disconnected = asyncio.Event()

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await _read_request(reader)
        writer.write(_sse_head())
        writer.write(
            b'data: {"choices": [{"index": 0, "delta": {"content": "tick"}, '
            b'"finish_reason": null}]}\n\n'
        )
        await writer.drain()
        eof = asyncio.create_task(reader.read(1))
        try:
            while not eof.done():
                writer.write(
                    b'data: {"choices": [{"index": 0, "delta": {"content": "tick"}, '
                    b'"finish_reason": null}]}\n\n'
                )
                await writer.drain()
                await asyncio.sleep(0.02)
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            eof.cancel()
            disconnected.set()
            writer.close()

    server, port = await _serve(handler)
    try:
        transport = build_http_transport(_provider(port), ModelConfig(id="m"))
        assert transport is not None
        raw = transport.stream({"model": "m", "stream": True, "messages": []})
        first = await raw.__anext__()
        assert first["choices"][0]["delta"]["content"] == "tick"

        async def consume() -> None:
            async for _frame in raw:
                pass

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        await asyncio.wait_for(disconnected.wait(), timeout=3)
        assert raw.closed is True
    finally:
        server.close()
        await server.wait_closed()


async def test_loopback_ignores_proxy_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await _read_request(reader)
        writer.write(_sse_head())
        await writer.drain()
        await _write_frames(writer, OPENAI_FRAMES)
        await _finish(writer)

    server, port = await _serve(handler)
    try:
        assert is_loopback_url(f"http://127.0.0.1:{port}/v1")
        transport = build_http_transport(_provider(port), ModelConfig(id="m"))
        assert transport is not None
        frames = [
            frame
            async for frame in transport.stream(
                {"model": "m", "stream": True, "messages": []}
            )
        ]
        assert len(frames) == len(OPENAI_FRAMES)
    finally:
        server.close()
        await server.wait_closed()
