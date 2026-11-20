"""Apply numbered SQL migrations.

Each file is ``NNN_description.sql`` (SQLite) or ``NNN_description.pg.sql``
(PostgreSQL). Version is stored in ``_schema_version``.

The implementation is split by feature area; this module keeps the historical
import surface (``octop.infra.db.migrate.<name>``) intact for callers and tests.
"""

from __future__ import annotations

from octop.infra.db.migrate.agents import (
    _AGENT_PROFILE_COLUMNS,
    _backfill_agent_profile_from_config,
    _collapse_legacy_agent_welcome_columns,
    _ensure_agent_profile_columns,
)
from octop.infra.db.migrate.auth import (
    _create_user_role_table,
    _ensure_sso_oidc_schema,
    _ensure_sso_provider_kind_schema,
    _ensure_user_invites_schema,
    _ensure_user_role_schema,
    _ensure_user_sso_identities_schema,
    _fold_invites_user_role_id_into_role,
    _fold_users_user_role_id_into_role,
    _seed_user_roles,
)
from octop.infra.db.migrate.bridge import (
    _ensure_bridge_connections_schema,
)
from octop.infra.db.migrate.columns import (
    _BAO_TASK_FOLLOWUP_COLUMNS,
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
    _CRON_SCHEDULE_COLUMNS,
    _ensure_cron_jobs_schema,
    _ensure_cron_run_schema,
    _rename_legacy_cron_schedule_column,
)
from octop.infra.db.migrate.discovery import (
    _current_version,
    _discover,
)
from octop.infra.db.migrate.experts import (
    _create_published_experts_identity_table,
    _ensure_published_experts_schema,
    _published_experts_identity_ready,
    _rebuild_published_experts_identity_schema,
)
from octop.infra.db.migrate.introspect import (
    _drop_column,
    _ensure_column,
    _integer_pk_sql,
    _relation_columns,
    _relation_exists,
    _split_pg_sql,
    _sqlite_references_threads,
    _table_columns,
    _table_exists,
)
from octop.infra.db.migrate.knowledge import (
    _create_knowledge_identity_tables,
    _drop_knowledge_base_members,
    _ensure_knowledge_bases_schema,
    _knowledge_identity_ready,
    _rebuild_knowledge_identity_schema,
)
from octop.infra.db.migrate.legacy import (
    _max_discovered_version,
    _reconcile_pre_squash_schema_version,
    _repair_legacy_schema,
)
from octop.infra.db.migrate.mfa import (
    _ensure_user_mfa_schema,
)
from octop.infra.db.migrate.permissions import (
    _BRIDGE_PERMISSIONS,
    _BRIDGE_PERMISSIONS_FLAG,
    _NAV_PAGE_PERMISSIONS,
    _NAV_PAGE_PERMISSIONS_FLAG,
    _PAGE_TAB_EXPANSIONS_FLAG,
    _PERSONALIZATION_TAB_PERMISSIONS,
    _PERSONALIZATION_TAB_PERMISSIONS_FLAG,
    _expand_page_tab_permissions,
    _grant_bridge_permission,
    _grant_default_nav_permissions,
    _grant_permission_keys_once,
    _grant_personalization_tab_permissions,
    _parse_perm_list,
)
from octop.infra.db.migrate.policies import (
    _USER_POLICY_IDENTITY_COLUMNS,
    _copy_legacy_user_policy_columns,
    _copy_legacy_user_resource_policies,
    _create_user_policies_table,
    _ensure_user_policy_schema,
    _insert_user_policy_row,
    _rebuild_user_policies_from_legacy_kv,
    _user_policies_identity_ready,
)
from octop.infra.db.migrate.projects import (
    _PROJECT_THREAD_COLUMNS,
    _ensure_projects_schema,
)
from octop.infra.db.migrate.runner import (
    run_migrations,
)
from octop.infra.db.migrate.single_user import (
    _ensure_single_user_schema,
)
from octop.infra.db.migrate.skills import (
    _create_skill_packages_identity_table,
    _ensure_skill_packages_schema,
    _rebuild_skill_packages_identity_schema,
    _skill_packages_identity_ready,
)
from octop.infra.db.migrate.steps import (
    _apply_postgresql_migration,
    _apply_sqlite_migration,
)
from octop.infra.db.migrate.threads import (
    _ensure_thread_contributed_schema,
    _ensure_thread_message_projection_schema,
    _ensure_trajectory_events_postgresql,
    _ensure_trajectory_events_schema,
)

