"""Attribute contract shared by the AgentManager mixins."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from octop_harness import HarnessAgent, HarnessAgentConfig, HarnessAgentManager

    from octop.config import OctopConfig
    from octop.infra.agents.plugins.manager import PluginManager
    from octop.infra.connectors.service import ConnectorService
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
    # Pooled harness instances: one per (expert, project directory).
    _workspace_pool: dict[str, dict[str, str]]
    _pool_workspaces: dict[str, str]
    _pool_last_used: dict[str, float]
    _session_workspace_mw: dict[str, Any]

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


__all__ = ["AgentManagerBase"]
