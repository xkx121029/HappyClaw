"""Pre-squash schema reconciliation and legacy repair entry point."""

from __future__ import annotations

from octop.infra.db.migrate.agents import (
    _backfill_agent_profile_from_config,
    _ensure_agent_profile_columns,
)
from octop.infra.db.migrate.auth import (
    _ensure_sso_oidc_schema,
    _ensure_sso_provider_kind_schema,
    _ensure_user_invites_schema,
    _ensure_user_role_schema,
)
from octop.infra.db.migrate.columns import (
    _ensure_agent_teams_schema,
    _ensure_skill_package_download_schema,
    _ensure_skill_package_shared_schema,
    _ensure_thread_conversation_mode_schema,
    _ensure_usage_cache_schema,
)
from octop.infra.db.migrate.connectors import (
    _ensure_connectors_v13_schema,
)
from octop.infra.db.migrate.control import (
    _ensure_instance_lease_schema,
)
from octop.infra.db.migrate.cron import (
    _ensure_cron_jobs_schema,
)
from octop.infra.db.migrate.discovery import (
    _current_version,
    _discover,
)
from octop.infra.db.migrate.experts import (
    _ensure_published_experts_schema,
)
from octop.infra.db.migrate.introspect import (
    _ensure_column,
    _table_exists,
)
from octop.infra.db.migrate.knowledge import (
    _ensure_knowledge_bases_schema,
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
from octop.infra.db.migrate.steps import (
    _apply_postgresql_migration,
)
from octop.infra.db.migrate.threads import (
    _ensure_thread_message_projection_schema,
    _ensure_trajectory_events_schema,
)
from octop.infra.db.pool import DatabasePool


def _repair_legacy_schema(db: DatabasePool) -> None:
    """Idempotent compatibility repairs for local databases from old builds."""
    if _table_exists(db, "users"):
        _ensure_column(db, "users", "locale", "TEXT NOT NULL DEFAULT 'zh'")
        _ensure_column(db, "users", "login_failed_count", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(db, "users", "login_locked_until", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(db, "users", "preferences_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(db, "users", "email", "TEXT")
        _ensure_column(db, "users", "sso_provider_id", "INTEGER")
        _ensure_column(db, "users", "sso_subject", "TEXT")
        # Pre-squash DBs may already report version ≥6; reconcile can clamp to 6
        # without applying 006_user_permissions.sql — ensure the column here.
        _ensure_column(db, "users", "permissions", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_cron_jobs_schema(db)
    if _table_exists(db, "threads"):
        _ensure_column(db, "threads", "model_ref", "TEXT")
        _ensure_column(db, "threads", "reasoning_mode", "TEXT")
        _ensure_column(db, "threads", "reasoning_effort", "TEXT")
        _ensure_column(db, "threads", "artifacts", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(db, "threads", "contributed", "INTEGER NOT NULL DEFAULT 0")
        _ensure_thread_conversation_mode_schema(db)
    if _table_exists(db, "agents"):
        _ensure_column(db, "agents", "is_shared", "INTEGER NOT NULL DEFAULT 0")
        _ensure_agent_profile_columns(db)
        _backfill_agent_profile_from_config(db)
    _ensure_skill_packages_schema(db)
    _ensure_published_experts_schema(db)
    _ensure_usage_cache_schema(db)
    # Cover pre-squash develop DBs that already recorded version ≥5 but only
    # applied a subset of the former 005–009 files (or the old thin 005).
    # Require ``users`` first — SSO rebuild and knowledge FKs need it, and a
    # brand-new DB has not applied 001 yet when repair runs.
    if _table_exists(db, "users"):
        _ensure_sso_oidc_schema(db)
        _ensure_knowledge_bases_schema(db)
        # SSO rebuild recreates ``users``; ensure permissions after that path.
        _ensure_column(db, "users", "permissions", "TEXT NOT NULL DEFAULT '[]'")
        # 029 records the watermark in SQL while the ADD COLUMN helpers live
        # here. Run them every boot so a DB that already sat at 29 (before the
        # helpers existed) gets the thread project/workspace columns too.
        if _table_exists(db, "threads"):
            _ensure_projects_schema(db)


def _max_discovered_version(dialect: str) -> int:
    versions = [version for version, _ in _discover(dialect)]
    return max(versions) if versions else 0


def _reconcile_pre_squash_schema_version(db: DatabasePool) -> None:
    """Clamp develop DBs that applied split 005–009 down to the consolidated max.

    Before squash, local/develop installs could sit at schema versions 6–9.
    After those files are merged into a single 005, leaving version > max would
    permanently skip future migrations (e.g. a new 006).
    """
    current = _current_version(db)
    max_version = _max_discovered_version(db.dialect)
    if max_version <= 0 or current <= max_version:
        return
    if db.dialect == "postgresql":
        # v7 SQL rebuilds tables with RENAME; re-applying it would copy integer
        # ``id`` into public ``*_id`` columns. Use idempotent helpers instead.
        if max_version >= 7:
            _ensure_agent_profile_columns(db)
            _backfill_agent_profile_from_config(db)
            if _table_exists(db, "threads"):
                _ensure_column(db, "threads", "artifacts", "TEXT NOT NULL DEFAULT '[]'")
            _ensure_knowledge_bases_schema(db)
            _ensure_skill_packages_schema(db)
            _ensure_published_experts_schema(db)
            if max_version >= 8:
                _ensure_usage_cache_schema(db)
            if max_version >= 9:
                _ensure_user_invites_schema(db)
            if max_version >= 10:
                _ensure_thread_message_projection_schema(db)
            if max_version >= 11:
                _ensure_cron_jobs_schema(db)
            if max_version >= 12:
                _ensure_trajectory_events_schema(db)
            if max_version >= 13:
                _ensure_connectors_v13_schema(db)
            if max_version >= 14:
                _ensure_user_policy_schema(db)
            if max_version >= 15:
                _ensure_sso_provider_kind_schema(db)
            if max_version >= 16:
                _ensure_agent_teams_schema(db)
            if max_version >= 17:
                _ensure_thread_conversation_mode_schema(db)
            if max_version >= 18:
                _ensure_user_role_schema(db)
            if max_version >= 25:
                _ensure_user_mfa_schema(db)
                _ensure_instance_lease_schema(db)
            with db.connect() as conn:
                conn.execute("UPDATE _schema_version SET version = %s", (max_version,))
            return
        path = next(path for version, path in _discover("postgresql") if version == max_version)
        sql = path.read_text(encoding="utf-8")
        with db.connect() as conn, conn.transaction():
            _apply_postgresql_migration(conn, sql)
            conn.execute("UPDATE _schema_version SET version = %s", (max_version,))
        return
    # SQLite: ensure helpers already ran via _repair_legacy_schema; also apply
    # the max migration's ensure path so clamping to a new max (e.g. 6) does not
    # skip ADD COLUMN for DBs that previously sat at version 7–9.
    if max_version >= 6 and _table_exists(db, "users"):
        _ensure_column(db, "users", "permissions", "TEXT NOT NULL DEFAULT '[]'")
    if max_version >= 7:
        _ensure_agent_profile_columns(db)
        _backfill_agent_profile_from_config(db)
        if _table_exists(db, "threads"):
            _ensure_column(db, "threads", "artifacts", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_knowledge_bases_schema(db)
        _ensure_skill_packages_schema(db)
        _ensure_published_experts_schema(db)
    if max_version >= 8:
        _ensure_usage_cache_schema(db)
    if max_version >= 9:
        _ensure_user_invites_schema(db)
    if max_version >= 10:
        _ensure_thread_message_projection_schema(db)
    if max_version >= 11:
        _ensure_cron_jobs_schema(db)
    if max_version >= 12:
        _ensure_trajectory_events_schema(db)
    if max_version >= 13:
        _ensure_connectors_v13_schema(db)
    if max_version >= 14:
        _ensure_user_policy_schema(db)
    if max_version >= 15:
        _ensure_sso_provider_kind_schema(db)
    if max_version >= 16:
        _ensure_agent_teams_schema(db)
    if max_version >= 17:
        _ensure_thread_conversation_mode_schema(db)
    if max_version >= 18:
        _ensure_user_role_schema(db)
    if max_version >= 21:
        _ensure_skill_package_download_schema(db)
    if max_version >= 22:
        _ensure_skill_package_shared_schema(db)
    if max_version >= 25:
        _ensure_user_mfa_schema(db)
        _ensure_instance_lease_schema(db)
    with db.connect() as conn:
        conn.execute("UPDATE _schema_version SET version = ?", (max_version,))
