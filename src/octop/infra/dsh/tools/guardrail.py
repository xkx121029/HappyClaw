"""Guardrail assembly for mounted DSH plugin tools.

Every mounted tool goes through ``ToolPipeline``; this module supplies the
guardrail that pipeline evaluates before dispatch:

* capability: supplied by the caller and, since S4, that is the plugin's real
  sandbox probe (or the explicit absence gate). There is no default "available"
  stub any more — a guardrail without a probe denies with
  ``TOOL_CAPABILITY_UNAVAILABLE``;
* risk: read-only tools are LOW. A tool that somehow carries a write/egress
  declaration is HIGH with a user-visible reason, so the approval layer decides;
* approval: attached only when ``OCTOP_DSH_HITL`` is on. With HITL off there is
  no approval channel, and ``ToolGuardrail`` denies a call that needs approval
  with ``TOOL_APPROVAL_UNAVAILABLE`` instead of letting it run.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from octop.infra.plugins.bridge.approval import (
    ApprovalChannel,
    ApprovalLedger,
    CapabilityProbe,
    RiskAssessment,
    RiskLevel,
    ToolGuardrail,
)

READ_ONLY_NOTE = "read-only DSH tool: no fs.write/exec/network declared"
UNKNOWN_TOOL_NOTE = "tool is not part of the read-only DSH mount set"


def _approval_note(plugin_id: str, tool_name: str) -> str:
    """Reason shown on the existing HITL card: who, what, and why."""
    owner = f"plugin {plugin_id}" if plugin_id else "DSH plugin"
    return (
        f"{owner} tool {tool_name}: HITL is enabled for DSH plugin tools, "
        "so a human must approve this read-only call before it runs"
    )


def build_read_only_guardrail(
    *,
    capability: CapabilityProbe,
    hitl: bool,
    approval: ApprovalChannel | None = None,
    risky_tools: Mapping[str, tuple[str, ...]] | None = None,
    known_tools: Iterable[str] | None = None,
    plugin_id: str = "",
    ledger: ApprovalLedger | None = None,
) -> ToolGuardrail:
    """Build the guardrail every mounted tool is bound to.

    ``capability`` is mandatory: it is the sandbox probe, and it is evaluated
    before any approval request, so a sandbox denial never reaches a human.
    Omitting it is not allowed; a guardrail built without one denies every call.

    ``risky_tools`` maps exposed tool names to the write/egress permissions they
    declare. It is empty for tools admitted by S2, but the parameter keeps the
    approval semantics in place for the stages that widen the gate.

    ``hitl`` means the operator opted into human approval for DSH plugin tools.
    In that mode every mounted tool is MEDIUM risk, so the call pauses on the
    existing ``hitl_required`` frame before it runs. With the switch off nothing
    is escalated, and a call that somehow still needs approval is denied because
    no channel is attached.
    """

    risky = {name: tuple(values) for name, values in (risky_tools or {}).items()}
    known = None if known_tools is None else frozenset(known_tools)

    def assess(tool_name: str, arguments: Mapping[str, object]) -> RiskAssessment:
        declared = risky.get(tool_name)
        if declared:
            return RiskAssessment(
                RiskLevel.HIGH,
                f"plugin {plugin_id or 'unknown'} tool {tool_name} declares "
                + ", ".join(declared),
            )
        if known is not None and tool_name not in known:
            return RiskAssessment(RiskLevel.HIGH, UNKNOWN_TOOL_NOTE)
        if hitl:
            return RiskAssessment(
                RiskLevel.MEDIUM,
                _approval_note(plugin_id, tool_name),
            )
        return RiskAssessment(RiskLevel.LOW, READ_ONLY_NOTE)

    return ToolGuardrail(
        capability=capability,
        approval=approval if hitl else None,
        assessor=assess,
        ledger=ledger,
    )


__all__ = ["READ_ONLY_NOTE", "UNKNOWN_TOOL_NOTE", "build_read_only_guardrail"]
