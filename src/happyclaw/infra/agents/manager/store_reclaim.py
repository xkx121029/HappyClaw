"""Thread checkpoint deletion and idle SQLite store rebuilds."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from happyclaw.infra.agents.manager.base import AgentManagerBase
from happyclaw.infra.errors import (
    ErrorCode,
    HappyclawError,
)

logger = logging.getLogger(__name__)

class StoreReclaimMixin(AgentManagerBase):
    """Thread checkpoint deletion and idle SQLite store rebuilds."""


    async def delete_thread_checkpoint(
        self, agent_id: str, thread_id: str, *, reclaim: bool = True
    ) -> None:
        """Delete a thread's conversation data from the checkpoint store.

        Uses the live harness checkpointer when the agent is loaded.
        Otherwise opens the configured SQLite or Postgres memory store
        directly, so a restart does not skip the delete. Raises
        ``CHECKPOINT_DELETE_FAILED`` when persisted data could not be
        removed. Returns normally when the store has nothing for this
        thread. Callers should invoke this *before* removing their own
        thread row, so a failure leaves the thread visible and retryable.

        ``reclaim=False`` skips the incremental SQLite vacuum. Delete-only
        uses that so the request itself does not vacuum.
        """
        # Session ended: drop its DSH skill cursor explicitly (never GC-driven).
        self._dsh_prompt_sessions.discard(agent_id, thread_id)
        row = self.get_row(agent_id)
        harness = None
        try:
            harness = self.get_agent(agent_id)
        except HappyclawError as exc:
            if exc.code == ErrorCode.AGENT_NOT_FOUND or row is None:
                raise
            harness = None
        live_error: Exception | None = None
        if harness is not None:
            adelete = getattr(harness, "adelete_thread", None)
            if adelete is not None:
                try:
                    await adelete(thread_id)
                except HappyclawError:
                    raise
                except Exception as exc:
                    live_error = exc
        if row is None:
            if live_error is not None:
                raise HappyclawError(
                    ErrorCode.CHECKPOINT_DELETE_FAILED,
                    f"could not delete conversation data for thread {thread_id!r}",
                ) from live_error
            return
        try:
            await asyncio.to_thread(
                self._delete_thread_from_store, agent_id, thread_id, row, reclaim
            )
        except HappyclawError:
            if live_error is not None:
                raise HappyclawError(
                    ErrorCode.CHECKPOINT_DELETE_FAILED,
                    f"could not delete conversation data for thread {thread_id!r}",
                ) from live_error
            raise


    def _delete_thread_from_store(
        self, agent_id: str, thread_id: str, row: Any, reclaim: bool = True
    ) -> None:
        from happyclaw.infra.agents.memory.thread_cleanup import (  # noqa: PLC0415
            delete_thread_from_agent_stores,
            workspace_for_agent_row,
        )

        cfg = self._agent_config_dict(row)
        workspace = workspace_for_agent_row(row, paths=self._paths)
        delete_thread_from_agent_stores(
            agent_id=agent_id,
            thread_id=thread_id,
            cfg=cfg,
            octop_config=self._config,
            workspace_dir=workspace,
            paths=self._paths,
            reclaim=reclaim,
        )


    def _reclaim_thread_store(self, agent_id: str, thread_id: str, row: Any) -> None:
        if row is None:
            return
        from happyclaw.infra.agents.memory.thread_cleanup import (  # noqa: PLC0415
            reclaim_stored_thread,
            workspace_for_agent_row,
        )

        reclaim_stored_thread(
            agent_id=agent_id,
            thread_id=thread_id,
            cfg=self._agent_config_dict(row),
            octop_config=self._config,
            workspace_dir=workspace_for_agent_row(row, paths=self._paths),
        )


    def schedule_store_reclaim(self, agent_id: str) -> None:
        """Shrink this agent's database after it is idle.

        Used when compact-now could not run, and when the idle sweep finds
        a large freelist. Delete-only does not call this.
        """
        self._reclaim_pending.add(agent_id)
        self._ensure_reclaim_task()


    def schedule_idle_reclaim_sweep(self) -> None:
        """Queue loaded stores whose freelist is already large enough to compact."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        current = self._reclaim_sweep_task
        if current is not None and not current.done():
            return
        self._reclaim_sweep_task = loop.create_task(
            self._sweep_bloated_stores(), name="store-reclaim-sweep"
        )


    async def compact_agent_database(self, agent_id: str, *, wait_s: float = 60) -> bool:
        """Rebuild the database now. False means it was deferred until idle."""
        deadline = time.monotonic() + wait_s
        while True:
            if self._try_acquire_reclaim(agent_id):
                try:
                    done = await asyncio.to_thread(self._compact_agent_database_sync, agent_id)
                finally:
                    self._release_reclaim(agent_id)
                if done:
                    self._reclaim_pending.discard(agent_id)
                    return True
                self.schedule_store_reclaim(agent_id)
                return False
            if time.monotonic() >= deadline:
                self.schedule_store_reclaim(agent_id)
                return False
            await asyncio.sleep(0.25)


    def _try_acquire_reclaim(self, agent_id: str) -> bool:
        if (
            self.is_agent_active(agent_id)
            or self._invocation_waiters.get(agent_id, 0) > 0
            or agent_id in self._reclaim_holds
            or agent_id in self._history_backfills
        ):
            return False
        self._reclaim_holds[agent_id] = asyncio.Event()
        if self.is_agent_active(agent_id) or self._invocation_waiters.get(agent_id, 0) > 0:
            self._release_reclaim(agent_id)
            return False
        return True


    def _release_reclaim(self, agent_id: str) -> None:
        event = self._reclaim_holds.pop(agent_id, None)
        if event is not None:
            event.set()


    def _ensure_reclaim_task(self) -> None:
        if self._reclaim_wake is None:
            self._reclaim_wake = asyncio.Event()
        self._reclaim_wake.set()
        task = self._reclaim_task
        if task is not None and not task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._reclaim_task = loop.create_task(self._reclaim_pending_loop(), name="store-reclaim")


    async def _sweep_bloated_stores(self) -> None:
        try:
            queued = await asyncio.to_thread(self._queue_bloated_sqlite_stores)
            if queued:
                self._ensure_reclaim_task()
        finally:
            current = asyncio.current_task()
            if self._reclaim_sweep_task is current:
                self._reclaim_sweep_task = None


    def _queue_bloated_sqlite_stores(self) -> int:
        from happyclaw.infra.agents.memory.thread_cleanup import (  # noqa: PLC0415
            RECLAIM_MIN_FREELIST_BYTES,
            agent_config_from_row,
            agent_sqlite_freelist_bytes,
            workspace_for_agent_row,
        )

        queued = 0
        for row in self._repos.agent_repo.list_all(include_disabled=True):
            try:
                nbytes = agent_sqlite_freelist_bytes(
                    agent_id=row.agent_id,
                    cfg=agent_config_from_row(row),
                    octop_config=self._config,
                    workspace_dir=workspace_for_agent_row(row, paths=self._paths),
                    paths=self._paths,
                )
            except Exception:
                logger.warning("freelist scan failed agent=%s", row.agent_id, exc_info=True)
                continue
            if nbytes < RECLAIM_MIN_FREELIST_BYTES:
                continue
            self._reclaim_pending.add(row.agent_id)
            queued += 1
        return queued


    async def _reclaim_pending_loop(self) -> None:
        try:
            while self._reclaim_pending:
                finished_one = False
                for agent_id in list(self._reclaim_pending):
                    if not self._try_acquire_reclaim(agent_id):
                        continue
                    try:
                        done = await asyncio.to_thread(self._compact_agent_database_sync, agent_id)
                    except Exception:
                        logger.warning("idle compact failed agent=%s", agent_id, exc_info=True)
                        done = False
                    finally:
                        self._release_reclaim(agent_id)
                    if done:
                        self._reclaim_pending.discard(agent_id)
                        finished_one = True
                if not self._reclaim_pending:
                    break
                if finished_one:
                    continue
                wake = self._reclaim_wake
                if wake is None:
                    await asyncio.sleep(30)
                    continue
                wake.clear()
                try:
                    await asyncio.wait_for(wake.wait(), timeout=30)
                except TimeoutError:
                    continue
        finally:
            current = asyncio.current_task()
            if self._reclaim_task is current:
                self._reclaim_task = None
            if self._reclaim_pending and (self._reclaim_task is None or self._reclaim_task.done()):
                self._ensure_reclaim_task()


    def _compact_agent_database_sync(self, agent_id: str) -> bool:
        from happyclaw.infra.agents.memory.thread_cleanup import (  # noqa: PLC0415
            agent_config_from_row,
            compact_agent_store_file,
            compact_live_sqlite,
            workspace_for_agent_row,
        )

        row = self.get_row(agent_id)
        if row is None:
            return True
        harness = self._happyclaw_harness_or_none(agent_id)
        if harness is not None:
            memory = getattr(getattr(harness, "_memory_runtime", None), "memory", None)
            if memory is None:
                return True
            return compact_live_sqlite(memory)
        return compact_agent_store_file(
            agent_id=agent_id,
            cfg=agent_config_from_row(row),
            octop_config=self._config,
            workspace_dir=workspace_for_agent_row(row, paths=self._paths),
        )
