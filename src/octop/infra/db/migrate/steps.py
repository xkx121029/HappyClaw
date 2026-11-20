"""Dialect-specific migration file appliers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from octop.infra.db.migrate.agents import (
    _backfill_agent_profile_from_config,
    _ensure_agent_profile_columns,
)
from octop.infra.db.migrate.auth import (
    _ensure_sso_oidc_schema,
    _ensure_sso_provider_kind_schema,
    _ensure_user_invites_schema,
)
from octop.infra.db.migrate.columns import (
    _ensure_agent_teams_schema,
    _ensure_bridge_icon_url_schema,
    _ensure_bridge_shared_schema,
    _ensure_knowledge_base_icon_url_schema,
    _ensure_skill_copy_policy_schema,
    _ensure_skill_package_download_schema,
    _ensure_skill_package_shared_schema,
    _ensure_thread_conversation_mode_schema,
    _ensure_usage_cache_schema,
    _ensure_user_group_profile_schema,
)
from octop.infra.db.migrate.control import (
    _ensure_instance_lease_schema,
)
from octop.infra.db.migrate.cron import (
    _ensure_cron_jobs_schema,
    _ensure_cron_run_schema,
)
from octop.infra.db.migrate.experts import (
    _ensure_published_experts_schema,
)
from octop.infra.db.migrate.introspect import (
    _ensure_column,
    _split_pg_sql,
    _table_exists,
)
from octop.infra.db.migrate.knowledge import (
    _drop_knowledge_base_members,
    _ensure_knowledge_bases_schema,
    _rebuild_knowledge_identity_schema,
)
from octop.infra.db.migrate.mfa import (
    _ensure_user_mfa_schema,
)
from octop.infra.db.migrate.policies import (
    _ensure_user_policy_schema,
)
from octop.infra.db.migrate.projects import (
    _ensure_projects_schema,
)
from octop.infra.db.migrate.skills import (
    _ensure_skill_packages_schema,
)
from octop.infra.db.migrate.threads import (
    _ensure_thread_contributed_schema,
    _ensure_trajectory_events_schema,
)
from octop.infra.db.pool import DatabasePool


def _apply_postgresql_migration(conn: Any, sql: str) -> None:
    for stmt in _split_pg_sql(sql):
        conn.execute(stmt)


def _apply_sqlite_migration(db: DatabasePool, version: int, path: Path) -> None:
    """Apply one SQLite migration.

    Version 2 uses ``_ensure_column`` / table helpers so re-running after a
    partial upgrade does not fail.

    Version 3 bumps schema then rewrites legacy hard-cut thread titles in Python.
    Version 4 adds composer columns idempotently after legacy schema repair.
    Version 5 adds shared experts, published templates, OIDC SSO, and knowledge
    bases idempotently after legacy schema repair.
    Version 6 adds ``users.permissions`` idempotently (also covered by
    ``_repair_legacy_schema`` for DBs whose version was clamped past 006).
    Version 7 matches ``007_resource_identity_and_profile.sql``: profile
    columns, thread artifacts, integer PK + public string ids, document
    folders, drop ``knowledge_base_members``. SQLite uses these helpers
    (idempotent); PostgreSQL runs the ``.pg.sql`` file then the same helpers
    as a no-op safety net. ``config_json`` profile keys are backfilled in
    Python either way.
    Version 8 adds cache-aware usage buckets and model call counts.
    Version 9 adds one-time ``user_invites`` codes.
    Version 10 adds the dashboard thread-message projection when the legacy
    database actually contains conversation tables.
    Version 11 adds cron job display names.
    Version 12 adds the append-only chat trajectory event ledger.
    Version 13 adds multi-instance and shared connectors.
    Version 14 adds per-user named policy rows.
    Version 15 adds pluggable SSO provider ``kind`` / ``extra`` and
    multi-identity ``user_sso_identities``.
    Version 16 adds ``agents.kind`` so team hosts can be listed.
    Version 17 adds sticky ``conversation_mode`` and ``pending_plan_path`` on threads.
    Version 18 adds ``user_role`` templates and non-FK role id/name snapshots.
    Version 29 adds ``projects`` and thread project/workspace columns.
    """
    if version == 2:
        if _table_exists(db, "cron_jobs"):
            _ensure_column(
                db,
                "cron_jobs",
                "mcp_servers",
                "TEXT NOT NULL DEFAULT '[]'",
            )
        _ensure_skill_packages_schema(db)
        with db.connect() as conn:
            conn.execute("UPDATE _schema_version SET version = ?", (version,))
        return
    if version == 3:
        with db.connect() as conn:
            conn.execute("UPDATE _schema_version SET version = ?", (version,))
        if _table_exists(db, "threads"):
            from octop.infra.db.repos.threads import repair_all_legacy_thread_titles

            repair_all_legacy_thread_titles(db)
        return
    if version == 4:
        if _table_exists(db, "threads"):
            _ensure_column(db, "threads", "model_ref", "TEXT")
            _ensure_column(db, "threads", "reasoning_mode", "TEXT")
            _ensure_column(db, "threads", "reasoning_effort", "TEXT")
        with db.connect() as conn:
            conn.execute("UPDATE _schema_version SET version = ?", (version,))
        return
    if version == 5:
        if _table_exists(db, "agents"):
            _ensure_column(db, "agents", "is_shared", "INTEGER NOT NULL DEFAULT 0")
            with db.connect() as conn:
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_agents_shared "
                    "ON agents(is_shared) WHERE is_shared = 1"
                )
        _ensure_published_experts_schema(db)
        _ensure_sso_oidc_schema(db)
        _ensure_knowledge_bases_schema(db)
        with db.connect() as conn:
            conn.execute("UPDATE _schema_version SET version = ?", (version,))
        return
    if version == 6:
        if _table_exists(db, "users"):
            _ensure_column(db, "users", "permissions", "TEXT NOT NULL DEFAULT '[]'")
        with db.connect() as conn:
            conn.execute("UPDATE _schema_version SET version = ?", (version,))
        return
    if version == 7:
        _ensure_agent_profile_columns(db)
        _backfill_agent_profile_from_config(db)
        if _table_exists(db, "threads"):
            _ensure_column(db, "threads", "artifacts", "TEXT NOT NULL DEFAULT '[]'")
        _rebuild_knowledge_identity_schema(db)
        _drop_knowledge_base_members(db)
        _ensure_skill_packages_schema(db)
        _ensure_published_experts_schema(db)
        with db.connect() as conn:
            conn.execute("UPDATE _schema_version SET version = ?", (version,))
        return
    if version == 8:
        _ensure_usage_cache_schema(db)
        with db.connect() as conn:
            conn.execute("UPDATE _schema_version SET version = ?", (version,))
        return
    if version == 9:
        _ensure_user_invites_schema(db)
        with db.connect() as conn:
            conn.execute("UPDATE _schema_version SET version = ?", (version,))
        return
    if version == 10 and not _table_exists(db, "threads"):
        # Some very old/partial installs only contain ``users``. They still
        # need the version watermark to advance, but there is no history to
        # project and the migration's INSERT ... SELECT threads cannot run.
        with db.connect() as conn:
            conn.execute("UPDATE _schema_version SET version = ?", (version,))
        return
    if version == 11:
        _ensure_cron_jobs_schema(db)
        with db.connect() as conn:
            conn.execute("UPDATE _schema_version SET version = ?", (version,))
        return
    if version == 12:
        _ensure_trajectory_events_schema(db)
        with db.connect() as conn:
            conn.execute("UPDATE _schema_version SET version = ?", (version,))
        return
    if version == 13 and not _table_exists(db, "connectors"):
        # Very old/partial installs may contain only ``users``. There are no
        # connector rows to rebuild, so only advance the migration watermark.
        with db.connect() as conn:
            conn.execute("UPDATE _schema_version SET version = ?", (version,))
        return
    if version == 14:
        _ensure_agent_profile_columns(db)
        _ensure_user_policy_schema(db)
        with db.connect() as conn:
            conn.execute("UPDATE _schema_version SET version = ?", (version,))
        return
    if version == 15:
        _ensure_sso_provider_kind_schema(db)
        with db.connect() as conn:
            conn.execute("UPDATE _schema_version SET version = ?", (version,))
        return
    if version == 16:
        _ensure_agent_teams_schema(db)
        with db.connect() as conn:
            conn.execute("UPDATE _schema_version SET version = ?", (version,))
        return
    if version == 17:
        _ensure_thread_conversation_mode_schema(db)
        with db.connect() as conn:
            conn.execute("UPDATE _schema_version SET version = ?", (version,))
        return
    if version == 20:
        _ensure_skill_copy_policy_schema(db)
        with db.connect() as conn:
            conn.execute("UPDATE _schema_version SET version = ?", (version,))
        return
    if version == 21:
        _ensure_skill_package_download_schema(db)
        with db.connect() as conn:
            conn.execute("UPDATE _schema_version SET version = ?", (version,))
        return
    if version == 22:
        _ensure_skill_package_shared_schema(db)
        with db.connect() as conn:
            conn.execute("UPDATE _schema_version SET version = ?", (version,))
        return
    if version == 24:
        _ensure_user_group_profile_schema(db)
        _ensure_knowledge_base_icon_url_schema(db)
        _ensure_bridge_icon_url_schema(db)
        _ensure_bridge_shared_schema(db)
        with db.connect() as conn:
            conn.execute("UPDATE _schema_version SET version = ?", (version,))
        return
    if version == 25:
        _ensure_user_mfa_schema(db)
        _ensure_instance_lease_schema(db)
        _ensure_thread_contributed_schema(db)
        with db.connect() as conn:
            conn.execute("UPDATE _schema_version SET version = ?", (version,))
        return
    if version == 29:
        _ensure_projects_schema(db)
        with db.connect() as conn:
            conn.execute("UPDATE _schema_version SET version = ?", (version,))
        return
    if version == 30:
        _ensure_cron_run_schema(db)
        with db.connect() as conn:
            conn.execute("UPDATE _schema_version SET version = ?", (version,))
        return
    if version == 31:
        # SQLite has no ``ADD COLUMN IF NOT EXISTS``. A database that already
        # gained ``note`` but crashed before the version watermark advanced must
        # still be able to finish the upgrade.
        _ensure_column(db, "cron_runs", "note", "TEXT")
        with db.connect() as conn:
            conn.execute("UPDATE _schema_version SET version = ?", (version,))
        return
    sql = path.read_text(encoding="utf-8")
    with db.connect() as conn:
        conn.executescript(sql)
