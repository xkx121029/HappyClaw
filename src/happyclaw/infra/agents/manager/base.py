"""State and internal interface declared for the AgentManager mixins.

The mixins in this package split AgentManager by responsibility. Every attribute
and method they reach through ``self`` is declared here once, under
``TYPE_CHECKING``, so the split keeps static typing without duplicating
implementations. At runtime this module only carries annotations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncio
    from collections.abc import (
        AsyncIterator,
        Awaitable,
        Callable,
        Sequence,
    )
    from contextlib import AbstractAsyncContextManager
    from pathlib import Path
    from typing import Any

    from happyclaw_harness import (
        HarnessAgent,
        HarnessAgentConfig,
        HarnessAgentManager,
    )
    from happyclaw_harness.registry import AgentEntry
    from happyclaw_harness.security.models import SecurityPolicy

    from happyclaw.config import HappyclawConfig
    from happyclaw.infra.agents.experts.catalog import ExpertCatalog
    from happyclaw.infra.agents.manager.create_spec import AgentCreateSpec
    from happyclaw.infra.agents.memory.slim import MemorySlimCoordinator
    from happyclaw.infra.agents.plugins.manager import PluginManager
    from happyclaw.infra.agents.providers import (
        HostModelFactory,
        ProviderStore,
    )
    from happyclaw.infra.agents.providers.health import ModelHealthRegistry
    from happyclaw.infra.agents.security import (
        SecuritySettingsStore,
        ToolGuardRulesStore,
    )
    from happyclaw.infra.agents.security.hitl_session import HitlSessionPolicyStore
    from happyclaw.infra.agents.settings.acp import ACPSettingsStore
    from happyclaw.infra.agents.settings.decision import (
        DecisionSettings,
        DecisionSettingsStore,
    )
    from happyclaw.infra.agents.settings.langfuse import (
        LangfuseSettings,
        LangfuseSettingsStore,
    )
    from happyclaw.infra.agents.settings.media_generation import (
        MediaGenerationSettings,
        MediaGenerationSettingsStore,
        MediaProviderUpdate,
    )
    from happyclaw.infra.agents.teams import TeamJobTracker, TeamService
    from happyclaw.infra.connectors.service import ConnectorService
    from happyclaw.infra.cron.manager import CronManager
    from happyclaw.infra.db.repos.agents import AgentRow
    from happyclaw.infra.db.services import RepoBundle
    from happyclaw.infra.dsh.integration import DshPromptSessionStore
    from happyclaw.infra.dsh.prompts.skills_injection import SkillPromptSnapshot
    from happyclaw.infra.errors import HappyclawError
    from happyclaw.infra.proactive.scheduler import ProactiveCareScheduler
    from happyclaw.infra.skills.skill_package_store import SkillPackageStore
    from happyclaw.infra.utils.locale import Locale
    from happyclaw.infra.utils.paths import PathLayout


class AgentManagerBase:
    """Attributes and methods the AgentManager mixins must provide."""

    _acp_settings: ACPSettingsStore
    _active_invocations: dict[str, int]
    _agent_lifecycle_locks: dict[str, asyncio.Lock]
    _bootstrap_graph_refresh_pending: set[str]
    _bootstrap_known: dict[str, bool]
    _config: HappyclawConfig
    _connector_svc: ConnectorService
    _connector_user_override: dict[str, int]
    _cron_manager: CronManager | None
    _decision: DecisionSettingsStore
    _dsh_llm_install: Any | None
    _dsh_prompt_sessions: DshPromptSessionStore
    _dsh_skill_snapshots: dict[str, SkillPromptSnapshot]
    _dsh_tool_providers: dict[str, Any]
    _dsh_tools_status: Any | None
    _dsh_transport_factory: Any | None
    _expert_catalog: ExpertCatalog | None
    _harness_manager: HarnessAgentManager | None
    _history_backfills: dict[str, asyncio.Event]
    _hitl_session_store: HitlSessionPolicyStore | None
    _host_models: HostModelFactory
    _invocation_waiters: dict[str, int]
    _langfuse: LangfuseSettingsStore
    _lock: asyncio.Lock
    _mcp_tool_cache: dict[tuple[int, str, str], list[Any]]
    _mcp_tool_cache_guard: asyncio.Lock
    _mcp_tool_cache_locks: dict[tuple[int, str], asyncio.Lock]
    _media_generation: MediaGenerationSettingsStore
    _model_health: ModelHealthRegistry
    _paths: PathLayout
    _plugin_manager: PluginManager | None
    _plugin_tool_labels: dict[str, dict[str, str]]
    _proactive_scheduler: ProactiveCareScheduler | None
    _providers: ProviderStore
    _reclaim_holds: dict[str, asyncio.Event]
    _reclaim_pending: set[str]
    _reclaim_sweep_task: asyncio.Task[None] | None
    _reclaim_task: asyncio.Task[None] | None
    _reclaim_wake: asyncio.Event | None
    _reload_dirty: set[str]
    _reload_worker_running: dict[str, bool]
    _repos: RepoBundle
    _security: SecuritySettingsStore
    _team_jobs: TeamJobTracker
    _team_processor: Any | None
    _teams: TeamService
    _thread_execution_locks: dict[tuple[str, str], asyncio.Lock]
    _tool_guard_rules: ToolGuardRulesStore
    memory_slim: MemorySlimCoordinator

    if TYPE_CHECKING:

        def replace_persistence(self, repos: RepoBundle, config: HappyclawConfig) -> None: ...

        def set_cron_manager(self, cron_manager: CronManager) -> None: ...

        def set_proactive_scheduler(self, scheduler: ProactiveCareScheduler) -> None: ...

        def set_team_processor(self, team_processor: Any | None) -> None: ...

        def set_hitl_session_store(self, store: HitlSessionPolicyStore | None) -> None: ...

        def set_dsh_transport_factory(self, factory: Any | None) -> None: ...

        @property
        def teams(self) -> Any: ...

        async def boot(self, *, restore_agents: bool = True) -> None: ...

        def _install_dsh_llm(self) -> None: ...

        def dsh_llm_status(self) -> dict[str, Any]: ...

        def register_dsh_tool_provider(self, plugin_id: str, provider: Any) -> None: ...

        def dsh_tools_status(self) -> dict[str, Any]: ...

        def _dsh_sandbox_root(self, row: Any) -> Any: ...

        def _dsh_plugin_tools(self, row: Any, *, reserved: Sequence[Any]) -> list[Any]: ...

        async def restore_agents(self) -> None: ...

        async def shutdown(self) -> None: ...

        @property
        def providers(self) -> ProviderStore: ...

        @property
        def host_models(self) -> HostModelFactory: ...

        @property
        def security(self) -> SecuritySettingsStore: ...

        @property
        def acp_settings(self) -> ACPSettingsStore: ...

        @property
        def tool_guard_rules(self) -> ToolGuardRulesStore: ...

        @property
        def langfuse(self) -> LangfuseSettingsStore: ...

        @property
        def decision(self) -> DecisionSettingsStore: ...

        @property
        def media_generation(self) -> MediaGenerationSettingsStore: ...

        @property
        def paths(self) -> PathLayout: ...

        @property
        def harness_manager(self) -> HarnessAgentManager | None: ...

        @property
        def octop_config(self) -> HappyclawConfig: ...

        async def create(
            self,
            spec: AgentCreateSpec,
            *,
            defer_bootstrap: bool = False,
            workspace_initializer: Callable[[AgentRow, Any], Awaitable[None]] | None = None,
        ) -> AgentRow: ...

        async def _abort_incomplete_create(self, agent_id: str) -> None: ...

        def _preserve_internal_layout(
            self, agent_id: str, cfg: dict[str, Any], *, pin_workspace_dir: bool = False
        ) -> dict[str, Any]: ...

        async def update(self, agent_id: str, **kwargs: Any) -> AgentRow: ...

        async def set_shared(self, agent_id: str, shared: bool) -> AgentRow: ...

        def set_icon_url(self, agent_id: str, icon_url: str | None) -> AgentRow: ...

        async def delete(self, agent_id: str) -> None: ...

        async def start(self, agent_id: str) -> None: ...

        def _lifecycle_lock_for(self, agent_id: str) -> asyncio.Lock: ...

        def _thread_execution_lock(self, agent_id: str, thread_id: str) -> asyncio.Lock: ...

        @staticmethod
        def _is_already_registered_error(exc: BaseException) -> bool: ...

        def _happyclaw_harness_or_none(self, agent_id: str) -> HarnessAgent | None: ...

        async def stop(self, agent_id: str) -> None: ...

        def _quiesce_happyclaw_memory(self, agent_id: str) -> None: ...

        async def restore_memory_store(
            self,
            agent_id: str,
            memory: Any,
            operation: Callable[[], dict[str, Any]],
            *,
            locale: str,
        ) -> dict[str, Any]: ...

        @staticmethod
        def _wait_memory_maintenance_idle(mw: object, *, timeout: float = 5.0) -> None: ...

        def get_row(self, agent_id: str) -> AgentRow | None: ...

        def workspace_for_agent(self, agent_id: str) -> Any | None: ...

        async def save_manual_memory_document(
            self, agent_id: str, filename: str, content: str
        ) -> None: ...

        async def review_manual_memory_documents(self, agent_id: str) -> dict[str, Any]: ...

        def list_agents(self, user_id: int) -> list[AgentRow]: ...

        def list_rows(self) -> list[AgentRow]: ...

        def resolve_user_agent(self, user_id: int, query: str) -> AgentRow | None: ...

        def get_config(self, agent_id: str) -> dict[str, Any]: ...

        def persist_harness_config(
            self, agent_id: str, cfg: dict[str, Any], **extra: Any
        ) -> None: ...

        def resolve_workspace_dir(
            self, agent_id: str, *, persist_if_missing: bool = True
        ) -> Path: ...

        def is_bootstrapped(self, agent_id: str) -> bool: ...

        def find_agents_using_provider(self, provider_name: str) -> list[dict[str, str]]: ...

        def find_agents_using_storage_backend(self, backend_name: str) -> list[dict[str, str]]: ...

        def get_agent(self, agent_id: str) -> HarnessAgent: ...

        def _unavailable_error(self, agent_id: str) -> HappyclawError: ...

        def ensure_dispatchable(self, agent_id: str) -> None: ...

        def _require_live_agent(self, agent_id: str) -> None: ...

        def _has_usable_model(self, row: AgentRow) -> bool: ...

        def assert_agents_deletable(self, agent_ids: Sequence[str]) -> None: ...

        async def delete_thread_checkpoint(
            self, agent_id: str, thread_id: str, *, reclaim: bool = True
        ) -> None: ...

        def _delete_thread_from_store(
            self, agent_id: str, thread_id: str, row: Any, reclaim: bool = True
        ) -> None: ...

        def _reclaim_thread_store(self, agent_id: str, thread_id: str, row: Any) -> None: ...

        def schedule_store_reclaim(self, agent_id: str) -> None: ...

        def schedule_idle_reclaim_sweep(self) -> None: ...

        async def compact_agent_database(self, agent_id: str, *, wait_s: float = 60) -> bool: ...

        def _try_acquire_reclaim(self, agent_id: str) -> bool: ...

        def _release_reclaim(self, agent_id: str) -> None: ...

        def _ensure_reclaim_task(self) -> None: ...

        async def _sweep_bloated_stores(self) -> None: ...

        def _queue_bloated_sqlite_stores(self) -> int: ...

        async def _reclaim_pending_loop(self) -> None: ...

        def _compact_agent_database_sync(self, agent_id: str) -> bool: ...

        def is_agent_active(self, agent_id: str) -> bool: ...

        def try_begin_history_backfill(self, agent_id: str) -> bool: ...

        def end_history_backfill(self, agent_id: str) -> None: ...

        async def _begin_invocation(self, agent_id: str) -> None: ...

        def _end_invocation(self, agent_id: str) -> None: ...

        def _track_invocation(self, agent_id: str) -> AbstractAsyncContextManager[None]: ...

        def stream(self, agent_id: str, request: dict[str, Any]) -> AsyncIterator[Any]: ...

        async def call(self, agent_id: str, request: dict[str, Any]) -> dict[str, Any]: ...

        def resume_hitl(
            self, agent_id: str, thread_id: str, decisions: list[dict[str, Any]]
        ) -> AsyncIterator[Any]: ...

        def cancel_stream(self, agent_id: str, thread_id: str) -> None: ...

        def get_thread_model(self, agent_id: str, thread_id: str) -> str | None: ...

        def set_thread_model(self, agent_id: str, thread_id: str, model: str) -> None: ...

        def clear_thread_model(self, agent_id: str, thread_id: str) -> None: ...

        def _resolve_configured_fallback_model_ref(self) -> str | None: ...

        def resolve_fallback_model_ref(self) -> str | None: ...

        def is_auto_route_model_available(self, ref: str) -> bool: ...

        async def reload(self, agent_id: str) -> None: ...

        async def reload_all(self) -> None: ...

        def reload_happyclaw_harness(self) -> None: ...

        def _agent_uses_auto_default(self, row: AgentRow) -> bool: ...

        def _provider_reload_impact_ids(
            self, *, provider_name: str | None = None, active_model_changed: bool = False
        ) -> list[str]: ...

        def _stale_auto_default_ids(
            self, *, provider_name: str, enabled_ids: set[str], auto_ids: set[str]
        ) -> set[str]: ...

        async def _reload_agents(self, agent_ids: list[str]) -> None: ...

        async def on_provider_changed(
            self, *, provider_name: str | None = None, active_model_changed: bool = False
        ) -> None: ...

        async def reload_connectors(
            self, agent_id: str, *, connector_user_id: int | None = None
        ) -> None: ...

        async def reload_connectors_for_user(self, user_id: int) -> None: ...

        def invalidate_mcp_tool_cache(self, user_id: int | None = None) -> None: ...

        def mcp_server_labels_for_user(self, user_id: int) -> dict[str, str]: ...

        def resolve_tool_display_name_for_chat(
            self, *, agent_id: str, user_id: int | None, tool_name: str, locale: str
        ) -> str: ...

        async def _server_lock(self, user_id: int, server_name: str) -> asyncio.Lock: ...

        async def _get_or_load_mcp_tools(
            self, user_id: int, server_name: str, spec: dict[str, Any]
        ) -> list[Any]: ...

        def merge_turn_mcp_servers(
            self,
            user_id: int,
            explicit: list[str] | None,
            *,
            apply_defaults: bool | None = None,
            extra_defaults: list[str] | None = None,
            agent_owner_id: int | None = None,
        ) -> list[str] | None: ...

        def present_mcp_names_for_viewer(
            self, owner_user_id: int, viewer_user_id: int, names: list[str]
        ) -> list[str]: ...

        def align_mcp_names_to_harness(
            self, owner_user_id: int, viewer_user_id: int, names: list[str]
        ) -> list[str]: ...

        def mcp_names_for_chips(
            self,
            owner_user_id: int,
            viewer_user_id: int,
            requested: list[str],
            harness_names: list[str],
        ) -> list[str]: ...

        def default_mcp_servers(self, agent_id: str) -> list[str]: ...

        def default_knowledge_base_ids(self, agent_id: str) -> list[str]: ...

        async def prepare_chat_mcp(
            self, agent_id: str, names: list[str] | None, *, connector_user_id: int | None = None
        ) -> list[str]: ...

        async def _attach_gateway_tools(
            self, agent: HarnessAgent, *, agent_id: str, user_id: int, server_names: list[str]
        ) -> None: ...

        def save_langfuse(
            self, *, enabled: bool, public_key: str, host: str, secret_key: str | None = None
        ) -> LangfuseSettings: ...

        async def save_decision(
            self,
            *,
            enabled: bool,
            provider: str,
            endpoint: str,
            model: str,
            skills: bool,
            tools: bool,
            team: bool,
            threshold: float,
            tool_min_count: int,
            api_key: str | None = None,
            services: list[dict[str, object]] | None = None,
        ) -> DecisionSettings: ...

        async def probe_decision(
            self,
            *,
            endpoint: str | None = None,
            api_key: str | None = None,
            model: str | None = None,
            provider: str | None = None,
        ) -> dict[str, Any]: ...

        async def save_media_generation(
            self,
            *,
            enabled: bool,
            providers: list[MediaProviderUpdate],
            default_image_provider: str | None,
            default_video_provider: str | None,
        ) -> MediaGenerationSettings: ...

        def save_security(self, policy: SecurityPolicy | dict[str, Any]) -> SecurityPolicy: ...

        async def apply_persona_mbti(self, agent_id: str, code: str) -> AgentRow: ...

        async def update_config_json(self, agent_id: str, config_json: str) -> AgentRow: ...

        async def persist_skills_disabled(self, agent_id: str, disabled: set[str]) -> None: ...

        async def persist_tools_disabled(self, agent_id: str, disabled: set[str]) -> None: ...

        async def persist_plugin_tools_config(
            self, agent_id: str, plugins: dict[str, Any]
        ) -> None: ...

        def _skill_package_store(self) -> SkillPackageStore: ...

        def _resolve_skill_package_dirs(self, agent_id: str) -> list[str]: ...

        @staticmethod
        def _normalize_skills_dir_config(value: Any) -> list[str]: ...

        @staticmethod
        def _backend_supports_host_skill_packages(
            spec: Any, *, workspace_dir: Path | None = None
        ) -> bool: ...

        @staticmethod
        def _backend_blocks_acp_outbound(
            spec: Any, *, workspace_dir: Path | None = None
        ) -> bool: ...

        async def persist_skill_package_ids(
            self, agent_id: str, package_ids: list[str]
        ) -> None: ...

        def sync_skill_package_dirs(self, agent_id: str) -> None: ...

        def validate_skill_package_ids(self, package_ids: list[str]) -> list[str]: ...

        def _user_is_admin(self, user_id: int | None) -> bool: ...

        def model_ref_allowed_for_user(self, user_id: int, model_ref: str | None) -> bool: ...

        def _assert_model_ref(self, user_id: int, model_ref: str | None) -> None: ...

        def _assert_named_storage_backends(self, user_id: int, backend: Any) -> None: ...

        def _skill_package_shared_with(self, user_id: int, package: Any) -> bool: ...

        def _skill_package_visible(self, user_id: int, package: Any) -> bool: ...

        def _assert_skill_packages_visible(self, user_id: int, package_ids: list[str]) -> None: ...

        def persist_knowledge_base_ids(
            self, agent_id: str, knowledge_base_ids: list[str]
        ) -> None: ...

        def persist_mcp_servers(self, agent_id: str, mcp_servers: list[str]) -> None: ...

        def validate_knowledge_base_ids(
            self, user_id: int, knowledge_base_ids: list[str]
        ) -> list[str]: ...

        def validate_mcp_servers(self, user_id: int, mcp_servers: list[str]) -> list[str]: ...

        def assert_backend_supports_skill_packages(
            self, backend_spec: Any | None, *, workspace_dir: Path | None = None
        ) -> None: ...

        async def refresh_agents_for_package(self, package_id: str) -> None: ...

        async def strip_skill_package_id(self, package_id: str) -> None: ...

        def resolve_context_max_tokens(self, agent_id: str, *, fallback: int = 128000) -> int: ...

        async def list_skill_summaries(
            self, agent_id: str, *, locale: Locale | None = None
        ) -> list[dict[str, Any]]: ...

        async def list_subagent_summaries(self, agent_id: str) -> list[dict[str, Any]]: ...

        def sync_skills_disabled(self, agent_id: str, disabled: set[str]) -> None: ...

        def sync_tools_disabled(self, agent_id: str, disabled: set[str]) -> None: ...

        def strip_team_host_runtime_tools(self, agent_id: str) -> None: ...

        def sync_effective_tools_disabled(self, agent_id: str) -> None: ...

        def _assert_agent_name_available(
            self, user_id: int | None, name: str, *, exclude_agent_id: str | None = None
        ) -> None: ...

        async def _complete_create_bootstrap(self, row: AgentRow) -> None: ...

        def _repair_persisted_backend_root(self, row: AgentRow) -> None: ...

        async def _start_agent(
            self, row: AgentRow, *, init_workspace: bool = True
        ) -> HarnessAgent | None: ...

        async def _post_start_agent(
            self,
            row: AgentRow,
            agent: HarnessAgent,
            cfg: HarnessAgentConfig,
            *,
            user_display: str = "User",
        ) -> None: ...

        def _mark_bootstrap_graph_refresh_pending(
            self, agent_id: str, agent: HarnessAgent
        ) -> None: ...

        def _apply_pending_bootstrap_graph_refresh(self, agent_id: str) -> None: ...

        def _agent_config_dict(self, row: AgentRow) -> dict[str, Any]: ...

        def _backend_spec_for_row(
            self,
            row: AgentRow,
            *,
            cfg: dict[str, Any] | None = None,
            workspace_dir: Path | None = None,
        ) -> Any: ...

        def resolved_backend_spec(self, agent_id: str) -> Any: ...

        def _owner_username(self, row: AgentRow) -> str | None: ...

        @staticmethod
        def _spec_is_opensandbox(spec: Any) -> bool: ...

        def _prepare_docker_backend(self, backend: Any, row: AgentRow) -> Any: ...

        def _backend_workspace_for_row(
            self,
            row: AgentRow,
            *,
            cfg: dict[str, Any] | None = None,
            workspace_dir: Path | None = None,
            allow_ephemeral_remote: bool = False,
        ) -> Any: ...

        async def _seed_expert_template(self, row: AgentRow, template_name: str) -> None: ...

        async def _reload_agent(self, agent_id: str) -> None: ...

        def _schedule_reload(self, agent_id: str) -> None: ...

        async def _reload_worker(self, agent_id: str) -> None: ...

        def _agent_runtime_bundle(
            self, row: AgentRow
        ) -> tuple[HarnessAgentConfig, dict[str, Any], list[str], str]: ...

        def _refresh_peer_entry(self, entry: AgentEntry) -> None: ...

        def _apply_peer_profile_metadata(
            self, metadata: dict[str, Any], agent_id: str, row_description: str | None
        ) -> None: ...

        def _peer_manifest_metadata(
            self, agent_id: str, row_description: str | None
        ) -> dict[str, Any]: ...

        def _connector_uid_for(
            self, row: AgentRow, *, connector_user_id: int | None = None
        ) -> int | None: ...

        def _prepare_stream_request(
            self, agent_id: str, request: dict[str, Any]
        ) -> dict[str, Any]: ...

        def _apply_dsh_skill_delta(self, agent_id: str, req: dict[str, Any]) -> dict[str, Any]: ...

        def _stream_model_label(
            self, agent_id: str, request: dict[str, Any], thread_id: str
        ) -> str: ...

        def _build_harness_config(self, row: AgentRow) -> HarnessAgentConfig: ...

        def _install_team_host_dispatch(self) -> None: ...

        def _agently_write_interrupts(self, user_id: int | None) -> dict[str, Any]: ...

        def _merge_agently_write_interrupts(
            self, cfg: HarnessAgentConfig, user_id: int | None
        ) -> HarnessAgentConfig: ...

        def _apply_team_host_config(
            self, cfg: HarnessAgentConfig, row: Any
        ) -> HarnessAgentConfig: ...
