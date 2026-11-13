"""暂停异常必须穿透护栏与流水线，不能被记成审批拒绝（S5 先决条件）。"""

from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

import pytest

from octop.infra.plugins.bridge import (
    ApprovalRequest,
    CapabilityDecision,
    DshToolErrorCode,
    GuardrailContext,
    RiskAssessment,
    RiskLevel,
    ToolPipeline,
)
from octop.infra.plugins.bridge.approval import ToolGuardrail


class FakeGraphPause(Exception):
    """Stand-in for langgraph's GraphBubbleUp."""


class PausingChannel:
    """审批通道：请求时直接抛出暂停异常，并声明可穿透类型。"""

    pause_exceptions = (FakeGraphPause,)

    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error or FakeGraphPause("paused")

    def request(self, _request: ApprovalRequest) -> object:
        raise self.error


def _available(_tool: str, _args: Mapping[str, Any]) -> CapabilityDecision:
    return CapabilityDecision(True, "local sandbox ready")


def _high_risk(_tool: str, _args: Mapping[str, Any]) -> RiskAssessment:
    return RiskAssessment(RiskLevel.HIGH, "writes outside the workspace")


def _context() -> GuardrailContext:
    return GuardrailContext(
        call_id="call-1",
        tool_name="dsh__demo__write",
        arguments={"path": "/tmp/report.txt"},
        actor="tester",
    )


async def test_guardrail_inherits_pause_exceptions_from_channel() -> None:
    guardrail = ToolGuardrail(
        capability=_available,
        approval=PausingChannel(),
        assessor=_high_risk,
    )

    assert guardrail.passthrough_exceptions == (FakeGraphPause,)
    with pytest.raises(FakeGraphPause):
        await guardrail.evaluate(_context())
    assert guardrail.ledger.records == []


async def test_pipeline_approver_pause_exception_reaches_the_runtime() -> None:
    pipeline = ToolPipeline(lookup=lambda _name: None, approver=PausingChannel().request)

    with pytest.raises(FakeGraphPause):
        await pipeline._request_approval(SimpleNamespace(call_id="call-1", signal=None), "write")


async def test_pipeline_approver_other_errors_still_deny() -> None:
    channel = PausingChannel(error=RuntimeError("boom"))
    pipeline = ToolPipeline(lookup=lambda _name: None, approver=channel.request)

    code, message = await pipeline._request_approval(
        SimpleNamespace(call_id="call-1", signal=None), "write"
    )

    assert code == DshToolErrorCode.TOOL_DENIED
    assert "approval failed" in message
