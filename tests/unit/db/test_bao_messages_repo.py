"""Conversation retention for Bao messages."""

from __future__ import annotations

from pathlib import Path

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.bao_messages import MAX_MESSAGES_PER_USER, BaoMessageRepo


def _repo(path: Path) -> BaoMessageRepo:
    db = SqlitePool(path)
    run_migrations(db)
    return BaoMessageRepo(db)


def test_messages_roundtrip_and_refs(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "msg.db")
    user = repo.append(user_id=1, role="user", text="让 A 跑健康检查", intent="new_task")
    task = repo.append(
        user_id=1,
        role="bao",
        text="已经派给 A",
        intent="dispatch",
        refs={"agent_id": "a1", "thread_id": "t1"},
        task_id="task-1",
    )

    rows = repo.list_for_user(1)
    assert [row.id for row in rows] == [user.id, task.id]
    assert rows[1].refs()["agent_id"] == "a1"
    assert repo.latest_task_ref(1) == {
        "agent_id": "a1",
        "thread_id": "t1",
        "task_id": "task-1",
    }


def test_messages_capped_per_user(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "cap.db")
    for index in range(MAX_MESSAGES_PER_USER + 5):
        repo.append(
            user_id=1,
            role="user",
            text=f"消息 {index}",
            created_at=1_700_000_000 + index,
        )

    rows = repo.list_for_user(1, limit=999)
    assert len(rows) == MAX_MESSAGES_PER_USER
    texts = {row.text for row in rows}
    assert "消息 0" not in texts
    assert f"消息 {MAX_MESSAGES_PER_USER + 4}" in texts
