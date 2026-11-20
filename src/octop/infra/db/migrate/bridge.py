"""Bridge connection table."""

from __future__ import annotations

from octop.infra.db.migrate.introspect import (
    _ensure_column,
    _table_exists,
)
from octop.infra.db.pool import DatabasePool


def _ensure_bridge_connections_schema(db: DatabasePool) -> None:
    """Fold notes + unique display_name + auto_reconnect into unreleased v19."""
    if not _table_exists(db, "bridge_connections"):
        return
    _ensure_column(db, "bridge_connections", "notes", "TEXT")
    _ensure_column(db, "bridge_connections", "icon_name", "TEXT")
    _ensure_column(db, "bridge_connections", "auto_reconnect", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(db, "bridge_connections", "peer_client_host", "TEXT")
    # Make every (owner, display_name) unique before creating the index.
    # Empty names are filled from peer username / URL; colliding names get a suffix.
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, owner_user_id, peer_base_url, peer_username, display_name "
            "FROM bridge_connections ORDER BY id ASC"
        ).fetchall()
    used: dict[int, set[str]] = {}
    updates: list[tuple[str, int]] = []
    for row in rows:
        owner = int(row["owner_user_id"])
        used.setdefault(owner, set())
        current = str(row["display_name"] or "").strip()
        base = (
            current
            or str(row["peer_username"] or "").strip()
            or str(row["peer_base_url"] or "").strip()
            or f"bridge-{row['id']}"
        )
        candidate = base
        n = 2
        while candidate in used[owner]:
            candidate = f"{base} ({n})"
            n += 1
        used[owner].add(candidate)
        if candidate != str(row["display_name"] or ""):
            updates.append((candidate, int(row["id"])))
    if updates:
        with db.transaction() as conn:
            for name, row_id in updates:
                conn.execute(
                    "UPDATE bridge_connections SET display_name = ? WHERE id = ?",
                    (name, row_id),
                )
    with db.connect() as conn:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_bridge_connections_owner_display "
            "ON bridge_connections(owner_user_id, display_name)"
        )
