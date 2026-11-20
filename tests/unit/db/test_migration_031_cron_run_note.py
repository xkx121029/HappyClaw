"""Migration 031: ``cron_runs.note`` lands and the watermark advances exactly once."""

from __future__ import annotations

from pathlib import Path

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool


def _version(db: SqlitePool) -> int:
    with db.connect() as conn:
        return int(conn.execute("SELECT version FROM _schema_version").fetchone()["version"])


def _columns(db: SqlitePool, table: str) -> set[str]:
    with db.connect() as conn:
        return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}


def test_031_is_idempotent_when_the_column_landed_before_the_watermark(
    tmp_path: Path,
) -> None:
    db = SqlitePool(tmp_path / "upgrade.db")
    run_migrations(db)
    assert "note" in _columns(db, "cron_runs")
    assert _version(db) == 31

    # Crash window: the column exists but the version row still says 30.
    with db.connect() as conn:
        conn.execute("UPDATE _schema_version SET version = 30")

    run_migrations(db)

    assert "note" in _columns(db, "cron_runs")
    assert _version(db) == 31
