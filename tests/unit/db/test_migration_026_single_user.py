"""Migration 026: single-user owner marker is additive and idempotent."""

from __future__ import annotations

from pathlib import Path

import pytest

from octop.infra.db import migrate
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.users import UserRepo


def _owner_rows(db: SqlitePool) -> list[int]:
    with db.connect() as conn:
        rows = conn.execute("SELECT user_id FROM local_owner ORDER BY user_id").fetchall()
    return [int(row["user_id"]) for row in rows]


def test_migration_adopts_admin_and_keeps_all_users(tmp_path: Path) -> None:
    db = SqlitePool(tmp_path / "upgrade.db")
    run_migrations(db)
    repo = UserRepo(db)
    repo.create(username="alice", password_hash="x", role="user")
    admin = repo.create(username="bob", password_hash="x", role="admin")
    repo.create(username="carol", password_hash="x", role="admin")
    with db.connect() as conn:
        conn.execute("DELETE FROM local_owner")
        conn.execute("UPDATE _schema_version SET version = 25")
    before = [row.id for row in repo.list(include_disabled=True)]

    run_migrations(db)

    after = [row.id for row in repo.list(include_disabled=True)]
    assert after == before, "migration must not delete or rewrite user rows"
    assert _owner_rows(db) == [admin]


def test_migration_is_idempotent(tmp_path: Path) -> None:
    db = SqlitePool(tmp_path / "idempotent.db")
    run_migrations(db)
    repo = UserRepo(db)
    admin = repo.create(username="bob", password_hash="x", role="admin")
    migrate._ensure_single_user_schema(db)
    migrate._ensure_single_user_schema(db)
    assert _owner_rows(db) == [admin]


def test_empty_database_has_no_owner_yet(tmp_path: Path) -> None:
    db = SqlitePool(tmp_path / "empty.db")
    run_migrations(db)
    assert _owner_rows(db) == []


def test_failure_preserves_data_and_reports_chinese(tmp_path: Path) -> None:
    db = SqlitePool(tmp_path / "broken.db")
    run_migrations(db)
    repo = UserRepo(db)
    admin = repo.create(username="bob", password_hash="x", role="admin")

    with db.connect() as conn:
        conn.execute("ALTER TABLE users RENAME TO users_renamed")

    with pytest.raises(RuntimeError) as excinfo:
        migrate._ensure_single_user_schema(db)

    assert "单人模式迁移失败" in str(excinfo.value)

    with db.connect() as conn:
        conn.execute("ALTER TABLE users_renamed RENAME TO users")
    assert [row.id for row in repo.list(include_disabled=True)] == [admin]
    assert _owner_rows(db) == []
