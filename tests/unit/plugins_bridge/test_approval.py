"""Tests for the three-layer guardrail (capability → approval → policy)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from octop.infra.plugins.bridge import (
    ApprovalOutcome,
    ApprovalRequest,
    CapabilityDecision,
    DshToolErrorCode,
    DshToolRegistry,
    GuardrailContext,
    InMemoryApprovalLedger,
    PolicyVerdict,
    RiskAssessment,
    RiskLevel,
    ToolCall,
    ToolDefinition,
    ToolOutputSpec,
    text_content,
)
from octop.infra.plugins.bridge.approval import ApprovalDecision, ToolGuardrail

WRITE_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {"path": {"type": "string"}},
    "required": ["path"],
    "additionalProperties": False,
}


def _available(_tool: str, _args: Mapping[str, Any]) -> CapabilityDecision:
    return CapabilityDecision(True, "local sandbox ready")


def _unavailable(_tool: str, _args: Mapping[str, Any]) -> CapabilityDecision:
    return CapabilityDecision(False, "no sandbox backend")


class FakeChannel:
    """In-process approval channel; records every request it receives."""

    def __init__(self, outcome: object = ApprovalOutcome.ALLOWED_ONCE) -> None:
        self.outcome = outcome
        self.requests: list[ApprovalRequest] = []

    def request(self, request: ApprovalRequest) -> object:
        self.requests.append(request)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def _context(call_id: str = "call-1") -> GuardrailContext:
    return GuardrailContext(
        call_id=call_id,
        tool_name="dsh__demo__write",
        arguments={"path": "/tmp/report.txt"},
        actor="tester",
    )


def _high_risk(_tool: str, _args: Mapping[str, Any]) -> RiskAssessment:
    return RiskAssessment(RiskLevel.HIGH, "writes outside the workspace")


async def test_no_approval_channel_denies() -> None:
    ledger = InMemoryApprovalLedger()
    guardrail = ToolGuardrail(
        capability=_available,
        approval=None,
        assessor=_high_risk,
        ledger=ledger,
    )

    decision = await guardrail.evaluate(_context())

    assert decision.action == "deny"
    assert decision.code is DshToolErrorCode.TOOL_APPROVAL_UNAVAILABLE
    assert len(ledger.records) == 1
    record = ledger.records[0]
    assert record.actor == "tester"
    assert record.tool_name == "dsh__demo__write"
    assert record.arguments == {"path": "/tmp/report.txt"}
    assert record.decision is ApprovalDecision.DENIED
    assert record.approval_required is True
    assert record.approval_outcome is None
    assert record.error_code == DshToolErrorCode.TOOL_APPROVAL_UNAVAILABLE.value


async def test_allowed_once_is_consumed_only_once() -> None:
    channel = FakeChannel(ApprovalOutcome.ALLOWED_ONCE)
    ledger = InMemoryApprovalLedger()
    guardrail = ToolGuardrail(
        capability=_available,
        approval=channel,
        assessor=_high_risk,
        ledger=ledger,
    )

    first = await guardrail.evaluate(_context())
    second = await guardrail.evaluate(_context())

    assert first.action == "allow"
    assert first.approval is ApprovalOutcome.ALLOWED_ONCE
    assert second.action == "deny"
    assert second.code is DshToolErrorCode.TOOL_APPROVAL_DENIED
    assert "already consumed" in second.reason
    assert len(channel.requests) == 1
    assert [record.decision for record in ledger.records] == [
        ApprovalDecision.ALLOWED,
        ApprovalDecision.DENIED,
    ]
    assert channel.requests[0].tool_name == "dsh__demo__write"
    assert channel.requests[0].arguments == {"path": "/tmp/report.txt"}


async def test_policy_hooks_cannot_loosen_a_denial() -> None:
    ledger = InMemoryApprovalLedger()
    guardrail = ToolGuardrail(
        capability=_available,
        assessor=None,
        policy_hooks=(
            lambda _ctx, _risk: PolicyVerdict(False, "workspace policy: read-only"),
            lambda _ctx, _risk: PolicyVerdict(True),
        ),
        ledger=ledger,
    )

    decision = await guardrail.evaluate(_context())

    assert decision.action == "deny"
    assert decision.code is DshToolErrorCode.TOOL_DENIED
    assert "workspace policy" in decision.reason
    assert ledger.records[-1].decision is ApprovalDecision.DENIED

    channel = FakeChannel(ApprovalOutcome.ALLOWED_ONCE)
    approved_then_blocked = ToolGuardrail(
        capability=_available,
        approval=channel,
        assessor=_high_risk,
        policy_hooks=(lambda _ctx, _risk: PolicyVerdict(False, "post-approval policy"),),
    )
    blocked = await approved_then_blocked.evaluate(_context())

    assert blocked.action == "deny"
    assert blocked.code is DshToolErrorCode.TOOL_DENIED
    assert blocked.approval is ApprovalOutcome.ALLOWED_ONCE
    assert "post-approval policy" in blocked.reason


async def test_risk_escalation_without_reason_is_denied() -> None:
    channel = FakeChannel(ApprovalOutcome.ALLOWED_ONCE)
    ledger = InMemoryApprovalLedger()
    guardrail = ToolGuardrail(
        capability=_available,
        approval=channel,
        assessor=lambda _tool, _args: RiskAssessment(RiskLevel.HIGH, "   "),
        ledger=ledger,
    )

    decision = await guardrail.evaluate(_context())

    assert decision.action == "deny"
    assert decision.code is DshToolErrorCode.TOOL_RISK_ESCALATION_INVALID
    assert decision.risk.level is RiskLevel.HIGH
    assert channel.requests == []
    assert ledger.records[0].error_code == DshToolErrorCode.TOOL_RISK_ESCALATION_INVALID.value
    assert "without a user-visible reason" in ledger.records[0].reason


async def test_capability_boundary_denies_before_approval() -> None:
    channel = FakeChannel(ApprovalOutcome.ALLOWED_ONCE)

    unavailable = ToolGuardrail(capability=_unavailable, approval=channel)
    denied = await unavailable.evaluate(_context())
    assert denied.action == "deny"
    assert denied.code is DshToolErrorCode.TOOL_CAPABILITY_UNAVAILABLE
    assert "no sandbox backend" in denied.reason

    missing = ToolGuardrail(capability=None, approval=channel)
    denied_missing = await missing.evaluate(_context())
    assert denied_missing.action == "deny"
    assert denied_missing.code is DshToolErrorCode.TOOL_CAPABILITY_UNAVAILABLE
    assert channel.requests == []


async def test_approval_channel_failure_is_recorded_as_failed() -> None:
    ledger = InMemoryApprovalLedger()
    guardrail = ToolGuardrail(
        capability=_available,
        approval=FakeChannel(RuntimeError("ui offline")),
        assessor=_high_risk,
        ledger=ledger,
    )

    decision = await guardrail.evaluate(_context())

    assert decision.action == "deny"
    assert decision.code is DshToolErrorCode.TOOL_APPROVAL_UNAVAILABLE
    assert len(ledger.records) == 1
    record = ledger.records[0]
    assert record.decision is ApprovalDecision.FAILED
    assert record.error_code == DshToolErrorCode.TOOL_APPROVAL_UNAVAILABLE.value
    assert "ui offline" in record.reason
    assert "Traceback" not in record.reason


async def test_pipeline_reports_guardrail_denial_without_dispatching() -> None:
    executed = {"value": False}

    async def execute(_args: Mapping[str, Any], _ctx: Any) -> dict[str, Any]:
        executed["value"] = True
        return {"ok": True}

    registry = DshToolRegistry(plugin_id="dsh:demo")
    registry.register(
        ToolDefinition(
            name="write",
            description="Write a file.",
            parameters=WRITE_PARAMETERS,
            output=ToolOutputSpec(
                schema={
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}},
                    "required": ["ok"],
                },
                render=lambda _args, _value: text_content("written"),
            ),
            execute=execute,
        )
    )
    events: list[str] = []
    guardrail = ToolGuardrail(capability=_unavailable)
    pipeline = registry.build_pipeline(
        guardrail=guardrail,
        on_event=lambda kind, _record: events.append(kind),
    )

    invocation = await pipeline.invoke(
        ToolCall(call_id="call-1", name="write", arguments={"path": "/tmp/report.txt"}),
    )

    assert executed["value"] is False
    assert invocation.result.is_error is True
    assert invocation.result.error is not None
    assert (
        invocation.result.error["code"]
        == DshToolErrorCode.TOOL_CAPABILITY_UNAVAILABLE.value
    )
    assert events == ["tool/call", "tool/result"]
