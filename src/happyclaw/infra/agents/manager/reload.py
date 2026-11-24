"""Hot reload of harness agents after config or provider changes."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from happyclaw.i18n.domains.agents import format_agent_start_error
from happyclaw.infra.agents.manager.base import AgentManagerBase
from happyclaw.infra.agents.providers import sync_providers_to_harness

if TYPE_CHECKING:
    from happyclaw.infra.db.repos.agents import AgentRow

logger = logging.getLogger(__name__)

# Bounded parallelism for awaited provider/active-model reload batches.
_PROVIDER_RELOAD_CONCURRENCY = 6


_AGENT_STATES_NEEDING_MODEL_RELOAD = frozenset({"failed", "created"})


class ReloadMixin(AgentManagerBase):
    """Hot reload of harness agents after config or provider changes."""

    async def reload(self, agent_id: str) -> None:
        """Rebuild harness runtime for one agent (e.g. after plugin install)."""
        await self._reload_agent(agent_id)

    async def reload_all(self) -> None:
        """Rebuild harness runtime for every enabled agent (bounded parallel)."""
        agent_ids = [
            row.agent_id for row in self._repos.agent_repo.list_all(include_disabled=False)
        ]
        await self._reload_agents(agent_ids)

    def reload_happyclaw_harness(self) -> None:
        """Rebuild harness agents in place (e.g. after tool-guard rules changed on disk).

        Does not rebuild Octop-side agent config from the DB — use :meth:`reload` for that.
        """
        if self._harness_manager is not None:
            self._harness_manager.rebuild_all_agents()

    def _agent_uses_auto_default(self, row: AgentRow) -> bool:
        cfg = self.get_config(row.agent_id)
        return self._providers.resolve_explicit_default_model(row, cfg) is None

    def _provider_reload_impact_ids(
        self,
        *,
        provider_name: str | None = None,
        active_model_changed: bool = False,
    ) -> list[str]:
        """Agent IDs that must be rebuilt after a provider / active-model change.

        AUTO agents bake a resolved fallback model ref into their harness config
        at build time (active model first, else first usable) and that ref is
        invisible to the DB config scan, so a provider change can strand it
        (#2388). An AUTO agent is rebuilt when the active model changed or,
        for a named provider change, when its baked ref points at that provider
        or no longer matches what a build would resolve now. Explicit refs to
        other providers are left alone.
        """
        rows = self._repos.agent_repo.list_all(include_disabled=False)
        if provider_name is None and not active_model_changed:
            return [row.agent_id for row in rows]

        enabled_ids = {row.agent_id for row in rows}
        auto_ids = {row.agent_id for row in rows if self._agent_uses_auto_default(row)}
        impact: set[str] = set()
        for row in rows:
            if row.last_state in _AGENT_STATES_NEEDING_MODEL_RELOAD or (
                active_model_changed and row.agent_id in auto_ids
            ):
                impact.add(row.agent_id)

        if provider_name:
            for ref in self.find_agents_using_provider(provider_name):
                aid = ref.get("agent_id")
                if isinstance(aid, str) and aid in enabled_ids:
                    impact.add(aid)
            impact.update(
                self._stale_auto_default_ids(
                    provider_name=provider_name,
                    enabled_ids=enabled_ids,
                    auto_ids=auto_ids,
                )
            )

        return sorted(impact)

    def _stale_auto_default_ids(
        self,
        *,
        provider_name: str,
        enabled_ids: set[str],
        auto_ids: set[str],
    ) -> set[str]:
        """AUTO agents whose baked fallback ref went stale after a provider change.

        The DB config only shows AUTO, so read the built harness configs:
        rebuild when the baked ref points at the changed provider or differs
        from what a build would resolve now. An agent built while no model was
        usable has no baked ref at all, so it is rebuilt as soon as a fallback
        exists — otherwise it would keep running without a model until restart.
        """
        if self._harness_manager is None or not auto_ids:
            return set()
        new_fallback = self._resolve_configured_fallback_model_ref()
        prefix = f"{provider_name}/"
        stale: set[str] = set()
        for entry in self._harness_manager.list_agents():
            aid = getattr(entry, "agent_id", None)
            if not isinstance(aid, str) or aid not in auto_ids:
                continue
            built = getattr(getattr(entry, "config", None), "default_model", None)
            if not isinstance(built, str) or not built:
                if new_fallback is not None:
                    stale.add(aid)
                continue
            if built.startswith(prefix) or (new_fallback is not None and built != new_fallback):
                stale.add(aid)
        return stale & enabled_ids

    async def _reload_agents(self, agent_ids: list[str]) -> None:
        """Reload agents concurrently with a fixed concurrency cap."""
        if not agent_ids:
            return
        sem = asyncio.Semaphore(_PROVIDER_RELOAD_CONCURRENCY)

        async def _one(agent_id: str) -> None:
            async with sem:
                try:
                    await self._reload_agent(agent_id)
                except Exception:
                    logger.exception("Parallel reload failed for agent %s", agent_id)

        await asyncio.gather(*(_one(agent_id) for agent_id in agent_ids))

    async def on_provider_changed(
        self,
        *,
        provider_name: str | None = None,
        active_model_changed: bool = False,
    ) -> None:
        """Sync harness factory from DB, then reload impacted agents (awaited).

        When *provider_name* or *active_model_changed* is set, only the impact set
        is rebuilt. With neither set (backup restore, OAuth, unknown), all enabled
        agents are rebuilt in parallel.
        """
        if self._harness_manager is None:
            return
        providers = self._providers.build_harness_configs()
        self._host_models.sync(providers)
        sync_providers_to_harness(
            self._harness_manager,
            providers,
            shared_factory=self._harness_manager.shared_factory,
        )
        if self._harness_manager.shared_factory is None:
            return
        await self._reload_agents(
            self._provider_reload_impact_ids(
                provider_name=provider_name,
                active_model_changed=active_model_changed,
            )
        )

    async def _reload_agent(self, agent_id: str) -> None:
        assert self._harness_manager is not None
        async with self._lifecycle_lock_for(agent_id):
            self._bootstrap_graph_refresh_pending.discard(agent_id)
            row = self._repos.agent_repo.get(agent_id)
            if not row or not row.enabled or row.last_state == "stopped":
                await asyncio.to_thread(self._quiesce_happyclaw_memory, agent_id)
                await self._harness_manager.aremove_agent(agent_id)
                return
            if self._harness_manager.shared_factory is None:
                return
            try:
                cfg, metadata, tags, user_display = self._agent_runtime_bundle(row)
                entry = await self._harness_manager.arebuild_agent(
                    agent_id,
                    cfg,
                    metadata=metadata,
                    tags=tags,
                )
                await self._post_start_agent(row, entry.agent, cfg, user_display=user_display)
                self._repos.agent_repo.set_state(agent_id, "running", error=None)
            except Exception as exc:
                recovered = self._happyclaw_harness_or_none(agent_id)
                if recovered is not None and self._is_already_registered_error(exc):
                    self._repos.agent_repo.set_state(agent_id, "running", error=None)
                    logger.warning(
                        "Agent %s reload raced; keeping existing registry entry",
                        agent_id,
                    )
                    return
                logger.exception("Background reload failed for agent %s", agent_id)
                self._repos.agent_repo.set_state(
                    agent_id,
                    "failed",
                    error=format_agent_start_error(exc),
                )

    def _schedule_reload(self, agent_id: str) -> None:
        """Queue a background harness reload; coalesces rapid successive updates."""
        self._reload_dirty.add(agent_id)
        if self._reload_worker_running.get(agent_id):
            return
        self._reload_worker_running[agent_id] = True
        asyncio.create_task(self._reload_worker(agent_id), name=f"reload-agent-{agent_id}")

    async def _reload_worker(self, agent_id: str) -> None:
        try:
            while agent_id in self._reload_dirty:
                self._reload_dirty.discard(agent_id)
                try:
                    await self._reload_agent(agent_id)
                except Exception:
                    logger.exception("Background reload failed for agent %s", agent_id)
                if agent_id not in self._reload_dirty:
                    break
        finally:
            self._reload_worker_running[agent_id] = False
            if agent_id in self._reload_dirty:
                self._schedule_reload(agent_id)
