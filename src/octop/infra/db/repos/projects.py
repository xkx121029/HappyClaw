"""Projects — long-lived directories that own a group of conversations.

A project is the unit the sidebar groups threads by. Its ``root_dir`` may point
at a user-chosen folder outside ``{OCTOP_HOME}``; a NULL ``root_dir`` means the
directory has not been materialized yet (the default project until its first
file operation). Threads keep a ``project_id`` plus a resolvable workspace
snapshot; see ``infra/projects`` for resolution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from octop.infra.db.pool import DatabasePool
from octop.infra.db.repos._base import UNSET, DbRow, bool_int, map_rows, now_ts

__all__ = ["ProjectRepo", "ProjectRow"]


@dataclass(frozen=True)
class ProjectRow:
    id: int
    project_id: str
    user_id: int
    name: str
    root_dir: str | None
    is_default: bool
    origin: str
    created_at: int
    updated_at: int

    @classmethod
    def from_row(cls, r: DbRow) -> ProjectRow:
        root_dir = r["root_dir"]
        return cls(
            id=int(r["id"]),
            project_id=str(r["project_id"]),
            user_id=int(r["user_id"]),
            name=str(r["name"]),
            root_dir=str(root_dir) if root_dir else None,
            is_default=bool(r["is_default"]),
            origin=str(r["origin"] or "manual"),
            created_at=int(r["created_at"]),
            updated_at=int(r["updated_at"]),
        )


class ProjectRepo:
    def __init__(self, db: DatabasePool) -> None:
        self._db = db

    def create(
        self,
        *,
        project_id: str,
        user_id: int,
        name: str,
        root_dir: str | None = None,
        is_default: bool = False,
        origin: str = "manual",
    ) -> ProjectRow:
        ts = now_ts()
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO projects(project_id, user_id, name, root_dir, is_default, "
                "origin, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (project_id, user_id, name, root_dir, bool_int(is_default), origin, ts, ts),
            )
        return ProjectRow(
            id=0,
            project_id=project_id,
            user_id=user_id,
            name=name,
            root_dir=root_dir,
            is_default=is_default,
            origin=origin,
            created_at=ts,
            updated_at=ts,
        )

    def get(self, project_id: str) -> ProjectRow | None:
        with self._db.connect() as conn:
            r = conn.execute(
                "SELECT * FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
        return ProjectRow.from_row(r) if r else None

    def get_default(self, user_id: int) -> ProjectRow | None:
        with self._db.connect() as conn:
            r = conn.execute(
                "SELECT * FROM projects WHERE user_id = ? AND is_default = 1",
                (user_id,),
            ).fetchone()
        return ProjectRow.from_row(r) if r else None

    def find_by_root_dir(self, user_id: int, root_dir: str) -> ProjectRow | None:
        with self._db.connect() as conn:
            r = conn.execute(
                "SELECT * FROM projects WHERE user_id = ? AND root_dir = ?",
                (user_id, root_dir),
            ).fetchone()
        return ProjectRow.from_row(r) if r else None

    def ensure_default(
        self,
        *,
        project_id: str,
        user_id: int,
        name: str,
    ) -> ProjectRow:
        """Return the owner's default project, creating it on first use."""
        existing = self.get_default(user_id)
        if existing is not None:
            return existing
        try:
            return self.create(
                project_id=project_id,
                user_id=user_id,
                name=name,
                is_default=True,
                origin="manual",
            )
        except Exception:
            # Two concurrent first calls: the partial unique index picks one.
            existing = self.get_default(user_id)
            if existing is None:
                raise
            return existing

    def list_for_user(self, user_id: int) -> list[ProjectRow]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM projects WHERE user_id = ? "
                "ORDER BY is_default DESC, updated_at DESC, id DESC",
                (user_id,),
            ).fetchall()
        return map_rows(rows, ProjectRow)

    def update(
        self,
        project_id: str,
        *,
        name: str | None | object = UNSET,
        root_dir: str | None | object = UNSET,
        origin: str | None | object = UNSET,
    ) -> None:
        fields: list[str] = []
        params: list[Any] = []
        for column, value in (("name", name), ("root_dir", root_dir), ("origin", origin)):
            if value is UNSET:
                continue
            fields.append(f"{column} = ?")
            params.append(value)
        if not fields:
            return
        fields.append("updated_at = ?")
        params.append(now_ts())
        params.append(project_id)
        with self._db.transaction() as conn:
            conn.execute(f"UPDATE projects SET {', '.join(fields)} WHERE project_id = ?", params)

    def delete(self, project_id: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM projects WHERE project_id = ?", (project_id,))

    def touch(self, project_id: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE projects SET updated_at = ? WHERE project_id = ?",
                (now_ts(), project_id),
            )
