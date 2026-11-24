"""S5: the real ApprovalChannel is the repository's HITL pause/resume path.

The transport is replaced with scripted fakes so the pause, the resume decision
and all three failure kinds can be asserted without a graph or a browser. The
payload asserted here is exactly the ``HITLRequest`` the dashboard already
renders.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from langgraph.errors import GraphBubbleUp
from tests.dsh_integration.fixtures.tools import fixture_tool
from tests.unit.infra.dsh.plugin_fixtures import write_package

from happyclaw.infra.dsh.tools import build_dsh_plugin_tools
from happyclaw.infra.dsh.tools.guardrail import build_read_only_guardrail
from happyclaw.infra.plugins.bridge import ToolCall
from happyclaw.infra.plugins.bridge.hitl import HitlApprovalChannel
from happyclaw.infra.plugins.bridge.registry import DshToolRegistry

NAME = "dsh__demo__dsh_fixture_report"


class _PausingTransport:
    """Stands in for ``langgraph.types.interrupt`` inside a graph node."""

    pause_exceptions = (GraphBubbleUp,)

    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def ask(self, payload: Any) -> object:
        self.payloads.append(dict(payload))
        raise GraphBubbleUp()


class _AnsweringTransport:
    def __init__(self, answer: object) -> None:
        self.answer = answer
        self.payloads: list[dict[str, Any]] = []

    def ask(self, payload: Any) -> object:
        self.payloads.append(dict(payload))
        return self.answer


class _RaisingTransport:
    def __init__(self, exc: BaseException) -> None:
        self.exc = exc

    def ask(self, payload: Any) -> object:
        raise self.exc


def _passing_probe(tool_name: str, arguments: Any) -> Any:
    """Test double: this file covers HITL, not sandbox inspection."""
    from happyclaw.infra.plugins.sandbox import SandboxCoverage, SandboxProbeResult

    return SandboxProbeResult(True, "test probe", SandboxCoverage.NOT_APPLICABLE)


def _pipeline(executed: list[dict[str, Any]], *, hitl: bool, approval: Any) -> Any:
    def execute(arguments: Any, context: Any) -> dict[str, Any]:
        executed.append(dict(arguments))
        return dict(fixture_tool.EXPECTED_RESULT)

    registry = DshToolRegistry(plugin_id="dsh:demo")
    registry.register(replace(fixture_tool.build_definition(), execute=execute), scope="AGT")
    guardrail = build_read_only_guardrail(
        capability=_passing_probe,
        hitl=hitl,
        approval=approval,
        known_tools=[NAME],
        plugin_id="dsh:demo",
    )
    return registry.build_pipeline(scope="AGT", guardrail=guardrail)


def _call() -> ToolCall:
    return ToolCall(call_id="c-pause", name=NAME, arguments={"message": "x"})


async def test_pause_propagates_instead_of_becoming_a_denial() -> None:
    executed: list[dict[str, Any]] = []
    transport = _PausingTransport()
    pipeline = _pipeline(executed, hitl=True, approval=HitlApprovalChannel(transport=transport))

    with pytest.raises(GraphBubbleUp):
        await pipeline.invoke(_call())

    assert executed == []

    payload = transport.payloads[0]
    request = payload["action_requests"][0]
    assert request["name"] == NAME
    assert request["args"] == {"message": "x"}
    assert "dsh:demo" in request["description"]
    assert "dsh__demo__dsh_fixture_report" in request["description"]
    assert "MEDIUM" in request["description"]
    assert "read-only" in request["description"]
    assert payload["review_configs"][0]["allowed_decisions"] == ["approve", "reject"]


async def test_resume_approve_runs_the_tool() -> None:
    executed: list[dict[str, Any]] = []
    transport = _AnsweringTransport({"decisions": [{"type": "approve"}]})
    pipeline = _pipeline(executed, hitl=True, approval=HitlApprovalChannel(transport=transport))

    invocation = await pipeline.invoke(_call())

    assert not invocation.result.is_error
    assert executed == [{"message": "x"}]


async def test_resume_reject_denies_without_running() -> None:
    executed: list[dict[str, Any]] = []
    transport = _AnsweringTransport({"decisions": [{"type": "reject"}]})
    pipeline = _pipeline(executed, hitl=True, approval=HitlApprovalChannel(transport=transport))

    invocation = await pipeline.invoke(_call())

    assert invocation.result.is_error
    assert invocation.result.error is not None
    assert invocation.result.error["code"] == "TOOL_APPROVAL_DENIED"
    assert executed == []


@pytest.mark.parametrize(
    ("transport", "code"),
    [
        (_RaisingTransport(TimeoutError("no answer")), "TOOL_APPROVAL_TIMEOUT"),
        (_AnsweringTransport({}), "TOOL_APPROVAL_CLOSED"),
        (
            _RaisingTransport(RuntimeError("websocket closed")),
            "TOOL_APPROVAL_DISCONNECTED",
        ),
    ],
)
async def test_each_failure_kind_is_distinct_and_denies(transport: Any, code: str) -> None:
    executed: list[dict[str, Any]] = []
    pipeline = _pipeline(executed, hitl=True, approval=HitlApprovalChannel(transport=transport))

    invocation = await pipeline.invoke(_call())

    assert invocation.result.is_error
    assert invocation.result.error is not None
    assert invocation.result.error["code"] == code
    assert executed == []


async def test_late_decision_is_a_timeout_not_an_allow() -> None:
    executed: list[dict[str, Any]] = []
    clock_values = iter([0.0, 120.0])
    channel = HitlApprovalChannel(
        transport=_AnsweringTransport({"decisions": [{"type": "approve"}]}),
        timeout_s=60.0,
        clock=lambda: next(clock_values),
    )
    pipeline = _pipeline(executed, hitl=True, approval=channel)

    invocation = await pipeline.invoke(_call())

    assert invocation.result.is_error
    assert invocation.result.error is not None
    assert invocation.result.error["code"] == "TOOL_APPROVAL_TIMEOUT"
    assert executed == []


async def test_hitl_off_never_asks_a_human() -> None:
    executed: list[dict[str, Any]] = []
    transport = _PausingTransport()
    channel = HitlApprovalChannel(transport=transport)
    pipeline = _pipeline(executed, hitl=False, approval=channel)

    invocation = await pipeline.invoke(_call())

    assert not invocation.result.is_error
    assert executed == [{"message": "x"}]
    assert transport.payloads == []


async def test_mounted_tool_pauses_through_the_catalog(tmp_path: Path) -> None:
    """The tool list the agent binds pauses on the real HITL payload."""
    root = tmp_path / "local"
    write_package(root / "demo", "demo")
    transport = _PausingTransport()
    build = build_dsh_plugin_tools(
        scope="AGT",
        local_roots=[root],
        providers={
            "dsh:demo": lambda envelope: [replace(fixture_tool.build_definition(), name="echo")]
        },
        hitl=True,
        approval=HitlApprovalChannel(transport=transport),
    )
    assert [tool.name for tool in build.tools] == ["dsh__demo__echo"]

    with pytest.raises(GraphBubbleUp):
        await build.tools[0].ainvoke({"message": "x"})

    assert transport.payloads[0]["action_requests"][0]["name"] == "dsh__demo__echo"
