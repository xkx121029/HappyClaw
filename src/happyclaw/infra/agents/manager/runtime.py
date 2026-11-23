"""Live agent handles: start/stop, dispatch guards, chat invocation and thread model overrides."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import (
    TYPE_CHECKING,
    Any,
    cast,
)

from happyclaw_harness import HarnessAgent

from happyclaw.infra.agents.manager.base import AgentManagerBase
from happyclaw.infra.agents.security.hitl_session import (
    hitl_thread_scope,
    thread_id_from_request,
)
from happyclaw.infra.errors import (
    ErrorCode,
    HappyclawError,
)
from happyclaw.infra.utils.turn_failure import turn_model_scope

if TYPE_CHECKING:
    from happyclaw.infra.db.repos.agents import AgentRow

class RuntimeMixin(AgentManagerBase):
    """Live agent handles: start/stop, dispatch guards, chat invocation and thread model overrides."""


    async def start(self, agent_id: str) -> None:
        """Load agent into harness runtime (no-op config merge)."""
        async with self._lock:
            row = self._repos.agent_repo.get(agent_id)
            if row is None:
                raise HappyclawError(ErrorCode.AGENT_NOT_FOUND, f"agent {agent_id!r} not found")
            await self._start_agent(row, init_workspace=False)


    def _lifecycle_lock_for(self, agent_id: str) -> asyncio.Lock:
        lock = self._agent_lifecycle_locks.get(agent_id)
        if lock is None:
            lock = asyncio.Lock()
            self._agent_lifecycle_locks[agent_id] = lock
        return lock


    def _thread_execution_lock(self, agent_id: str, thread_id: str) -> asyncio.Lock:
        key = (agent_id, thread_id)
        lock = self._thread_execution_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._thread_execution_locks[key] = lock
        return lock


    @staticmethod
    def _is_already_registered_error(exc: BaseException) -> bool:
        return "already exists in the registry" in str(exc)


    def _happyclaw_harness_or_none(self, agent_id: str) -> HarnessAgent | None:
        if self._harness_manager is None:
            return None
        try:
            return self._harness_manager.get_agent(agent_id).agent
        except KeyError:
            return None


    async def stop(self, agent_id: str) -> None:
        """Unload agent from harness runtime and persist ``last_state=stopped``."""
        async with self._lock:
            row = self._repos.agent_repo.get(agent_id)
            if row is None:
                raise HappyclawError(ErrorCode.AGENT_NOT_FOUND, f"agent {agent_id!r} not found")
            async with self._lifecycle_lock_for(agent_id):
                await asyncio.to_thread(self._quiesce_happyclaw_memory, agent_id)
                await self._harness_manager.aremove_agent(agent_id)  # type: ignore[union-attr]
                self._bootstrap_known.pop(agent_id, None)
                # Agent stopped: drop every DSH session cursor and its snapshot.
                self._dsh_prompt_sessions.discard_agent(agent_id)
                self._dsh_skill_snapshots.pop(agent_id, None)
                self._repos.agent_repo.set_state(agent_id, "stopped", error=None)


    def get_agent(self, agent_id: str) -> HarnessAgent:
        """Return the live HarnessAgent for agent_id (ULID).

        Raises:
            AGENT_NOT_FOUND — no such agent row
            AGENT_FAILED — agent exists but last start failed
            AGENT_NOT_RUNNING — agent exists but is not loaded in harness
        """
        if self._harness_manager is None:
            raise self._unavailable_error(agent_id)
        try:
            return self._harness_manager.get_agent(agent_id).agent
        except KeyError:
            raise self._unavailable_error(agent_id) from None


    def _unavailable_error(self, agent_id: str) -> HappyclawError:
        """Map a missing live harness handle to the right public error code."""
        row = self.get_row(agent_id)
        if row is None:
            return HappyclawError(ErrorCode.AGENT_NOT_FOUND, f"agent {agent_id!r} not found")
        state = (row.last_state or "").strip().lower()
        if state in ("failed", "error"):
            return HappyclawError(ErrorCode.AGENT_FAILED, f"agent {agent_id!r} failed to start")
        if state in ("created", "starting") and not self._has_usable_model(row):
            # First run with no provider: an actionable "add a model" hint beats
            # the generic "expert is not enabled" copy.
            return HappyclawError(
                ErrorCode.AGENT_NO_MODEL,
                f"agent {agent_id!r} has no model configured",
            )
        return HappyclawError(ErrorCode.AGENT_NOT_RUNNING, f"agent {agent_id!r} not running")


    def ensure_dispatchable(self, agent_id: str) -> None:
        """Fail before the harness registry raises ``KeyError``.

        ``happyclaw_harness`` indexes its registry directly when a turn is
        dispatched, so an agent that never started surfaces as
        ``KeyError: 'main'`` and the UI shows a raw model error. Callers check
        here before enqueueing a turn to convert that into the public
        ``AGENT_NO_MODEL`` / ``AGENT_NOT_RUNNING`` 409 with actionable copy.
        """
        self.get_agent(agent_id)


    def _require_live_agent(self, agent_id: str) -> None:
        """Last-moment guard inside ``stream`` / ``call`` / ``resume_hitl``."""
        self.ensure_dispatchable(agent_id)


    def _has_usable_model(self, row: AgentRow) -> bool:
        if self._harness_manager is not None and self._harness_manager.shared_factory is not None:
            return True
        return bool((row.default_model or "").strip())


    def is_agent_active(self, agent_id: str) -> bool:
        """Whether the agent is currently executing a user-visible invocation."""
        return self._active_invocations.get(agent_id, 0) > 0


    def try_begin_history_backfill(self, agent_id: str) -> bool:
        """Reserve an idle agent for one history backfill without racing a new turn."""
        if (
            self.is_agent_active(agent_id)
            or self._invocation_waiters.get(agent_id, 0) > 0
            or agent_id in self._history_backfills
        ):
            return False
        self._history_backfills[agent_id] = asyncio.Event()
        return True


    def end_history_backfill(self, agent_id: str) -> None:
        """Release one history-backfill reservation and wake waiting invocations."""
        event = self._history_backfills.pop(agent_id, None)
        if event is not None:
            event.set()


    async def _begin_invocation(self, agent_id: str) -> None:
        self._invocation_waiters[agent_id] = self._invocation_waiters.get(agent_id, 0) + 1
        try:
            while True:
                event = self._history_backfills.get(agent_id) or self._reclaim_holds.get(agent_id)
                if event is None:
                    break
                await event.wait()
        finally:
            waiting = self._invocation_waiters.get(agent_id, 1) - 1
            if waiting > 0:
                self._invocation_waiters[agent_id] = waiting
            else:
                self._invocation_waiters.pop(agent_id, None)
        self._active_invocations[agent_id] = self._active_invocations.get(agent_id, 0) + 1


    def _end_invocation(self, agent_id: str) -> None:
        active = self._active_invocations.get(agent_id, 1) - 1
        if active > 0:
            self._active_invocations[agent_id] = active
        else:
            self._active_invocations.pop(agent_id, None)
            if agent_id in self._reclaim_pending:
                self._ensure_reclaim_task()


    @asynccontextmanager
    async def _track_invocation(self, agent_id: str) -> AsyncIterator[None]:
        await self._begin_invocation(agent_id)
        try:
            yield
        finally:
            self._end_invocation(agent_id)


    async def stream(self, agent_id: str, request: dict[str, Any]) -> AsyncIterator[Any]:
        """Stream harness chunks (Langfuse tracing handled inside happyclaw-harness)."""
        if self._harness_manager is None:
            raise self._unavailable_error(agent_id)
        self._require_live_agent(agent_id)

        thread_id = str(request.get("thread_id") or "")
        async with (
            self._thread_execution_lock(agent_id, thread_id),
            self._track_invocation(agent_id),
        ):
            self._apply_pending_bootstrap_graph_refresh(agent_id)
            req = self._prepare_stream_request(agent_id, request)
            with (
                hitl_thread_scope(thread_id_from_request(req)),
                turn_model_scope(self._stream_model_label(agent_id, req, thread_id)),
            ):
                async for chunk in self._harness_manager.stream(agent_id, cast(Any, req)):
                    yield chunk
            self._apply_pending_bootstrap_graph_refresh(agent_id)


    async def call(self, agent_id: str, request: dict[str, Any]) -> dict[str, Any]:
        """Non-streaming harness invocation (one-shot agent call)."""
        if self._harness_manager is None:
            raise self._unavailable_error(agent_id)
        self._require_live_agent(agent_id)
        async with self._track_invocation(agent_id):
            self._apply_pending_bootstrap_graph_refresh(agent_id)
            req = self._prepare_stream_request(agent_id, request)
            thread_id = str(req.get("thread_id") or thread_id_from_request(req) or "")
            with (
                hitl_thread_scope(thread_id_from_request(req)),
                turn_model_scope(self._stream_model_label(agent_id, req, thread_id)),
            ):
                result = await self._harness_manager.call(agent_id, cast(Any, req))
            self._apply_pending_bootstrap_graph_refresh(agent_id)
        if not isinstance(result, dict):
            return {"result": result}
        return result


    async def resume_hitl(
        self,
        agent_id: str,
        thread_id: str,
        decisions: list[dict[str, Any]],
    ) -> AsyncIterator[Any]:
        """Resume a paused HITL interrupt for *thread_id*."""
        if self._harness_manager is None:
            raise self._unavailable_error(agent_id)
        self._require_live_agent(agent_id)
        async with (
            self._thread_execution_lock(agent_id, thread_id),
            self._track_invocation(agent_id),
        ):
            self._apply_pending_bootstrap_graph_refresh(agent_id)
            with (
                hitl_thread_scope(thread_id),
                turn_model_scope(self._stream_model_label(agent_id, {}, thread_id)),
            ):
                async for chunk in self._harness_manager.resume_hitl(
                    agent_id, thread_id, decisions
                ):
                    yield chunk
            self._apply_pending_bootstrap_graph_refresh(agent_id)


    def cancel_stream(self, agent_id: str, thread_id: str) -> None:
        """Signal happyclaw-harness to stop the active stream for *(agent_id, thread_id)*."""
        if self._harness_manager is not None:
            self._harness_manager.cancel(agent_id, thread_id)


    def get_thread_model(self, agent_id: str, thread_id: str) -> str | None:
        if self._harness_manager is None:
            return None
        return self._harness_manager.get_thread_model(agent_id, thread_id)


    def set_thread_model(self, agent_id: str, thread_id: str, model: str) -> None:
        if self._harness_manager is not None:
            self._harness_manager.set_thread_model(agent_id, thread_id, model)


    def clear_thread_model(self, agent_id: str, thread_id: str) -> None:
        if self._harness_manager is not None:
            self._harness_manager.clear_thread_model(agent_id, thread_id)


    def _resolve_configured_fallback_model_ref(self) -> str | None:
        """Return the configured fallback without applying runtime health."""
        name, model_id = self._repos.settings_repo.get_active_model()
        if name and model_id:
            ref = f"{name}/{model_id}"
            if self._providers.is_model_ref_usable(ref):
                return ref
        return self._providers.resolve_first_model_ref()


    def resolve_fallback_model_ref(self) -> str | None:
        """Return the first healthy model for an automatic route."""
        configured = self._resolve_configured_fallback_model_ref()
        if configured and self._model_health.is_routable(configured):
            return configured
        for candidate in self._providers.list_auto_route_candidates(needs_multimodal=False):
            if self._model_health.is_routable(candidate.ref):
                return candidate.ref
        return None


    def is_auto_route_model_available(self, ref: str) -> bool:
        """Return whether a usable model can start an automatic route now."""
        return self._providers.is_model_ref_usable(ref) and self._model_health.is_routable(ref)
