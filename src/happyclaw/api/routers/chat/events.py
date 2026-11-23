"""Stream frame contracts for dashboard chat (WebSocket + HITL resume SSE).

The chat socket and the SSE resume endpoint send JSON frames whose shape comes
from the harness stream (``token``, ``tool_call_chunk``, ``done``, …) plus a
handful of gateway control frames (``turn.started``, ``steer.queue_snapshot``, …).
They are not part of any OpenAPI response, so the models here are documentation
and client-generation contracts only: nothing validates frames against them at
runtime, which keeps the live protocol tolerant of unknown keys.

``stream_event_schemas`` returns the component schemas that
:func:`octop.api.openapi_meta.configure_openapi` publishes under
``components/schemas`` so generated clients can type the stream.
"""

from __future__ import annotations

from typing import Any, Literal, get_args

from pydantic import BaseModel, JsonValue

from happyclaw.api.routers.chat.responses import ChatAuthorOut, PayloadOut, model_schemas


class ChatChunkFrame(PayloadOut):
    """Common tail of every harness stream chunk (team room stamps these)."""

    agent_id: str | None = None
    agent: str | None = None
    turn_id: str | None = None


class TokenFrame(ChatChunkFrame):
    type: Literal["token"]
    node: str = "agent"
    content: str
    team_snapshot: bool | None = None
    team_live: bool | None = None
    team_wrapup: bool | None = None


class ReasoningFrame(ChatChunkFrame):
    type: Literal["reasoning"]
    content: str


class ToolCallFrame(ChatChunkFrame):
    type: Literal["tool_call_chunk"]
    id: str | None = None
    name: str | None = None
    display_name: str | None = None
    args: str | None = None
    index: int | None = None


class ToolResultFrame(ChatChunkFrame):
    type: Literal["tool_result"]
    node: str = "tool"
    messages: list[JsonValue]


class StateUpdateFrame(ChatChunkFrame):
    type: Literal["state_update"]
    node: str = ""
    data: JsonValue


class StateSnapshotFrame(ChatChunkFrame):
    type: Literal["state_snapshot"]
    data: JsonValue


class CustomFrame(ChatChunkFrame):
    type: Literal["custom"]
    data: JsonValue
    team_wrapup: bool | None = None


class UsageFrame(ChatChunkFrame):
    type: Literal["usage"]
    call_id: str | None = None
    model: str | None = None
    node: str | None = None
    usage: dict[str, JsonValue]


class DoneFrame(ChatChunkFrame):
    type: Literal["done"]
    team_wrapup: bool | None = None
    team_member_continuing: bool | None = None
    hitl_paused: bool | None = None
    conversation_mode: Literal["ask", "plan", "craft"] | None = None
    pending_plan_path: str | None = None
    duration_ms: int | None = None


class ErrorFrame(ChatChunkFrame):
    type: Literal["error"]
    message: str
    error_code: str | None = None


class HitlRequiredFrame(ChatChunkFrame):
    type: Literal["hitl_required"]
    request: dict[str, JsonValue]


class SlashActionFrame(ChatChunkFrame):
    type: Literal["slash_action"]
    action: str
    mode: str | None = None


class AttachmentFrame(ChatChunkFrame):
    type: Literal["attachment"]
    url: str | None = None
    preview_url: str | None = None
    data: str | None = None
    mime_type: str | None = None
    kind: str | None = None
    filename: str | None = None


class PongFrame(PayloadOut):
    type: Literal["pong"]


class TurnStatusFrame(PayloadOut):
    type: Literal["turn_status"]
    thread_id: str
    active: bool


class UserFrame(PayloadOut):
    """Question bubble for every subscriber of the thread."""

    type: Literal["user"]
    content: str
    thread_id: str
    message_id: str | None = None
    author: ChatAuthorOut | None = None


class TurnStartedFrame(PayloadOut):
    type: Literal["turn.started"]
    turn_id: str
    seq: int
    phase: str
    thread_id: str


class TurnResumedFrame(PayloadOut):
    type: Literal["turn.resumed"]
    turn_id: str
    seq: int
    phase: str
    thread_id: str


