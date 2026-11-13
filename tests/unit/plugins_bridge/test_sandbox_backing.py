"""Tests for sandbox coverage/backing in the approval guardrail.

The probe is the real ``octop.infra.plugins.sandbox`` result type, so these
tests also prove the bridge's duck-typed read still matches the sandbox
interface. Nothing under ``plugins/sandbox`` is modified.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from octop.infra.plugins.bridge import (
    ApprovalOutcome,
    CapabilityDecision,
    DshToolErrorCode,
    DshToolRegistry,
    GuardrailContext,
    InMemoryApprovalLedger,
    RiskAssessment,
    RiskLevel,
    ToolCall,
    ToolDefinition,
    ToolOutputSpec,
    text_content,
)
from octop.infra.plugins.bridge.approval import ApprovalDecision, ToolGuardrail
from octop.infra.plugins.sandbox.inspection import SandboxCoverage, SandboxProbeResult

PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {"path": {"type": "string"}},
    "required": ["path"],
    "additionalProperties": False,
}


class FakeChannel:
    """Approves once and records how often it was asked."""

    def __init__(self, outcome: ApprovalOutcome = ApprovalOutcome.ALLOWED_ONCE) -> None:
        self.outcome = outcome
        self.requests: list[Any] = []

    def request(self, request: Any) -> ApprovalOutcome:
        self.requests.append(request)
        return self.outcome


def _covered(_tool: str, _args: Mapping[str, Any]) -> SandboxProbeResult:
    return SandboxProbeResult(
        True,
        "沙箱已覆盖：已检查 path。",
        SandboxCoverage.COVERED,
        ("path",),
    )


def _not_applicable(_tool: str, _args: Mapping[str, Any]) -> SandboxProbeResult:
    return SandboxProbeResult(
        True,
        "沙箱未覆盖：参数里没有可检查的路径或命令，本次审批没有沙箱背书。",
        SandboxCoverage.NOT_APPLICABLE,
    )


def _plain(_tool: str, _args: Mapping[str, Any]) -> CapabilityDecision:
    return CapabilityDecision(True, "local sandbox ready")


def _high_risk(_tool: str, _args: Mapping[str, Any]) -> RiskAssessment:
    return RiskAssessment(RiskLevel.HIGH, "writes outside the workspace")


def _context(call_id: str = "call-1") -> GuardrailContext:
    return GuardrailContext(
        call_id=call_id,
        tool_name="dsh__demo__write",
        arguments={"path": "/tmp/report.txt"},
    )


def _guardrail(
    probe: Any,
    *,
    channel: FakeChannel | None = None,
    ledger: InMemoryApprovalLedger | None = None,
    strict: bool = False,
) -> tuple[ToolGuardrail, FakeChannel]:
    channel = channel or FakeChannel()
    guardrail = ToolGuardrail(
        capability=probe,
        approval=channel,
        assessor=_high_risk,
        ledger=ledger,
        require_sandbox_backing=strict,
    )
    return guardrail, channel


def _write_registry(executed: dict[str, bool]) -> DshToolRegistry:
    async def execute(_args: Mapping[str, Any], _ctx: Any) -> dict[str, Any]:
        executed["value"] = True
        return {"ok": True}

    registry = DshToolRegistry(plugin_id="dsh:demo")
    registry.register(
        ToolDefinition(
            name="write",
            description="Write a file.",
            parameters=PARAMETERS,
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


async def test_covered_probe_is_backed_and_allows() -> None:
    ledger = InMemoryApprovalLedger()
    guardrail, channel = _guardrail(_covered, ledger=ledger, strict=True)

    decision = await guardrail.evaluate(_context())

    assert decision.action == "allow"
    assert decision.backing.backed is True
    assert decision.backing.coverage == "covered"
    assert decision.backing.checked == ("path",)
    assert len(channel.requests) == 1
    record = ledger.records[0]
    assert record.sandbox_backed is True
    assert record.sandbox_coverage == "covered"
    assert record.sandbox_checked == ("path",)


async def test_strict_mode_denies_unbacked_call_without_running_the_tool() -> None:
    executed = {"value": False}
    registry = _write_registry(executed)
    channel = FakeChannel()
    guardrail, _ = _guardrail(_not_applicable, channel=channel, strict=True)
    events: list[str] = []
    pipeline = registry.build_pipeline(
        guardrail=guardrail,
        on_event=lambda kind, _record: events.append(kind),
    )

    invocation = await pipeline.invoke(
        ToolCall(call_id="call-1", name="write", arguments={"path": "/tmp/report.txt"}),
    )

    assert executed["value"] is False
    assert channel.requests == []
    assert invocation.result.is_error is True
    assert invocation.result.error is not None
    assert (
        invocation.result.error["code"]
        == DshToolErrorCode.TOOL_SANDBOX_BACKING_MISSING.value
    )
    assert events == ["tool/call", "tool/result"]
    record = guardrail.ledger.records[0]
    assert record.decision is ApprovalDecision.DENIED
    assert record.sandbox_backed is False
    assert record.sandbox_coverage == "not_applicable"


async def test_default_mode_allows_unbacked_call_but_records_backed_false() -> None:
    ledger = InMemoryApprovalLedger()
    guardrail, channel = _guardrail(_not_applicable, ledger=ledger, strict=False)

    decision = await guardrail.evaluate(_context())

    assert decision.action == "allow"
    assert decision.approval is ApprovalOutcome.ALLOWED_ONCE
    assert decision.backing.backed is False
    assert decision.backing.coverage == "not_applicable"
    assert len(channel.requests) == 1
    record = ledger.records[0]
    assert record.sandbox_backed is False
    assert record.sandbox_coverage == "not_applicable"


async def test_probe_without_coverage_is_unknown_not_a_pass() -> None:
    guardrail, channel = _guardrail(_plain, strict=True)

    decision = await guardrail.evaluate(_context())

    assert decision.action == "deny"
    assert decision.code is DshToolErrorCode.TOOL_SANDBOX_BACKING_MISSING
    assert decision.backing.coverage == "unknown"
    assert decision.backing.backed is False
    assert channel.requests == []
