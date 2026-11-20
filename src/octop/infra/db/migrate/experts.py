"""Published expert identity schema rebuild."""

from __future__ import annotations

from octop.infra.db.migrate.introspect import (
    _integer_pk_sql,
    _table_columns,
    _table_exists,
)
from octop.infra.db.pool import DatabasePool


def _published_experts_identity_ready(db: DatabasePool) -> bool:
    return _table_exists(db, "published_experts") and "published_expert_id" in _table_columns(
        db, "published_experts"
    )


def _create_published_experts_identity_table(db: DatabasePool) -> None:
    pk = _integer_pk_sql(db)
    with db.connect() as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS published_experts (
              id {pk},
              published_expert_id TEXT NOT NULL UNIQUE,
              slug TEXT NOT NULL,
              name TEXT NOT NULL,
              description TEXT NOT NULL DEFAULT '',
              created_by TEXT NOT NULL,
              source_agent_id TEXT,
              icon_name TEXT NOT NULL DEFAULT '',
              color TEXT NOT NULL DEFAULT '',
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_published_experts_slug "
            "ON published_experts(slug)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_published_experts_created_by "
            "ON published_experts(created_by)"
        )


def _rebuild_published_experts_identity_schema(db: DatabasePool) -> None:
    """Give published_experts an integer PK plus public ``published_expert_id``."""
    if _published_experts_identity_ready(db):
        return
    if not _table_exists(db, "published_experts"):
        _create_published_experts_identity_table(db)
        return
    pk = _integer_pk_sql(db)
    with db.transaction() as conn:
        if db.dialect == "sqlite":
            conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("ALTER TABLE published_experts RENAME TO published_experts_legacy")
        conn.execute(
            f"""
            CREATE TABLE published_experts (
              id {pk},
              published_expert_id TEXT NOT NULL UNIQUE,
              slug TEXT NOT NULL,
              name TEXT NOT NULL,
              description TEXT NOT NULL DEFAULT '',
              created_by TEXT NOT NULL,
              source_agent_id TEXT,
              icon_name TEXT NOT NULL DEFAULT '',
              color TEXT NOT NULL DEFAULT '',
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO published_experts(
              published_expert_id, slug, name, description, created_by,
              source_agent_id, icon_name, color, created_at, updated_at
            )
            SELECT id, slug, name, description, created_by,
              source_agent_id, COALESCE(icon_name, ''), COALESCE(color, ''),
              created_at, updated_at
            FROM published_experts_legacy
            """
        )
        conn.execute("DROP TABLE published_experts_legacy")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_published_experts_slug "
            "ON published_experts(slug)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_published_experts_created_by "
            "ON published_experts(created_by)"
        )
        if db.dialect == "sqlite":
            conn.execute("PRAGMA foreign_keys = ON")


def _ensure_published_experts_schema(db: DatabasePool) -> None:
    """Create or rebuild published_experts to the integer-PK identity schema."""
    _rebuild_published_experts_identity_schema(db)
