"""Connector instance schema (v13) and credential text repair."""

from __future__ import annotations

from octop.infra.db.migrate.introspect import (
    _table_columns,
    _table_exists,
)
from octop.infra.db.pool import DatabasePool


def _ensure_connectors_v13_schema(db: DatabasePool) -> None:
    """Ensure connectors supports multiple named instances and sharing."""
    if not _table_exists(db, "connectors"):
        return
    if db.dialect == "postgresql":
        with db.connect() as conn, conn.transaction():
            conn.execute(
                "ALTER TABLE connectors DROP CONSTRAINT IF EXISTS connectors_user_id_kind_key"
            )
            conn.execute(
                "ALTER TABLE connectors ADD COLUMN IF NOT EXISTS shared INTEGER NOT NULL DEFAULT 0"
            )
            conn.execute(
                """
                WITH ranked AS (
                  SELECT id, display_name, instance_id,
                         ROW_NUMBER() OVER (
                           PARTITION BY user_id, display_name ORDER BY id
                         ) AS duplicate_number
                  FROM connectors
                  WHERE kind <> 'custom-mcp'
                )
                UPDATE connectors AS c
                SET display_name = ranked.display_name || ' (' ||
                    right(ranked.instance_id, 6) || ')'
                FROM ranked
                WHERE c.id = ranked.id AND ranked.duplicate_number > 1
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_connectors_shared "
                "ON connectors(shared) WHERE shared = 1"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_connectors_user_display_name "
                "ON connectors(user_id, display_name) WHERE kind <> 'custom-mcp'"
            )
        return

    if "shared" in _table_columns(db, "connectors"):
        with db.connect() as conn:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_connectors_shared "
                "ON connectors(shared) WHERE shared = 1"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_connectors_user_display_name "
                "ON connectors(user_id, display_name) WHERE kind <> 'custom-mcp'"
            )
        return

    with db.connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        try:
            conn.execute("BEGIN")
            conn.execute("ALTER TABLE connectors RENAME TO connectors_legacy")
            conn.execute(
                """
                CREATE TABLE connectors (
                  id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                  instance_id           TEXT NOT NULL UNIQUE,
                  user_id               INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                  kind                  TEXT NOT NULL,
                  display_name          TEXT NOT NULL,
                  status                TEXT NOT NULL DEFAULT 'active',
                  shared                INTEGER NOT NULL DEFAULT 0,
                  mcp_server_name       TEXT NOT NULL UNIQUE,
                  credential_blob       BLOB,
                  credential_expires_at INTEGER,
                  credential_rotated_at INTEGER,
                  config_json           TEXT,
                  created_at            INTEGER NOT NULL,
                  updated_at            INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO connectors(
                  id, instance_id, user_id, kind, display_name, status, shared,
                  mcp_server_name, credential_blob, credential_expires_at,
                  credential_rotated_at, config_json, created_at, updated_at
                )
                SELECT
                  id, instance_id, user_id, kind,
                  CASE
                    WHEN kind = 'custom-mcp' THEN display_name
                    WHEN ROW_NUMBER() OVER (
                      PARTITION BY user_id, display_name ORDER BY id
                    ) = 1 THEN display_name
                    ELSE display_name || ' (' || substr(instance_id, -6) || ')'
                  END,
                  status, 0, mcp_server_name, credential_blob, credential_expires_at,
                  credential_rotated_at, config_json, created_at, updated_at
                FROM connectors_legacy
                """
            )
            conn.execute("DROP TABLE connectors_legacy")
            conn.execute("CREATE INDEX idx_connectors_user ON connectors(user_id)")
            conn.execute(
                "CREATE INDEX idx_connectors_shared ON connectors(shared) WHERE shared = 1"
            )
            conn.execute(
                "CREATE UNIQUE INDEX idx_connectors_user_display_name "
                "ON connectors(user_id, display_name) WHERE kind <> 'custom-mcp'"
            )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.execute("PRAGMA foreign_keys = ON")


def _repair_connector_text_credentials(db: DatabasePool) -> None:
    """Cast TEXT ``connectors.credential_blob`` values back to BLOB.

    Idempotent. PostgreSQL ``BYTEA`` cannot store the historical TEXT row, and
    databases already at the current schema version must still be repaired, so
    this stays out of the numbered migrations.
    """
    if db.dialect != "sqlite" or not _table_exists(db, "connectors"):
        return
    with db.transaction() as conn:
        conn.execute(
            "UPDATE connectors "
            "SET credential_blob = CAST(credential_blob AS BLOB) "
            "WHERE typeof(credential_blob) = 'text'"
        )
