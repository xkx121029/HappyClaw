"""AgentManager — process-wide singleton managing all HarnessAgent instances."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
)

from happyclaw_harness import (
    HarnessAgentConfig,
    HarnessAgentManager,
)
from happyclaw_harness.registry import AgentEntry
from happyclaw_harness.security.models import SecurityPolicy

from happyclaw.i18n.domains.agents import AGENT_START_TIMEOUT
from happyclaw.infra.agents.manager.base import AgentManagerBase
from happyclaw.infra.agents.manager.config import (
    ConfigMixin,
    skills_disabled_set,
)
from happyclaw.infra.agents.manager.constants import _HARNESS_AGENT_CONFIG_FIELDS
from happyclaw.infra.agents.manager.crud import CrudMixin
from happyclaw.infra.agents.manager.dsh import DshMixin
from happyclaw.infra.agents.manager.mcp import McpMixin
from happyclaw.infra.agents.manager.memory import (
    MemoryMixin,
    _memory_extract_settings,
    _memory_namespace,
    _resolve_memory_backend_kwargs,
)
from happyclaw.infra.agents.manager.queries import QueriesMixin
from happyclaw.infra.agents.manager.reload import ReloadMixin
from happyclaw.infra.agents.manager.runtime import RuntimeMixin
from happyclaw.infra.agents.manager.skills import SkillsMixin
from happyclaw.infra.agents.manager.startup import StartupMixin
from happyclaw.infra.agents.manager.store_reclaim import StoreReclaimMixin
from happyclaw.infra.agents.memory.slim import MemorySlimCoordinator
from happyclaw.infra.agents.providers import (
    HostModelFactory,
    ProviderStore,
)
from happyclaw.infra.agents.providers.health import ModelHealthRegistry
from happyclaw.infra.agents.security import (
    SecuritySettingsStore,
    ToolGuardRulesStore,
)
from happyclaw.infra.agents.security.hitl_session import (
    HitlSessionPolicyStore,
    apply_session_bypass,
)
from happyclaw.infra.agents.settings.acp import ACPSettingsStore
from happyclaw.infra.agents.settings.decision import DecisionSettingsStore
from happyclaw.infra.agents.settings.langfuse import LangfuseSettingsStore
from happyclaw.infra.agents.settings.media_generation import MediaGenerationSettingsStore
from happyclaw.infra.agents.settings.runtime_limits import apply_agent_runtime_to_stream_request
from happyclaw.infra.connectors.builder import build_mcp_server_configs_for_user
from happyclaw.infra.connectors.service import ConnectorService
from happyclaw.infra.dsh.integration import (
    DshPromptSessionStore,
    compose_system_prompt,
    dsh_skills_prompts_enabled,
    workspace_skill_snapshot,
)
from happyclaw.infra.dsh.prompts.skills_injection import SkillPromptSnapshot
from happyclaw.infra.dsh.switches import stage_enabled as dsh_stage_enabled
from happyclaw.infra.utils.locale import resolve_user_locale

if TYPE_CHECKING:
    from happyclaw.config import HappyclawConfig
    from happyclaw.infra.agents.experts.catalog import ExpertCatalog
    from happyclaw.infra.agents.plugins.manager import PluginManager
    from happyclaw.infra.cron.manager import CronManager
    from happyclaw.infra.db.repos.agents import AgentRow
    from happyclaw.infra.db.services import RepoBundle
    from happyclaw.infra.proactive.scheduler import ProactiveCareScheduler
    from happyclaw.infra.utils.paths import PathLayout


from happyclaw.infra.agents.manager.config import skill_package_ids_list as skill_package_ids_list
from happyclaw.infra.agents.manager.config import tools_disabled_set as tools_disabled_set
from happyclaw.infra.agents.manager.create_spec import _CUSTOM_AGENT_ID_RE as _CUSTOM_AGENT_ID_RE
from happyclaw.infra.agents.manager.create_spec import _RESERVED_AGENT_IDS as _RESERVED_AGENT_IDS
from happyclaw.infra.agents.manager.create_spec import AgentCreateSpec as AgentCreateSpec
from happyclaw.infra.agents.manager.create_spec import _stored_id_list as _stored_id_list
from happyclaw.infra.agents.manager.create_spec import (
    validate_custom_agent_id as validate_custom_agent_id,
)
from happyclaw.infra.agents.manager.dsh import _dsh_local_roots as _dsh_local_roots
from happyclaw.infra.agents.manager.mcp import _bind_custom_mcp_tools as _bind_custom_mcp_tools
from happyclaw.infra.agents.manager.mcp import (
    _sanitize_bound_mcp_tools as _sanitize_bound_mcp_tools,
)
from happyclaw.infra.agents.manager.memory import _MEMORY_NS_PREFIX as _MEMORY_NS_PREFIX
from happyclaw.infra.agents.manager.memory import (
    _memory_aux_model_settings as _memory_aux_model_settings,
)
from happyclaw.infra.agents.manager.memory import _model_retry_on_failure as _model_retry_on_failure
from happyclaw.infra.agents.manager.memory import (
    memory_extract_supported_options as memory_extract_supported_options,
)
from happyclaw.infra.agents.manager.reload import (
    _AGENT_STATES_NEEDING_MODEL_RELOAD as _AGENT_STATES_NEEDING_MODEL_RELOAD,
)
from happyclaw.infra.agents.manager.reload import (
    _PROVIDER_RELOAD_CONCURRENCY as _PROVIDER_RELOAD_CONCURRENCY,
)
from happyclaw.infra.agents.manager.startup import (
    _fill_missing_subagent_colors as _fill_missing_subagent_colors,
)

logger = logging.getLogger(__name__)

# One hung remote backend must not block ``octop run`` from serving HTTP.
_AGENT_BOOT_START_TIMEOUT = 60.0


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# AgentManager
# ---------------------------------------------------------------------------


class AgentManager(SkillsMixin, StartupMixin, ConfigMixin, McpMixin, ReloadMixin, StoreReclaimMixin, RuntimeMixin, QueriesMixin, CrudMixin, DshMixin, MemoryMixin, AgentManagerBase):
    """Process-wide singleton: owns harness HarnessAgentManager + all HarnessAgent instances.

    On boot, loads all enabled agents from the DB and registers them with the
    harness HarnessAgentManager. Provides CRUD that stays in sync between DB and runtime.

    Row data is always read directly from the DB — no in-process row cache —
    so callers always see the latest persisted state.

    Public surface (by concern):
      - Lifecycle: boot / shutdown, start / stop individual agents
      - CRUD: create / update / delete
      - Reads: get_row, list_*, get_config, resolve_user_agent
      - Runtime: get_agent, stream / call / HITL / thread model
      - Hot-reload: reload*, on_provider_changed, reload_happyclaw_harness
      - Connectors: reload_connectors*, prepare_chat_mcp
      - Settings stores: langfuse, security, acp_settings, tool_guard_rules, providers
    """

    # ------------------------------------------------------------------
    # Lifecycle — construction, wiring, boot / shutdown
    # ------------------------------------------------------------------

    def __init__(
        self,
        *,
        repos: RepoBundle,
        paths: PathLayout,
        config: HappyclawConfig | None = None,
        expert_catalog: ExpertCatalog | None = None,
        plugin_manager: PluginManager | None = None,
    ) -> None:
        self._repos = repos
        self._paths = paths
        from happyclaw.config import HappyclawConfig  # noqa: PLC0415

        self._config = config or HappyclawConfig()
        self._expert_catalog = expert_catalog
        self._plugin_manager = plugin_manager
        self._cron_manager: CronManager | None = None
        self._proactive_scheduler: ProactiveCareScheduler | None = None
        self._team_processor: Any | None = None
        self._hitl_session_store: HitlSessionPolicyStore | None = None
        from happyclaw.infra.agents.teams import TeamJobTracker, TeamService

        self._team_jobs = TeamJobTracker()
        self._teams = TeamService(
            repos,
            self._team_jobs,
            workspace_for=self.workspace_for_agent,
        )
        self._harness_manager: HarnessAgentManager | None = None
        self.memory_slim = MemorySlimCoordinator(self)
        self._lock = asyncio.Lock()
        # Serialize start/reload per agent so parallel provider reloads cannot
        # double-register the same harness id ("already exists in the registry").
        self._agent_lifecycle_locks: dict[str, asyncio.Lock] = {}
        # Serialize harness execution per thread. Dashboard turns are queued by
        # the channel debounce lock, but POST /chat/hitl/resume (and cron)
        # drive the same checkpoint without it — two concurrent executions on
        # one thread interleave LangGraph checkpoint writes.
        self._thread_execution_locks: dict[tuple[str, str], asyncio.Lock] = {}
        # Opt-in DSH skill/prompt state. Session cursors live on this instance
        # (never in module globals) and are keyed by (agent_id, thread_id).
        self._dsh_prompt_sessions = DshPromptSessionStore()
        self._dsh_skill_snapshots: dict[str, SkillPromptSnapshot] = {}
        # S8 model adapter: transport factory injected before boot(), plus the
        # last install result for the read-only status query. Both stay None
        # when the stage is off, which costs no DSH LLM import.
        self._dsh_transport_factory: Any | None = None
        self._dsh_llm_install: Any | None = None
        # S2 read-only tool mounting: optional in-process tool bodies keyed by
        # plugin id, plus the last assembly result for the status query. Both are
        # empty/None while the stage is off, which costs no DSH tools import.
        self._dsh_tool_providers: dict[str, Any] = {}
        self._dsh_tools_status: Any | None = None
        self._active_invocations: dict[str, int] = {}
        self._invocation_waiters: dict[str, int] = {}
        self._history_backfills: dict[str, asyncio.Event] = {}
        # Agents whose SQLite file should be rebuilt once they are idle.
        self._reclaim_pending: set[str] = set()
        self._reclaim_holds: dict[str, asyncio.Event] = {}
        self._reclaim_task: asyncio.Task[None] | None = None
        self._reclaim_sweep_task: asyncio.Task[None] | None = None
        self._reclaim_wake: asyncio.Event | None = None
        self._reload_dirty: set[str] = set()
        self._reload_worker_running: dict[str, bool] = {}
        self._bootstrap_graph_refresh_pending: set[str] = set()
        # Completion latch set by the bootstrap callback. Do not cache False:
        # the middleware can complete between dashboard polls.
        self._bootstrap_known: dict[str, bool] = {}
        # Chat user id used to resolve connectors when agent.user_id is NULL (shared agents).
        self._connector_user_override: dict[str, int] = {}
        self._langfuse = LangfuseSettingsStore(
            settings_repo=repos.settings_repo,
            secret_repo=repos.secret_repo,
        )
        self._decision = DecisionSettingsStore(
            settings_repo=repos.settings_repo,
            secret_repo=repos.secret_repo,
        )
        self._media_generation = MediaGenerationSettingsStore(
            settings_repo=repos.settings_repo,
            secret_repo=repos.secret_repo,
        )
        self._security = SecuritySettingsStore(settings_repo=repos.settings_repo)
        self._acp_settings = ACPSettingsStore(
            settings_repo=repos.settings_repo,
            agents_repo=repos.agent_repo,
        )
        self._tool_guard_rules = ToolGuardRulesStore(paths=paths, settings=repos.settings_repo)
        self._providers = ProviderStore(
            provider_repo=repos.provider_repo,
        )
        self._host_models = HostModelFactory()
        self._model_health = ModelHealthRegistry()
        self._connector_svc = ConnectorService(
            repo=repos.connector_repo,
            secret_repo=repos.secret_repo,
            settings_repo=repos.settings_repo,
            config=self._config,
        )
        # User-scoped custom MCP tools: (user_id, server_name, fingerprint) -> tools
        self._mcp_tool_cache: dict[tuple[int, str, str], list[Any]] = {}
        self._mcp_tool_cache_locks: dict[tuple[int, str], asyncio.Lock] = {}
        self._mcp_tool_cache_guard = asyncio.Lock()
        # Sanitized plugin tool name → original label (per agent, rebuilt on reload).
        self._plugin_tool_labels: dict[str, dict[str, str]] = {}

    def replace_persistence(self, repos: RepoBundle, config: HappyclawConfig) -> None:
        """Retarget repos/config and rebuild settings stores after control-plane rebind."""
        self._repos = repos
        self._config = config
        self._langfuse = LangfuseSettingsStore(
            settings_repo=repos.settings_repo,
            secret_repo=repos.secret_repo,
        )
        self._decision = DecisionSettingsStore(
            settings_repo=repos.settings_repo,
            secret_repo=repos.secret_repo,
        )
        self._media_generation = MediaGenerationSettingsStore(
            settings_repo=repos.settings_repo,
            secret_repo=repos.secret_repo,
        )
        self._security = SecuritySettingsStore(settings_repo=repos.settings_repo)
        self._acp_settings = ACPSettingsStore(
            settings_repo=repos.settings_repo,
            agents_repo=repos.agent_repo,
        )
        self._tool_guard_rules = ToolGuardRulesStore(
            paths=self._paths, settings=repos.settings_repo
        )
        self._providers = ProviderStore(provider_repo=repos.provider_repo)
        self._connector_svc = ConnectorService(
            repo=repos.connector_repo,
            secret_repo=repos.secret_repo,
            settings_repo=repos.settings_repo,
            config=self._config,
        )

    def set_cron_manager(self, cron_manager: CronManager) -> None:
        """Attach the process-wide CronManager (must be set before boot())."""
        self._cron_manager = cron_manager

    def set_proactive_scheduler(self, scheduler: ProactiveCareScheduler) -> None:
        """Attach the process-wide proactive-care scheduler (optional; used after create/delete)."""
        self._proactive_scheduler = scheduler

    def set_team_processor(self, team_processor: Any | None) -> None:
        """Attach harness TeamProcessor (GlobalProcessor); required before boot()."""
        self._team_processor = team_processor
        if self._harness_manager is not None:
            self._install_team_host_dispatch()

    def set_hitl_session_store(self, store: HitlSessionPolicyStore | None) -> None:
        """Attach the thread-scoped HITL bypass store (set before boot())."""
        self._hitl_session_store = store

    def set_dsh_transport_factory(self, factory: Any | None) -> None:
        """Override the S8 DSH transport factory (set before boot(); optional).

        ``None`` means "use the built-in httpx transport" once the stage is
        enabled; without any transport the installer reports ``skipped`` and
        every model call keeps using the harness factory.
        """
        self._dsh_transport_factory = factory

    @property
    def teams(self) -> Any:
        return self._teams

    async def boot(self, *, restore_agents: bool = True) -> None:
        """Wire the harness, then (optionally) start every persisted agent.

        ``restore_agents=False`` leaves agent start-up to :meth:`restore_agents`
        so ``octop run`` can bind the socket first: a harness graph compile can
        take tens of seconds (and hard-times-out at 60s), which used to delay
        ``/api/health`` by the same amount.
        """
        self._tool_guard_rules.ensure_seeded()
        providers = self._providers.build_harness_configs()
        self._harness_manager = HarnessAgentManager(
            providers=providers,
            langfuse=self._langfuse.harness_config(),
            team_processor=self._team_processor,
            file_logging=False,
        )
        self._host_models.sync(providers)
        if self._harness_manager is not None:
            self._harness_manager.team.bind_peer_enrich(self._refresh_peer_entry)
            proc = self._team_processor
            if proc is not None:
                prepare = getattr(proc, "prepare_peer_session", None)
                after = getattr(proc, "record_peer_turn", None)
                if prepare is not None or after is not None:
                    self._harness_manager.team.bind_peer_session(prepare=prepare, after=after)
            self._install_team_host_dispatch()
            from happyclaw.infra.agents.teams.team_manager import (  # noqa: PLC0415
                wire_shared_member_peers,
            )

            wire_shared_member_peers(
                self._harness_manager.team,
                load_agent=self.get_row,
                load_user=self._repos.user_repo.get,
            )
            self._harness_manager.set_security_policy(self._security.harness_policy())

        self._install_dsh_llm()

        if restore_agents:
            await self.restore_agents()

    async def restore_agents(self) -> None:
        """Start every persisted agent that is not explicitly stopped.

        Each start is bounded by ``_AGENT_BOOT_START_TIMEOUT``; a timeout marks
        the row ``failed`` and boot continues. Safe to call after the socket is
        bound — ``_start_agent`` is guarded by a per-agent lifecycle lock.
        """
        rows = self._repos.agent_repo.list_all(include_disabled=False)
        for row in rows:
            if row.last_state == "stopped":
                continue
            try:
                await asyncio.wait_for(
                    self._start_agent(row),
                    timeout=_AGENT_BOOT_START_TIMEOUT,
                )
            except TimeoutError:
                if self._happyclaw_harness_or_none(row.agent_id) is not None:
                    self._repos.agent_repo.set_state(row.agent_id, "running", error=None)
                    logger.warning(
                        "Agent %s start exceeded %.0fs but is already registered",
                        row.agent_id,
                        _AGENT_BOOT_START_TIMEOUT,
                    )
                    continue
                logger.error(
                    "Agent %s start timed out after %.0fs; continuing boot",
                    row.agent_id,
                    _AGENT_BOOT_START_TIMEOUT,
                )
                self._repos.agent_repo.set_state(
                    row.agent_id,
                    "failed",
                    error=AGENT_START_TIMEOUT,
                )

    async def shutdown(self) -> None:
        # The idle sweep reads the control-plane DB on a worker thread. Wait for
        # that read to finish before the caller closes the shared connection.
        sweep = self._reclaim_sweep_task
        self._reclaim_sweep_task = None
        if sweep is not None and not sweep.done():
            try:
                await sweep
            except Exception:
                logger.warning("idle reclaim sweep failed during shutdown", exc_info=True)
        self._reclaim_pending.clear()
        # The idle sweep runs list_all on a worker thread. Cancelling that
        # task does not stop the thread, so wait until the scan returns before
        # the caller closes the control-plane connection.
        sweep_task = self._reclaim_sweep_task
        self._reclaim_sweep_task = None
        if sweep_task is not None and not sweep_task.done():
            await sweep_task
        reclaim_task = self._reclaim_task
        self._reclaim_task = None
        if reclaim_task is not None and not reclaim_task.done():
            reclaim_task.cancel()
            with suppress(asyncio.CancelledError):
                await reclaim_task
        await self.memory_slim.close()
        async with self._lock:
            if self._harness_manager:
                try:
                    # Drain SQLite workers before the owning event loop can close.
                    await self._harness_manager.aclose()
                except Exception:
                    logger.exception("harness_manager.aclose() failed")
                self._harness_manager = None
            self._host_models.close()

    # ------------------------------------------------------------------
    # Exposed stores & paths (read-only accessors)
    # ------------------------------------------------------------------

    @property
    def providers(self) -> ProviderStore:
        return self._providers

    @property
    def host_models(self) -> HostModelFactory:
        """One-shot model access outside an agent turn."""
        return self._host_models

    @property
    def security(self) -> SecuritySettingsStore:
        return self._security

    @property
    def acp_settings(self) -> ACPSettingsStore:
        return self._acp_settings

    @property
    def tool_guard_rules(self) -> ToolGuardRulesStore:
        return self._tool_guard_rules

    @property
    def langfuse(self) -> LangfuseSettingsStore:
        return self._langfuse

    @property
    def decision(self) -> DecisionSettingsStore:
        return self._decision

    @property
    def media_generation(self) -> MediaGenerationSettingsStore:
        return self._media_generation

    @property
    def paths(self) -> PathLayout:
        return self._paths

    @property
    def harness_manager(self) -> HarnessAgentManager | None:
        return self._harness_manager

    @property
    def octop_config(self) -> HappyclawConfig:
        return self._config

    # ------------------------------------------------------------------
    # CRUD — persist agent rows and sync harness runtime
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Row & config reads — DB lookups, no harness required
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Runtime access — live HarnessAgent handle
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Chat / invoke — stream, call, HITL, thread model overrides
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Hot-reload — rebuild harness agents after config / provider changes
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Connectors & MCP — OAuth refresh and pre-chat tool loading
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Settings persistence — push global policy into harness runtime
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Agent config mutations — persona, skills, config_json patches
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Internal — validation
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Internal — agent startup & workspace seeding
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Internal — background reload worker
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Internal — harness config assembly & stream request prep
    # ------------------------------------------------------------------

    def _agent_runtime_bundle(
        self, row: AgentRow
    ) -> tuple[HarnessAgentConfig, dict[str, Any], list[str], str]:
        from happyclaw.infra.utils.browser_media import (  # noqa: PLC0415
            agent_outbound_screenshots_dir,
            configure_browser_profiles_dir,
            configure_browser_screenshots_dir,
            octop_browser_profiles_dir,
        )

        configure_browser_screenshots_dir(
            agent_outbound_screenshots_dir(self.resolve_workspace_dir(row.agent_id)),
        )
        # Shared across agents — not under a single agent workspace.
        configure_browser_profiles_dir(octop_browser_profiles_dir(self._paths))
        user_display = "User"
        if row.user_id is not None:
            owner = self._repos.user_repo.get(row.user_id)
            if owner is not None:
                user_display = owner.display_name or owner.username or user_display
        cfg = self._build_harness_config(row)
        metadata: dict[str, Any] = {
            "user_id": row.user_id,
            "description": row.description,
            "display_name": row.name,
            "icon": row.icon,
            "template_name": row.template_name,
        }
        self._apply_peer_profile_metadata(metadata, row.agent_id, row.description)
        tags: list[str] = []
        if getattr(row, "kind", None) == "team":
            tags.append("team")
        if row.template_name:
            tags.append(row.template_name)
        return cfg, metadata, tags, user_display

    def _refresh_peer_entry(self, entry: AgentEntry) -> None:
        """Re-read description / guidance cards into a running registry entry."""
        row = self._repos.agent_repo.get(entry.agent_id)
        row_desc = row.description if row is not None else None
        if row is not None and str(row.name or "").strip():
            entry.metadata["display_name"] = row.name
        self._apply_peer_profile_metadata(entry.metadata, entry.agent_id, row_desc)

    def _apply_peer_profile_metadata(
        self,
        metadata: dict[str, Any],
        agent_id: str,
        row_description: str | None,
    ) -> None:
        extra = self._peer_manifest_metadata(agent_id, row_description)
        if row_description and str(row_description).strip():
            metadata["description"] = row_description
        elif extra.get("description"):
            metadata["description"] = extra["description"]
        if "quick_prompts" not in extra:
            return
        prompts = extra["quick_prompts"]
        if isinstance(prompts, list) and prompts:
            metadata["quick_prompts"] = prompts
        else:
            metadata.pop("quick_prompts", None)

    def _peer_manifest_metadata(
        self,
        agent_id: str,
        row_description: str | None,
    ) -> dict[str, Any]:
        """Guidance cards (and fallback description) from workspace ``manifest.json``."""
        extra: dict[str, Any] = {}
        try:
            host = self.resolve_workspace_dir(agent_id, persist_if_missing=False)
        except Exception:
            return extra
        for rel in (Path(".octop") / "manifest.json", Path("manifest.json")):
            path = host / rel
            if not path.is_file():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                break
            if not isinstance(data, dict):
                break
            prompts = data.get("quick_prompts")
            extra["quick_prompts"] = prompts if isinstance(prompts, list) else []
            if not (row_description or "").strip():
                desc = data.get("description")
                if isinstance(desc, str | dict) and desc:
                    extra["description"] = desc
            break
        return extra

    def _connector_uid_for(
        self,
        row: AgentRow,
        *,
        connector_user_id: int | None = None,
    ) -> int | None:
        override = self._connector_user_override.get(row.agent_id)
        if override is not None:
            return override
        if connector_user_id is not None:
            return connector_user_id
        return row.user_id

    def _prepare_stream_request(self, agent_id: str, request: dict[str, Any]) -> dict[str, Any]:
        from happyclaw_harness.plugins import collect_plugin_tool_configs  # noqa: PLC0415

        req = dict(request)
        if req.get("agent_id") is None:
            req["agent_id"] = agent_id
        agent_cfg = self.get_config(agent_id)
        plugins_cfg = agent_cfg.get("plugins")
        tool_configs = collect_plugin_tool_configs(
            plugins_cfg if isinstance(plugins_cfg, dict) else None
        )
        if tool_configs:
            configurable = dict(req.get("configurable") or {})
            configurable["plugin_tool_configs"] = tool_configs
            req["configurable"] = configurable
        req = apply_agent_runtime_to_stream_request(req, agent_cfg)
        if dsh_skills_prompts_enabled():
            req = self._apply_dsh_skill_delta(agent_id, req)
        return req

    def _apply_dsh_skill_delta(self, agent_id: str, req: dict[str, Any]) -> dict[str, Any]:
        """Attach this turn's incremental DSH skill text, if the set changed.

        Pure bookkeeping over the per-agent snapshot cached at graph build time:
        no filesystem read happens per turn.
        """

        snapshot = self._dsh_skill_snapshots.get(agent_id)
        if snapshot is None:
            return req
        thread_id = str(req.get("thread_id") or "")
        text = self._dsh_prompt_sessions.advance(agent_id, thread_id, snapshot)
        if not text:
            return req
        configurable = dict(req.get("configurable") or {})
        configurable["dsh_skills_delta"] = text
        req["configurable"] = configurable
        return req

    def _stream_model_label(self, agent_id: str, request: dict[str, Any], thread_id: str) -> str:
        raw = request.get("model")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        cfg = request.get("configurable")
        if isinstance(cfg, dict):
            nested = cfg.get("model")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
        if thread_id:
            with suppress(Exception):
                override = self.get_thread_model(agent_id, thread_id)
                if override:
                    return override
        with suppress(Exception):
            row = self.get_row(agent_id)
            if row is not None and (row.default_model or "").strip():
                return str(row.default_model).strip()
        return ""

    def _build_harness_config(self, row: AgentRow) -> HarnessAgentConfig:
        """Convert an AgentRow into a HarnessAgentConfig."""
        from happyclaw_harness.middleware.bootstrap import bootstrap_marker_exists  # noqa: PLC0415

        from happyclaw.infra.agents.workspace.dir import (  # noqa: PLC0415
            harness_workspace_path,
            resolve_workspace_host_path,
            system_files_path_from_config,
        )

        cfg = self._agent_config_dict(row)
        raw = cfg.get("workspace_dir")
        stored = self._repos.agent_repo.get(row.agent_id) is not None
        if isinstance(raw, str) and raw.strip() and stored:
            # Host mkdir may remap an unwritable leftover (e.g. /root/.octop/…)
            # and persist the new path; re-read so harness gets that string.
            workspace_dir = self.resolve_workspace_dir(row.agent_id)
            persisted = self.get_config(row.agent_id)
            if persisted:
                cfg = persisted
            raw = cfg.get("workspace_dir")
            if isinstance(raw, str) and raw.strip():
                harness_workspace = harness_workspace_path(raw, cfg)
            else:
                harness_workspace = workspace_dir
        elif isinstance(raw, str) and raw.strip():
            # Unit tests pass an in-memory row that is not in the repo.
            harness_workspace = harness_workspace_path(raw, cfg)
            workspace_dir = resolve_workspace_host_path(raw, cfg)
            workspace_dir.mkdir(parents=True, exist_ok=True)
        else:
            # Legacy / incomplete row: backfill classic host workspace (also
            # lifts profile keys such as skill_package_ids into columns).
            workspace_dir = self.resolve_workspace_dir(row.agent_id)
            harness_workspace = workspace_dir
            persisted = self.get_config(row.agent_id)
            if persisted:
                cfg = persisted

        backend = self._backend_spec_for_row(row, cfg=cfg, workspace_dir=workspace_dir)
        ws = self._backend_workspace_for_row(
            row,
            cfg=cfg,
            workspace_dir=workspace_dir,
            allow_ephemeral_remote=self._spec_is_opensandbox(backend),
        )

        from happyclaw.infra.agents.teams import is_team_agent  # noqa: PLC0415

        team_host = is_team_agent(row)

        cron_tools: list[Any] | None = None
        if not team_host and self._cron_manager is not None:
            from happyclaw.infra.cron.tools import build_cronjob_tools  # noqa: PLC0415

            cron_tools = build_cronjob_tools(self._cron_manager)

        from happyclaw.infra.knowledge.tools import (  # noqa: PLC0415
            KnowledgeToolServices,
            build_knowledge_tools,
        )

        knowledge_tools: list[Any] = []
        if not team_host:
            knowledge_tools = build_knowledge_tools(KnowledgeToolServices(self))

        mobile_tools: list[Any] = []
        if not team_host and self._config.capabilities.mobile.enabled:
            from happyclaw.infra.control.mobile.tools import build_mobile_tools  # noqa: PLC0415

            def _mobile_workspace_for(agent_id: str) -> Any:
                # Prefer the running agent's workspace — authoritative for
                # docker / ephemeral remote sandboxes; ws is the start-time
                # fallback for the agent being configured here.
                if self._harness_manager is not None:
                    with suppress(Exception):
                        return self._harness_manager.get_agent(agent_id).agent.workspace
                return ws if agent_id == row.agent_id else None

            mobile_tools = build_mobile_tools(
                self._config,
                user_repo=self._repos.user_repo,
                workspace_for=_mobile_workspace_for,
            )

        from happyclaw_harness.plugins import PluginRegistry, build_plugin_tools  # noqa: PLC0415

        from happyclaw.infra.agents.plugins.plugin_tool_defaults import (  # noqa: PLC0415
            agent_plugin_enabled,
            expand_plugin_tools_default_on,
        )

        global_plugins = (
            self._plugin_manager.global_enabled_map() if self._plugin_manager is not None else {}
        )
        registered = [(reg.plugin_id, reg.name) for reg in PluginRegistry().all_tools()]
        agent_plugins = cfg.get("plugins")
        agent_plugins_map = agent_plugins if isinstance(agent_plugins, dict) else {}
        effective_plugins = dict(global_plugins)
        plugin_tools: list[Any] = []
        if not team_host:
            for plugin in PluginRegistry().list_plugins():
                if not agent_plugin_enabled(agent_plugins_map, plugin.manifest.id):
                    effective_plugins[plugin.manifest.id] = False
            mount_plugins = expand_plugin_tools_default_on(
                agent_plugins_map,
                registered_tools=registered,
                global_plugins=effective_plugins,
            )
            plugin_tools = build_plugin_tools(
                agent_plugins=mount_plugins,
                global_plugins=effective_plugins,
            )
        else:
            for plugin in PluginRegistry().list_plugins():
                effective_plugins[plugin.manifest.id] = False
        # Plugin authors may register tools with non-ASCII (e.g. Chinese) names,
        # which strict LLM tool-name APIs reject. Rewrite them to legal names
        # before binding, keeping the original in the description. Config keys
        # and the plugin-side closures still use the original names.
        from happyclaw.infra.agents.plugins.plugin_tool_names import (  # noqa: PLC0415
            extract_original_plugin_label,
            sanitize_plugin_tool_names,
        )

        sanitize_plugin_tool_names(
            plugin_tools,
            reserved={
                str(getattr(t, "name", ""))
                for t in [*(cron_tools or []), *knowledge_tools, *mobile_tools]
            },
        )
        self._plugin_tool_labels[row.agent_id] = {
            str(getattr(tool, "name", "")): label
            for tool in plugin_tools
            if (label := extract_original_plugin_label(str(getattr(tool, "description", "") or "")))
        }
        plugin_middleware = PluginRegistry().build_middleware_chain(
            global_enabled=effective_plugins
        )
        global_policy = self._security.harness_policy()
        agent_override = cfg.get("security") if isinstance(cfg.get("security"), dict) else None
        policy = SecurityPolicy.merge(global_policy, agent_override)

        from happyclaw.infra.agents.middleware.binary_read_guard import BinaryReadGuardMiddleware
        from happyclaw.infra.agents.middleware.browser_profile import BrowserProfileMiddleware
        from happyclaw.infra.agents.middleware.mcp_output_schema import (
            McpOutputSchemaMiddleware,
            harness_handles_mcp_tool_errors,
        )
        from happyclaw.infra.agents.middleware.octop_ui_offload import HappyclawUiOffloadMiddleware
        from happyclaw.infra.agents.middleware.reasoning import ReasoningRequestMiddleware
        from happyclaw.infra.agents.middleware.thread_artifacts import ThreadArtifactsMiddleware
        from happyclaw.infra.agents.middleware.token_quota import TokenQuotaMiddleware
        from happyclaw.infra.agents.middleware.workspace_image import (
            WorkspaceImageMaterializeMiddleware,
        )
        from happyclaw.infra.knowledge.hint import KnowledgeSearchHintMiddleware

        # FilesystemGuard + ModelSettings live in happyclaw-harness (auto-mounted).
        # BinaryReadGuard stays Octop-specific (inbound/attachment product policy).
        # ThreadArtifacts writes workspace paths onto threads after successful tools.
        # WorkspaceImageMaterialize expands path-only vision refs at model-call time.
        # HappyclawUiOffload stays innermost so every outer middleware observes the
        # slimmed content consistently; it only touches octop_ui plugin envelopes,
        # disjoint from the file-tool results ThreadArtifacts cares about.
        agent_middleware: list[Any] = [
            *plugin_middleware,
            TokenQuotaMiddleware(
                policy_repo=self._repos.user_policy_repo,
                usage_repo=self._repos.usage_repo,
            ),
            ReasoningRequestMiddleware(),
            KnowledgeSearchHintMiddleware(),
            BrowserProfileMiddleware(),
            BinaryReadGuardMiddleware(),
            *(() if harness_handles_mcp_tool_errors() else (McpOutputSchemaMiddleware(),)),
            WorkspaceImageMaterializeMiddleware(workspace=ws),
            ThreadArtifactsMiddleware(
                thread_repo=self._repos.thread_repo,
                workspace_dir=harness_workspace,
                agent_id=row.agent_id,
            ),
            HappyclawUiOffloadMiddleware(),
        ]
        if dsh_skills_prompts_enabled():
            # Only mounts when the opt-in flag is on, so the flag-off middleware
            # chain is byte-identical to before this integration existed.
            from happyclaw.infra.agents.middleware.dsh_skills_prompt import (
                DshSkillPromptMiddleware,
            )

            agent_middleware.append(DshSkillPromptMiddleware())

        merged_tools: list[Any] = []
        if cron_tools:
            merged_tools.extend(cron_tools)
        merged_tools.extend(knowledge_tools)
        merged_tools.extend(mobile_tools)
        merged_tools.extend(plugin_tools)
        # dsh:stage-tools — the only S2 insertion point. When the switch is off
        # this block neither imports the tools package nor touches the list.
        if dsh_stage_enabled("tools"):
            merged_tools.extend(self._dsh_plugin_tools(row, reserved=merged_tools))
        # agent_list / ask_agent: PeerAgentMiddleware (team_enabled=True), not config.tools.

        acp_section = cfg.get("acp")
        acp_raw: dict[str, Any] = acp_section if isinstance(acp_section, dict) else {}
        from happyclaw_harness.acp.models import ACPConfig

        if team_host:
            acp_raw = {}
            acp_config = ACPConfig.from_dict({"runners": {}})
        else:
            acp_user_id = row.user_id
            if acp_user_id is None:
                acp_user_id = self._connector_user_override.get(row.agent_id)
            runners_dict = (
                self._acp_settings.load_runners(acp_user_id) if acp_user_id is not None else {}
            )
            acp_config = ACPConfig.from_dict({"runners": runners_dict})

        system_prompt = row.system_prompt
        memory: tuple[str, ...] | None = None
        if not team_host and not bootstrap_marker_exists(ws):
            system_prompt = None
            memory = ()

        if dsh_skills_prompts_enabled() and not team_host and system_prompt:
            # Opt-in: fold the deterministic DSH skills section into the graph
            # prompt. Flag off keeps the exact previous string and reads nothing.
            snapshot = workspace_skill_snapshot(workspace_dir, agent_id=row.agent_id)
            self._dsh_skill_snapshots[row.agent_id] = snapshot
            system_prompt = compose_system_prompt(system_prompt, snapshot)

        mcp_server_configs: dict[str, Any] = {}
        if not team_host:
            uid = self._connector_uid_for(row)
            if uid is not None:
                mcp_server_configs = build_mcp_server_configs_for_user(
                    svc=self._connector_svc,
                    connector_repo=self._repos.connector_repo,
                    user_id=uid,
                    agent_id=row.agent_id,
                    agent_user_id=row.user_id,
                    config=self._config,
                )
            elif row.user_id is None:
                logger.warning(
                    "_build_harness_config agent=%s agent.user_id=NULL and no "
                    "connector_user_override — mcp_server_configs will be empty "
                    "(shared agent needs chat user id)",
                    row.agent_id,
                )

            from happyclaw.infra.utils.env_file import (  # noqa: PLC0415
                env_file_path,
                load_env_file,
                overlay_stdio_mcp_configs,
            )

            mcp_server_configs = overlay_stdio_mcp_configs(
                mcp_server_configs,
                load_env_file(env_file_path(self._paths.root)),
            )

        skill_dirs: list[str] = []
        plugin_skills_disabled: set[str] = set()
        if not team_host:
            configured_skill_dirs = self._normalize_skills_dir_config(cfg.get("skills"))
            package_skill_dirs = (
                self._resolve_skill_package_dirs(row.agent_id)
                if self._backend_supports_host_skill_packages(
                    backend,
                    workspace_dir=workspace_dir,
                )
                else []
            )
            skill_dirs = configured_skill_dirs + package_skill_dirs
            if self._plugin_manager is not None:
                for plugin_item in self._plugin_manager.list_installed():
                    plugin_id = str(plugin_item.get("id") or "")
                    if plugin_id and (
                        plugin_item.get("enabled", True) is False
                        or not agent_plugin_enabled(agent_plugins_map, plugin_id)
                    ):
                        plugin_skills_disabled.update(
                            self._plugin_manager.plugin_skill_names(plugin_id)
                        )

        from happyclaw.infra.agents.workspace.execute_env import (
            inject_agent_execute_env,  # noqa: PLC0415
        )

        backend = inject_agent_execute_env(
            self._prepare_docker_backend(backend, row),
            paths=self._paths,
            row=row,
            workspace_dir=workspace_dir,
            cfg=cfg,
        )
        # OpenSandbox.create is not idempotent — reuse the instance already
        # wrapped by ``ws`` so start does not spawn a second remote sandbox.
        # The same reuse applies when the workspace wrap adapted an older
        # read/ls surface (S3 / Postgres / COS / …) to ReadResult/LsResult.
        from happyclaw.infra.backend.compat import (  # noqa: PLC0415
            is_adapted_backend,
            is_remote_backend_spec,
        )

        harness_backend: Any = (
            ws.backend
            if (
                self._spec_is_opensandbox(backend)
                or is_adapted_backend(ws.backend)
                or is_remote_backend_spec(backend)
            )
            else backend
        )

        harness_fields: dict[str, Any] = {}
        if "decision" in _HARNESS_AGENT_CONFIG_FIELDS:
            harness_fields["decision"] = self._decision.harness_config()

        harness_cfg = HarnessAgentConfig(
            name=_memory_namespace(row.agent_id),
            workspace_dir=harness_workspace,
            system_files_path=system_files_path_from_config(cfg),
            # Owner's stored locale only. Per-message language would change
            # the cached system prefix on every switch.
            language=resolve_user_locale(
                user_repo=self._repos.user_repo,
                user_id=row.user_id or 0,
            ),
            # Memory aux LLM (extraction / promotion) needs a concrete ref; fall
            # back to the same resolution AUTO chat routing uses (active model
            # first, else first usable) — so promotion works whenever chat does.
            # Per-turn AUTO routing is unaffected: the gateway resolves models via
            # ``resolve_explicit_default_model`` directly.
            default_model=(
                self._providers.resolve_explicit_default_model(row, cfg)
                or self._resolve_configured_fallback_model_ref()
            ),
            system_prompt=system_prompt,
            memory=memory,
            backend=harness_backend,  # spec, or live OpenSandbox instance
            mcp_server_configs=mcp_server_configs,
            tools=merged_tools or None,
            middleware=agent_middleware or None,
            bootstrap_enabled=not team_host,
            acp_runners=acp_config.runners,
            acp_delegate_enabled=bool(acp_raw.get("tool_enabled", False)),
            skills_disabled=frozenset(skills_disabled_set(cfg) | plugin_skills_disabled),
            skills_dir=skill_dirs or None,
            default_timezone=self._config.default_timezone,
            media_generation=self._media_generation.harness_config(),
            **harness_fields,
            **_memory_extract_settings(cfg, is_ref_usable=self._providers.is_model_ref_usable),
            **_resolve_memory_backend_kwargs(cfg, workspace_dir=workspace_dir, config=self._config),
        )
        if "tools_disabled" in _HARNESS_AGENT_CONFIG_FIELDS:
            from happyclaw.infra.agents.settings.tool_catalog import effective_tools_disabled
            from happyclaw.infra.agents.teams import host_tools_disabled

            disabled = effective_tools_disabled(
                cfg,
                registered_plugin_tools=registered,
                global_plugins=global_plugins,
            )
            if team_host:
                disabled = set(host_tools_disabled(disabled))
            harness_cfg.tools_disabled = frozenset(disabled)
        applied = policy.apply_to_config(harness_cfg)
        applied = self._apply_team_host_config(applied, row)
        applied = self._merge_agently_write_interrupts(
            applied, self._connector_uid_for(row) if not team_host else None
        )
        interrupt_on = apply_session_bypass(applied.interrupt_on, self._hitl_session_store)
        if interrupt_on is not applied.interrupt_on:
            applied = replace(applied, interrupt_on=interrupt_on)
        if applied.model_retry_enabled:
            factory = (
                self._harness_manager.shared_factory if self._harness_manager is not None else None
            )
            get_chat_model = getattr(factory, "get_chat_model", None)
            if callable(get_chat_model):
                from happyclaw.infra.agents.middleware.model_failover import (
                    SafeModelFailoverMiddleware,
                )

                retry_middleware: Any = SafeModelFailoverMiddleware(
                    health=self._model_health,
                    candidates=lambda _current_ref, needs_multimodal: (
                        self._providers.list_auto_route_candidates(
                            needs_multimodal=needs_multimodal
                        )
                    ),
                    model_for_ref=get_chat_model,
                    max_retries=applied.model_retry_max_retries,
                    initial_delay=applied.model_retry_initial_delay,
                    max_delay=applied.model_retry_max_delay,
                    on_failure="error",
                )
            else:
                from langchain.agents.middleware import ModelRetryMiddleware

                retry_middleware = ModelRetryMiddleware(
                    max_retries=applied.model_retry_max_retries,
                    initial_delay=applied.model_retry_initial_delay,
                    max_delay=applied.model_retry_max_delay,
                    on_failure="error",
                )

            applied = replace(
                applied,
                model_retry_enabled=False,
                middleware=[
                    retry_middleware,
                    *(applied.middleware or []),
                ],
            )
        self._tool_guard_rules.ensure_seeded()
        return replace(
            applied,
            tool_guard_rules_dir=str(self._tool_guard_rules.rules_dir),
        )

    def _install_team_host_dispatch(self) -> None:
        """Team hosts always enqueue inbox work, even on harness 1.0.8 (default sync)."""
        from happyclaw.infra.agents.teams import is_team_agent
        from happyclaw.infra.agents.teams.team_manager import wire_host_dispatch

        team = getattr(self._harness_manager, "team", None)
        if team is None:
            return
        proc = self._team_processor
        room = getattr(proc, "teams", proc)
        installer = getattr(room, "install_host_dispatch", None)
        if callable(installer):
            installer(team)
            return
        wire_host_dispatch(
            team,
            is_team=lambda agent_id: is_team_agent(self.get_row(agent_id)),
            stream_peer=getattr(room, "stream_peer_to_room", None)
            or getattr(proc, "stream_team_peer_to_room", None),
            stream_host=getattr(room, "stream_host_followup_to_room", None),
            take_prompt=getattr(room, "take_peer_prompt", None)
            or getattr(proc, "take_team_peer_prompt", None),
        )

    def _agently_write_interrupts(self, user_id: int | None) -> dict[str, Any]:
        from happyclaw.infra.connectors.gateway.adapters.agently_cli import write_interrupt_on

        if user_id is None:
            return {}
        if not self._repos.connector_repo.connector_feature_allows(user_id):
            return {}
        return write_interrupt_on(
            [
                inst.mcp_server_name
                for inst in self._repos.connector_repo.list_visible(user_id)
                if inst.kind == "agently-cli" and inst.status == "active"
            ]
        )

    def _merge_agently_write_interrupts(
        self, cfg: HarnessAgentConfig, user_id: int | None
    ) -> HarnessAgentConfig:
        extra = self._agently_write_interrupts(user_id)
        if not extra:
            return cfg
        return replace(cfg, interrupt_on={**(cfg.interrupt_on or {}), **extra})

    def _apply_team_host_config(self, cfg: HarnessAgentConfig, row: Any) -> HarnessAgentConfig:
        from happyclaw.infra.agents.teams import (
            host_system_prompt,
            host_tools_disabled,
            is_team_agent,
        )

        if not is_team_agent(row):
            if "peer_invoke_mode" in _HARNESS_AGENT_CONFIG_FIELDS:
                return replace(cfg, peer_invoke_mode="sync")
            return cfg
        updates: dict[str, Any] = {}
        if "tools_disabled" in _HARNESS_AGENT_CONFIG_FIELDS:
            updates["tools_disabled"] = host_tools_disabled(
                frozenset(getattr(cfg, "tools_disabled", ()) or ())
            )
        if "team_peers" in _HARNESS_AGENT_CONFIG_FIELDS:
            updates["team_peers"] = tuple(self._teams.member_ids(row.agent_id))
        if "peer_invoke_mode" in _HARNESS_AGENT_CONFIG_FIELDS:
            updates["peer_invoke_mode"] = "async"
        if "mcp_server_configs" in _HARNESS_AGENT_CONFIG_FIELDS:
            updates["mcp_server_configs"] = {}
        if "skills_dir" in _HARNESS_AGENT_CONFIG_FIELDS:
            updates["skills_dir"] = None
        if "tools" in _HARNESS_AGENT_CONFIG_FIELDS:
            updates["tools"] = None
        if "subagents_auto_load" in _HARNESS_AGENT_CONFIG_FIELDS:
            updates["subagents_auto_load"] = False
        if "bootstrap_enabled" in _HARNESS_AGENT_CONFIG_FIELDS:
            updates["bootstrap_enabled"] = False
        if "system_prompt" in _HARNESS_AGENT_CONFIG_FIELDS:
            updates["system_prompt"] = host_system_prompt(row, self._repos.user_repo)
        return replace(cfg, **updates) if updates else cfg
