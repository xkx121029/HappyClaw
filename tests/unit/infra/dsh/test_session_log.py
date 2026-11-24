"""Tests for the generation-switched session log."""

from __future__ import annotations

from pathlib import Path

import pytest

from happyclaw.infra.dsh.session import EventType, LogCorruptionError, SessionLog


def _clock() -> str:
    return "2026-11-12T00:00:00.000Z"


def _open(root: Path) -> SessionLog:
    return SessionLog(root, clock=_clock)


def test_append_then_reload_replays_identical_records(tmp_path: Path) -> None:
    root = tmp_path / "session"
    log = _open(root)
    log.append(EventType.SESSION_START, {"session_id": "s-1"})
    log.append(EventType.USER_MESSAGE, {"text": "你好，先看日志"})
    log.append(EventType.TOOL_RESULT, {"call_id": "c1", "content": "ok"})

    reopened = _open(root)
    records = reopened.load()

    assert [(record.seq, record.type, record.data) for record in records] == [
        (0, "session/start", {"session_id": "s-1"}),
        (1, "user/message", {"text": "你好，先看日志"}),
        (2, "tool/result", {"call_id": "c1", "content": "ok"}),
    ]
    assert all(record.ts == _clock() for record in records)
    assert reopened.append(EventType.SESSION_END, {}).seq == 3


def test_truncated_tail_is_discarded_and_next_append_is_clean(tmp_path: Path) -> None:
    root = tmp_path / "session"
    log = _open(root)
    log.append(EventType.SESSION_START, {"session_id": "s-2"})
    log.append(EventType.USER_MESSAGE, {"text": "第一句"})
    path = log.current_path
    torn = '{"seq":2,"type":"user/message","data":{"text":"未写完'
    with path.open("ab") as handle:
        handle.write(torn.encode("utf-8"))

    reopened = _open(root)
    assert [record.seq for record in reopened.load()] == [0, 1]

    appended = reopened.append(EventType.USER_MESSAGE, {"text": "第二句"})
    assert appended.seq == 2
    raw = path.read_text(encoding="utf-8")
    assert "未写完" not in raw
    assert _open(root).load()[-1].data == {"text": "第二句"}


def test_only_the_tail_is_tolerated(tmp_path: Path) -> None:
    root = tmp_path / "session"
    log = _open(root)
    log.append(EventType.SESSION_START, {"session_id": "s-3"})
    path = log.current_path
    with path.open("ab") as handle:
        handle.write(b"not-json\n")
        handle.write(b'{"seq":2,"type":"session/end","data":{}}\n')

    with pytest.raises(LogCorruptionError):
        _open(root).load()


def test_rewrite_switches_generation_without_touching_the_old_file(tmp_path: Path) -> None:
    root = tmp_path / "session"
    log = _open(root)
    log.append(EventType.SESSION_START, {"session_id": "s-4"})
    log.append(EventType.USER_MESSAGE, {"text": "旧代内容"})
    old_path = log.current_path
    old_bytes = old_path.read_bytes()
    records = log.load()

    new_generation = log.rewrite(records)

    assert new_generation == 1
    assert old_path.read_bytes() == old_bytes
    assert (root / "session.g1.jsonl").exists()
    assert [record.data for record in _open(root).load()] == [record.data for record in records]

    log.append(EventType.SESSION_END, {"reason": "done"})
    assert old_path.read_bytes() == old_bytes
    assert [record.seq for record in _open(root).load()] == [0, 1, 2]


def test_seq_gap_in_committed_prefix_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "session"
    root.mkdir(parents=True)
    (root / "session.g0.jsonl").write_text(
        '{"seq":0,"type":"session/start","data":{}}\n{"seq":2,"type":"session/end","data":{}}\n',
        encoding="utf-8",
    )

    with pytest.raises(LogCorruptionError):
        SessionLog(root).load()
