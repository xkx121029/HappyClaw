"""Persistence, retention and writeback semantics for ``bao_tasks``."""

from __future__ import annotations

from pathlib import Path

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.bao_tasks import (
    INTERRUPTED_ERROR,
    MAX_TASKS_PER_USER,
    BaoTaskRepo,
)


def _repo(path: Path) -> BaoTaskRepo:
    db = SqlitePool(path)
    run_migrations(db)
    return BaoTaskRepo(db)


def _create(repo: BaoTaskRepo, index: int = 0, *, dispatched_at: int | None = None):
    return repo.create(
        user_id=7,
        agent_id="a1",
        agent_name="小写",
        thread_id=f"t{index}",
        session_title=f"会话{index}",
        project_key="ws:alpha",
        project_name="alpha",
        task_text=f"任务 {index}",
        dispatched_at=dispatched_at,
    )


def test_task_survives_new_pool(tmp_path: Path) -> None:
    path = tmp_path / "bao.db"
    first = _repo(path)
    created = _create(first)

    reopened = BaoTaskRepo(SqlitePool(path))
    rows = reopened.list_for_user(7)

    assert [row.id for row in rows] == [created.id]
    assert rows[0].status == "running"
    assert rows[0].task_text == "任务 0"


def test_retention_caps_read_terminal_rows(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "cap.db")
    now = 1_800_000_000
    rows = [
        {
            "id": f"legacy-{index}",
            "agentId": "a1",
            "threadId": f"t{index}",
            "text": f"旧任务 {index}",
            "status": "done",
            "dispatchedAt": now - index,
        }
        for index in range(MAX_TASKS_PER_USER + 5)
    ]

    imported, skipped = repo.import_legacy(7, rows)

    assert imported == MAX_TASKS_PER_USER + 5
    assert skipped == 0
    # Imported legacy rows are protected as unread until the page sees them.
    assert repo.count_for_user(7) == MAX_TASKS_PER_USER + 5
    repo.acknowledge(7, [row["id"] for row in rows])
    assert repo.prune(7, now=now) == 5
    remaining = repo.list_for_user(7, limit=999)
    assert len(remaining) == MAX_TASKS_PER_USER
    assert "legacy-0" in {row.id for row in remaining}
    assert "legacy-204" not in {row.id for row in remaining}


def test_prune_keeps_running_awaiting_and_unread(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "protect.db")
    now = 1_800_000_000
    old = now - 40 * 86400

    running = _create(repo, 1, dispatched_at=old)
    awaiting = _create(repo, 2, dispatched_at=old)
    repo.complete_running(
        thread_id=awaiting.thread_id,
        agent_id="a1",
        status="awaiting",
        now=old,
    )
    unread_done = _create(repo, 3, dispatched_at=old)
    repo.complete_running(
        thread_id=unread_done.thread_id,
        agent_id="a1",
        status="done",
        result_text="结果",
        now=old,
    )

    deleted = repo.prune(7, now=now)

    assert deleted == 0
    ids = {row.id for row in repo.list_for_user(7, limit=999)}
    assert ids == {running.id, awaiting.id, unread_done.id}


def test_complete_running_is_idempotent(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "idempotent.db")
    task = _create(repo)

    assert (
        repo.complete_running(
            thread_id=task.thread_id,
            agent_id="a1",
            status="done",
            result_text="第一版结果",
        )
        == 1
    )
    assert (
        repo.complete_running(
            thread_id=task.thread_id,
            agent_id="a1",
            status="failed",
            error_text="晚了",
        )
        == 0
    )
    row = repo.get(task.id)
    assert row is not None
    assert row.status == "done"
    assert row.result_text == "第一版结果"
    assert row.completed_at is not None


def test_reconcile_interrupted_respects_grace_and_active(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "reconcile.db")
    now = 1_800_000_000
    stale = _create(repo, 1, dispatched_at=now - 120)
    active = _create(repo, 2, dispatched_at=now - 120)
    fresh = _create(repo, 3, dispatched_at=now)

    changed = repo.reconcile_interrupted(
        user_id=7,
        active_thread_ids={active.thread_id},
        now=now,
        grace_seconds=30,
    )

    assert changed == 1
    assert repo.get(stale.id).status == "failed"  # type: ignore[union-attr]
    assert repo.get(stale.id).error_text == INTERRUPTED_ERROR  # type: ignore[union-attr]
    assert repo.get(active.id).status == "running"  # type: ignore[union-attr]
    assert repo.get(fresh.id).status == "running"  # type: ignore[union-attr]


