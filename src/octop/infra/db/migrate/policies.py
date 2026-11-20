"""User policy table rebuild and legacy copy steps."""

from __future__ import annotations

import time
from typing import Any

from octop.infra.db.migrate.introspect import (
    _drop_column,
    _integer_pk_sql,
    _table_columns,
    _table_exists,
)
from octop.infra.db.pool import DatabasePool
from octop.infra.utils.ulid import new_ulid

_USER_POLICY_IDENTITY_COLUMNS = {
    "id",
    "policy_id",
    "user_id",
    "name",
    "enabled",
    "value",
    "created_at",
    "updated_at",
}


def _user_policies_identity_ready(db: DatabasePool) -> bool:
    return _table_exists(db, "user_policies") and _USER_POLICY_IDENTITY_COLUMNS.issubset(
        _table_columns(db, "user_policies")
    )


def _create_user_policies_table(db: DatabasePool) -> None:
    pk = _integer_pk_sql(db)
    id_type = "BIGINT" if db.dialect == "postgresql" else "INTEGER"
    with db.connect() as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS user_policies (
              id {pk},
              policy_id TEXT NOT NULL UNIQUE,
              user_id {id_type} NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              name TEXT NOT NULL,
              enabled INTEGER NOT NULL DEFAULT 1,
              value TEXT NOT NULL DEFAULT '',
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL,
              UNIQUE(user_id, name)
            )
            """
        )


def _insert_user_policy_row(conn: Any, *, user_id: int, name: str, value: str, ts: int) -> None:
    conn.execute(
        """
        INSERT INTO user_policies(
          policy_id, user_id, name, enabled, value, created_at, updated_at
        )
        VALUES (?, ?, ?, 1, ?, ?, ?)
        ON CONFLICT(user_id, name) DO UPDATE SET
          enabled = 1,
          value = excluded.value,
          updated_at = excluded.updated_at
        """,
        (new_ulid(), user_id, name, value, ts, ts),
    )


def _ensure_user_policy_schema(db: DatabasePool) -> None:
    if not _table_exists(db, "users"):
        return
    if _table_exists(db, "user_policies") and not _user_policies_identity_ready(db):
        _rebuild_user_policies_from_legacy_kv(db)
    if not _table_exists(db, "user_policies"):
        _create_user_policies_table(db)
    _copy_legacy_user_resource_policies(db)
    _copy_legacy_user_policy_columns(db)


def _rebuild_user_policies_from_legacy_kv(db: DatabasePool) -> None:
    cols = _table_columns(db, "user_policies")
    if "key" not in cols:
        with db.connect() as conn:
            conn.execute("DROP TABLE IF EXISTS user_policies")
        _create_user_policies_table(db)
        return
    ts = int(time.time())
    with db.connect() as conn:
        rows = conn.execute("SELECT user_id, key, value FROM user_policies").fetchall()
    legacy = [
        (int(row["user_id"]), str(row["key"]), str(row["value"]))
        for row in rows
        if row["key"] and row["value"] is not None
    ]
    with db.transaction() as conn:
        if db.dialect == "sqlite":
            conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("ALTER TABLE user_policies RENAME TO user_policies_kv_legacy")
    _create_user_policies_table(db)
    with db.transaction() as conn:
        for user_id, name, value in legacy:
            if not str(value).strip():
                continue
            _insert_user_policy_row(conn, user_id=user_id, name=name, value=value, ts=ts)
        conn.execute("DROP TABLE IF EXISTS user_policies_kv_legacy")
        if db.dialect == "sqlite":
            conn.execute("PRAGMA foreign_keys = ON")


def _copy_legacy_user_policy_columns(db: DatabasePool) -> None:
    user_columns = _table_columns(db, "users")
    ts = int(time.time())
    if "workspace_root_dir" in user_columns:
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT id, workspace_root_dir FROM users "
                "WHERE workspace_root_dir IS NOT NULL AND workspace_root_dir <> ''"
            ).fetchall()
        with db.transaction() as conn:
            for row in rows:
                _insert_user_policy_row(
                    conn,
                    user_id=int(row["id"]),
                    name="workspace_root_dir",
                    value=str(row["workspace_root_dir"]),
                    ts=ts,
                )
        _drop_column(db, "users", "workspace_root_dir")
    if "token_quota" in user_columns:
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT id, token_quota FROM users WHERE token_quota IS NOT NULL"
            ).fetchall()
        with db.transaction() as conn:
            for row in rows:
                _insert_user_policy_row(
                    conn,
                    user_id=int(row["id"]),
                    name="token_quota",
                    value=str(row["token_quota"]),
                    ts=ts,
                )
        _drop_column(db, "users", "token_quota")


def _copy_legacy_user_resource_policies(db: DatabasePool) -> None:
    if not _table_exists(db, "user_resource_policies"):
        return
    cols = _table_columns(db, "user_resource_policies")
    ts = int(time.time())
    if {"user_id", "workspace_root_dir", "token_quota"}.issubset(cols):
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT user_id, workspace_root_dir, token_quota FROM user_resource_policies"
            ).fetchall()
        with db.transaction() as conn:
            for row in rows:
                uid = int(row["user_id"])
                root = row["workspace_root_dir"]
                quota = row["token_quota"]
                if root:
                    _insert_user_policy_row(
                        conn,
                        user_id=uid,
                        name="workspace_root_dir",
                        value=str(root),
                        ts=ts,
                    )
                if quota is not None:
                    _insert_user_policy_row(
                        conn,
                        user_id=uid,
                        name="token_quota",
                        value=str(quota),
                        ts=ts,
                    )
    with db.connect() as conn:
        conn.execute("DROP TABLE IF EXISTS user_resource_policies")
