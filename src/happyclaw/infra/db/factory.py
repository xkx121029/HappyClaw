"""Open a database pool from process configuration."""

from __future__ import annotations

from pathlib import Path

from happyclaw.config import OctopConfig, database_env_configured
from happyclaw.infra.db.pool import DatabasePool, PostgresPool, SqlitePool
from happyclaw.infra.utils.paths import PathLayout


def resolve_sqlite_db_path(config: OctopConfig, paths: PathLayout) -> Path:
    """Return the SQLite file path that ``open_database`` would use for sqlite."""
    db_cfg = config.database
    if config.database_in_file or database_env_configured():
        return db_cfg.resolve_sqlite_path(paths.root)
    return paths.db


def should_defer_control_plane_db(config: OctopConfig, paths: PathLayout) -> bool:  # noqa: ARG001
    """Deprecated: single-user mode always opens the default SQLite control plane.

    Kept as a public name for older callers/tests. Deferring the DB made a clean
    ``OCTOP_HOME`` wait for the setup wizard, which left ``/api/health``
    unreachable for up to 90s on first launch.
    """
    return False


def open_database(config: OctopConfig, paths: PathLayout) -> DatabasePool:
    """Return a DB pool for the configured driver.

    When ``config.json`` has no ``database`` section and no ``OCTOP_DATABASE_*``
    env overrides are set, falls back to ``paths.db`` (legacy layout).
    """
    db_cfg = config.database
    if db_cfg.is_postgresql:
        return PostgresPool(db_cfg.postgresql_conninfo())

    return SqlitePool(resolve_sqlite_db_path(config, paths))
