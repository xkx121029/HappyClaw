"""Regression tests for the chat response contracts (``response_model``).

The point of these models is that they are inert: the handler dicts must still
serialize byte-for-byte the same, and every chat route must declare a real
schema instead of an open ``additionalProperties`` object.
"""

from __future__ import annotations

from typing import Any

from octop.api.routers.chat.events import CHAT_CHUNK_FRAMES, CHAT_WS_FRAMES, stream_event_schemas
from octop.api.routers.chat.responses import (
    RESPONSE_MODELS,
    ChatWelcomeOut,
    HistoryMigrationStartOut,
    HitlPendingListOut,
    QuickChatCreatedOut,
    ThreadContextUsageOut,
    ThreadCreatedOut,
    ThreadDeletedOut,
    ThreadForkOut,
    ThreadHistoryOut,
    ThreadSummaryOut,
    ThreadUpdatedOut,
    model_schemas,
)

_THREAD_ROW: dict[str, Any] = {
    "thread_id": "t1",
    "title": "新对话",
    "channel_type": "dashboard",
    "session_key": "agent:dashboard:1:dm",
    "last_active": 1,
    "created_at": 2,
    "is_active": True,
    "has_messages": False,
    "pinned": False,
    "unread_count": 0,
    "contributed": False,
    "owned": True,
    "model_ref": None,
    "reasoning_mode": None,
    "reasoning_effort": None,
    "conversation_mode": "craft",
    "pending_plan_path": None,
    "hitl_policy": {"mode": "ask"},
    "project_id": None,
    "project_name": None,
    "workspace_kind": None,
    "workspace_dir": None,
    "quick_chat": False,
    "created_by_name": None,
    "turn_active": False,
    "awaiting_user": False,
    "artifacts": [],
    "artifact_refs": [],
}

_HISTORY: dict[str, Any] = {
    "thread_id": "t1",
    "messages": [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "hi"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png"}},
            ],
            "author_user_id": 1,
            "author": {
                "user_id": 1,
                "display_name": "Ann",
                "username": "ann",
                "avatar_icon": None,
                "avatar_url": None,
            },
            "timestamp": 1_700_000_000_000,
        },
        {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "plan"},
                {"type": "text", "text": "done"},
                {"type": "tool_use", "name": "read_file", "id": "c1", "input": {"path": "a.md"}},
            ],
            "usage": {"input_tokens": 3},
            "duration_ms": 12,
            "edited_files": ["a.md"],
            "team_wrapup": True,
        },
        {
            "role": "tool",
            "content": [
                {
                    "type": "tool_result",
                    "id": "c1",
                    "name": "read_file",
                    "output": "body",
                    "artifact": {"raw": [1, None]},
                }
            ],
            "status": "error",
            "error_code": "tool_error",
            "agent_id": "member-1",
        },
    ],
    "has_more": False,
    "limit": 25,
    "offset": 0,
    "next_cursor": None,
    "history_loading": False,
    "history_status": "ready",
    "history_retry_after_ms": 0,
    "turn_active": False,
    "hitl_pending": {
        "pending_id": "p1",
        "action_requests": [{"name": "shell", "args": {"cmd": "ls"}}],
        "review_configs": [{"action_name": "shell", "allowed_decisions": ["approve"]}],
    },
    "artifacts": ["a.md"],
    "artifact_refs": [{"path": "a.md", "agent_id": "member-1"}],
    "conversation_mode": "craft",
    "pending_plan_path": None,
    "hitl_policy": {"mode": "allow_tools", "tools": ["read_file"]},
}


