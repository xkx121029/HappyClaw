"""The dashboard WS channel writes finished turns back into Bao's ledger."""

from __future__ import annotations

from typing import Any

import pytest

from octop.infra.gateway.ws.ws_channel import WS_CHANNEL_ID, WebSocketChannel
from octop_gateway.models import ChannelSubject, InboundMessage, TextContent


class _FakeHub:
    def __init__(self) -> None:
        self.frames: list[tuple[str, dict[str, Any]]] = []

    def subscribe(self, thread_id: str, connection_id: str) -> None:
        return None

    async def push(self, connection_id: str, frame: dict[str, Any]) -> None:
        self.frames.append((connection_id, frame))

    async def push_to_thread(self, thread_id: str, frame: dict[str, Any]) -> None:
        self.frames.append((thread_id, frame))

    def mark_turn_active(self, thread_id: str) -> None:
        return None

    def mark_turn_idle(self, thread_id: str) -> None:
        return None


class _FakeProcessor:
    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        self._chunks = chunks

    async def iter_turn_chunks(self, message: InboundMessage):
        for chunk in self._chunks:
            yield chunk


def _message() -> InboundMessage:
    return InboundMessage(
        channel_id=WS_CHANNEL_ID,
        channel_type="dashboard",
        tenant_id="a1",
        channel_subject=ChannelSubject(subject_id="7"),
        channel_session_id="dashboard|a1|7",
        content=[TextContent(text="hi")],
        metadata={
            "thread_id": "t1",
            "ws_connection_id": "c1",
            "user_id": 7,
        },
    )


async def _run(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    calls: list[dict[str, Any]] = []
    channel = WebSocketChannel(
        _FakeProcessor(chunks),  # type: ignore[arg-type]
        hub=_FakeHub(),  # type: ignore[arg-type]
        on_turn_finished=lambda **kwargs: calls.append(kwargs),
    )
    await channel.handle_inbound(_message())
    assert len(calls) == 1
    return calls[0]


@pytest.mark.asyncio
async def test_done_turn_writes_accumulated_text() -> None:
    call = await _run(
        [
            {"type": "token", "content": "你"},
            {"type": "token", "content": "好"},
            {"type": "done"},
        ]
    )

    assert call["thread_id"] == "t1"
    assert call["agent_id"] == "a1"
    assert call["status"] == "done"
    assert call["result_text"] == "你好"
    assert call["error_text"] is None


@pytest.mark.asyncio
async def test_hitl_turn_marks_awaiting() -> None:
    call = await _run(
        [
            {"type": "token", "content": "继续前需要确认"},
            {"type": "hitl_required", "request": {}},
        ]
    )

    assert call["status"] == "awaiting"
    assert call["result_text"] == "继续前需要确认"


@pytest.mark.asyncio
async def test_error_turn_marks_failed() -> None:
    call = await _run([{"type": "error", "message": "模型超时"}])

    assert call["status"] == "failed"
    assert call["error_text"] == "模型超时"
