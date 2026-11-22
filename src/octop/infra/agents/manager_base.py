"""Attribute contract shared by the AgentManager mixins."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

    from octop_harness import HarnessAgent, HarnessAgentConfig, HarnessAgentManager

    from octop.config import OctopConfig
    from octop.infra.agents.plugins.manager import PluginManager
    from octop.infra.agents.providers import ProviderStore
    from octop.infra.agents.providers.health import ModelHealthRegistry
    from octop.infra.agents.security import SecuritySettingsStore, ToolGuardRulesStore
    from octop.infra.agents.security.hitl_session import HitlSessionPolicyStore
    from octop.infra.agents.settings.acp import ACPSettingsStore
    from octop.infra.agents.settings.decision import DecisionSettingsStore
    from octop.infra.agents.settings.media_generation import MediaGenerationSettingsStore
    from octop.infra.connectors.service import ConnectorService
    from octop.infra.cron.manager import CronManager
    from octop.infra.db.repos.agents import AgentRow
    from octop.infra.db.services import RepoBundle
    from octop.infra.utils.paths import PathLayout


class AgentManagerBase:
    """Declares the state :class:`~octop.infra.agents.manager.AgentManager` owns.

    Cross-mixin calls are declared here as stubs so each mixin type-checks on
    its own; the mixins themselves supply the implementations and win in MRO.
    """

    _repos: RepoBundle
    _paths: PathLayout
    _config: OctopConfig
    _harness_manager: HarnessAgentManager | None
    _plugin_manager: PluginManager | None
    _connector_svc: ConnectorService
    _providers: ProviderStore
    _model_health: ModelHealthRegistry
    _tool_guard_rules: ToolGuardRulesStore
    _hitl_session_store: HitlSessionPolicyStore | None
    _security: SecuritySettingsStore
    _acp_settings: ACPSettingsStore
    _decision: DecisionSettingsStore
    _media_generation: MediaGenerationSettingsStore
    _cron_manager: CronManager | None
    _connector_user_override: dict[str, int]
    _plugin_tool_labels: dict[str, dict[str, str]]
    # Pooled harness instances: one per (expert, project directory).
    _workspace_pool: dict[str, dict[str, str]]
    _pool_workspaces: dict[str, str]
    _pool_last_used: dict[str, float]
    _session_workspace_mw: dict[str, Any]

    # Invocation tracking + store reclaim state.
    _active_invocations: dict[str, int]
    _invocation_waiters: dict[str, int]
    _history_backfills: dict[str, asyncio.Event]
    _reclaim_pending: set[str]
    _reclaim_holds: dict[str, asyncio.Event]
    _reclaim_task: asyncio.Task[None] | None
    _reclaim_sweep_task: asyncio.Task[None] | None
    _reclaim_wake: asyncio.Event | None

    # -- base implementation (AgentManager)

    def resolve_workspace_dir(self, agent_id: str, *, persist_if_missing: bool = True) -> Path:
        raise NotImplementedError

    def _octop_harness_or_none(self, agent_id: str) -> HarnessAgent | None:
        raise NotImplementedError

    def _lifecycle_lock_for(self, agent_id: str) -> asyncio.Lock:
        raise NotImplementedError

    def get_row(self, agent_id: str) -> AgentRow | None:
        raise NotImplementedError

    def get_config(self, agent_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def _build_harness_config(
        self, row: AgentRow, *, workspace_override: Path | None = None
    ) -> HarnessAgentConfig:
        raise NotImplementedError

    def _connector_uid_for(
        self,
        row: AgentRow,
        *,
        connector_user_id: int | None = None,
    ) -> int | None:
        raise NotImplementedError

    def _dsh(self) -> Any:
        raise NotImplementedError

    def get_agent(self, agent_id: str) -> HarnessAgent:
        raise NotImplementedError

    def _agent_config_dict(self, row: AgentRow) -> dict[str, Any]:
        raise NotImplementedError

    def is_agent_active(self, agent_id: str) -> bool:
        raise NotImplementedError

    def _backend_spec_for_row(
        self,
        row: AgentRow,
        *,
        cfg: dict[str, Any] | None = None,
        workspace_dir: Path | None = None,
    ) -> Any:
        raise NotImplementedError

    def _merge_agently_write_interrupts(
        self, cfg: HarnessAgentConfig, user_id: int | None
    ) -> HarnessAgentConfig:
        raise NotImplementedError

    def _apply_team_host_config(self, cfg: HarnessAgentConfig, row: Any) -> HarnessAgentConfig:
        raise NotImplementedError

    def _backend_workspace_for_row(
        self,
        row: AgentRow,
        *,
        cfg: dict[str, Any] | None = None,
        workspace_dir: Path | None = None,
        allow_ephemeral_remote: bool = False,
    ) -> Any:
        raise NotImplementedError

    def _prepare_docker_backend(self, backend: Any, row: AgentRow) -> Any:
        raise NotImplementedError

    def _spec_is_opensandbox(self, spec: Any) -> bool:
        raise NotImplementedError

    def _resolve_configured_fallback_model_ref(self) -> str | None:
        raise NotImplementedError

    def _dsh_plugin_tools(self, row: Any, *, reserved: Sequence[Any]) -> list[Any]:
        raise NotImplementedError

    def _resolve_skill_package_dirs(self, agent_id: str) -> list[str]:
        raise NotImplementedError

    def _normalize_skills_dir_config(self, value: Any) -> list[str]:
        raise NotImplementedError

    def _backend_supports_host_skill_packages(
        self, spec: Any, *, workspace_dir: Path | None = None
    ) -> bool:
        raise NotImplementedError


__all__ = ["AgentManagerBase"]
