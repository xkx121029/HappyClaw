"""Instance lease and control blob tables."""

from __future__ import annotations

from octop.infra.db.migrate.introspect import (
    _ensure_column,
    _table_exists,
)
from octop.infra.db.pool import DatabasePool


def _ensure_instance_lease_schema(db: DatabasePool) -> None:
    """Cron run leases and channel connection leases (v25). Idempotent."""
    until = "BIGINT" if db.dialect == "postgresql" else "INTEGER"
    if _table_exists(db, "cron_jobs"):
        _ensure_column(db, "cron_jobs", "run_lease_owner", "TEXT")
        _ensure_column(db, "cron_jobs", "run_lease_token", "TEXT")
        _ensure_column(db, "cron_jobs", "run_lease_until", until)
    if _table_exists(db, "channels"):
        _ensure_column(db, "channels", "runtime_lease_owner", "TEXT")
        _ensure_column(db, "channels", "runtime_lease_token", "TEXT")
        _ensure_column(db, "channels", "runtime_lease_until", until)
        _ensure_column(
            db,
            "channels",
            "runtime_generation",
            "INTEGER NOT NULL DEFAULT 0",
        )


def _ensure_control_blobs_schema(db: DatabasePool) -> None:
    """Profile avatars and shared file trees (plugins, published experts)."""
    if db.dialect == "postgresql":
        with db.connect() as conn, conn.transaction():
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS profile_avatars (
                  owner_kind TEXT NOT NULL,
                  owner_id TEXT NOT NULL,
                  media_type TEXT NOT NULL,
                  content BYTEA NOT NULL,
                  updated_at BIGINT NOT NULL,
                  PRIMARY KEY (owner_kind, owner_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS control_files (
                  namespace TEXT NOT NULL,
                  owner_id TEXT NOT NULL,
                  path TEXT NOT NULL,
                  content BYTEA NOT NULL,
                  PRIMARY KEY (namespace, owner_id, path)
                )
                """
            )
        return
    with db.connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS profile_avatars (
              owner_kind TEXT NOT NULL,
              owner_id TEXT NOT NULL,
              media_type TEXT NOT NULL,
              content BLOB NOT NULL,
              updated_at INTEGER NOT NULL,
              PRIMARY KEY (owner_kind, owner_id)
            );
            CREATE TABLE IF NOT EXISTS control_files (
              namespace TEXT NOT NULL,
              owner_id TEXT NOT NULL,
              path TEXT NOT NULL,
              content BLOB NOT NULL,
              PRIMARY KEY (namespace, owner_id, path)
            );
            """
        )
