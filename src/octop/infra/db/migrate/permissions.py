"""Default navigation / tab permission grants."""

from __future__ import annotations

import json
from typing import Any

from octop.infra.db.migrate.introspect import (
    _table_exists,
)
from octop.infra.db.pool import DatabasePool

_NAV_PAGE_PERMISSIONS = ("experts", "tasks", "token_usage")

_NAV_PAGE_PERMISSIONS_FLAG = "granted_nav_page_permissions"

_PERSONALIZATION_TAB_PERMISSIONS = (
    "skills",
    "subagents",
    "tools",
    "agent_plugins",
    "mbti",
    "memory",
)

_PERSONALIZATION_TAB_PERMISSIONS_FLAG = "granted_personalization_tab_permissions"

_BRIDGE_PERMISSIONS = ("bridge",)

_BRIDGE_PERMISSIONS_FLAG = "granted_bridge_permission"

_PAGE_TAB_EXPANSIONS_FLAG = "expanded_page_tab_permissions_v1"


def _parse_perm_list(raw: Any) -> list[str] | None:
    if isinstance(raw, list):
        return [str(item) for item in raw]
    if raw is None:
        return []
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    return None


def _grant_permission_keys_once(
    db: DatabasePool,
    keys: tuple[str, ...],
    flag: str,
) -> None:
    """Grant ``keys`` once to accounts that already had those pages open.

    Later removals stick: the settings flag stops this from running again.
    Admins are skipped; an empty permission list means "all" for that role.
    """
    if not _table_exists(db, "settings"):
        return
    with db.connect() as conn:
        existing = conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (flag,),
        ).fetchone()
    if existing is not None:
        return

    def grant(table: str, id_col: str, skip_where: str) -> None:
        if not _table_exists(db, table):
            return
        with db.connect() as conn:
            rows = conn.execute(
                f"SELECT {id_col}, permissions FROM {table} WHERE {skip_where}"
            ).fetchall()
        updates: list[tuple[str, object]] = []
        for row in rows:
            current = _parse_perm_list(row[1])
            if current is None:
                continue
            merged = list(current)
            changed = False
            for key in keys:
                if key not in merged:
                    merged.append(key)
                    changed = True
            if changed:
                updates.append((json.dumps(merged, ensure_ascii=False), row[0]))
        if not updates:
            return
        with db.transaction() as conn:
            for payload, pk in updates:
                conn.execute(
                    f"UPDATE {table} SET permissions = ? WHERE {id_col} = ?",
                    (payload, pk),
                )

    grant("users", "id", "role <> 'admin'")
    grant("user_role", "id", "user_role_id <> 'admin'")
    with db.transaction() as conn:
        if db.dialect == "postgresql":
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT (key) DO NOTHING",
                (flag, "1"),
            )
        else:
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                (flag, "1"),
            )


def _grant_default_nav_permissions(db: DatabasePool) -> None:
    """Grant experts/tasks/token usage once to accounts that already had them open."""
    _grant_permission_keys_once(db, _NAV_PAGE_PERMISSIONS, _NAV_PAGE_PERMISSIONS_FLAG)


def _grant_personalization_tab_permissions(db: DatabasePool) -> None:
    """Grant personalization tab keys once; those pages used to be open to everyone."""
    _grant_permission_keys_once(
        db,
        _PERSONALIZATION_TAB_PERMISSIONS,
        _PERSONALIZATION_TAB_PERMISSIONS_FLAG,
    )


def _grant_bridge_permission(db: DatabasePool) -> None:
    """Grant cloud-collab once; /bridge used to be ungated for every signed-in user."""
    _grant_permission_keys_once(db, _BRIDGE_PERMISSIONS, _BRIDGE_PERMISSIONS_FLAG)


def _expand_page_tab_permissions(db: DatabasePool) -> None:
    """Copy collapsed page tabs onto grants that already had the parent key.

    Runs once. Removing a tab afterwards stays removed.
    """
    if not _table_exists(db, "settings"):
        return
    with db.connect() as conn:
        existing = conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (_PAGE_TAB_EXPANSIONS_FLAG,),
        ).fetchone()
    if existing is not None:
        return

    from octop.infra.users.permissions import PAGE_TAB_EXPANSIONS

    def expand(table: str, id_col: str, skip_where: str) -> None:
        if not _table_exists(db, table):
            return
        with db.connect() as conn:
            rows = conn.execute(
                f"SELECT {id_col}, permissions FROM {table} WHERE {skip_where}"
            ).fetchall()
        updates: list[tuple[str, object]] = []
        for row in rows:
            current = _parse_perm_list(row[1])
            if current is None:
                continue
            merged = list(current)
            changed = False
            for parent, children, retire in PAGE_TAB_EXPANSIONS:
                if parent not in merged:
                    continue
                for child in children:
                    if child not in merged:
                        merged.append(child)
                        changed = True
                if retire:
                    merged = [key for key in merged if key != parent]
                    changed = True
            if changed:
                updates.append((json.dumps(merged, ensure_ascii=False), row[0]))
        if not updates:
            return
        with db.transaction() as conn:
            for payload, pk in updates:
                conn.execute(
                    f"UPDATE {table} SET permissions = ? WHERE {id_col} = ?",
                    (payload, pk),
                )

    expand("users", "id", "role <> 'admin'")
    expand("user_role", "id", "user_role_id <> 'admin'")
    with db.transaction() as conn:
        if db.dialect == "postgresql":
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT (key) DO NOTHING",
                (_PAGE_TAB_EXPANSIONS_FLAG, "1"),
            )
        else:
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                (_PAGE_TAB_EXPANSIONS_FLAG, "1"),
            )
