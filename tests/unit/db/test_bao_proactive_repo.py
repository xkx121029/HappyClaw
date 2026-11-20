"""Dedupe, rate limiting and mute semantics for Bao's proactive log."""

from __future__ import annotations

from pathlib import Path

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.bao_proactive import BaoProactiveRepo


def _repo(path: Path) -> BaoProactiveRepo:
    db = SqlitePool(path)
    run_migrations(db)
    return BaoProactiveRepo(db)


def test_same_task_kind_notifies_once(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "dedupe.db")
    base = 1_800_000_000

    assert repo.claim(user_id=1, task_id="t1", kind="done", now=base) == (True, None)
    assert repo.claim(user_id=1, task_id="t1", kind="done", now=base + 10) == (
        False,
        "duplicate",
    )
    assert repo.claim(user_id=1, task_id="t1", kind="failed", now=base + 20) == (
        False,
        "rate_limited",
    )


def test_min_interval_and_hourly_cap(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "rate.db")
    base = 1_800_000_000

    assert repo.claim(user_id=1, task_id="a", kind="done", now=base)[0]
    assert repo.claim(user_id=1, task_id="b", kind="done", now=base + 60) == (
        False,
        "rate_limited",
    )
    assert repo.claim(user_id=1, task_id="b", kind="done", now=base + 121)[0]

    delivered = 2
    moment = base + 121
    for index in range(4):
        moment += 121
        assert repo.claim(user_id=1, task_id=f"c{index}", kind="done", now=moment)[0]
        delivered += 1
    assert delivered == 6
    assert repo.claim(user_id=1, task_id="z", kind="done", now=moment + 121) == (
        False,
        "rate_limited",
    )


def test_muted_logs_without_delivering(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "mute.db")
    base = 1_800_000_000

    assert repo.claim(user_id=1, task_id="t1", kind="done", muted=True, now=base) == (
        False,
        "muted",
    )
    rows = repo.list_for_user(1)
    assert rows[0].delivered == 0
    assert rows[0].suppressed_reason == "muted"
    # A suppressed event does not consume the rate-limit budget.
    assert repo.claim(user_id=1, task_id="t2", kind="done", now=base + 1)[0]
