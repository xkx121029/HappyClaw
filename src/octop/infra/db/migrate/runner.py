"""The migration runner: applies pending files, then the always-on repairs."""

from __future__ import annotations

from octop.infra.db.migrate.agents import (
    _backfill_agent_profile_from_config,
    _collapse_legacy_agent_welcome_columns,
    _ensure_agent_profile_columns,
)
from octop.infra.db.migrate.auth import (
    _ensure_sso_provider_kind_schema,
    _ensure_user_invites_schema,
    _ensure_user_role_schema,
)
from octop.infra.db.migrate.bridge import _ensure_bridge_connections_schema
from octop.infra.db.migrate.columns import (
    _ensure_agent_teams_schema,
    _ensure_bao_task_followup_columns,
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
from octop.infra.db.migrate.connectors import (
    _ensure_connectors_v13_schema,
    _repair_connector_text_credentials,
)
from octop.infra.db.migrate.control import (
    _ensure_control_blobs_schema,
    _ensure_instance_lease_schema,
)
from octop.infra.db.migrate.cron import (
    _ensure_cron_jobs_schema,
    _ensure_cron_run_schema,
)
from octop.infra.db.migrate.discovery import _current_version, _discover
from octop.infra.db.migrate.experts import _ensure_published_experts_schema
from octop.infra.db.migrate.knowledge import (
    _drop_knowledge_base_members,
    _ensure_knowledge_bases_schema,
    _rebuild_knowledge_identity_schema,
)
from octop.infra.db.migrate.legacy import (
    _reconcile_pre_squash_schema_version,
    _repair_legacy_schema,
)
from octop.infra.db.migrate.mfa import _ensure_user_mfa_schema
from octop.infra.db.migrate.permissions import (
    _expand_page_tab_permissions,
    _grant_bridge_permission,
    _grant_default_nav_permissions,
    _grant_personalization_tab_permissions,
)
from octop.infra.db.migrate.policies import _ensure_user_policy_schema
from octop.infra.db.migrate.projects import _ensure_projects_schema
from octop.infra.db.migrate.single_user import _ensure_single_user_schema
from octop.infra.db.migrate.skills import _ensure_skill_packages_schema
from octop.infra.db.migrate.steps import (
    _apply_postgresql_migration,
    _apply_sqlite_migration,
)
from octop.infra.db.migrate.threads import (
    _ensure_thread_contributed_schema,
    _ensure_thread_message_projection_schema,
    _ensure_trajectory_events_schema,
)
from octop.infra.db.pool import DatabasePool


def run_migrations(db: DatabasePool) -> None:
    if db.dialect == "sqlite":
        _repair_legacy_schema(db)
    for version, path in _discover(db.dialect):
        if version <= _current_version(db):
            continue
        # v18 touches optional ``user_invites``; use the idempotent helper for both
        # dialects so restores from pre-invite physical schemas do not fail.
        if version == 18:
            _ensure_user_role_schema(db)
            with db.connect() as conn:
                if db.dialect == "postgresql":
                    conn.execute("UPDATE _schema_version SET version = %s", (version,))
                else:
                    conn.execute("UPDATE _schema_version SET version = ?", (version,))
            continue
        if db.dialect == "postgresql":
            sql = path.read_text(encoding="utf-8")
            with db.connect() as conn, conn.transaction():
                _apply_postgresql_migration(conn, sql)
            if version == 3:
                from octop.infra.db.repos.threads import repair_all_legacy_thread_titles

                repair_all_legacy_thread_titles(db)
            if version == 7:
                _backfill_agent_profile_from_config(db)
                _rebuild_knowledge_identity_schema(db)
                _drop_knowledge_base_members(db)
                _collapse_legacy_agent_welcome_columns(db)
                _ensure_skill_packages_schema(db)
                _ensure_published_experts_schema(db)
            if version == 10:
                _ensure_knowledge_bases_schema(db)
        else:
            _apply_sqlite_migration(db, version, path)
    _reconcile_pre_squash_schema_version(db)
    _ensure_single_user_schema(db)
    _ensure_knowledge_bases_schema(db)
    _ensure_skill_packages_schema(db)
    _ensure_published_experts_schema(db)
    _ensure_usage_cache_schema(db)
    _ensure_user_invites_schema(db)
    _ensure_thread_message_projection_schema(db)
    _ensure_cron_jobs_schema(db)
    _ensure_trajectory_events_schema(db)
    _ensure_connectors_v13_schema(db)
    _ensure_user_policy_schema(db)
    _ensure_agent_teams_schema(db)
    _ensure_bao_task_followup_columns(db)
    _ensure_thread_conversation_mode_schema(db)
    _ensure_agent_profile_columns(db)
    _ensure_sso_provider_kind_schema(db)
    _ensure_user_role_schema(db)
    _ensure_bridge_connections_schema(db)
    _ensure_skill_copy_policy_schema(db)
    _ensure_skill_package_download_schema(db)
    _ensure_skill_package_shared_schema(db)
    _ensure_user_group_profile_schema(db)
    _ensure_knowledge_base_icon_url_schema(db)
    _ensure_bridge_icon_url_schema(db)
    _ensure_bridge_shared_schema(db)
    # Always repair: version may already be 25 while MFA tables or lease
    # columns were never created.
    _ensure_user_mfa_schema(db)
    _ensure_instance_lease_schema(db)
    _ensure_cron_run_schema(db)
    _ensure_control_blobs_schema(db)
    _ensure_thread_contributed_schema(db)
    _ensure_projects_schema(db)
    _grant_default_nav_permissions(db)
    _grant_personalization_tab_permissions(db)
    _grant_bridge_permission(db)
    _expand_page_tab_permissions(db)
    _repair_connector_text_credentials(db)
