"""Single-user owner resolution (single-user refactor)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from happyclaw.infra.db.migrate import run_migrations
from happyclaw.infra.db.pool import SqlitePool
from happyclaw.infra.db.repos.users import UserRepo
from happyclaw.infra.users.owner import OWNER_USERNAME, OwnerIdentityService
from happyclaw.infra.users.permissions import PERMISSIONS


class _StubServices:
    def __init__(self, db: SqlitePool, repo: UserRepo) -> None:
        self.db = db
        self.user_repo = repo


@pytest.fixture
def env(tmp_path: Path) -> tuple[SqlitePool, UserRepo, OwnerIdentityService, _StubServices]:
    db = SqlitePool(tmp_path / "owner.db")
    run_migrations(db)
    repo = UserRepo(db)
    services = _StubServices(db, repo)
    return db, repo, OwnerIdentityService(services), services  # type: ignore[arg-type]


def _local_owner_id(db: SqlitePool) -> int | None:
    with db.connect() as conn:
        row = conn.execute("SELECT user_id FROM local_owner LIMIT 1").fetchone()
    return int(row["user_id"]) if row is not None else None


def test_empty_database_creates_local_owner(env: Any) -> None:
    db, repo, service, _ = env
    user = service.owner()
    assert user.username == OWNER_USERNAME
    assert user.role == "admin"
    assert user.permissions == sorted(PERMISSIONS)
    assert repo.get(user.id) is not None
    assert _local_owner_id(db) == user.id


def test_adopts_existing_admin_without_touching_other_rows(env: Any) -> None:
    db, repo, service, _ = env
    first = repo.create(username="alice", password_hash="x", role="user")
    admin = repo.create(username="bob", password_hash="x", role="admin")
    repo.create(username="carol", password_hash="x", role="admin")
    before = [row.id for row in repo.list(include_disabled=True)]

    user = service.owner()

    assert user.id == admin
    assert user.username == "bob"
    assert _local_owner_id(db) == admin
    assert [row.id for row in repo.list(include_disabled=True)] == before
    assert first in before


def test_recorded_owner_wins_over_other_admins(env: Any) -> None:
    db, repo, service, _ = env
    repo.create(username="first-admin", password_hash="x", role="admin")
    chosen = repo.create(username="chosen", password_hash="x", role="admin")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO local_owner(user_id, adopted_at, source) VALUES (?, 1, 'manual')",
            (chosen,),
        )
    assert service.owner().id == chosen


def test_owner_is_cached_per_services(env: Any) -> None:
    _, repo, service, _ = env
    repo.create(username="alice", password_hash="x", role="admin")
    first = service.owner()
    repo.create(username="later-admin", password_hash="x", role="admin")
    assert service.owner().id == first.id
    service.reset_cache()
    assert service.owner().id == first.id


def test_disabled_owner_is_replaced(env: Any) -> None:
    db, repo, service, _ = env
    stale = repo.create(username="stale", password_hash="x", role="admin")
    live = repo.create(username="live", password_hash="x", role="admin")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO local_owner(user_id, adopted_at, source) VALUES (?, 1, 'manual')",
            (stale,),
        )
    repo.set_disabled(stale, True)

    assert service.owner().id == live
    assert _local_owner_id(db) == live
