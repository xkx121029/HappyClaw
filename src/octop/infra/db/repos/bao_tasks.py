"""Persistence for Bao dispatch tasks.

Bao dispatches work into normal conversations, then follows the turn to a
terminal state. Each dispatch is one row here so a page reload or a process
restart does not lose the dispatch ledger. The worker writes results back
through :meth:`BaoTaskRepo.complete_running`; retention never removes work that
is still running or a finished task the user has not seen yet.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Iterable

from octop.infra.db.pool import DatabasePool
from octop.infra.db.repos._base import DbRow
from octop.infra.utils.ulid import new_ulid

MAX_TASKS_PER_USER = 200
MAX_TASK_AGE_DAYS = 30
RESULT_MAX_CHARS = 600
INTERRUPTED_ERROR = "server restarted or turn lost"

TASK_STATUSES = frozenset({"running", "awaiting", "done", "failed"})
TERMINAL_STATUSES = frozenset({"done", "failed"})


def _clip(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    return text if len(text) <= RESULT_MAX_CHARS else f"{text[:RESULT_MAX_CHARS]}…"


def _json_or_empty(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        return "{}"
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return "{}"


def _seconds(value: Any, *, fallback: int) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if number <= 0:
        return fallback
    # Browser records use milliseconds; server rows use seconds.
    return int(number / 1000) if number > 1e12 else int(number)


@dataclass(frozen=True)
class BaoTaskRow:
    id: str
    user_id: int
    agent_id: str
    agent_name: str
    thread_id: str
    session_title: str
    project_key: str
    project_name: str
    task_text: str
    source: str
    route_reason_json: str
    status: str
    result_text: str | None
    error_text: str | None
    created_at: int
    dispatched_at: int
    updated_at: int
    completed_at: int | None
    acknowledged_at: int | None
    followup_count: int = 0
    last_followup_at: int | None = None
    eval_status: str | None = None
    eval_at: int | None = None

    @classmethod
    def from_row(cls, row: DbRow) -> "BaoTaskRow":
        return cls(
            id=str(row["id"]),
            user_id=int(row["user_id"]),
            agent_id=str(row["agent_id"]),
            agent_name=str(row["agent_name"] or ""),
            thread_id=str(row["thread_id"]),
            session_title=str(row["session_title"] or ""),
            project_key=str(row["project_key"] or ""),
            project_name=str(row["project_name"] or ""),
            task_text=str(row["task_text"] or ""),
            source=str(row["source"] or "bao"),
            route_reason_json=str(row["route_reason_json"] or "{}"),
            status=str(row["status"]),
            result_text=row["result_text"],
            error_text=row["error_text"],
            created_at=int(row["created_at"]),
            dispatched_at=int(row["dispatched_at"]),
            updated_at=int(row["updated_at"]),
            completed_at=int(row["completed_at"]) if row["completed_at"] is not None else None,
            acknowledged_at=(
                int(row["acknowledged_at"]) if row["acknowledged_at"] is not None else None
            ),
            followup_count=int(row["followup_count"] or 0),
            last_followup_at=(
                int(row["last_followup_at"])
                if row["last_followup_at"] is not None
                else None
            ),
            eval_status=str(row["eval_status"]) if row["eval_status"] else None,
            eval_at=int(row["eval_at"]) if row["eval_at"] is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        try:
            route_reason = json.loads(self.route_reason_json)
        except (TypeError, ValueError):
            route_reason = {}
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "thread_id": self.thread_id,
            "session_title": self.session_title,
            "project_key": self.project_key,
            "project_name": self.project_name,
            "task_text": self.task_text,
            "source": self.source,
            "route_reason": route_reason if isinstance(route_reason, dict) else {},
            "status": self.status,
            "result_text": self.result_text,
            "error_text": self.error_text,
            "created_at": self.created_at,
            "dispatched_at": self.dispatched_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "acknowledged_at": self.acknowledged_at,
            "followup_count": self.followup_count,
            "last_followup_at": self.last_followup_at,
            "eval_status": self.eval_status,
        }


class BaoTaskRepo:
    """Data-access object for ``bao_tasks``."""

    def __init__(self, db: DatabasePool) -> None:
        self._db = db

    def create(
        self,
        *,
        user_id: int,
        agent_id: str,
        agent_name: str,
        thread_id: str,
        session_title: str,
        project_key: str,
        project_name: str,
        task_text: str,
        source: str = "bao",
        route_reason: dict[str, Any] | None = None,
        dispatched_at: int | None = None,
        task_id: str | None = None,
    ) -> BaoTaskRow:
        ts = int(dispatched_at if dispatched_at is not None else time.time())
        rid = task_id or new_ulid()
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO bao_tasks("
                "id, user_id, agent_id, agent_name, thread_id, session_title, "
                "project_key, project_name, task_text, source, route_reason_json, "
                "status, created_at, dispatched_at, updated_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, ?)",
                (
                    rid,
                    user_id,
                    agent_id,
                    agent_name,
                    thread_id,
                    session_title,
                    project_key,
                    project_name,
                    task_text,
                    source,
                    _json_or_empty(route_reason),
                    ts,
                    ts,
                    ts,
                ),
            )
        self.prune(user_id)
        row = self.get(rid)
        if row is None:  # pragma: no cover - insert just succeeded
            raise RuntimeError("bao task insert disappeared")
        return row

    def get(self, task_id: str) -> BaoTaskRow | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM bao_tasks WHERE id = ?", (task_id,)
            ).fetchone()
        return BaoTaskRow.from_row(row) if row is not None else None

    def get_for_thread(
        self,
        thread_id: str,
        agent_id: str,
        *,
        statuses: Iterable[str] | None = None,
        limit: int = 20,
    ) -> list[BaoTaskRow]:
        sql = "SELECT * FROM bao_tasks WHERE thread_id = ? AND agent_id = ?"
        params: list[Any] = [thread_id, agent_id]
        wanted = [status for status in (statuses or []) if status in TASK_STATUSES]
        if wanted:
            placeholders = ",".join("?" for _ in wanted)
            sql += f" AND status IN ({placeholders})"  # noqa: S608 - placeholders only
            params.extend(wanted)
        sql += " ORDER BY dispatched_at DESC, id DESC LIMIT ?"
        params.append(max(int(limit), 1))
        with self._db.connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [BaoTaskRow.from_row(row) for row in rows]

    def latest_terminal_for_thread(
        self, thread_id: str, agent_id: str
    ) -> BaoTaskRow | None:
        """Newest finished/awaiting task for a thread that has not been evaluated."""
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM bao_tasks WHERE thread_id = ? AND agent_id = ? "
                "AND status IN ('done', 'failed', 'awaiting') "
                "AND eval_status IS NULL "
                "ORDER BY updated_at DESC, dispatched_at DESC, id DESC LIMIT 1",
                (thread_id, agent_id),
            ).fetchone()
        return BaoTaskRow.from_row(row) if row is not None else None

    def record_followup(
        self, task_id: str, *, now: int | None = None
    ) -> BaoTaskRow | None:
        """Reopen a finished task for one more Bao follow-up turn."""
        ts = int(now if now is not None else time.time())
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE bao_tasks SET status = 'running', followup_count = followup_count + 1, "
                "last_followup_at = ?, updated_at = ?, completed_at = NULL, "
                "eval_status = NULL, eval_at = NULL "
                "WHERE id = ? AND status != 'running'",
                (ts, ts, task_id),
            )
        return self.get(task_id)

    def mark_evaluated(
        self, task_id: str, eval_status: str, *, now: int | None = None
    ) -> int:
        ts = int(now if now is not None else time.time())
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "UPDATE bao_tasks SET eval_status = ?, eval_at = ? WHERE id = ?",
                (eval_status, ts, task_id),
            )
        return int(cursor.rowcount or 0)

    def list_for_user(self, user_id: int, limit: int = 50) -> list[BaoTaskRow]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM bao_tasks WHERE user_id = ? "
                "ORDER BY dispatched_at DESC, id DESC LIMIT ?",
                (user_id, max(int(limit), 1)),
            ).fetchall()
        return [BaoTaskRow.from_row(row) for row in rows]

    def count_for_user(self, user_id: int) -> int:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM bao_tasks WHERE user_id = ?", (user_id,)
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def complete_running(
        self,
        *,
        thread_id: str,
        agent_id: str,
        status: str,
        result_text: str | None = None,
        error_text: str | None = None,
        now: int | None = None,
    ) -> int:
        """Move running tasks for one thread to a terminal/awaiting state.

        Only ``running`` rows are updated, so a duplicated ``turn.ended`` event
        cannot overwrite a result that already landed. ``awaiting`` keeps the
        task open for a later HITL resume; terminal states stamp completion.
        """
        if status not in TASK_STATUSES or status == "running":
            raise ValueError(f"invalid completion status: {status}")
        ts = int(now if now is not None else time.time())
        clipped = _clip(result_text)
        error = _clip(error_text)
        with self._db.transaction() as conn:
            if status == "awaiting":
                cursor = conn.execute(
                    "UPDATE bao_tasks SET status = 'awaiting', updated_at = ? "
                    "WHERE thread_id = ? AND agent_id = ? AND status = 'running'",
                    (ts, thread_id, agent_id),
                )
            else:
                cursor = conn.execute(
                    "UPDATE bao_tasks SET status = ?, result_text = ?, error_text = ?, "
                    "updated_at = ?, completed_at = ? "
                    "WHERE thread_id = ? AND agent_id = ? AND status = 'running'",
                    (status, clipped, error, ts, ts, thread_id, agent_id),
                )
        return int(cursor.rowcount or 0)

    def acknowledge(
        self,
        user_id: int,
        task_ids: Iterable[str],
        *,
        now: int | None = None,
    ) -> int:
        ids = [str(task_id) for task_id in task_ids if task_id]
        if not ids:
            return 0
        ts = int(now if now is not None else time.time())
        placeholders = ",".join("?" for _ in ids)
        with self._db.transaction() as conn:
            cursor = conn.execute(
                f"UPDATE bao_tasks SET acknowledged_at = ? "  # noqa: S608 - placeholders only
                f"WHERE user_id = ? AND id IN ({placeholders}) "
                "AND status IN ('done', 'failed') AND acknowledged_at IS NULL",
                (ts, user_id, *ids),
            )
        return int(cursor.rowcount or 0)

    def reconcile_interrupted(
        self,
        *,
        user_id: int,
        active_thread_ids: Iterable[str],
        now: int | None = None,
        grace_seconds: int = 30,
        followup_grace_seconds: int = 600,
    ) -> int:
        """Fail running tasks whose turn cannot still be alive.

        The grace window covers the gap between enqueue and the worker's
        ``mark_turn_active`` call, so a freshly dispatched task is never
        mistaken for an orphan.

        An auto follow-up is different: the turn runs in the worker process,
        so this process's WS hub cannot see it as active, and a real answer can
        take minutes. Its own, much longer grace window starts at
        ``last_followup_at``; failing it early would throw away the nudge's
        result.
        """
        ts = int(now if now is not None else time.time())
        cutoff = ts - max(int(grace_seconds), 0)
        followup_cutoff = ts - max(int(followup_grace_seconds), 0)
        active = [str(thread_id) for thread_id in active_thread_ids if thread_id]
        sql = (
            "UPDATE bao_tasks SET status = 'failed', error_text = ?, "
            "updated_at = ?, completed_at = ? "
            "WHERE user_id = ? AND status = 'running' AND dispatched_at < ? "
            "AND (last_followup_at IS NULL OR last_followup_at < ?)"
        )
        params: list[Any] = [
            INTERRUPTED_ERROR,
            ts,
            ts,
            user_id,
            cutoff,
            followup_cutoff,
        ]
        if active:
            placeholders = ",".join("?" for _ in active)
            sql += f" AND thread_id NOT IN ({placeholders})"  # noqa: S608
            params.extend(active)
        with self._db.transaction() as conn:
            cursor = conn.execute(sql, tuple(params))
        return int(cursor.rowcount or 0)

    def import_legacy(self, user_id: int, rows: Iterable[dict[str, Any]]) -> tuple[int, int]:
        """Import browser-local dispatch records once, keyed by their old id."""
        imported = 0
        skipped = 0
        now = int(time.time())
        with self._db.transaction() as conn:
            for raw in rows:
                if not isinstance(raw, dict):
                    skipped += 1
                    continue
                task_id = str(raw.get("id") or "").strip()
                thread_id = str(raw.get("thread_id") or raw.get("threadId") or "").strip()
                agent_id = str(raw.get("agent_id") or raw.get("agentId") or "").strip()
                text = str(raw.get("task_text") or raw.get("text") or "").strip()
                if not task_id or not thread_id or not agent_id or not text:
                    skipped += 1
                    continue
                existing = conn.execute(
                    "SELECT 1 FROM bao_tasks WHERE id = ?", (task_id,)
                ).fetchone()
                if existing is not None:
                    skipped += 1
                    continue
                status = str(raw.get("status") or "done")
                if status not in TASK_STATUSES:
                    status = "done"
                dispatched = _seconds(
                    raw.get("dispatched_at") or raw.get("dispatchedAt"), fallback=now
                )
                updated = _seconds(
                    raw.get("updated_at") or raw.get("updatedAt"), fallback=dispatched
                )
                completed = (
                    _seconds(
                        raw.get("completed_at") or raw.get("completedAt"),
                        fallback=updated,
                    )
                    if status in TERMINAL_STATUSES
                    else None
                )
                acknowledged = None
                route_reason = raw.get("route_reason") or raw.get("routeReason")
                conn.execute(
                    "INSERT INTO bao_tasks("
                    "id, user_id, agent_id, agent_name, thread_id, session_title, "
                    "project_key, project_name, task_text, source, route_reason_json, "
                    "status, result_text, error_text, created_at, dispatched_at, "
                    "updated_at, completed_at, acknowledged_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'legacy', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        task_id,
                        user_id,
                        agent_id,
                        str(raw.get("agent_name") or raw.get("agentName") or ""),
                        thread_id,
                        str(raw.get("session_title") or raw.get("sessionTitle") or ""),
                        str(raw.get("project_key") or raw.get("projectKey") or ""),
                        str(raw.get("project_name") or raw.get("projectName") or ""),
                        text,
                        _json_or_empty(route_reason if isinstance(route_reason, dict) else None),
                        status,
                        _clip(raw.get("result_text") or raw.get("resultText")),
                        _clip(raw.get("error_text") or raw.get("errorText")),
                        dispatched,
                        dispatched,
                        updated,
                        completed,
                        acknowledged,
                    ),
                )
                imported += 1
        self.prune(user_id)
        return imported, skipped

    def prune(self, user_id: int, *, now: int | None = None) -> int:
        """Remove old *read terminal* tasks; never touch work in flight."""
        ts = int(now if now is not None else time.time())
        cutoff = ts - MAX_TASK_AGE_DAYS * 86400
        deleted = 0
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM bao_tasks WHERE user_id = ? "
                "AND status IN ('done', 'failed') "
                "AND acknowledged_at IS NOT NULL AND dispatched_at < ?",
                (user_id, cutoff),
            )
            deleted += int(cursor.rowcount or 0)
            rows = conn.execute(
                "SELECT id FROM bao_tasks WHERE user_id = ? "
                "AND status IN ('done', 'failed') AND acknowledged_at IS NOT NULL "
                "ORDER BY dispatched_at DESC, id DESC",
                (user_id,),
            ).fetchall()
            extra = [str(row[0]) for row in rows[MAX_TASKS_PER_USER:]]
            for start in range(0, len(extra), 100):
                chunk = extra[start : start + 100]
                placeholders = ",".join("?" for _ in chunk)
                cursor = conn.execute(
                    f"DELETE FROM bao_tasks WHERE user_id = ? "  # noqa: S608
                    f"AND id IN ({placeholders})",
                    (user_id, *chunk),
                )
                deleted += int(cursor.rowcount or 0)
        return deleted


__all__ = [
    "BaoTaskRepo",
    "BaoTaskRow",
    "INTERRUPTED_ERROR",
    "MAX_TASK_AGE_DAYS",
    "MAX_TASKS_PER_USER",
    "RESULT_MAX_CHARS",
]
