"""End-to-end chain: discovery → tool call → sandbox probe → approval → audit.

Each layer already had unit tests; this file proves they are wired together and
that no layer is skipped: the real DSH loader discovers the fixture plugin, the
real sandbox gate probes the arguments, the guardrail asks for approval, the
pipeline executes the fixture tool once, and both ledgers keep a record.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from happyclaw.infra.plugins.bridge import (
    ApprovalOutcome,
    ApprovalRequest,
    CapabilityDecision,
    DshToolErrorCode,
    DshToolRegistry,
    InMemoryApprovalLedger,
    RiskAssessment,
    RiskLevel,
    ToolCall,
)
from happyclaw.infra.plugins.bridge.approval import ApprovalDecision, ToolGuardrail
from happyclaw.infra.plugins.runtime.dsh_plugin import DshPluginLoader
from happyclaw.infra.plugins.sandbox import (
    InMemorySandboxLedger,
    PluginSandbox,
    SandboxCapability,
    SandboxErrorCode,
    ToolInspection,
)
from tests.dsh_integration.fixture_specs import DSH_FIXTURE_DIR, DSH_FIXTURE_ID
from tests.dsh_integration.fixtures.tools import fixture_tool

EXPOSED_NAME = f"dsh__dsh-fixture-tool__{fixture_tool.TOOL_NAME}"
SANDBOX_PATH_ARGUMENT = {"message": "notes.txt"}
# Escapes the plugin workspace, so the real gate inspects the argument and
# denies on the path boundary rather than on a missing permission.
ESCAPING_PATH_ARGUMENT = {"message": "../outside.txt"}


class RecordingChannel:
    """Approves once and keeps every request so the approval layer is visible."""

    def __init__(self) -> None:
        self.requests: list[ApprovalRequest] = []

    def request(self, request: ApprovalRequest) -> ApprovalOutcome:
        self.requests.append(request)
        return ApprovalOutcome.ALLOWED_ONCE


def _discover() -> Any:
    envelopes = DshPluginLoader().discover([DSH_FIXTURE_DIR], strict=True)
    assert [envelope.id for envelope in envelopes] == [DSH_FIXTURE_ID]
    return envelopes[0]


def _registry(executed: list[dict[str, Any]]) -> tuple[DshToolRegistry, str]:
    envelope = _discover()
    assert "tool" in {capability.value for capability in envelope.capabilities}

    registry = DshToolRegistry(plugin_id=envelope.id)
    base = fixture_tool.build_definition()

    async def counted(
        args: Mapping[str, Any],
        ctx: Any,
    ) -> dict[str, Any]:
        executed.append(dict(args))
        return base.execute(args, ctx)

    registry.register(replace(base, execute=counted))
    exposed = registry.exposed_name(fixture_tool.TOOL_NAME)
    assert exposed == EXPOSED_NAME
    assert registry.get(exposed) is not None
    return registry, exposed


def _sandbox(
    plugin_id: str,
    root: Path,
) -> tuple[PluginSandbox, InMemorySandboxLedger]:
    ledger = InMemorySandboxLedger()
    sandbox = PluginSandbox(
        plugin_id=plugin_id,
        workspace_root=root,
        declarations={fixture_tool.TOOL_NAME: [SandboxCapability.FS_READ]},
        permissions=[SandboxCapability.FS_READ],
        # The fixture's free-form ``message`` is declared as the inspected path
        # so the real gate runs without changing the shared fixture tool.
        inspections={fixture_tool.TOOL_NAME: ToolInspection(path_args=("message",))},
        ledger=ledger,
    )
    return sandbox, ledger


def _probe(sandbox: PluginSandbox, calls: list[dict[str, Any]]):
    def probe(_exposed: str, arguments: Mapping[str, Any]) -> Any:
        calls.append(dict(arguments))
        return sandbox.probe(fixture_tool.TOOL_NAME, arguments)

    return probe


def _guardrail(
    probe: Any,
    channel: RecordingChannel,
    ledger: InMemoryApprovalLedger,
    *,
    strict: bool = False,
) -> ToolGuardrail:
    return ToolGuardrail(
        capability=probe,
        approval=channel,
        assessor=lambda _tool, _args: RiskAssessment(
            RiskLevel.HIGH,
            "writes inside the workspace",
        ),
        ledger=ledger,
        require_sandbox_backing=strict,
    )


async def test_full_chain_with_sandbox_backing_executes_and_audits(tmp_path: Path) -> None:
    executed: list[dict[str, Any]] = []
    probe_calls: list[dict[str, Any]] = []
    registry, exposed = _registry(executed)
    envelope_id = DSH_FIXTURE_ID

    sandbox, sandbox_ledger = _sandbox(envelope_id, tmp_path)
    channel = RecordingChannel()
    approvals = InMemoryApprovalLedger()
    events: list[str] = []
    pipeline = registry.build_pipeline(
        guardrail=_guardrail(_probe(sandbox, probe_calls), channel, approvals),
        on_event=lambda kind, _record: events.append(kind),
    )

    invocation = await pipeline.invoke(
        ToolCall(call_id="e2e-backed", name=exposed, arguments=SANDBOX_PATH_ARGUMENT),
    )

    # Execution layer: ran exactly once and returned the fixture value.
    assert invocation.result.is_error is False
    assert executed == [SANDBOX_PATH_ARGUMENT]
    assert json.loads(invocation.text) == fixture_tool.EXPECTED_RESULT
    assert events == ["tool/call", "tool/result"]

    # Sandbox layer: probed the same arguments, nothing denied.
    assert probe_calls == [SANDBOX_PATH_ARGUMENT]
    assert sandbox_ledger.records == []

    # Approval layer: asked once, with the sandbox backing visible on the request.
    assert len(channel.requests) == 1
    request = channel.requests[0]
    assert request.tool_name == exposed
    assert request.arguments == SANDBOX_PATH_ARGUMENT
    assert request.sandbox_backed is True
    assert request.sandbox_coverage == "covered"
    assert "HIGH" in request.reason

    # Audit layer: the approval ledger keeps the whole conclusion.
    record = approvals.records[0]
    assert record.decision is ApprovalDecision.ALLOWED
    assert record.approval_outcome == "allowed-once"
    assert record.sandbox_backed is True
    assert record.sandbox_coverage == "covered"
    assert record.sandbox_checked == ("message",)
    assert record.error_code is None


async def test_sandbox_denial_skips_approval_and_execution(tmp_path: Path) -> None:
    executed: list[dict[str, Any]] = []
    probe_calls: list[dict[str, Any]] = []
    registry, exposed = _registry(executed)

    sandbox, sandbox_ledger = _sandbox(DSH_FIXTURE_ID, tmp_path)
    channel = RecordingChannel()
    approvals = InMemoryApprovalLedger()
    events: list[str] = []
    pipeline = registry.build_pipeline(
        guardrail=_guardrail(_probe(sandbox, probe_calls), channel, approvals),
        on_event=lambda kind, _record: events.append(kind),
    )

    invocation = await pipeline.invoke(
        ToolCall(call_id="e2e-denied", name=exposed, arguments=ESCAPING_PATH_ARGUMENT),
    )

    assert invocation.result.is_error is True
    assert invocation.result.error is not None
    assert (
        invocation.result.error["code"]
        == DshToolErrorCode.TOOL_CAPABILITY_UNAVAILABLE.value
    )
    # The sandbox ran, but approval and execution were never reached.
    assert probe_calls == [ESCAPING_PATH_ARGUMENT]
    assert channel.requests == []
    assert executed == []
    assert events == ["tool/call", "tool/result"]

    # Sandbox audit keeps the denial, including the path it actually inspected.
    assert len(sandbox_ledger.records) == 1
    denial = sandbox_ledger.records[0]
    assert denial.stage == "probe"
    assert denial.plugin_id == DSH_FIXTURE_ID
    assert denial.tool_name == fixture_tool.TOOL_NAME
    assert denial.capability == SandboxCapability.FS_READ.value
    assert denial.target == "../outside.txt"
    assert denial.error_code == SandboxErrorCode.PATH_OUTSIDE_WORKSPACE.value

    # Approval audit keeps the denial with the coverage that led to it: the
    # probe did inspect the path (covered) and refused.
    record = approvals.records[0]
    assert record.decision is ApprovalDecision.DENIED
    assert record.sandbox_backed is False
    assert record.sandbox_coverage == "covered"
    assert record.sandbox_checked == ("message",)
    assert record.error_code == DshToolErrorCode.TOOL_CAPABILITY_UNAVAILABLE.value


async def test_no_sandbox_plus_strict_mode_denies_with_distinct_code(tmp_path: Path) -> None:
    executed: list[dict[str, Any]] = []
    registry, exposed = _registry(executed)
    channel = RecordingChannel()
    approvals = InMemoryApprovalLedger()

    def no_sandbox(_tool: str, _args: Mapping[str, Any]) -> CapabilityDecision:
        return CapabilityDecision(True, "no sandbox attached")

    pipeline = registry.build_pipeline(
        guardrail=_guardrail(no_sandbox, channel, approvals, strict=True),
    )

    invocation = await pipeline.invoke(
        ToolCall(call_id="e2e-unbacked", name=exposed, arguments=SANDBOX_PATH_ARGUMENT),
    )

    assert invocation.result.is_error is True
    assert invocation.result.error is not None
    assert (
        invocation.result.error["code"]
        == DshToolErrorCode.TOOL_SANDBOX_BACKING_MISSING.value
    )
    assert "coverage=unknown" in invocation.text
    assert channel.requests == []
    assert executed == []

    record = approvals.records[0]
    assert record.decision is ApprovalDecision.DENIED
    assert record.sandbox_backed is False
    assert record.sandbox_coverage == "unknown"
    assert record.error_code == DshToolErrorCode.TOOL_SANDBOX_BACKING_MISSING.value