def _roundtrip(model: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return model.model_validate(payload).model_dump(mode="json")


def test_thread_summary_round_trips_exactly() -> None:
    assert _roundtrip(ThreadSummaryOut, _THREAD_ROW) == _THREAD_ROW


def test_thread_history_round_trips_exactly() -> None:
    assert _roundtrip(ThreadHistoryOut, _HISTORY) == _HISTORY


def test_absent_optional_fields_are_not_serialized_as_null() -> None:
    history = {**_HISTORY, "hitl_pending": None, "messages": [{"role": "assistant", "content": [{"type": "text", "text": "x"}]}]}
    out = _roundtrip(ThreadHistoryOut, history)
    assert out == history
    assert "hitl_pending" in out
    assert "duration_ms" not in out["messages"][0]


def test_unknown_payload_keys_pass_through() -> None:
    row = {**_THREAD_ROW, "future_field": {"nested": 1}}
    assert _roundtrip(ThreadSummaryOut, row) == row


def test_thread_updated_keeps_explicit_nulls() -> None:
    payload = {
        "thread_id": "t1",
        "title": None,
        "pinned": True,
        "contributed": False,
        "owned": True,
        "model_ref": None,
        "reasoning_mode": None,
        "reasoning_effort": None,
        "conversation_mode": "craft",
        "pending_plan_path": None,
        "hitl_policy": {"mode": "ask"},
    }
    assert _roundtrip(ThreadUpdatedOut, payload) == payload


def test_welcome_keeps_null_icon_and_stamped_cards() -> None:
    payload = {
        "welcome_message": {"zh": "你好", "en": "Hi"},
        "quick_prompts": [
            {
                "title": {"zh": "总结", "en": "Summarize"},
                "description": {"zh": "", "en": ""},
                "prompt": {"zh": "p", "en": "p"},
                "color": "#e8f4ff",
                "icon_name": None,
                "expert": "Scribe",
                "agent_id": "member-1",
            }
        ],
        "task_examples": None,
    }
    assert _roundtrip(ChatWelcomeOut, payload) == payload


def test_small_payloads_round_trip() -> None:
    cases = [
        (QuickChatCreatedOut, {"thread_id": "t1", "session_key": "k", "quick": True}),
        (ThreadDeletedOut, {"compacted": True, "scheduled": False}),
        (HitlPendingListOut, {"ok": True, "items": []}),
        (
            ThreadContextUsageOut,
            {
                "max_tokens": 128_000,
                "used_tokens": 10,
                "decision_saved": 0,
                "segments": [{"key": "system", "tokens": 5}],
            },
        ),
        (
            ThreadForkOut,
            {
                "thread_id": "t2",
                "session_key": "k",
                "source_thread_id": "t1",
                "copied_messages": 3,
                "title": None,
                "last_active": 0,
                "created_at": 0,
            },
        ),
        (
            HistoryMigrationStartOut,
            {
                "remaining": 2,
                "pending": 0,
                "queued": 1,
                "running": 1,
                "failed": 0,
                "processing": True,
                "agent_busy": False,
                "can_start": False,
                "accepted": 1,
            },
        ),
    ]
    for model, payload in cases:
        assert _roundtrip(model, payload) == payload


def test_every_stream_frame_has_a_component_schema() -> None:
    schemas = stream_event_schemas()
    for model in CHAT_WS_FRAMES:
        assert model.__name__ in schemas
    assert len(schemas["ChatStreamChunk"]["oneOf"]) == len(CHAT_CHUNK_FRAMES)
    assert len(schemas["ChatWsServerFrame"]["oneOf"]) == len(CHAT_WS_FRAMES)
    assert schemas["ChatWsServerFrame"]["discriminator"]["propertyName"] == "type"


def test_chat_routes_declare_response_models() -> None:
    from octop.api.routers.chat.history import router as history_router  # noqa: PLC0415
    from octop.api.routers.chat.routes import router as routes_router  # noqa: PLC0415

    covered: dict[tuple[str, str], Any] = {}
    for router in (history_router, routes_router):
        for route in router.routes:
            for method in sorted(getattr(route, "methods", set()) or set()):
                covered[(method, route.path)] = route.response_model  # type: ignore[attr-defined]

    expected = {
        ("GET", "/agents/{agent_id}/threads"): list[ThreadSummaryOut],
        ("POST", "/agents/{agent_id}/threads"): ThreadCreatedOut,
        ("GET", "/agents/{agent_id}/quick-chats"): None,
        ("PATCH", "/agents/{agent_id}/threads/{thread_id}"): ThreadUpdatedOut,
        ("DELETE", "/agents/{agent_id}/threads/{thread_id}"): None,
        ("GET", "/agents/{agent_id}/threads/{thread_id}/history"): ThreadHistoryOut,
        ("GET", "/agents/{agent_id}/chat/welcome"): ChatWelcomeOut,
        ("GET", "/agents/{agent_id}/chat/hitl/pending"): HitlPendingListOut,
    }
    for key, model in expected.items():
        if model is None:
            # Streaming / empty-body routes document their shape elsewhere.
            continue
        assert covered.get(key) == model, key


def test_published_payload_schemas_look_through_the_serializer() -> None:
    schemas = model_schemas(RESPONSE_MODELS)
    history = schemas["ThreadHistoryOut"]
    assert "messages" in history["properties"]
    assert history["required"]
    message = schemas["ChatMessageOut"]
    assert "content" in message["properties"]
    assert "timestamp" in message["properties"]
    assert "author" in message["properties"]
    block = schemas["ChatContentBlockOut"]["properties"]
    for key in ("type", "text", "thinking", "id", "name", "input", "output", "artifact"):
        assert key in block
