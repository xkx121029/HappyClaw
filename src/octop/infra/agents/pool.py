"""Pooled harness runtimes — one instance per (expert, project directory)."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
import time
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from octop.infra.agents.manager_base import AgentManagerBase
from octop.infra.agents.plugins.mcp_bind import clamp_bound_mcp_tool_names
from octop.infra.connectors.builder import inject_missing_gateway_tools
from octop.infra.errors import ErrorCode, OctopError

if TYPE_CHECKING:
    from octop_harness import HarnessAgent, HarnessAgentConfig

    from octop.infra.db.repos.agents import AgentRow

logger = logging.getLogger(__name__)

# Pooled project runtimes are released after this much inactivity.
_POOL_IDLE_TTL_S = 30 * 60.0

# Expert context files the harness memory middleware reads from the active
# workspace. Pooled runtimes work in a project/session directory, so those
# files must be copied there or the model loses the expert's persona.
_POOLED_CONTEXT_FILES = (
    "AGENTS.md",
    "SOUL.md",
    "IDENTITY.md",
    "MEMORY.md",
    "USER.md",
    "PROACTIVE.md",
)


def _norm_path(path: Path | str) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _same_path(left: Path | str, right: Path | str) -> bool:
    return _norm_path(left) == _norm_path(right)


class AgentPoolMixin(AgentManagerBase):
    """Project workspaces — pooled instances per (agent, directory)."""

    def thread_workspace_path(self, agent_id: str, thread_id: str) -> Path | None:
        """Directory a conversation works in, or None when it has none yet.

        Returns None when the resolved path equals the expert's own workspace or
        the directory is not materialized (creating dirs is a P2 concern).
        """
        if not thread_id:
            return None
        try:
            thread = self._repos.thread_repo.get(thread_id)
        except Exception:  # pragma: no cover - defensive for old schemas
            return None
        if thread is None or thread.agent_id != agent_id:
            return None
        from octop.infra.projects.workspace import resolve_thread_workspace  # noqa: PLC0415

        resolved = resolve_thread_workspace(
            thread=cast("Any", thread),
            project_repo=self._repos.project_repo,
            paths=self._paths,
        )
        if resolved.path is None or not resolved.path.is_dir():
            return None
        base = self.resolve_workspace_dir(agent_id)
        if _same_path(resolved.path, base):
            return None
        return resolved.path

    def pooled_agent_id(self, agent_id: str, workspace: Path) -> str:
        digest = hashlib.sha1(str(workspace).encode("utf-8")).hexdigest()[:10]  # noqa: S324
        return f"{agent_id}~{digest}"

    async def _dispatch_agent_id(self, agent_id: str, thread_id: str) -> str:
        """Registry id to run this turn under: base agent or a pooled instance."""
        if self._harness_manager is None:
            return agent_id
        workspace = self.thread_workspace_path(agent_id, thread_id)
        if workspace is None:
            return agent_id
        key = _norm_path(workspace)
        pooled = self._workspace_pool.get(agent_id, {}).get(key)
        if pooled and self._octop_harness_or_none(pooled) is not None:
            self._pool_last_used[pooled] = time.monotonic()
            return pooled
        return await self._ensure_pooled_instance(agent_id, workspace)

    def _seed_pooled_workspace(self, agent_id: str, workspace: Path) -> None:
        """Copy expert context files into a fresh conversation directory.

        Memory middleware resolves ``AGENTS.md`` / ``SOUL.md`` / ``USER.md`` /
        ``MEMORY.md`` inside the *active* workspace. A new project or session
        directory has only the built-in templates, so without this copy the
        expert's persona never reaches the model. Existing conversation files
        win: a project may legitimately ship its own ``AGENTS.md``.
        """
        base = self.resolve_workspace_dir(agent_id)
        if _same_path(base, workspace) or not base.is_dir():
            return
        for name in _POOLED_CONTEXT_FILES:
            source = base / name
            target = workspace / name
            if not source.is_file() or target.exists():
                continue
            with suppress(OSError):
                shutil.copy2(source, target)

    async def _ensure_pooled_instance(self, agent_id: str, workspace: Path) -> str:
        assert self._harness_manager is not None
        key = _norm_path(workspace)
        pooled = self.pooled_agent_id(agent_id, workspace)
        async with self._lifecycle_lock_for(agent_id):
            existing = self._octop_harness_or_none(pooled)
            if existing is not None:
                self._workspace_pool.setdefault(agent_id, {})[key] = pooled
                self._pool_workspaces[pooled] = str(workspace)
                self._pool_last_used[pooled] = time.monotonic()
                return pooled
            await self._acquire_pool_slot(agent_id)
            row = self.get_row(agent_id)
            if row is None:
                return agent_id
            self._seed_pooled_workspace(agent_id, workspace)
            cfg = self._build_harness_config(row, workspace_override=workspace)
            entry = await self._harness_manager.acreate_agent(
                cfg,
                agent_id=pooled,
                metadata={"parent_agent_id": agent_id, "workspace": str(workspace)},
                tags=["pooled"],
                init_workspace=True,
            )
            await self._wire_pooled_agent(row, entry.agent, cfg)
            self._workspace_pool.setdefault(agent_id, {})[key] = pooled
            self._pool_workspaces[pooled] = str(workspace)
            self._pool_last_used[pooled] = time.monotonic()
            logger.info(
                "Agent %s: pooled runtime for workspace %s (%s)",
                agent_id,
                workspace,
                pooled,
            )
            return pooled

    async def _wire_pooled_agent(
        self, row: AgentRow, agent: HarnessAgent, cfg: HarnessAgentConfig
    ) -> None:
        """Per-instance wiring that must not touch the base agent's callbacks."""
        uid = self._connector_uid_for(row)
        if uid is not None:
            inject_missing_gateway_tools(
                agent,
                svc=self._connector_svc,
                connector_repo=self._repos.connector_repo,
                user_id=uid,
                agent_id=row.agent_id,
                mcp_server_configs=cfg.mcp_server_configs,
            )
        clamp_bound_mcp_tool_names(agent)
        ws = agent.workspace
        with suppress(Exception):
            from octop.infra.agents.builtin_skills import (  # noqa: PLC0415
                sync_octop_builtin_skills,
            )

            await sync_octop_builtin_skills(ws)
        if self._plugin_manager is not None:
            with suppress(Exception):
                await asyncio.to_thread(
                    self._plugin_manager.sync_skills_to_workspace,
                    ws,
                    agent_plugins=self.get_config(row.agent_id).get("plugins"),
                )

    async def _release_pool_for_agent(self, agent_id: str) -> None:
        """Drop every pooled runtime of an expert (delete / full stop)."""
        pooled_ids = list(self._workspace_pool.pop(agent_id, {}).values())
        for pooled in pooled_ids:
            self._pool_last_used.pop(pooled, None)
            self._pool_workspaces.pop(pooled, None)
            if self._harness_manager is not None:
                with suppress(Exception):
                    await self._harness_manager.aremove_agent(pooled)
            logger.info("Released pooled runtime %s for agent %s", pooled, agent_id)

    async def _acquire_pool_slot(self, agent_id: str) -> None:
        """Wait for runtime capacity; raise AGENT_BUSY after the queue timeout."""
        limit_total = max(1, int(getattr(self._config, "project_runtime_max_instances", 6)))
        limit_agent = max(1, int(getattr(self._config, "project_runtime_per_agent", 2)))
        timeout = float(getattr(self._config, "project_runtime_queue_timeout_s", 120.0))
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            await self._release_idle_pool()
            total = len(self._pool_last_used)
            per_agent = len(self._workspace_pool.get(agent_id, {}))
            if total < limit_total and per_agent < limit_agent:
                return
            if loop.time() >= deadline:
                logger.warning(
                    "Project runtime capacity reached: %d/%d total, %d/%d for %s",
                    total,
                    limit_total,
                    per_agent,
                    limit_agent,
                    agent_id,
                )
                raise OctopError.localized(ErrorCode.AGENT_BUSY)
            await asyncio.sleep(0.5)

    async def _finalize_session_workspace(self, agent_id: str, thread_id: str) -> None:
        """Bind ``sessions/<thread_id>`` after its first user file was written."""
        # ``getattr`` keeps partially constructed managers (tests) working.
        middleware = getattr(self, "_session_workspace_mw", {}).get(agent_id)
        if middleware is None or not thread_id:
            return
        written = middleware.take(thread_id)
        if not written:
            return
        from octop.infra.projects.session import bind_session_workspace  # noqa: PLC0415

        try:
            await asyncio.to_thread(
                bind_session_workspace,
                thread_repo=cast("Any", self._repos.thread_repo),
                paths=self._paths,
                thread_id=thread_id,
                workspace_dir=self.resolve_workspace_dir(agent_id),
                written=written,
            )
        except Exception:
            logger.warning("Failed to enable session workspace for %s", thread_id, exc_info=True)

    async def _release_idle_pool(self) -> None:
        """Drop pooled instances idle longer than the TTL (~30 min)."""
        if self._harness_manager is None:
            return
        now = time.monotonic()
        expired = [
            pooled for pooled, used in self._pool_last_used.items() if now - used > _POOL_IDLE_TTL_S
        ]
        for pooled in expired:
            parent = self._pool_workspaces.pop(pooled, None)
            self._pool_last_used.pop(pooled, None)
            for key, value in list(self._workspace_pool.items()):
                for workspace_key, candidate in list(value.items()):
                    if candidate == pooled:
                        del value[workspace_key]
                if not value:
                    self._workspace_pool.pop(key, None)
            with suppress(Exception):
                await self._harness_manager.aremove_agent(pooled)
            logger.info("Released idle pooled runtime %s (%s)", pooled, parent)


__all__ = ["AgentPoolMixin", "_norm_path", "_same_path"]
