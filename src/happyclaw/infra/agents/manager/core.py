"""AgentManager construction, wiring, boot and shutdown."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import (
    TYPE_CHECKING,
    Any,
)

from happyclaw_harness import HarnessAgentManager

from happyclaw.i18n.domains.agents import AGENT_START_TIMEOUT
from happyclaw.infra.agents.manager.base import AgentManagerBase
from happyclaw.infra.agents.manager.config import ConfigMixin
from happyclaw.infra.agents.manager.crud import CrudMixin
from happyclaw.infra.agents.manager.dsh import DshMixin
from happyclaw.infra.agents.manager.harness_config import HarnessConfigMixin
from happyclaw.infra.agents.manager.mcp import McpMixin
from happyclaw.infra.agents.manager.memory import MemoryMixin
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
from happyclaw.infra.agents.security.hitl_session import HitlSessionPolicyStore
from happyclaw.infra.agents.settings.acp import ACPSettingsStore
from happyclaw.infra.agents.settings.decision import DecisionSettingsStore
from happyclaw.infra.agents.settings.langfuse import LangfuseSettingsStore
from happyclaw.infra.agents.settings.media_generation import MediaGenerationSettingsStore
from happyclaw.infra.connectors.service import ConnectorService
from happyclaw.infra.dsh.integration import DshPromptSessionStore
from happyclaw.infra.dsh.prompts.skills_injection import SkillPromptSnapshot

if TYPE_CHECKING:
    from happyclaw.config import HappyclawConfig
    from happyclaw.infra.agents.experts.catalog import ExpertCatalog
    from happyclaw.infra.agents.plugins.manager import PluginManager
    from happyclaw.infra.cron.manager import CronManager
    from happyclaw.infra.db.services import RepoBundle
    from happyclaw.infra.proactive.scheduler import ProactiveCareScheduler
    from happyclaw.infra.utils.paths import PathLayout

logger = logging.getLogger(__name__)

# One hung remote backend must not block ``octop run`` from serving HTTP.
_AGENT_BOOT_START_TIMEOUT = 60.0


class AgentManager(HarnessConfigMixin, SkillsMixin, StartupMixin, ConfigMixin, McpMixin, ReloadMixin, StoreReclaimMixin, RuntimeMixin, QueriesMixin, CrudMixin, DshMixin, MemoryMixin, AgentManagerBase):
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
  - Settings stores: langfuse, security, acp_settings, tool_guard_rules, providers"""


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