def test_reconcile_keeps_a_task_nudged_moments_ago(tmp_path: Path) -> None:
    """An auto follow-up restarts the grace clock.

    The first attempt can be minutes old; while its nudge turn is still
    replying the compensating refresh must not mark it as an orphan.
    """
    repo = _repo(tmp_path / "reconcile-nudge.db")
    now = 1_800_000_000
    task = _create(repo, 1, dispatched_at=now - 180)
    repo.complete_running(
        thread_id=task.thread_id,
        agent_id=task.agent_id,
        status="failed",
        error_text="请补充需求？",
        now=now - 6,
    )
    reopened = repo.record_followup(task.id, now=now - 5)
    assert reopened is not None and reopened.status == "running"

    changed = repo.reconcile_interrupted(
        user_id=7,
        active_thread_ids=set(),
        now=now,
        grace_seconds=30,
    )

    assert changed == 0
    row = repo.get(task.id)
    assert row is not None
    assert row.status == "running"
    assert row.followup_count == 1


def test_reconcile_fails_a_task_whose_nudge_is_long_gone(tmp_path: Path) -> None:
    """The follow-up grace is bounded: an abandoned nudge still gets cleared."""
    repo = _repo(tmp_path / "reconcile-old-nudge.db")
    now = 1_800_000_000
    task = _create(repo, 1, dispatched_at=now - 1800)
    repo.complete_running(
        thread_id=task.thread_id,
        agent_id=task.agent_id,
        status="failed",
        error_text="请补充需求？",
        now=now - 1200,
    )
    repo.record_followup(task.id, now=now - 1200)

    changed = repo.reconcile_interrupted(
        user_id=7,
        active_thread_ids=set(),
        now=now,
        grace_seconds=30,
        followup_grace_seconds=600,
    )

    assert changed == 1
    row = repo.get(task.id)
    assert row is not None
    assert row.status == "failed"


def test_import_legacy_is_idempotent(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "legacy.db")
    rows = [
        {
            "id": "legacy-1",
            "agentId": "a1",
            "agentName": "小写",
            "threadId": "t1",
            "text": "升级前的任务",
            "status": "done",
            "resultText": "已完成",
            "dispatchedAt": 1_700_000_000,
            "routeReason": {"code": "session_title", "params": {"title": "会话一"}},
        }
    ]

    first = repo.import_legacy(7, rows)
    second = repo.import_legacy(7, rows)

    assert first == (1, 0)
    assert second == (0, 1)
    row = repo.get("legacy-1")
    assert row is not None
    assert row.source == "legacy"
    assert row.status == "done"
    assert row.result_text == "已完成"
    assert row.acknowledged_at is None
    assert '"session_title"' in row.route_reason_json

    repo.acknowledge(7, [row.id])
    assert repo.get("legacy-1").acknowledged_at is not None  # type: ignore[union-attr]


def test_followup_reopens_task_and_tracks_count(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "followup.db")
    task = _create(repo)
    repo.complete_running(
        thread_id=task.thread_id,
        agent_id="a1",
        status="done",
        result_text="需要更多信息才能继续",
    )

    terminal = repo.latest_terminal_for_thread(task.thread_id, "a1")
    assert terminal is not None
    assert terminal.id == task.id

    reopened = repo.record_followup(task.id)
    assert reopened is not None
    assert reopened.status == "running"
    assert reopened.followup_count == 1
    assert reopened.completed_at is None
    assert reopened.eval_status is None
    assert repo.latest_terminal_for_thread(task.thread_id, "a1") is None

    repo.complete_running(
        thread_id=task.thread_id,
        agent_id="a1",
        status="done",
        result_text="这是可交付的完整结果，包含结论与下一步建议。",
    )
    again = repo.latest_terminal_for_thread(task.thread_id, "a1")
    assert again is not None and again.followup_count == 1

    assert repo.mark_evaluated(task.id, "done_ok") == 1
    assert repo.latest_terminal_for_thread(task.thread_id, "a1") is None


def test_get_for_thread_filters_status(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "thread.db")
    first = _create(repo, 1)
    second = _create(repo, 2)
    repo.complete_running(
        thread_id=second.thread_id,
        agent_id="a1",
        status="failed",
        error_text="boom",
    )

    assert [row.id for row in repo.get_for_thread(first.thread_id, "a1")] == [first.id]
    assert repo.get_for_thread("missing", "a1") == []
