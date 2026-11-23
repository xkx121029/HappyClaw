"""Optional DSH stage wiring: model adapter install and read-only tool mounting."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from happyclaw.infra.agents.manager.base import AgentManagerBase
from happyclaw.infra.dsh.switches import stage_enabled as dsh_stage_enabled
from happyclaw.infra.utils.env_alias import env_get

logger = logging.getLogger(__name__)

def _dsh_local_roots() -> tuple[str, ...]:
    """Explicit local plugin directories for S2 discovery.

    No default roots: scanning the home directory on every config build would be
    a surprise, and the market install root already covers installed plugins.
    """
    raw = env_get("DSH_TOOL_ROOTS", "") or ""
    return tuple(part.strip() for part in raw.split(",") if part.strip())


class DshMixin(AgentManagerBase):
    """Optional DSH stage wiring: model adapter install and read-only tool mounting."""


    def _install_dsh_llm(self) -> None:
        """Wire the S8 model adapter into the harness factory when enabled.

        Default-off costs one environment lookup: :mod:`happyclaw.infra.dsh.switches`
        is stdlib-only, and no harness/adapter module is imported until the
        stage is on. Any failure is logged and swallowed so boot never depends
        on the adapter; the original factory keeps serving model calls.
        """
        from happyclaw.infra.dsh.switches import llm_enabled  # noqa: PLC0415

        if not llm_enabled():
            return
        try:
            from happyclaw.infra.dsh.llm.factory import (  # noqa: PLC0415
                install_dsh_model_factory,
            )

            transport_factory = self._dsh_transport_factory
            if transport_factory is None:
                from happyclaw.infra.dsh.llm.http_transport import (  # noqa: PLC0415
                    build_http_transport,
                )

                transport_factory = build_http_transport
            self._dsh_llm_install = install_dsh_model_factory(
                self._harness_manager,
                transport_factory=transport_factory,
            )
        except Exception:
            logger.exception(
                "DSH LLM adapter setup failed; continuing with the harness factory"
            )
            self._dsh_llm_install = None


    def dsh_llm_status(self) -> dict[str, Any]:
        """Read-only snapshot of the S8 adapter wiring (which refs, why)."""
        from happyclaw.infra.dsh.llm.factory import describe_installation  # noqa: PLC0415

        return describe_installation(
            self._harness_manager, result=self._dsh_llm_install
        ).as_dict()


    def register_dsh_tool_provider(self, plugin_id: str, provider: Any) -> None:
        """Register the tool body provider for one ``dsh:<native>`` plugin (S2).

        Optional by design: this stage never executes plugin JavaScript, so tool
        bodies are supplied in-process. With no provider registered, discovery
        still reports ``no_tool_provider`` per plugin and the tool list is
        exactly what it was before S2.
        """
        self._dsh_tool_providers[str(plugin_id)] = provider


    def dsh_tools_status(self) -> dict[str, Any]:
        """Read-only view of the last S2 assembly: mounted tools + skip reasons.

        The ``sandbox`` block reports the posture even before any assembly, so a
        reader can always tell whether a missing sandbox would allow or deny.
        """
        if self._dsh_tools_status is None:
            # Mirrors the runtime rule without importing the sandbox package
            # while the stage is off: unknown values are treated as strict.
            raw = (env_get("DSH_SANDBOX_ABSENCE") or "allow").strip().lower()
            mode = raw if raw in {"allow", "strict"} else "strict"
            return {
                "enabled": dsh_stage_enabled("tools"),
                "mounted": [],
                "tools": [],
                "skipped": [],
                "sandbox": {"mode": mode, "assembled": False, "plugins": []},
            }
        return {"enabled": True, **self._dsh_tools_status.report()}


    def _dsh_sandbox_root(self, row: Any) -> Any:
        """Workspace the DSH sandbox confines calls to, or None if unresolvable.

        ``workspace_for_agent_row`` only computes the path; it does not create
        anything. A failure here must not stop tool assembly: the probe then
        falls back to the absence gate, whose posture is reported by
        ``dsh_tools_status()``.
        """
        try:
            from happyclaw.infra.agents.memory.thread_cleanup import (  # noqa: PLC0415
                workspace_for_agent_row,
            )

            return workspace_for_agent_row(row, paths=self._paths)
        except Exception as exc:  # noqa: BLE001 - tool assembly must not fail here
            logger.warning("DSH sandbox workspace unavailable: %s", exc)
            return None


    def _dsh_plugin_tools(self, row: Any, *, reserved: Sequence[Any]) -> list[Any]:
        """Assemble read-only DSH tools for one agent (called only when enabled)."""
        from happyclaw.infra.dsh.tools import build_dsh_plugin_tools  # noqa: PLC0415

        hitl = dsh_stage_enabled("hitl")
        approval = None
        if hitl:
            # S5: reuse the repository's HITL pause/resume path (interrupt →
            # ``hitl_required`` frame → POST .../hitl/resume). No new protocol.
            from happyclaw.infra.plugins.bridge.hitl import (  # noqa: PLC0415
                HitlApprovalChannel,
            )

            approval = HitlApprovalChannel()
        build = build_dsh_plugin_tools(
            scope=str(row.agent_id),
            market_root=env_get("DSH_MARKET_ROOT") or None,
            local_roots=_dsh_local_roots(),
            providers=self._dsh_tool_providers,
            hitl=hitl,
            approval=approval,
            reserved_names=[str(getattr(tool, "name", "")) for tool in reserved],
            # S4: the sandbox confines calls to this agent's workspace. If the
            # path cannot be resolved the probe falls back to the absence gate,
            # whose mode (allow / strict) is visible through dsh_tools_status().
            sandbox_root=self._dsh_sandbox_root(row),
            sandbox_absence=env_get("DSH_SANDBOX_ABSENCE") or None,
        )
        self._dsh_tools_status = build
        for skip in build.skipped:
            logger.info(
                "DSH tool skipped: %s (%s) %s",
                skip.plugin_id,
                skip.reason,
                skip.detail,
            )
        return list(build.tools)
