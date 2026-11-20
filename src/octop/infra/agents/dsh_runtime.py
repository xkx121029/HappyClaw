"""DSH (plugin runtime) wiring for one :class:`AgentManager`.

Owns the opt-in DSH stages that used to be a handful of methods on the agent
manager: the S8 model-adapter installation, the S2 read-only tool assembly, and
their read-only status reports. Everything here is default-off and imports the
DSH package lazily, so the disabled path stays free of that import cost.

The manager keeps thin forwarding methods so existing callers and tests do not
change.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from octop.infra.dsh.switches import stage_enabled as dsh_stage_enabled

if TYPE_CHECKING:
    from octop.infra.agents.manager import AgentManager

logger = logging.getLogger(__name__)


def _dsh_local_roots() -> tuple[str, ...]:
    """Explicit local plugin directories for S2 discovery.

    No default roots: scanning the home directory on every config build would be
    a surprise, and the market install root already covers installed plugins.
    """
    raw = os.environ.get("OCTOP_DSH_TOOL_ROOTS", "")
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def attach_dsh_runtime(manager: AgentManager) -> DshRuntime:
    """Return the manager's DSH coordinator, creating it on first use.

    ``__init__`` attaches it eagerly, but partial constructions (tests that use
    ``object.__new__``, or code that predates this split) must not crash.
    """
    existing = getattr(manager, "dsh", None)
    if isinstance(existing, DshRuntime):
        return existing
    runtime = DshRuntime(manager)
    manager.dsh = runtime  # type: ignore[attr-defined]
    return runtime


class DshRuntime:
    """Process-wide DSH stage coordinator bound to one agent manager."""

    def __init__(self, manager: AgentManager) -> None:
        self._manager = manager
        # Session cursors live here (never in module globals), keyed by
        # (agent_id, thread_id). Built on first use so the default-off path
        # never imports the DSH skill/integration tree during startup.
        self._prompt_sessions: Any | None = None
        self._skill_snapshots: dict[str, Any] = {}
        # S8 model adapter: transport factory injected before boot(), plus the
        # last install result for the read-only status query. Both stay None
        # when the stage is off, which costs no DSH LLM import.
        self._transport_factory: Any | None = None
        self._llm_install: Any | None = None
        # S2 read-only tool mounting: optional in-process tool bodies keyed by
        # plugin id, plus the last assembly result for the status query. Both
        # are empty/None while the stage is off.
        self._tool_providers: dict[str, Any] = {}
        self._tools_status: Any | None = None

    # ------------------------------------------------------------------ S8

    def set_transport_factory(self, factory: Any | None) -> None:
        """Override the S8 DSH transport factory (set before boot(); optional).

        ``None`` means "use the built-in httpx transport" once the stage is
        enabled; without any transport the installer reports ``skipped`` and
        every model call keeps using the harness factory.
        """
        self._transport_factory = factory

    def install_llm(self) -> None:
        """Wire the S8 model adapter into the harness factory when enabled."""
        from octop.infra.dsh.switches import llm_enabled

        if not llm_enabled():
            return
        try:
            from octop.infra.dsh.llm.factory import install_dsh_model_factory

            transport_factory = self._transport_factory
            if transport_factory is None:
                from octop.infra.dsh.llm.http_transport import build_http_transport

                transport_factory = build_http_transport
            self._llm_install = install_dsh_model_factory(
                self._manager._harness_manager,
                transport_factory=transport_factory,
            )
        except Exception:
            logger.exception("DSH LLM adapter setup failed; continuing with the harness factory")
            self._llm_install = None

    def llm_status(self) -> dict[str, Any]:
        """Read-only snapshot of the S8 adapter wiring (which refs, why)."""
        from octop.infra.dsh.llm.factory import describe_installation

        return describe_installation(
            self._manager._harness_manager, result=self._llm_install
        ).as_dict()

    # ------------------------------------------------------------------ S2

    def prompt_store(self) -> Any:
        """Return the DSH session-cursor store, importing it on first use."""
        if self._prompt_sessions is None:
            from octop.infra.dsh.integration import DshPromptSessionStore

            self._prompt_sessions = DshPromptSessionStore()
        return self._prompt_sessions

    # -- session cursors --------------------------------------------------

    @property
    def snapshots(self) -> dict[str, Any]:
        """Per-agent skill snapshot handed to the prompt store."""
        return self._skill_snapshots

    def discard_agent(self, agent_id: str) -> None:
        """Drop every cursor and snapshot for a removed agent."""
        if self._prompt_sessions is not None:
            self._prompt_sessions.discard_agent(agent_id)
        self._skill_snapshots.pop(agent_id, None)

    def discard_thread(self, agent_id: str, thread_id: str) -> None:
        """Drop one conversation's cursor (session ended)."""
        if self._prompt_sessions is not None:
            self._prompt_sessions.discard(agent_id, thread_id)

    def advance_prompt(self, agent_id: str, thread_id: str) -> str | None:
        """Next DSH skill prompt for this turn, or None when the stage is off."""
        if self._prompt_sessions is None:
            return None
        snapshot = self._skill_snapshots.get(agent_id)
        if snapshot is None:
            return None
        return self._prompt_sessions.advance(agent_id, thread_id, snapshot)  # type: ignore[no-any-return]

    def register_tool_provider(self, plugin_id: str, provider: Any) -> None:
        """Register the tool body provider for one ``dsh:<native>`` plugin (S2)."""
        self._tool_providers[str(plugin_id)] = provider

    def tools_status(self) -> dict[str, Any]:
        """Read-only view of the last S2 assembly: mounted tools + skip reasons.

        The ``sandbox`` block reports the posture even before any assembly, so a
        reader can always tell whether a missing sandbox would allow or deny.
        """
        if self._tools_status is None:
            # Mirrors the runtime rule without importing the sandbox package
            # while the stage is off: unknown values are treated as strict.
            raw = (os.environ.get("OCTOP_DSH_SANDBOX_ABSENCE") or "allow").strip().lower()
            mode = raw if raw in {"allow", "strict"} else "strict"
            return {
                "enabled": dsh_stage_enabled("tools"),
                "mounted": [],
                "tools": [],
                "skipped": [],
                "runtime": [],
                "sandbox": {"mode": mode, "assembled": False, "plugins": []},
            }
        return {"enabled": True, **self._tools_status.report()}

    def _sandbox_root(self, row: Any) -> Any:
        """Workspace the DSH sandbox confines calls to, or None if unresolvable."""
        return self._manager._dsh_sandbox_root(row)

    def _runtime_tools(self, sandbox_root: Any) -> dict[str, Any]:
        """S10 exec grants for this agent; empty unless the stage is on.

        Two independent opt-ins are required: ``OCTOP_DSH_EXEC`` (stage) and a
        plugin id listed in ``OCTOP_DSH_EXEC_PLUGINS`` (grant).
        """
        if not dsh_stage_enabled("exec"):
            return {}
        from octop.infra.dsh.tools.runtime import (
            ENV_NODE,
            ExecGrant,
            RuntimeTools,
            resolve_exec_plugins,
        )

        node = os.environ.get(ENV_NODE) or ""
        return {
            plugin_id: RuntimeTools(
                grant=ExecGrant(
                    plugin_id=plugin_id,
                    workspace_root=sandbox_root,
                    node_executable=node,
                )
            )
            for plugin_id in sorted(resolve_exec_plugins())
        }

    def plugin_tools(self, row: Any, *, reserved: Sequence[Any]) -> list[Any]:
        """Assemble read-only DSH tools for one agent (called only when enabled)."""
        from octop.infra.dsh.tools import build_dsh_plugin_tools
        from octop.infra.plugins.market import default_market_root

        hitl = dsh_stage_enabled("hitl")
        approval = None
        if hitl:
            # S5: reuse the repository's HITL pause/resume path.
            from octop.infra.plugins.bridge.hitl import HitlApprovalChannel

            approval = HitlApprovalChannel()
        sandbox_root = self._sandbox_root(row)
        runtime = self._runtime_tools(sandbox_root)
        build = build_dsh_plugin_tools(
            scope=str(row.agent_id),
            market_root=os.environ.get("OCTOP_DSH_MARKET_ROOT") or default_market_root(),
            local_roots=_dsh_local_roots(),
            providers=self._tool_providers,
            hitl=hitl,
            approval=approval,
            reserved_names=[str(getattr(tool, "name", "")) for tool in reserved],
            sandbox_root=sandbox_root,
            sandbox_absence=os.environ.get("OCTOP_DSH_SANDBOX_ABSENCE") or None,
            runtime=runtime,
        )
        self._tools_status = build
        if build.skipped:
            from octop.infra.dsh.diagnostics import record_failure

            for skip in build.skipped:
                logger.info(
                    "DSH tool skipped: %s (%s) %s",
                    skip.plugin_id,
                    skip.reason,
                    skip.detail,
                )
                record_failure(
                    kind="load",
                    plugin_id=skip.plugin_id,
                    code=skip.reason,
                    reason=skip.detail or skip.reason,
                    detail=skip.tool,
                )
        return list(build.tools)


__all__ = ["DshRuntime", "attach_dsh_runtime"]
