"""Cron run history: one row per planned (or manual) delivery attempt."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from octop.infra.db.lease import opt_int
from octop.infra.db.pool import DatabasePool
from octop.infra.db.repos._base import DbRow, map_rows, now_ts

__all__ = [
    "RUN_STATUS_ERROR",
    "RUN_STATUS_MISSED",
    "RUN_STATUS_OK",
    "RUN_STATUS_RUNNING",
    "RUN_STATUS_SKIPPED",
    "CronRunRepo",
    "CronRunRow",
]

RUN_STATUS_RUNNING = "running"
RUN_STATUS_OK = "ok"
RUN_STATUS_ERROR = "error"
RUN_STATUS_MISSED = "missed"
RUN_STATUS_SKIPPED = "skipped"

TRIGGER_KIND_SCHEDULE = "schedule"
TRIGGER_KIND_MANUAL = "manual"
TRIGGER_KIND_MAIL = "mail"
TRIGGER_KIND_CATCHUP = "catchup"

# Keep the ledger small enough to stay useful: the dashboard only reads the tail.
RUN_HISTORY_KEEP = 200


@dataclass(frozen=True)
class CronRunRow:
    id: int
    run_id: str
    cron_id: str
    trigger_kind: str
    scheduled_for: int | None
    status: str
    attempt: int
    started_at: int
    finished_at: int | None
    duration_ms: int | None
    error: str | None
    note: str | None
    created_at: int

    @classmethod
    def from_row(cls, r: DbRow) -> CronRunRow:
        return cls(
            id=r["id"],
            run_id=r["run_id"],
            cron_id=r["cron_id"],
            trigger_kind=str(r["trigger_kind"]),
            scheduled_for=opt_int(r["scheduled_for"]),
            status=str(r["status"]),
            attempt=int(r["attempt"]),
            started_at=int(r["started_at"]),
            finished_at=opt_int(r["finished_at"]),
            duration_ms=opt_int(r["duration_ms"]),
            error=r["error"],
            note=r["note"],
            created_at=int(r["created_at"]),
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "cron_id": self.cron_id,
            "trigger_kind": self.trigger_kind,
            "scheduled_for": self.scheduled_for,
            "status": self.status,
            "attempt": self.attempt,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "note": self.note,
        }


class CronRunRepo:
    def __init__(self, db: DatabasePool) -> None:
        self._db = db

    def start(
        self,
        cron_id: str,
        *,
        trigger_kind: str,
        scheduled_for: int | None,
        run_id: str | None = None,
    ) -> CronRunRow | None:
        """Open a run record; return None when this slot is already claimed.

        The unique index on ``(cron_id, scheduled_for)`` is the dedupe: a
        restarted process, a duplicated scheduler tick, or a catch-up pass that
        replays a slot all collide here instead of running the job twice.
        """
        rid = run_id or uuid.uuid4().hex
        ts = now_ts()
        sql = (
            "INSERT INTO cron_runs(run_id, cron_id, trigger_kind, scheduled_for, status, "
            "attempt, started_at, created_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?) "
            "ON CONFLICT DO NOTHING RETURNING *"
        )
        with self._db.transaction() as conn:
            row = conn.execute(
                sql,
                (rid, cron_id, trigger_kind, scheduled_for, RUN_STATUS_RUNNING, ts, ts),
            ).fetchone()
        return CronRunRow.from_row(row) if row else None

    def finish(
        self,
        run_id: str,
        *,
        status: str,
        error: str | None = None,
        attempt: int | None = None,
        note: str | None = None,
    ) -> bool:
        ts = now_ts()
        with self._db.transaction() as conn:
            cur = conn.execute(
                "UPDATE cron_runs SET status = ?, error = ?, note = ?, finished_at = ?, "
                "duration_ms = (? - started_at) * 1000, "
                "attempt = COALESCE(?, attempt) "
                "WHERE run_id = ? AND status = ?",
                (status, error, note, ts, ts, attempt, run_id, RUN_STATUS_RUNNING),
            )
            return int(cur.rowcount or 0) > 0

    def mark_attempt(self, run_id: str, *, attempt: int, error: str | None = None) -> None:
        """Record a failed attempt that is about to be retried."""
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE cron_runs SET attempt = ?, error = ?, started_at = ? "
                "WHERE run_id = ? AND status = ?",
                (attempt, error, now_ts(), run_id, RUN_STATUS_RUNNING),
            )

    def record_missed_slot(
        self,
        cron_id: str,
        *,
        scheduled_for: int,
        reason: str | None = None,
    ) -> bool:
        """Write a terminal ``missed`` row for a slot the process never ran."""
        ts = now_ts()
        sql = (
            "INSERT INTO cron_runs(run_id, cron_id, trigger_kind, scheduled_for, status, "
            "attempt, started_at, finished_at, duration_ms, error, created_at) "
            "VALUES (?, ?, 'schedule', ?, ?, 0, ?, ?, 0, ?, ?) "
            "ON CONFLICT DO NOTHING RETURNING id"
        )
        with self._db.transaction() as conn:
            row = conn.execute(
                sql,
                (
                    uuid.uuid4().hex,
                    cron_id,
                    scheduled_for,
                    RUN_STATUS_MISSED,
                    scheduled_for,
                    scheduled_for,
                    reason,
                    ts,
                ),
            ).fetchone()
        return row is not None

    def close_stale_running(self, *, older_than_seconds: int) -> int:
        """Fail runs whose owning process died without recording a result.

        A run is only closed when its job holds no live lease: another instance
        sharing the database may still be executing it and renewing.
        """
        now = now_ts()
        cutoff = now - older_than_seconds
        with self._db.transaction() as conn:
            cur = conn.execute(
                "UPDATE cron_runs SET status = ?, finished_at = ?, "
                "duration_ms = (? - started_at) * 1000, error = ? "
                "WHERE status = ? AND started_at < ? AND NOT EXISTS ("
                "SELECT 1 FROM cron_jobs j WHERE j.cron_id = cron_runs.cron_id "
                "AND j.run_lease_until IS NOT NULL AND j.run_lease_until >= ?"
                ")",
                (
                    RUN_STATUS_ERROR,
                    now,
                    now,
                    "run interrupted before completion",
                    RUN_STATUS_RUNNING,
                    cutoff,
                    now,
                ),
            )
            return int(cur.rowcount or 0)

    def list_for_job(self, cron_id: str, *, limit: int = 20) -> list[CronRunRow]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM cron_runs WHERE cron_id = ? ORDER BY id DESC LIMIT ?",
                (cron_id, max(1, int(limit))),
            ).fetchall()
        return map_rows(rows, CronRunRow)

    def latest(self, cron_id: str) -> CronRunRow | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM cron_runs WHERE cron_id = ? ORDER BY id DESC LIMIT 1",
                (cron_id,),
            ).fetchone()
        return CronRunRow.from_row(row) if row else None

    def running_count(self, cron_id: str) -> int:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM cron_runs WHERE cron_id = ? AND status = ?",
                (cron_id, RUN_STATUS_RUNNING),
            ).fetchone()
        return int(row[0]) if row else 0

    def prune(self, cron_id: str, *, keep: int = RUN_HISTORY_KEEP) -> int:
        with self._db.transaction() as conn:
            cur = conn.execute(
                "DELETE FROM cron_runs WHERE cron_id = ? AND id NOT IN ("
                "SELECT id FROM cron_runs WHERE cron_id = ? ORDER BY id DESC LIMIT ?"
                ")",
                (cron_id, cron_id, max(1, int(keep))),
            )
            return int(cur.rowcount or 0)
