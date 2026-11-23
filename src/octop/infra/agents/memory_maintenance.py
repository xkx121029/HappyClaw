"""Memory maintenance — quiesce, restore, and manual document review.

Split out of :mod:`octop.infra.agents.manager` so AgentManager keeps a focused
lifecycle/invoke surface. Cross-mixin calls are declared as stubs on
:class:`AgentManagerBase` and resolved through the MRO.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from octop.i18n.domains.agents import format_agent_start_error
from octop.infra.agents.manager_base import AgentManagerBase
from octop.infra.errors import ErrorCode, OctopError


class AgentMemoryMaintenanceMixin(AgentManagerBase):
    """Stop, drain, and rebuild the memory runtime around lifecycle changes."""

    def _quiesce_octop_memory(self, agent_id: str) -> None:
        """Stop memory GC before the harness closes the SQLite backend.

        ``octop-memory`` runs lifecycle GC on a daemon thread. Closing the
        store while ``list_candidates`` is in flight segfaults (Linux live CI
        and Windows unit tests with a real HarnessAgentManager).
        """
        hm = self._harness_manager
        if hm is None:
            return
        try:
            entry = hm.get_agent(agent_id)
        except KeyError:
            return
        agent = getattr(entry, "agent", entry)
        runtime = getattr(agent, "_memory_runtime", None)
        mw = getattr(runtime, "_middleware", None) if runtime is not None else None
        if mw is None:
            return
        shutdown = getattr(mw, "shutdown", None)
        if callable(shutdown):
            with suppress(Exception):
                shutdown()
        self._wait_memory_maintenance_idle(mw)

    async def restore_memory_store(
        self, agent_id: str, memory: Any, operation: Callable[[], dict[str, Any]], *, locale: str
    ) -> dict[str, Any]:
        """Drain and recreate only this expert; caller owns its turn reservation."""
        from octop_harness.memory.store import shared_memory_store

        from octop.i18n import tr

        assert self._harness_manager is not None
        async with self._lifecycle_lock_for(agent_id):
            agent = self.get_agent(agent_id)
            runtime = agent._memory_runtime
            if runtime.memory is not memory:
                raise ValueError(tr("memory_storage.restore_changed", locale))
            key = runtime._memory_key
            if key is not None and shared_memory_store().refs(key) != 1:
                raise ValueError(tr("memory_storage.shared_sqlite", locale))
            mw = runtime._middleware
            pause_background = getattr(mw, "pause_background", None)
            if not callable(pause_background):
                raise ValueError(tr("memory_storage.incompatible", locale))
            pause = pause_background(timeout=120)
            draining = asyncio.create_task(asyncio.to_thread(pause.__enter__))
            try:
                await asyncio.shield(draining)
            except asyncio.CancelledError:
                await draining
                await asyncio.to_thread(pause.__exit__, None, None, None)
                raise
            removed = False
            try:
                row = self.get_row(agent_id)
                if row is None:
                    raise ValueError(tr("memory_storage.restore_changed", locale))
                cfg, metadata, tags, user_display = self._agent_runtime_bundle(row)
                removed = True
                await self._release_pool_for_agent(agent_id)
                await self._harness_manager.aremove_agent(agent_id)
                if runtime.memory is not None or (
                    key is not None and shared_memory_store().peek(key) is not None
                ):
                    raise ValueError(tr("memory_storage.restore_changed", locale))
                worker = asyncio.create_task(asyncio.to_thread(operation))
                try:
                    return await asyncio.shield(worker)
                except asyncio.CancelledError:
                    await worker
                    raise
            finally:
                try:
                    if removed:
                        try:
                            assert row is not None
                            entry = await self._harness_manager.acreate_agent(
                                cfg,
                                agent_id=agent_id,
                                metadata=metadata,
                                tags=tags,
                                init_workspace=False,
                            )
                            await self._post_start_agent(
                                row, entry.agent, cfg, user_display=user_display
                            )
                            self._repos.agent_repo.set_state(agent_id, "running", error=None)
                        except Exception as exc:
                            self._repos.agent_repo.set_state(
                                agent_id, "failed", error=format_agent_start_error(exc)
                            )
                            raise ValueError(
                                tr("memory_storage.restore_reload_failed", locale)
                            ) from exc
                finally:
                    await asyncio.to_thread(pause.__exit__, None, None, None)

    @staticmethod
    def _wait_memory_maintenance_idle(mw: object, *, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        lock = getattr(mw, "_maintenance_running", None)
        while time.monotonic() < deadline:
            named_busy = any(
                thread.is_alive() and thread.name == "hm-maintenance"
                for thread in threading.enumerate()
            )
            lock_busy = isinstance(lock, type(threading.Lock())) and lock.locked()
            if not named_busy and not lock_busy:
                return
            time.sleep(0.05)
        if isinstance(lock, type(threading.Lock())):
            acquired = lock.acquire(timeout=max(0.0, deadline - time.monotonic()))
            if acquired:
                lock.release()

    async def save_manual_memory_document(self, agent_id: str, filename: str, content: str) -> None:
        """Serialize owner edits with document review and lifecycle changes."""
        if filename not in {"USER.md", "MEMORY.md"}:
            raise ValueError("Unsupported manual memory document")
        async with self._lifecycle_lock_for(agent_id):
            workspace = await asyncio.to_thread(self.workspace_for_agent, agent_id)
            if workspace is None:
                raise self._unavailable_error(agent_id)
            await workspace.awrite_text(filename, content, force=True)

    async def review_manual_memory_documents(self, agent_id: str) -> dict[str, Any]:
        """Review current files, including for stopped agents, without changing session snapshots."""
        async with self._lifecycle_lock_for(agent_id):
            if self.memory_slim.busy and self.memory_slim.status(agent_id) is not None:
                raise OctopError.localized(ErrorCode.AGENT_BUSY)
            workspace = await asyncio.to_thread(self.workspace_for_agent, agent_id)
            if workspace is None:
                raise self._unavailable_error(agent_id)
            documents = {}
            for filename in ("USER.md", "MEMORY.md"):
                data = await workspace.adownload_bytes(filename)
                documents[filename] = data.decode("utf-8") if data is not None else ""

            def run() -> dict[str, Any]:
                from octop_harness.llm.factory import ChatModelFactory
                from octop_harness.memory.runtime import MemoryRuntime

                temporary = None
                owned_factory = None
                try:
                    try:
                        service = self.get_agent(agent_id)._memory_runtime.service
                    except OctopError:
                        row = self.get_row(agent_id)
                        if row is None:
                            raise self._unavailable_error(agent_id) from None
                        cfg = self._build_harness_config(row)
                        if not cfg.memory_enabled:
                            return {"status": "disabled"}
                        factory = (
                            self._harness_manager.shared_factory
                            if self._harness_manager is not None
                            else None
                        )
                        if factory is None:
                            factory = owned_factory = ChatModelFactory(
                                cfg.providers, agent_config=cfg
                            )
                        temporary = MemoryRuntime(
                            config=cfg,
                            workspace_path=Path(cfg.workspace_dir),
                            model_factory=factory,
                            workspace=workspace,
                        )
                        service = temporary.service
                    if service is None:
                        return {"status": "disabled"}

                    def current() -> bool:
                        return all(
                            (workspace.download_bytes(name) or b"").decode("utf-8") == body
                            for name, body in documents.items()
                        )

                    return dict(service.reconcile_manual_documents(documents, is_current=current))
                finally:
                    if temporary is not None:
                        temporary.close()
                    if owned_factory is not None:
                        owned_factory.close()

            worker = asyncio.create_task(asyncio.to_thread(run))
            try:
                return await asyncio.shield(worker)
            except asyncio.CancelledError:
                await worker
                raise


__all__ = ["AgentMemoryMaintenanceMixin"]
