"""Rate-limited log for Bao's proactive notifications.

Only three events may reach the user: task finished, task needs a decision,
task failed. Every attempt is recorded — delivered or suppressed — so the
"stay quiet unless you are needed" rule is auditable and testable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from octop.infra.db.pool import DatabasePool
from octop.infra.db.repos._base import DbRow
from octop.infra.utils.ulid import new_ulid

MAX_LOG_PER_USER = 500
MAX_LOG_AGE_DAYS = 30
MIN_INTERVAL_SECONDS = 120
HOURLY_CAP = 6
PROACTIVE_KINDS = frozenset({"done", "needs_decision", "failed"})


@dataclass(frozen=True)
class BaoProactiveRow:
    id: str
    user_id: int
    task_id: str
    kind: str
    dedupe_key: str
    delivered: int
    suppressed_reason: str | None
    created_at: int

    @classmethod
    def from_row(cls, row: DbRow) -> "BaoProactiveRow":
        return cls(
            id=str(row["id"]),
            user_id=int(row["user_id"]),
            task_id=str(row["task_id"]),
            kind=str(row["kind"]),
            dedupe_key=str(row["dedupe_key"]),
            delivered=int(row["delivered"]),
            suppressed_reason=(
                str(row["suppressed_reason"])
                if row["suppressed_reason"] is not None
                else None
            ),
            created_at=int(row["created_at"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "kind": self.kind,
            "delivered": bool(self.delivered),
            "suppressed_reason": self.suppressed_reason,
            "created_at": self.created_at,
        }


class BaoProactiveRepo:
    """Claim + log proactive notifications for one user."""

    def __init__(self, db: DatabasePool) -> None:
        self._db = db

    def claim(
        self,
        *,
        user_id: int,
        task_id: str,
        kind: str,
        muted: bool = False,
        now: int | None = None,
        min_interval: int = MIN_INTERVAL_SECONDS,
        hourly_cap: int = HOURLY_CAP,
    ) -> tuple[bool, str | None]:
        """Return ``(claimed, suppressed_reason)``.

        ``dedupe_key`` is ``{task}:{kind}`` and permanent: the same event never
        notifies twice. A muted user gets a log row but no frame. Rate limits
        apply to delivered rows only, so a suppressed burst does not starve the
        next legitimate notification.
        """
        if kind not in PROACTIVE_KINDS:
            raise ValueError(f"invalid proactive kind: {kind}")
        ts = int(now if now is not None else time.time())
        dedupe_key = f"{task_id}:{kind}"
        with self._db.transaction() as conn:
            exists = conn.execute(
                "SELECT 1 FROM bao_proactive_log WHERE dedupe_key = ? AND delivered = 1",
                (dedupe_key,),
            ).fetchone()
            if exists is not None:
                return False, "duplicate"

            reason: str | None = None
            if muted:
                reason = "muted"
            else:
                recent = conn.execute(
                    "SELECT COUNT(*) FROM bao_proactive_log "
                    "WHERE user_id = ? AND delivered = 1 AND created_at >= ?",
                    (user_id, ts - max(int(min_interval), 0)),
                ).fetchone()
                hourly = conn.execute(
                    "SELECT COUNT(*) FROM bao_proactive_log "
                    "WHERE user_id = ? AND delivered = 1 AND created_at >= ?",
                    (user_id, ts - 3600),
                ).fetchone()
                recent_count = int(recent[0]) if recent is not None else 0
                hourly_count = int(hourly[0]) if hourly is not None else 0
                if recent_count > 0 or hourly_count >= hourly_cap:
                    reason = "rate_limited"

            conn.execute(
                "INSERT INTO bao_proactive_log("
                "id, user_id, task_id, kind, dedupe_key, delivered, "
                "suppressed_reason, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    new_ulid(),
                    user_id,
                    task_id,
                    kind,
                    dedupe_key,
                    0 if reason else 1,
                    reason,
                    ts,
                ),
            )
        self.prune(user_id)
        return (reason is None), reason

    def list_for_user(self, user_id: int, limit: int = 50) -> list[BaoProactiveRow]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM bao_proactive_log WHERE user_id = ? "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                (user_id, max(int(limit), 1)),
            ).fetchall()
        return [BaoProactiveRow.from_row(row) for row in rows]

    def prune(self, user_id: int, *, now: int | None = None) -> int:
        ts = int(now if now is not None else time.time())
        cutoff = ts - MAX_LOG_AGE_DAYS * 86400
        deleted = 0
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM bao_proactive_log WHERE user_id = ? AND created_at < ?",
                (user_id, cutoff),
            )
            deleted += int(cursor.rowcount or 0)
            rows = conn.execute(
                "SELECT id FROM bao_proactive_log WHERE user_id = ? "
                "ORDER BY created_at DESC, id DESC",
                (user_id,),
            ).fetchall()
            extra = [str(row[0]) for row in rows[MAX_LOG_PER_USER:]]
            for start in range(0, len(extra), 100):
                chunk = extra[start : start + 100]
                placeholders = ",".join("?" for _ in chunk)
                cursor = conn.execute(
                    f"DELETE FROM bao_proactive_log WHERE user_id = ? "  # noqa: S608
                    f"AND id IN ({placeholders})",
                    (user_id, *chunk),
                )
                deleted += int(cursor.rowcount or 0)
        return deleted


__all__ = [
    "BaoProactiveRepo",
    "BaoProactiveRow",
    "HOURLY_CAP",
    "MAX_LOG_PER_USER",
    "MIN_INTERVAL_SECONDS",
]
