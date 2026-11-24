"""Tests for the HITL-backed approval channel.

The transport fake mirrors the payloads the repository's HITL resume path
actually produces (``{"decisions": [{"type": "approve" | "reject"}]}``), so the
adapter is exercised without a graph, a network, or a real user.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from happyclaw.infra.plugins.bridge import (
    ApprovalChannelError,
    ApprovalOutcome,
    ApprovalRequest,
    CapabilityDecision,
    DshToolErrorCode,
    DshToolRegistry,
    GuardrailContext,
    HitlApprovalChannel,
    InMemoryApprovalLedger,
    RiskAssessment,
    RiskLevel,
    ToolCall,
    ToolDefinition,
    ToolOutputSpec,
    build_hitl_request,
    text_content,
)
from happyclaw.infra.plugins.bridge.approval import ApprovalDecision, ToolGuardrail

WRITE_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {"path": {"type": "string"}},
    "required": ["path"],
    "additionalProperties": False,
}

APPROVE: dict[str, Any] = {"decisions": [{"type": "approve"}]}
REJECT: dict[str, Any] = {"decisions": [{"type": "reject", "message": "not this time"}]}


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeHitlTransport:
    """Test double for the HITL pause; records every payload it was asked."""

    def __init__(
        self,
        *payloads: object,
        error: BaseException | None = None,
        delay_s: float = 0.0,
        clock: FakeClock | None = None,
        pause_exceptions: tuple[type[BaseException], ...] = (),
    ) -> None:
        self._payloads = list(payloads)
        self.error = error
        self.delay_s = delay_s
        self.clock = clock
        self.pause_exceptions = pause_exceptions
        self.asked: list[dict[str, Any]] = []

    def ask(self, payload: Mapping[str, Any]) -> object:
        self.asked.append(dict(payload))
        if self.clock is not None and self.delay_s:
            self.clock.advance(self.delay_s)
        if self.error is not None:
            raise self.error
        if not self._payloads:
            return None
        return self._payloads.pop(0)


class FakeGraphPause(Exception):
    """Stands in for langgraph's ``GraphBubbleUp``."""


class SetSignal:
    def is_set(self) -> bool:
        return True


def _available(_tool: str, _args: Mapping[str, Any]) -> CapabilityDecision:
    return CapabilityDecision(True, "local sandbox ready")


def _high_risk(_tool: str, _args: Mapping[str, Any]) -> RiskAssessment:
    return RiskAssessment(RiskLevel.HIGH, "writes outside the workspace")


def _context(call_id: str = "call-1") -> GuardrailContext:
    return GuardrailContext(
        call_id=call_id,
        tool_name="dsh__demo__write",
        arguments={"path": "/tmp/report.txt"},
        actor="tester",
    )


def _guardrail(
    transport: FakeHitlTransport,
    *,
    ledger: InMemoryApprovalLedger | None = None,
    timeout_s: float | None = 30 * 60.0,
    clock: FakeClock | None = None,
    passthrough_exceptions: tuple[type[BaseException], ...] = (),
) -> ToolGuardrail:
    return ToolGuardrail(
        capability=_available,
        approval=HitlApprovalChannel(transport, timeout_s=timeout_s, clock=clock or FakeClock()),
        assessor=_high_risk,
        ledger=ledger,
        passthrough_exceptions=passthrough_exceptions,
    )


def _write_registry(executed: dict[str, bool]) -> DshToolRegistry:
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
    return registry


def test_payload_matches_the_existing_hitl_contract() -> None:
    request = ApprovalRequest(
        call_id="call-1",
        reason="[HIGH] dsh__demo__write: writes outside the workspace",
        tool_name="dsh__demo__write",
        arguments={"path": "/tmp/report.txt"},
    )

    payload = build_hitl_request(request)

    assert payload == {
        "action_requests": [
            {
                "name": "dsh__demo__write",
                "args": {"path": "/tmp/report.txt"},
                "description": "[HIGH] dsh__demo__write: writes outside the workspace",
            }
        ],
        "review_configs": [
            {
                "action_name": "dsh__demo__write",
                "allowed_decisions": ["approve", "reject"],
            }
        ],
    }


