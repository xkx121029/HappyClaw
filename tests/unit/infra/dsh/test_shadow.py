"""Shadow writer, switch, read-only verify, and processor hook."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import pytest

from happyclaw.infra.db.repos.thread_messages import ThreadMessageInput
from happyclaw.infra.dsh.session import shadow as shadow_mod
from happyclaw.infra.dsh.session import verify
from happyclaw.infra.dsh.session.log import SessionLog
from happyclaw.infra.dsh.session.shadow import (
    append_shadow_turn,
    shadow_enabled,
    thread_shadow_dir,
    write_shadow_turn,
)
from happyclaw.infra.gateway.process.processor import GlobalProcessor


def _message(role: str, content: str, *, message_id: str | None = None) -> str:
    return json.dumps({"type": role, "data": {"content": content}}, ensure_ascii=False)


def _input(
    role: str,
    content: str,
    *,
    message_id: str | None = None,
    created_at: int = 1,
) -> ThreadMessageInput:
    return ThreadMessageInput(
        message_id=message_id,
        role=role,
        message_json=_message(role, content),
        created_at=created_at,
    )


def _tool_input(
    call_id: str,
    content: str,
    *,
    name: str = "search",
    message_id: str | None = None,
    created_at: int = 1,
) -> ThreadMessageInput:
    payload = {
        "type": "tool",
        "data": {"content": content, "tool_call_id": call_id, "name": name},
    }
    return ThreadMessageInput(
        message_id=message_id,
        role="tool",
        message_json=json.dumps(payload, ensure_ascii=False),
        created_at=created_at,
    )


def _create_db(path: Path, rows: list[ThreadMessageInput]) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "create table thread_messages("
            "thread_id text not null, seq integer not null, message_id text, "
            "role text not null, message_json text not null, created_at integer not null, "
            "primary key(thread_id, seq))"
        )
        for seq, row in enumerate(rows, start=1):
            connection.execute(
                "insert into thread_messages(thread_id, seq, message_id, role, message_json, created_at) "
                "values (?, ?, ?, ?, ?, ?)",
                ("thr_test", seq, row.message_id, row.role, row.message_json, row.created_at),
            )
        connection.commit()
    finally:
        connection.close()


def test_shadow_switch_defaults_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(shadow_mod.ENV_ENABLED, raising=False)
    assert shadow_enabled() is False
    for value in ("0", "false", "", "off"):
        monkeypatch.setenv(shadow_mod.ENV_ENABLED, value)
        assert shadow_enabled() is False
    for value in ("1", "true", "yes", "on"):
        monkeypatch.setenv(shadow_mod.ENV_ENABLED, value)
        assert shadow_enabled() is True


def test_shadow_turn_writes_once_and_dedupes(tmp_path: Path) -> None:
    root = tmp_path / "shadow"
    inputs = [
        _input("human", "你好", message_id="m1", created_at=10),
        _input("ai", "你好，有什么可以帮你？", message_id="m2", created_at=11),
        _tool_input("call_1", "result body", message_id="m3", created_at=12),
    ]
    assert append_shadow_turn("thr_test", inputs, root=root) == 3
    assert append_shadow_turn("thr_test", inputs, root=root) == 0

    records = SessionLog(thread_shadow_dir("thr_test", root)).load()
    assert [record.type for record in records] == [
        "session/start",
        "user/message",
        "assistant/message",
        "tool/result",
    ]
    assert [record.seq for record in records] == [0, 1, 2, 3]


def test_anonymous_duplicate_messages_are_all_kept(tmp_path: Path) -> None:
    root = tmp_path / "shadow"
    inputs = [
        _input("human", "hi", created_at=1),
        _input("ai", "same failure text", created_at=2),
        _input("ai", "same failure text", created_at=2),
    ]
    assert append_shadow_turn("thr_test", inputs, root=root) == 3
    assert append_shadow_turn("thr_test", inputs, root=root) == 0
    records = SessionLog(thread_shadow_dir("thr_test", root)).load()
    assert [record.type for record in records].count("assistant/message") == 2


def test_write_shadow_turn_swallows_failures(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def _boom(*_args: object, **_kwargs: object) -> int:
        raise OSError("disk full")

    monkeypatch.setattr(shadow_mod, "append_shadow_turn", _boom)
    with caplog.at_level(logging.WARNING, logger="happyclaw.infra.dsh.session.shadow"):
        write_shadow_turn("thr_test", [_input("human", "hi")])
    assert any("DSH shadow log write failed" in record.message for record in caplog.records)


def test_processor_hook_skips_work_when_switch_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, list[ThreadMessageInput]]] = []

    def _record(thread_id: str, items: list[ThreadMessageInput]) -> None:
        calls.append((thread_id, items))

    monkeypatch.delenv(shadow_mod.ENV_ENABLED, raising=False)
    monkeypatch.setattr(shadow_mod, "write_shadow_turn", _record)
    GlobalProcessor._write_shadow_history("thr_test", [_input("human", "hi")])
    assert calls == []

    monkeypatch.setenv(shadow_mod.ENV_ENABLED, "1")
    GlobalProcessor._write_shadow_history("thr_test", [_input("human", "hi")])
    assert len(calls) == 1


def test_verify_reports_consistent(tmp_path: Path) -> None:
    root = tmp_path / "shadow"
    rows = [
        _input("human", "你好", message_id="m1", created_at=10),
        _input("ai", "你好", message_id="m2", created_at=11),
        _tool_input("call_1", "ok", message_id="m3", created_at=12),
    ]
    db_path = tmp_path / "octop.db"
    _create_db(db_path, rows)
    append_shadow_turn("thr_test", rows, root=root)

    result = verify.compare("thr_test", db_path=db_path, shadow_dir=root)
    assert result.consistent is True
    assert result.existing_count == 3
    assert result.shadow_count == 3
    assert (
        verify.main(
            [
                "--thread-id",
                "thr_test",
                "--db",
                str(db_path),
                "--shadow-dir",
                str(root),
            ]
        )
        == 0
    )


def test_verify_reports_field_level_difference(tmp_path: Path) -> None:
    root = tmp_path / "shadow"
    stored = [_input("human", "你好", message_id="m1", created_at=10)]
    replayed = [_input("human", "你好呀", message_id="m1", created_at=10)]
    db_path = tmp_path / "octop.db"
    _create_db(db_path, stored)
    append_shadow_turn("thr_test", replayed, root=root)

    result = verify.compare("thr_test", db_path=db_path, shadow_dir=root)
    assert result.consistent is False
    assert result.differences is not None
    difference = result.differences[0]
    assert difference["kind"] == "field_mismatch"
    assert difference["fields"]["text"]["existing"] == "你好"
    assert difference["fields"]["text"]["shadow"] == "你好呀"
    assert (
        verify.main(
            [
                "--thread-id",
                "thr_test",
                "--db",
                str(db_path),
                "--shadow-dir",
                str(root),
            ]
        )
        == 1
    )


def test_verify_reports_missing_and_extra(tmp_path: Path) -> None:
    root = tmp_path / "shadow"
    stored = [
        _input("human", "one", message_id="m1", created_at=10),
        _input("ai", "two", message_id="m2", created_at=11),
        _input("ai", "three", message_id="m3", created_at=12),
    ]
    replayed = [
        _input("human", "one", message_id="m1", created_at=10),
        _tool_input("call_9", "tool only in shadow", message_id="m9", created_at=12),
        _input("ai", "two", message_id="m2", created_at=11),
    ]
    db_path = tmp_path / "octop.db"
    _create_db(db_path, stored)
    append_shadow_turn("thr_test", replayed, root=root)

    result = verify.compare("thr_test", db_path=db_path, shadow_dir=root)
    kinds = [difference["kind"] for difference in result.differences or []]
    assert "missing_in_shadow" in kinds
    assert "extra_in_shadow" in kinds


def test_verify_handles_missing_shadow_log(tmp_path: Path) -> None:
    db_path = tmp_path / "octop.db"
    _create_db(db_path, [_input("human", "hi", message_id="m1")])
    result = verify.compare(
        "thr_test",
        db_path=db_path,
        shadow_dir=tmp_path / "shadow",
    )
    assert result.consistent is False
    assert result.differences == [{"kind": "missing_shadow_log"}]
    assert result.notes
