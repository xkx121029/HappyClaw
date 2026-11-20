"""Single-user owner schema."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping

from octop.infra.db.pool import DatabasePool

logger = logging.getLogger(__name__)


def _ensure_single_user_schema(db: DatabasePool) -> None:
    """v26 single-user marker: additive, idempotent and rollback-safe.

    Never rewrites or deletes existing accounts. If adoption fails the
    transaction rolls back and the caller sees a Chinese warning while the
    English original goes to the log.
    """
    id_type = "BIGINT" if db.dialect == "postgresql" else "INTEGER"
    try:
        with db.transaction() as conn:
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS local_owner ("
                f"user_id {id_type} PRIMARY KEY, "
                f"adopted_at {id_type} NOT NULL, "
                f"source TEXT NOT NULL DEFAULT 'migration')"
            )
            existing = conn.execute("SELECT user_id FROM local_owner LIMIT 1").fetchone()
            if existing is not None:
                return
            row = conn.execute(
                "SELECT id FROM users WHERE role = 'admin' AND disabled = 0 ORDER BY id LIMIT 1"
            ).fetchone()
            source = "migration-admin"
            if row is None:
                row = conn.execute(
                    "SELECT id FROM users WHERE disabled = 0 ORDER BY id LIMIT 1"
                ).fetchone()
                source = "migration"
            if row is None:
                # Empty installation: OwnerIdentityService creates the owner on
                # first boot instead of inventing credentials here.
                return
            user_id = row["id"] if isinstance(row, Mapping) else row[0]
            conn.execute(
                "INSERT INTO local_owner(user_id, adopted_at, source) VALUES (?, ?, ?)",
                (int(user_id), int(time.time()), source),
            )
    except Exception as exc:
        logger.exception("single-user schema adoption failed; existing rows were left untouched")
        raise RuntimeError("单人模式迁移失败：已保留原有数据，请查看日志") from exc
