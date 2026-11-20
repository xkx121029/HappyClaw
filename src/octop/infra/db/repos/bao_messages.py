"""Persistence for Bao's conversation memory.

Every user line and Bao's reply is stored so a later turn can resolve
anaphora ("刚才那个", "再等等", "把那个也一起做了"). Messages are capped per
user; the oldest rows are dropped first, never the current turn.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from octop.infra.db.pool import DatabasePool
from octop.infra.db.repos._base import DbRow
from octop.infra.utils.ulid import new_ulid

MAX_MESSAGES_PER_USER = 200
MESSAGE_ROLES = frozenset({"user", "bao"})


def _json_or_empty(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        return "{}"
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return "{}"


@dataclass(frozen=True)
class BaoMessageRow:
    id: str
    user_id: int
    role: str
    text: str
    intent: str
    refs_json: str
    task_id: str | None
    created_at: int

    @classmethod
    def from_row(cls, row: DbRow) -> "BaoMessageRow":
        return cls(
            id=str(row["id"]),
            user_id=int(row["user_id"]),
            role=str(row["role"]),
            text=str(row["text"] or ""),
            intent=str(row["intent"] or ""),
            refs_json=str(row["refs_json"] or "{}"),
            task_id=str(row["task_id"]) if row["task_id"] is not None else None,
            created_at=int(row["created_at"]),
        )

    def refs(self) -> dict[str, Any]:
        try:
            parsed = json.loads(self.refs_json)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role,
            "text": self.text,
            "intent": self.intent,
            "refs": self.refs(),
            "task_id": self.task_id,
            "created_at": self.created_at,
        }


class BaoMessageRepo:
    """Data-access object for ``bao_messages``."""

    def __init__(self, db: DatabasePool) -> None:
        self._db = db

    def append(
        self,
        *,
        user_id: int,
        role: str,
        text: str,
        intent: str = "",
        refs: dict[str, Any] | None = None,
        task_id: str | None = None,
        created_at: int | None = None,
    ) -> BaoMessageRow:
        if role not in MESSAGE_ROLES:
            raise ValueError(f"invalid message role: {role}")
        ts = int(created_at if created_at is not None else time.time())
        rid = new_ulid()
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO bao_messages("
                "id, user_id, role, text, intent, refs_json, task_id, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rid,
                    user_id,
                    role,
                    text.strip(),
                    intent,
                    _json_or_empty(refs),
                    task_id,
                    ts,
                ),
            )
        self.prune(user_id)
        row = self.get(rid)
        if row is None:  # pragma: no cover - insert just succeeded
            raise RuntimeError("bao message insert disappeared")
        return row

    def get(self, message_id: str) -> BaoMessageRow | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM bao_messages WHERE id = ?", (message_id,)
            ).fetchone()
        return BaoMessageRow.from_row(row) if row is not None else None

    def list_for_user(self, user_id: int, limit: int = 100) -> list[BaoMessageRow]:
        """Return the newest *limit* rows in chronological order."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM bao_messages WHERE user_id = ? "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                (user_id, max(int(limit), 1)),
            ).fetchall()
        return [BaoMessageRow.from_row(row) for row in reversed(rows)]

    def latest_task_ref(self, user_id: int) -> dict[str, Any] | None:
        """Most recent message that points at a dispatched task."""
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM bao_messages WHERE user_id = ? "
                "AND task_id IS NOT NULL ORDER BY created_at DESC, id DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        message = BaoMessageRow.from_row(row)
        refs = message.refs()
        refs.setdefault("task_id", message.task_id)
        return refs

    def prune(self, user_id: int) -> int:
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT id FROM bao_messages WHERE user_id = ? "
                "ORDER BY created_at DESC, id DESC",
                (user_id,),
            ).fetchall()
            extra = [str(row[0]) for row in rows[MAX_MESSAGES_PER_USER:]]
            deleted = 0
            for start in range(0, len(extra), 100):
                chunk = extra[start : start + 100]
                placeholders = ",".join("?" for _ in chunk)
                cursor = conn.execute(
                    f"DELETE FROM bao_messages WHERE user_id = ? "  # noqa: S608
                    f"AND id IN ({placeholders})",
                    (user_id, *chunk),
                )
                deleted += int(cursor.rowcount or 0)
        return deleted


__all__ = ["BaoMessageRepo", "BaoMessageRow", "MAX_MESSAGES_PER_USER"]
