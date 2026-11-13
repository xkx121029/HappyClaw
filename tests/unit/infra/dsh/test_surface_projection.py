"""Tests for the deterministic surface projection."""

from __future__ import annotations

from octop.infra.dsh.session import EventType, LogRecord, project, surface_json


def _records() -> list[LogRecord]:
    return [
        LogRecord.make(0, EventType.SESSION_START, {"session_id": "s-1"}),
        LogRecord.make(1, EventType.USER_MESSAGE, {"text": "帮我查一下磁盘"}),
        LogRecord.make(
            2,
            EventType.ASSISTANT_MESSAGE,
            {
                "text": "我调用工具查。",
                "tool_calls": [{"id": "call-1", "name": "disk_usage"}],
            },
        ),
        LogRecord.make(
            3,
            EventType.TOOL_CALL,
            {"call_id": "call-1", "name": "disk_usage", "arguments": {"path": "/"}},
        ),
        LogRecord.make(
            4,
            EventType.TOOL_RESULT,
            {"call_id": "call-1", "name": "disk_usage", "content": "used 40%", "is_error": False},
        ),
        LogRecord.make(5, EventType.ASSISTANT_MESSAGE, {"text": "磁盘已用 40%。"}),
        LogRecord.make(6, EventType.SESSION_END, {}),
    ]


def test_projection_contains_user_assistant_and_tool_nodes() -> None:
    nodes = project(_records())

    assert [node.kind for node in nodes] == [
        "user_message",
        "assistant_message",
        "tool_call",
        "tool_result",
        "assistant_message",
    ]
    assert nodes[1].payload["tool_calls"] == [{"id": "call-1", "name": "disk_usage"}]
    assert nodes[3].payload["content"] == "used 40%"


def test_replaying_the_same_log_twice_is_byte_identical() -> None:
    first = surface_json(project(_records()))
    second = surface_json(project(list(_records())))

    assert first == second
    assert first.startswith('[{"attachments":[]')


def test_unknown_event_types_are_ignored() -> None:
    records = [
        *_records(),
        LogRecord.make(7, "future/event", {"anything": True}),
    ]

    assert len(project(records)) == 5