async def test_approve_once_then_same_call_id_is_denied() -> None:
    transport = FakeHitlTransport(APPROVE)
    ledger = InMemoryApprovalLedger()
    guardrail = _guardrail(transport, ledger=ledger)

    first = await guardrail.evaluate(_context())
    second = await guardrail.evaluate(_context())

    assert first.action == "allow"
    assert first.approval is ApprovalOutcome.ALLOWED_ONCE
    assert second.action == "deny"
    assert second.code is DshToolErrorCode.TOOL_APPROVAL_DENIED
    assert "already consumed" in second.reason
    assert len(transport.asked) == 1
    assert [record.decision for record in ledger.records] == [
        ApprovalDecision.ALLOWED,
        ApprovalDecision.DENIED,
    ]


async def test_reject_denies() -> None:
    decision = await _guardrail(FakeHitlTransport(REJECT)).evaluate(_context())

    assert decision.action == "deny"
    assert decision.code is DshToolErrorCode.TOOL_APPROVAL_DENIED


async def test_late_decision_is_a_timeout() -> None:
    clock = FakeClock()
    transport = FakeHitlTransport(APPROVE, delay_s=1801, clock=clock)
    ledger = InMemoryApprovalLedger()

    decision = await _guardrail(
        transport,
        ledger=ledger,
        timeout_s=1800,
        clock=clock,
    ).evaluate(_context())

    assert decision.action == "deny"
    assert decision.code is DshToolErrorCode.TOOL_APPROVAL_TIMEOUT
    assert "above the 1800s limit" in decision.reason
    assert ledger.records[0].decision is ApprovalDecision.FAILED
    assert ledger.records[0].error_code == DshToolErrorCode.TOOL_APPROVAL_TIMEOUT.value


async def test_closed_ui_denies() -> None:
    decision = await _guardrail(FakeHitlTransport()).evaluate(_context())

    assert decision.action == "deny"
    assert decision.code is DshToolErrorCode.TOOL_APPROVAL_CLOSED
    assert "closed without a decision" in decision.reason


async def test_disconnected_channel_denies_and_never_runs_the_tool() -> None:
    executed = {"value": False}
    registry = _write_registry(executed)
    guardrail = _guardrail(
        FakeHitlTransport(error=ConnectionError("bridge peer dropped")),
    )
    events: list[str] = []
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
    assert invocation.result.error["code"] == DshToolErrorCode.TOOL_APPROVAL_DISCONNECTED.value
    assert events == ["tool/call", "tool/result"]


async def test_timeout_denies_and_never_runs_the_tool() -> None:
    executed = {"value": False}
    registry = _write_registry(executed)
    clock = FakeClock()
    guardrail = _guardrail(
        FakeHitlTransport(APPROVE, delay_s=3600, clock=clock),
        timeout_s=1800,
        clock=clock,
    )
    pipeline = registry.build_pipeline(guardrail=guardrail)

    invocation = await pipeline.invoke(
        ToolCall(call_id="call-1", name="write", arguments={"path": "/tmp/report.txt"}),
    )

    assert executed["value"] is False
    assert invocation.result.error is not None
    assert invocation.result.error["code"] == DshToolErrorCode.TOOL_APPROVAL_TIMEOUT.value


async def test_pause_exception_reaches_the_runtime() -> None:
    transport = FakeHitlTransport(
        error=FakeGraphPause("paused"),
        pause_exceptions=(FakeGraphPause,),
    )
    guardrail = _guardrail(
        transport,
        passthrough_exceptions=transport.pause_exceptions,
    )

    with pytest.raises(FakeGraphPause):
        await guardrail.evaluate(_context())

    assert guardrail.ledger.records == []


def test_gone_session_is_disconnected_without_asking() -> None:
    transport = FakeHitlTransport(APPROVE)
    channel = HitlApprovalChannel(transport)

    with pytest.raises(ApprovalChannelError) as failure:
        channel.request(
            ApprovalRequest(
                call_id="call-1",
                reason="[HIGH] dsh__demo__write: writes outside the workspace",
                tool_name="dsh__demo__write",
                arguments={"path": "/tmp/report.txt"},
                signal=SetSignal(),
            )
        )

    assert failure.value.kind == "disconnected"
    assert transport.asked == []
