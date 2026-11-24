"""Memory extraction settings and the per-agent memory store lifecycle."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

from happyclaw.i18n.domains.agents import format_agent_start_error
from happyclaw.infra.agents.manager.base import AgentManagerBase
from happyclaw.infra.agents.manager.constants import _HARNESS_AGENT_CONFIG_FIELDS
from happyclaw.infra.agents.memory.backend import memory_backend_from_agent_config
from happyclaw.infra.errors import (
    ErrorCode,
    HappyclawError,
)

if TYPE_CHECKING:
    from happyclaw.infra.agents.manager import AgentManager

logger = logging.getLogger(__name__)


def _model_retry_on_failure(
    exc: Exception,
    *,
    agent_id: str = "",
    manager: AgentManager | None = None,
) -> str:
    # Legacy formatter for callers that explicitly request a recovery prompt.
    # Active agents use on_failure="error"; their entry points log the exception.
    from happyclaw.i18n.domains.stream import exception_display_message, model_retry_failure_prompt
    from happyclaw.infra.agents.security.hitl_session import current_hitl_thread_id
    from happyclaw.infra.metrics import METRICS
    from happyclaw.infra.utils.turn_failure import current_turn_model, log_turn_failure

    thread_id = current_hitl_thread_id() or ""
    model = current_turn_model()
    if not model and manager is not None and agent_id and thread_id:
        with suppress(Exception):
            model = manager.get_thread_model(agent_id, thread_id) or ""
    if not model and manager is not None and agent_id:
        with suppress(Exception):
            row = manager.get_row(agent_id)
            if row is not None:
                model = (row.default_model or "").strip()
    log_turn_failure(
        "model_retry",
        detail=exception_display_message(exc),
        agent_id=agent_id,
        thread_id=thread_id,
        model=model,
        exc=exc,
        level=logging.ERROR,
    )
    METRICS.inc("stream_errors_total")
    return model_retry_failure_prompt(exc, "en")


# happyclaw-memory builds SQLite table names as ``{namespace}_*``. The namespace
# must be a valid bare SQL identifier: start with a letter, only [A-Za-z0-9_].
_MEMORY_NS_PREFIX = "agent_"


def _memory_namespace(agent_id: str) -> str:
    return f"{_MEMORY_NS_PREFIX}{agent_id}"


def _memory_aux_model_settings(
    mem: dict[str, Any],
    supported_fields: frozenset[str],
    is_ref_usable: Callable[[str], bool] | None,
) -> dict[str, Any]:
    """Map the ``memory.aux_model`` ref onto both harness extraction tiers.

    A stale ref (provider deleted / model disabled since it was saved) is
    dropped with a warning so extraction falls back to the default model
    instead of failing at call time.
    """
    aux_model = mem.get("aux_model")
    if (
        not isinstance(aux_model, str)
        or not aux_model.strip()
        or "memory_aux_light_model" not in supported_fields
        or "memory_aux_heavy_model" not in supported_fields
    ):
        return {}
    ref = aux_model.strip()
    if is_ref_usable is not None and not is_ref_usable(ref):
        logger.warning(
            "memory aux_model %r no longer usable; falling back to the default model",
            ref,
        )
        return {}
    # One user-chosen model drives both extraction tiers.
    return {"memory_aux_light_model": ref, "memory_aux_heavy_model": ref}


def memory_extract_supported_options() -> list[str]:
    """Call options supported by the installed harness, for the settings UI."""
    fields = {
        "memory_capture_enabled": "memory_capture_enabled",
        "memory_recall_inject_enabled": "memory_recall_inject_enabled",
        "extract_max_tokens": "memory_extract_max_tokens",
        "extract_light_timeout_s": "memory_aux_light_timeout_s",
        "extract_heavy_timeout_s": "memory_aux_heavy_timeout_s",
        "extract_thinking": "memory_aux_thinking",
        "extract_extra_body": "memory_aux_extra_body",
        "extract_max_retries": "memory_aux_max_retries",
        "extract_retry_backoff_s": "memory_aux_retry_backoff_s",
    }
    return [key for key, field in fields.items() if field in _HARNESS_AGENT_CONFIG_FIELDS]


def _memory_extract_settings(
    cfg: dict[str, Any],
    *,
    supported_fields: frozenset[str] = _HARNESS_AGENT_CONFIG_FIELDS,
    is_ref_usable: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    """Extract the ``memory`` config section into HarnessAgentConfig kwargs.

    Mirrors the shape written by the dashboard's ``PUT .../memory/extract-config``
    endpoint. Only recognized keys are forwarded; anything missing falls through
    to HarnessAgentConfig's own defaults, so an agent with no ``memory`` section
    behaves exactly as before.
    """
    mem = cfg.get("memory")
    if not isinstance(mem, dict):
        return {}
    out: dict[str, Any] = _memory_aux_model_settings(mem, supported_fields, is_ref_usable)
    for key in ("memory_enabled", "memory_capture_enabled", "memory_recall_inject_enabled"):
        if key in supported_fields and isinstance(mem.get(key), bool):
            out[key] = mem[key]
    if "memory_extract_on_session_end" in supported_fields and isinstance(
        mem.get("extract_on_session_end"), bool
    ):
        out["memory_extract_on_session_end"] = mem["extract_on_session_end"]
    mode = mem.get("extract_trigger_mode")
    if mode in ("idle", "interval") and "memory_extract_trigger_mode" in supported_fields:
        out["memory_extract_trigger_mode"] = mode
    for src, dst in (
        ("extract_idle_seconds", "memory_extract_idle_seconds"),
        ("extract_interval_seconds", "memory_extract_interval_seconds"),
    ):
        val = mem.get(src)
        if (
            dst in supported_fields
            and isinstance(val, int | float)
            and not isinstance(val, bool)
            and val > 0
        ):
            out[dst] = float(val)

    # Aux-call options (#1360): read timeouts per tier, an extraction output
    # budget, and vendor request extras for the aux LLM. Forward-compat: only
    # forwarded when the installed happyclaw-harness knows the field.
    for src, dst in (
        ("extract_light_timeout_s", "memory_aux_light_timeout_s"),
        ("extract_heavy_timeout_s", "memory_aux_heavy_timeout_s"),
    ):
        val = mem.get(src)
        if (
            dst in supported_fields
            and isinstance(val, int | float)
            and not isinstance(val, bool)
            and val > 0
        ):
            # Older API versions accepted timeouts beyond harness limits.
            out[dst] = max(30.0, min(3600.0, float(val)))
    max_tokens = mem.get("extract_max_tokens")
    if (
        "memory_extract_max_tokens" in supported_fields
        and isinstance(max_tokens, int)
        and not isinstance(max_tokens, bool)
        and max_tokens > 0
    ):
        out["memory_extract_max_tokens"] = max(128, min(65536, max_tokens))
    thinking = mem.get("extract_thinking")
    if thinking in ("auto", "off", "on") and "memory_aux_thinking" in supported_fields:
        out["memory_aux_thinking"] = thinking
    for src, dst in (
        ("extract_max_retries", "memory_aux_max_retries"),
        ("extract_retry_backoff_s", "memory_aux_retry_backoff_s"),
    ):
        value = mem.get(src)
        if (
            dst in supported_fields
            and isinstance(value, int | float)
            and not isinstance(value, bool)
        ):
            out[dst] = value
    extra_body = mem.get("extract_extra_body")
    aux_model = mem.get("aux_model")
    has_aux_override = isinstance(aux_model, str) and bool(aux_model.strip())
    if (
        "memory_aux_extra_body" in supported_fields
        and isinstance(extra_body, dict)
        and extra_body
        and (not has_aux_override or "memory_aux_light_model" in out)
    ):
        out["memory_aux_extra_body"] = dict(extra_body)

    # happyclaw-harness 0.9.5 predates the interval trigger fields. Keep
    # hot reload working against that release and approximate interval mode
    # with its per-session idle watchdog until a newer harness is installed.
    if (
        mode == "interval"
        and "memory_extract_trigger_mode" not in supported_fields
        and "memory_extract_idle_seconds" in supported_fields
    ):
        interval = mem.get("extract_interval_seconds")
        if isinstance(interval, int | float) and not isinstance(interval, bool) and interval > 0:
            out["memory_extract_idle_seconds"] = float(interval)
        logger.warning(
            "Installed happyclaw-harness lacks interval memory extraction; "
            "falling back to the idle watchdog for this agent"
        )
    return out


def _resolve_memory_backend_kwargs(
    cfg: dict[str, Any],
    *,
    workspace_dir: Any,
    config: Any,
) -> dict[str, Any]:
    return memory_backend_from_agent_config(cfg, octop_config=config, workspace_dir=workspace_dir)


class MemoryMixin(AgentManagerBase):
    """Memory extraction settings and the per-agent memory store lifecycle."""

    def _quiesce_happyclaw_memory(self, agent_id: str) -> None:
        """Stop memory GC before the harness closes the SQLite backend.

        ``happyclaw-memory`` runs lifecycle GC on a daemon thread. Closing the
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
        from happyclaw_harness.memory.store import shared_memory_store

        from happyclaw.i18n import tr

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
                raise HappyclawError.localized(ErrorCode.AGENT_BUSY)
            workspace = await asyncio.to_thread(self.workspace_for_agent, agent_id)
            if workspace is None:
                raise self._unavailable_error(agent_id)
            documents = {}
            for filename in ("USER.md", "MEMORY.md"):
                data = await workspace.adownload_bytes(filename)
                documents[filename] = data.decode("utf-8") if data is not None else ""

            def run() -> dict[str, Any]:
                from happyclaw_harness.llm.factory import ChatModelFactory
                from happyclaw_harness.memory.runtime import MemoryRuntime

                temporary = None
                owned_factory = None
                try:
                    try:
                        service = self.get_agent(agent_id)._memory_runtime.service
                    except HappyclawError:
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