__all__ = [
    "_table_columns",
    "_table_exists",
    "_ensure_column",
    "_drop_column",
    "_integer_pk_sql",
    "_relation_exists",
    "_relation_columns",
    "_sqlite_references_threads",
    "_split_pg_sql",
    "_AGENT_PROFILE_COLUMNS",
    "_ensure_agent_profile_columns",
    "_collapse_legacy_agent_welcome_columns",
    "_backfill_agent_profile_from_config",
    "_CRON_SCHEDULE_COLUMNS",
    "_rename_legacy_cron_schedule_column",
    "_ensure_cron_jobs_schema",
    "_ensure_cron_run_schema",
    "_skill_packages_identity_ready",
    "_create_skill_packages_identity_table",
    "_rebuild_skill_packages_identity_schema",
    "_ensure_skill_packages_schema",
    "_published_experts_identity_ready",
    "_create_published_experts_identity_table",
    "_rebuild_published_experts_identity_schema",
    "_ensure_published_experts_schema",
    "_knowledge_identity_ready",
    "_create_knowledge_identity_tables",
    "_rebuild_knowledge_identity_schema",
    "_drop_knowledge_base_members",
    "_ensure_knowledge_bases_schema",
    "_ensure_sso_oidc_schema",
    "_ensure_sso_provider_kind_schema",
    "_ensure_user_sso_identities_schema",
    "_ensure_user_invites_schema",
    "_ensure_user_role_schema",
    "_fold_users_user_role_id_into_role",
    "_fold_invites_user_role_id_into_role",
    "_create_user_role_table",
    "_seed_user_roles",
    "_ensure_thread_message_projection_schema",
    "_ensure_trajectory_events_schema",
    "_ensure_trajectory_events_postgresql",
    "_ensure_thread_contributed_schema",
    "_ensure_connectors_v13_schema",
    "_repair_connector_text_credentials",
    "_USER_POLICY_IDENTITY_COLUMNS",
    "_user_policies_identity_ready",
    "_create_user_policies_table",
    "_insert_user_policy_row",
    "_ensure_user_policy_schema",
    "_rebuild_user_policies_from_legacy_kv",
    "_copy_legacy_user_policy_columns",
    "_copy_legacy_user_resource_policies",
    "_BAO_TASK_FOLLOWUP_COLUMNS",
    "_ensure_usage_cache_schema",
    "_ensure_agent_teams_schema",
    "_ensure_thread_conversation_mode_schema",
    "_ensure_skill_copy_policy_schema",
    "_ensure_skill_package_download_schema",
    "_ensure_skill_package_shared_schema",
    "_ensure_user_group_profile_schema",
    "_ensure_knowledge_base_icon_url_schema",
    "_ensure_bridge_icon_url_schema",
    "_ensure_bridge_shared_schema",
    "_ensure_bao_task_followup_columns",
    "_ensure_instance_lease_schema",
    "_ensure_control_blobs_schema",
    "_ensure_user_mfa_schema",
    "_ensure_bridge_connections_schema",
    "_NAV_PAGE_PERMISSIONS",
    "_NAV_PAGE_PERMISSIONS_FLAG",
    "_PERSONALIZATION_TAB_PERMISSIONS",
    "_PERSONALIZATION_TAB_PERMISSIONS_FLAG",
    "_BRIDGE_PERMISSIONS",
    "_BRIDGE_PERMISSIONS_FLAG",
    "_PAGE_TAB_EXPANSIONS_FLAG",
    "_parse_perm_list",
    "_grant_permission_keys_once",
    "_grant_default_nav_permissions",
    "_grant_personalization_tab_permissions",
    "_grant_bridge_permission",
    "_expand_page_tab_permissions",
    "_ensure_single_user_schema",
    "_PROJECT_THREAD_COLUMNS",
    "_ensure_projects_schema",
    "_repair_legacy_schema",
    "_max_discovered_version",
    "_reconcile_pre_squash_schema_version",
    "_apply_postgresql_migration",
    "_apply_sqlite_migration",
    "_discover",
    "_current_version",
    "run_migrations",
]
