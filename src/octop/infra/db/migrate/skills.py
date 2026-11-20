"""Skill package identity schema (legacy text keys -> integer ids)."""

from __future__ import annotations

from octop.infra.db.migrate.introspect import (
    _ensure_column,
    _integer_pk_sql,
    _table_columns,
    _table_exists,
)
from octop.infra.db.pool import DatabasePool


def _skill_packages_identity_ready(db: DatabasePool) -> bool:
    return _table_exists(db, "skill_packages") and "skill_package_id" in _table_columns(
        db, "skill_packages"
    )


def _create_skill_packages_identity_table(db: DatabasePool) -> None:
    pk = _integer_pk_sql(db)
    with db.connect() as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS skill_packages (
              id {pk},
              skill_package_id TEXT NOT NULL UNIQUE,
              name TEXT NOT NULL,
              description TEXT NOT NULL DEFAULT '',
              created_by TEXT NOT NULL,
              skill_count INTEGER NOT NULL DEFAULT 0,
              icon_name TEXT NOT NULL DEFAULT '',
              icon_url TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_skill_packages_name ON skill_packages(name)"
        )


def _rebuild_skill_packages_identity_schema(db: DatabasePool) -> None:
    """Give skill_packages an integer PK plus public ``skill_package_id``."""
    if _skill_packages_identity_ready(db):
        return
    if not _table_exists(db, "skill_packages"):
        _create_skill_packages_identity_table(db)
        return
    if "icon_name" not in _table_columns(db, "skill_packages"):
        _ensure_column(db, "skill_packages", "icon_name", "TEXT NOT NULL DEFAULT ''")
    if "icon_url" not in _table_columns(db, "skill_packages"):
        _ensure_column(db, "skill_packages", "icon_url", "TEXT NOT NULL DEFAULT ''")
    pk = _integer_pk_sql(db)
    with db.transaction() as conn:
        if db.dialect == "sqlite":
            conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("ALTER TABLE skill_packages RENAME TO skill_packages_legacy")
        conn.execute(
            f"""
            CREATE TABLE skill_packages (
              id {pk},
              skill_package_id TEXT NOT NULL UNIQUE,
              name TEXT NOT NULL,
              description TEXT NOT NULL DEFAULT '',
              created_by TEXT NOT NULL,
              skill_count INTEGER NOT NULL DEFAULT 0,
              icon_name TEXT NOT NULL DEFAULT '',
              icon_url TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO skill_packages(
              skill_package_id, name, description, created_by, skill_count,
              icon_name, icon_url, created_at, updated_at
            )
            SELECT id, name, description, created_by, skill_count,
              COALESCE(icon_name, ''), COALESCE(icon_url, ''), created_at, updated_at
            FROM skill_packages_legacy
            """
        )
        conn.execute("DROP TABLE skill_packages_legacy")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_skill_packages_name ON skill_packages(name)"
        )
        if db.dialect == "sqlite":
            conn.execute("PRAGMA foreign_keys = ON")


def _ensure_skill_packages_schema(db: DatabasePool) -> None:
    """Create or rebuild skill_packages to the integer-PK identity schema."""
    _rebuild_skill_packages_identity_schema(db)