class TurnEndedFrame(PayloadOut):
    type: Literal["turn.ended"]
    turn_id: str
    thread_id: str
    failed: bool | None = None
    hitl_paused: bool | None = None


class TurnBusyFrame(PayloadOut):
    type: Literal["turn.busy"]
    thread_id: str
    reason: str
    message_id: str | None = None
    client_pending_id: str | None = None
    active_turn_id: str | None = None


class SteerQueueItem(PayloadOut):
    client_pending_id: str
    pending_id: str
    preview: str


class SteerQueueSnapshotFrame(PayloadOut):
    type: Literal["steer.queue_snapshot"]
    seq: int
    turn_id: str | None = None
    queue_length: int
    continuation_count: int
    items: list[SteerQueueItem]
    thread_id: str | None = None


class SteerDrainedFrame(PayloadOut):
    type: Literal["steer.drained"]
    seq: int
    client_pending_ids: list[str]
    pending_ids: list[str]
    turn_id: str
    message_id: str | None = None
    thread_id: str


class SteerDiscardedFrame(PayloadOut):
    type: Literal["steer.discarded"]
    seq: int
    client_pending_ids: list[str]
    pending_ids: list[str]
    turn_id: str | None = None
    reason: str | None = None
    thread_id: str


class ThreadFrame(PayloadOut):
    """New thread id announced before the first turn chunk."""

    type: Literal["thread"]
    thread_id: str


# Chunks the agent stream emits; also the payload of ``event: chunk`` SSE frames.
CHAT_CHUNK_FRAMES: tuple[type[BaseModel], ...] = (
    TokenFrame,
    ReasoningFrame,
    ToolCallFrame,
    ToolResultFrame,
    StateUpdateFrame,
    StateSnapshotFrame,
    CustomFrame,
    UsageFrame,
    DoneFrame,
    ErrorFrame,
    HitlRequiredFrame,
    SlashActionFrame,
    AttachmentFrame,
)

# Everything the chat WebSocket can push to a connected dashboard.
CHAT_WS_FRAMES: tuple[type[BaseModel], ...] = (
    *CHAT_CHUNK_FRAMES,
    PongFrame,
    TurnStatusFrame,
    UserFrame,
    TurnStartedFrame,
    TurnResumedFrame,
    TurnEndedFrame,
    TurnBusyFrame,
    SteerQueueSnapshotFrame,
    SteerDrainedFrame,
    SteerDiscardedFrame,
    ThreadFrame,
)

STREAM_EVENT_MODELS: tuple[type[BaseModel], ...] = (*CHAT_WS_FRAMES,)

_UNIONS: dict[str, tuple[str, tuple[type[BaseModel], ...]]] = {
    "ChatStreamChunk": (
        "One harness stream chunk: the payload of an `event: chunk` SSE frame and "
        "the bulk of what the chat WebSocket pushes.",
        CHAT_CHUNK_FRAMES,
    ),
    "ChatWsServerFrame": (
        "Any frame the chat WebSocket can send: a stream chunk, a turn lifecycle "
        "frame, a steer-queue frame, or a socket control frame.",
        CHAT_WS_FRAMES,
    ),
}


def _frame_type(model: type[BaseModel]) -> str:
    return str(get_args(model.model_fields["type"].annotation)[0])


def _union_schema(name: str, description: str, models: tuple[type[BaseModel], ...]) -> dict[str, Any]:
    return {
        "title": name,
        "description": description,
        "oneOf": [{"$ref": f"#/components/schemas/{m.__name__}"} for m in models],
        "discriminator": {
            "propertyName": "type",
            "mapping": {_frame_type(m): f"#/components/schemas/{m.__name__}" for m in models},
        },
    }


def stream_event_schemas() -> dict[str, Any]:
    """Named component schemas for the WS/SSE frames (documentation only)."""
    schemas = model_schemas(STREAM_EVENT_MODELS, open_schema=True)
    for name, (description, models) in _UNIONS.items():
        schemas[name] = _union_schema(name, description, models)
    return schemas


__all__ = [
    "CHAT_CHUNK_FRAMES",
    "CHAT_WS_FRAMES",
    "ChatChunkFrame",
    "STREAM_EVENT_MODELS",
    "stream_event_schemas",
]
