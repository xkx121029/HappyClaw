"""S2 mounting: pipeline-only execution, traceable skips, no name overwrites."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from octop.infra.dsh.tools import (
    SKIP_NO_PROVIDER,
    SKIP_NAME_CONFLICT,
    SKIP_PROVIDER_FAILED,
    SKIP_UNSAFE_PERMISSION,
    build_dsh_plugin_tools,
)
from octop.infra.dsh.tools.guardrail import build_read_only_guardrail
from octop.infra.plugins.bridge import (
    ApprovalOutcome,
    ToolCall,
    ToolDefinition,
    ToolExecutionContext,
)
from octop.infra.plugins.bridge.registry import DshToolRegistry

from tests.dsh_integration.fixtures.tools import fixture_tool
from tests.unit.infra.dsh.plugin_fixtures import write_package

EXPOSED = "dsh__demo__dsh_fixture_report"


def _provider(calls: list[str], name: str | None = None):
    def provide(envelope: Any) -> list[ToolDefinition]:
        calls.append(envelope.id)
        definition = fixture_tool.build_definition()
        return [replace(definition, name=name) if name else definition]

    return provide


def _local_plugin(
    tmp_path: Path,
    *,
    name: str = "demo",
    permissions: tuple[str, ...] | None = None,
) -> Path:
    root = tmp_path / "local"
    write_package(root / name, name, permissions=permissions)
    return root


async def test_read_only_tool_is_mounted_and_executes(tmp_path: Path) -> None:
    provider_calls: list[str] = []
    build = build_dsh_plugin_tools(
        scope="AGT1",
        local_roots=[_local_plugin(tmp_path)],
        providers={"dsh:demo": _provider(provider_calls)},
        hitl=False,
    )

    assert [tool.name for tool in build.tools] == [EXPOSED]
    assert build.mounted == ["dsh:demo"]
    assert provider_calls == ["dsh:demo"]

    text = await build.tools[0].ainvoke({"message": "hi"})
    assert "fixture-tool-ok" in str(text)


async def test_pipeline_still_validates_arguments(tmp_path: Path) -> None:
    build = build_dsh_plugin_tools(
        scope="AGT1",
        local_roots=[_local_plugin(tmp_path)],
        providers={"dsh:demo": _provider([])},
        hitl=False,
    )
    tool = build.tools[0]

    # Bypass LangChain's own pre-validation to prove the bridge pipeline validates.
    result = await tool.coroutine(dry_run=True)

    assert "invalid arguments" in str(result).lower()
    assert "message" in str(result)


def test_unsafe_plugin_never_reaches_the_provider(tmp_path: Path) -> None:
    provider_calls: list[str] = []
    build = build_dsh_plugin_tools(
        scope="AGT1",
        local_roots=[_local_plugin(tmp_path, permissions=("exec",))],
        providers={"dsh:demo": _provider(provider_calls)},
        hitl=False,
    )

    assert build.tools == []
    assert build.mounted == []
    assert provider_calls == []
    assert [skip.reason for skip in build.skipped] == [SKIP_UNSAFE_PERMISSION]
    assert build.skipped[0].plugin_id == "dsh:demo"


def test_plugin_without_provider_is_reported(tmp_path: Path) -> None:
    build = build_dsh_plugin_tools(
        scope="AGT1",
        local_roots=[_local_plugin(tmp_path)],
        providers={},
        hitl=False,
    )

    assert build.tools == []
    assert [skip.reason for skip in build.skipped] == [SKIP_NO_PROVIDER]


def test_provider_failure_is_isolated_per_plugin(tmp_path: Path) -> None:
    root = tmp_path / "local"
    write_package(root / "bad", "bad")
    write_package(root / "good", "good")

    def explode(_envelope: Any) -> list[ToolDefinition]:
        raise RuntimeError("provider exploded")

    build = build_dsh_plugin_tools(
        scope="AGT1",
        local_roots=[root],
        providers={
            "dsh:bad": explode,
            "dsh:good": _provider([]),
        },
        hitl=False,
    )

    assert build.mounted == ["dsh:good"]
    assert [tool.name for tool in build.tools] == ["dsh__good__dsh_fixture_report"]
    failures = [skip for skip in build.skipped if skip.reason == SKIP_PROVIDER_FAILED]
    assert len(failures) == 1
    assert failures[0].plugin_id == "dsh:bad"
    assert "provider exploded" in failures[0].detail


def test_name_conflict_is_traceable_and_does_not_overwrite(tmp_path: Path) -> None:
    build = build_dsh_plugin_tools(
        scope="AGT1",
        local_roots=[_local_plugin(tmp_path)],
        providers={"dsh:demo": _provider([])},
        hitl=False,
        reserved_names=[EXPOSED],
    )

    assert build.tools == []
    assert build.mounted == []
    conflict = build.skipped[0]
    assert conflict.reason == SKIP_NAME_CONFLICT
    assert conflict.plugin_id == "dsh:demo"
    assert conflict.tool == EXPOSED
    assert conflict.detail


def _passing_probe(tool_name: str, arguments: Any) -> Any:
    """Test double: this file covers approval/risk, not sandbox inspection."""
    from octop.infra.plugins.sandbox import SandboxCoverage, SandboxProbeResult

    return SandboxProbeResult(True, "test probe", SandboxCoverage.NOT_APPLICABLE)


def _pipeline_with_guardrail(
    executed: list[dict[str, Any]],
    *,
    hitl: bool,
    approval: Any = None,
) -> tuple[DshToolRegistry, Any]:
    def execute(arguments: Any, context: ToolExecutionContext) -> dict[str, Any]:
        executed.append(dict(arguments))
        return dict(fixture_tool.EXPECTED_RESULT)

    registry = DshToolRegistry(plugin_id="dsh:demo")
    registry.register(
        replace(fixture_tool.build_definition(), execute=execute), scope="AGT1"
    )
    guardrail = build_read_only_guardrail(
        capability=_passing_probe,
        hitl=hitl,
        approval=approval,
        risky_tools={EXPOSED: ("exec",)},
        known_tools=[EXPOSED],
    )
    return registry, registry.build_pipeline(scope="AGT1", guardrail=guardrail)


async def test_high_risk_call_is_denied_when_hitl_is_off() -> None:
    executed: list[dict[str, Any]] = []
    _registry, pipeline = _pipeline_with_guardrail(executed, hitl=False)

    invocation = await pipeline.invoke(
        ToolCall(call_id="c1", name=EXPOSED, arguments={"message": "x"})
    )

    assert invocation.result.is_error
    assert invocation.result.error is not None
    assert invocation.result.error["code"] == "TOOL_APPROVAL_UNAVAILABLE"
    assert executed == []


class _Approval:
    def __init__(self, outcome: ApprovalOutcome) -> None:
        self.outcome = outcome
        self.requests: list[Any] = []

    def request(self, request: Any) -> str:
        self.requests.append(request)
        return str(self.outcome)


async def test_high_risk_call_runs_after_human_approval() -> None:
    executed: list[dict[str, Any]] = []
    approval = _Approval(ApprovalOutcome.ALLOWED_ONCE)
    _registry, pipeline = _pipeline_with_guardrail(
        executed, hitl=True, approval=approval
    )

    invocation = await pipeline.invoke(
        ToolCall(call_id="c2", name=EXPOSED, arguments={"message": "x"})
    )

    assert not invocation.result.is_error
    assert executed == [{"message": "x"}]
    assert len(approval.requests) == 1


async def test_high_risk_call_is_denied_when_human_rejects() -> None:
    executed: list[dict[str, Any]] = []
    approval = _Approval(ApprovalOutcome.REJECTED)
    _registry, pipeline = _pipeline_with_guardrail(
        executed, hitl=True, approval=approval
    )

    invocation = await pipeline.invoke(
        ToolCall(call_id="c3", name=EXPOSED, arguments={"message": "x"})
    )

    assert invocation.result.is_error
    assert invocation.result.error is not None
    assert invocation.result.error["code"] == "TOOL_APPROVAL_DENIED"
    assert executed == []
