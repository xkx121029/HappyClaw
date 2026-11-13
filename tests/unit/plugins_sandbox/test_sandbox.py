"""Behavior tests for the plugin sandbox (declaration, path, command, audit).

Every test uses a temporary workspace and a fake executor: nothing outside
``tmp_path`` is touched, no real command runs, and no network call is made.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from octop.infra.plugins.bridge import (
    ApprovalOutcome,
    ApprovalRequest,
    DshToolErrorCode,
    GuardrailContext,
    RiskAssessment,
    RiskLevel,
    ToolGuardrail,
)
from octop.infra.plugins.sandbox import (
    MAX_REASON_CHARS,
    MAX_TARGET_CHARS,
    TRUNCATION_MARKER,
    CommandRequest,
    ExecutorOutput,
    InMemorySandboxLedger,
    JsonlCheckLedger,
    JsonlSandboxLedger,
    PluginSandbox,
    PreparedCommand,
    SandboxAbsenceMode,
    SandboxAuditRecord,
    SandboxCapability,
    SandboxCheckLedger,
    SandboxCoverage,
    SandboxDeniedError,
    SandboxErrorCode,
    SandboxLedger,
    SandboxLimits,
    ToolInspection,
    format_denial_summary,
    load_check_records,
    load_denial_records,
    new_audit_record,
    resolve_sandbox_gate,
    summarize_check_file,
    summarize_denial_file,
    summarize_denials,
)
from octop.infra.plugins.sandbox.command import CommandExecutor


class FakeExecutor:
    """Records prepared commands and returns a canned output."""

    def __init__(self, output: ExecutorOutput) -> None:
        self.output = output
        self.calls: list[PreparedCommand] = []

    def run(self, command: PreparedCommand) -> ExecutorOutput:
        self.calls.append(command)
        return self.output


class SpyApprovalChannel:
    """Counts approval requests; a sandbox denial must leave this empty."""

    def __init__(self) -> None:
        self.requests: list[ApprovalRequest] = []

    def request(self, request: ApprovalRequest) -> ApprovalOutcome:
        self.requests.append(request)
        return ApprovalOutcome.ALLOWED_ONCE


def _sandbox(
    workspace: Path,
    *,
    declarations: Mapping[str, object] | None = None,
    permissions: object = (),
    inspections: Mapping[str, ToolInspection] | None = None,
    limits: SandboxLimits | None = None,
    executor: CommandExecutor | None = None,
    ledger: SandboxLedger | None = None,
    check_ledger: SandboxCheckLedger | None = None,
    check_flush_every: int = 100,
) -> PluginSandbox:
    if declarations is None:
        declarations = {"write_note": {"fs.write"}, "read_note": {"fs.read"}}
    return PluginSandbox(
        plugin_id="octop:demo-toolkit",
        workspace_root=workspace,
        declarations=declarations,
        permissions=permissions,
        inspections=inspections,
        limits=limits,
        executor=executor,
        ledger=ledger,
        check_ledger=check_ledger,
        check_flush_every=check_flush_every,
    )


def test_path_escape_is_denied(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    ledger = InMemorySandboxLedger()
    sandbox = _sandbox(
        workspace,
        permissions={"fs.read", "fs.write"},
        ledger=ledger,
    )

    with pytest.raises(SandboxDeniedError) as relative_escape:
        sandbox.resolve_path("write_note", SandboxCapability.FS_WRITE, "../outside.txt")
    assert relative_escape.value.code is SandboxErrorCode.PATH_OUTSIDE_WORKSPACE
    assert "超出" in relative_escape.value.message
    assert str(workspace) in relative_escape.value.message

    with pytest.raises(SandboxDeniedError) as absolute_escape:
        sandbox.resolve_path(
            "write_note",
            SandboxCapability.FS_WRITE,
            tmp_path / "outside.txt",
        )
    assert absolute_escape.value.code is SandboxErrorCode.PATH_OUTSIDE_WORKSPACE

    inside = sandbox.resolve_path("write_note", SandboxCapability.FS_WRITE, "notes/a.md")
    assert inside == (workspace / "notes" / "a.md").resolve()

    assert len(ledger.records) == 2
    assert {record.error_code for record in ledger.records} == {
        SandboxErrorCode.PATH_OUTSIDE_WORKSPACE.value
    }
    assert ledger.records[0].plugin_id == "octop:demo-toolkit"
    assert ledger.records[0].capability == SandboxCapability.FS_WRITE.value


def test_undeclared_capability_is_denied(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    ledger = InMemorySandboxLedger()
    sandbox = _sandbox(
        workspace,
        permissions={"fs.read", "fs.write"},
        ledger=ledger,
    )

    with pytest.raises(SandboxDeniedError) as undeclared_tool:
        sandbox.resolve_path("delete_everything", SandboxCapability.FS_WRITE, "a.txt")
    assert undeclared_tool.value.code is SandboxErrorCode.CAPABILITY_UNDECLARED

    with pytest.raises(SandboxDeniedError) as undeclared_capability:
        sandbox.resolve_path("read_note", SandboxCapability.FS_WRITE, "a.txt")
    assert undeclared_capability.value.code is SandboxErrorCode.CAPABILITY_UNDECLARED
    assert "写文件" in undeclared_capability.value.message

    assert [record.error_code for record in ledger.records] == [
        SandboxErrorCode.CAPABILITY_UNDECLARED.value,
        SandboxErrorCode.CAPABILITY_UNDECLARED.value,
    ]


def test_command_timeout_is_denied(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    ledger = InMemorySandboxLedger()
    executor = FakeExecutor(ExecutorOutput(exit_code=-1, timed_out=True))
    sandbox = _sandbox(
        workspace,
        declarations={"run_script": {"exec"}},
        permissions={"exec"},
        limits=SandboxLimits(default_timeout_s=5.0, max_timeout_s=60.0),
        executor=executor,
        ledger=ledger,
    )

    with pytest.raises(SandboxDeniedError) as timed_out:
        sandbox.run_command("run_script", CommandRequest(argv=("slow-task", "--flag")))
    assert timed_out.value.code is SandboxErrorCode.COMMAND_TIMEOUT
    assert "没有结束" in timed_out.value.message
    assert len(executor.calls) == 1
    assert executor.calls[0].timeout_s == 5.0
    assert ledger.records[-1].capability == SandboxCapability.EXEC.value

    over_cap = CommandRequest(argv=("slow-task",), timeout_s=10_000.0)
    with pytest.raises(SandboxDeniedError) as rejected_before_run:
        sandbox.run_command("run_script", over_cap)
    assert rejected_before_run.value.code is SandboxErrorCode.COMMAND_INVALID
    assert "超过上限" in rejected_before_run.value.message
    assert len(executor.calls) == 1


def test_output_over_limit_is_truncated_and_marked(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    executor = FakeExecutor(
        ExecutorOutput(exit_code=0, stdout=b"a" * 5000, stderr=b"b" * 2000)
    )
    sandbox = _sandbox(
        workspace,
        declarations={"run_script": {"exec"}},
        permissions={"exec"},
        limits=SandboxLimits(max_output_bytes=100),
        executor=executor,
    )

    outcome = sandbox.run_command(
        "run_script",
        CommandRequest(argv=("noisy",), max_output_bytes=100),
    )
    assert outcome.truncated is True
    assert len(outcome.stdout) + len(outcome.stderr) == 100
    assert outcome.dropped_bytes == 6900
    assert outcome.stdout == b"a" * 100

    clamped = sandbox.run_command(
        "run_script",
        CommandRequest(argv=("noisy",), max_output_bytes=10_000_000),
    )
    assert clamped.truncated is True
    assert len(clamped.stdout) + len(clamped.stderr) == 100
    assert executor.calls[-1].max_output_bytes == 100


async def test_sandbox_denial_skips_approval(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    ledger = InMemorySandboxLedger()
    sandbox = _sandbox(workspace, permissions={"fs.read"}, ledger=ledger)
    channel = SpyApprovalChannel()

    def high_risk(_tool: str, _arguments: Mapping[str, Any]) -> RiskAssessment:
        return RiskAssessment(RiskLevel.HIGH, "写入工作区文件")

    guardrail = ToolGuardrail(
        capability=lambda tool, arguments: sandbox.probe(tool, arguments),
        approval=channel,
        assessor=high_risk,
        approval_threshold=RiskLevel.MEDIUM,
    )

    decision = await guardrail.evaluate(
        GuardrailContext(
            call_id="call-1",
            tool_name="write_note",
            arguments={"path": "notes/a.md"},
        )
    )

    assert decision.action == "deny"
    assert decision.code is DshToolErrorCode.TOOL_CAPABILITY_UNAVAILABLE
    assert channel.requests == []
    assert len(ledger.records) == 1
    assert ledger.records[0].error_code == SandboxErrorCode.PERMISSION_OUT_OF_SCOPE.value
    assert ledger.records[0].tool_name == "write_note"


def _high_risk(_tool: str, _arguments: Mapping[str, Any]) -> RiskAssessment:
    return RiskAssessment(RiskLevel.HIGH, "写入工作区文件")


def _guarded(sandbox: PluginSandbox, channel: SpyApprovalChannel) -> ToolGuardrail:
    return ToolGuardrail(
        capability=lambda tool, arguments: sandbox.probe(tool, arguments),
        approval=channel,
        assessor=_high_risk,
        approval_threshold=RiskLevel.MEDIUM,
    )


async def test_probe_denies_escaping_path_before_approval(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    ledger = InMemorySandboxLedger()
    sandbox = _sandbox(
        workspace,
        declarations={"write_note": {"fs.write"}, "run_script": {"exec"}},
        permissions={"fs.write", "exec"},
        inspections={
            "write_note": ToolInspection(path_args=("path",)),
            "run_script": ToolInspection(command_arg="argv", cwd_arg="cwd"),
        },
        executor=FakeExecutor(ExecutorOutput(exit_code=0)),
        ledger=ledger,
    )
    channel = SpyApprovalChannel()
    guardrail = _guarded(sandbox, channel)

    path_decision = await guardrail.evaluate(
        GuardrailContext(
            call_id="call-path",
            tool_name="write_note",
            arguments={"path": "../escape.txt"},
        )
    )
    assert path_decision.action == "deny"
    assert path_decision.code is DshToolErrorCode.TOOL_CAPABILITY_UNAVAILABLE
    assert "超出" in path_decision.reason

    command_decision = await guardrail.evaluate(
        GuardrailContext(
            call_id="call-command",
            tool_name="run_script",
            arguments={"argv": ["echo", "ok"], "cwd": "../outside"},
        )
    )
    assert command_decision.action == "deny"
    assert "超出" in command_decision.reason

    assert channel.requests == []
    assert [record.stage for record in ledger.records] == ["probe", "probe"]
    assert {record.error_code for record in ledger.records} == {
        SandboxErrorCode.PATH_OUTSIDE_WORKSPACE.value
    }


async def test_probe_reports_not_applicable_without_checkable_arguments(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    ledger = InMemorySandboxLedger()
    sandbox = _sandbox(
        workspace,
        permissions={"fs.read", "fs.write"},
        inspections={"write_note": ToolInspection(path_args=("path",))},
        ledger=ledger,
    )

    result = sandbox.probe("write_note", {"payload": {"path": "../escape.txt"}})
    assert result.available is True
    assert result.coverage is SandboxCoverage.NOT_APPLICABLE
    assert result.backed is False
    assert "未覆盖" in result.reason
    assert "背书" in result.reason
    assert result.checked == ()
    assert ledger.records == []

    channel = SpyApprovalChannel()
    decision = await _guarded(sandbox, channel).evaluate(
        GuardrailContext(
            call_id="call-uncovered",
            tool_name="write_note",
            arguments={"payload": {"path": "../escape.txt"}},
        )
    )
    assert decision.action == "allow"
    assert len(channel.requests) == 1


def test_execution_denial_after_uncovered_probe_is_recorded_as_miss(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    ledger = InMemorySandboxLedger()
    sandbox = _sandbox(
        workspace,
        permissions={"fs.read", "fs.write"},
        inspections={"write_note": ToolInspection(path_args=("path",))},
        ledger=ledger,
    )

    probe_result = sandbox.probe("write_note", {"payload": "../escape.txt"})
    assert probe_result.coverage is SandboxCoverage.NOT_APPLICABLE
    assert probe_result.available is True

    with pytest.raises(SandboxDeniedError) as denied:
        sandbox.resolve_path("write_note", SandboxCapability.FS_WRITE, "../escape.txt")

    assert denied.value.code is SandboxErrorCode.PATH_OUTSIDE_WORKSPACE
    assert denied.value.details["early_check_miss"] is True
    assert (
        denied.value.details["root_error_code"]
        == SandboxErrorCode.PATH_OUTSIDE_WORKSPACE.value
    )

    record = ledger.records[-1]
    assert record.error_code == SandboxErrorCode.EARLY_CHECK_MISS.value
    assert record.root_error_code == SandboxErrorCode.PATH_OUTSIDE_WORKSPACE.value
    assert record.stage == "execute"
    assert record.reason.startswith("前移漏判")


def test_declared_permission_allows_tool(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    sandbox = _sandbox(
        workspace,
        declarations={"write_note": {"fs.write"}},
        permissions={"fs.write"},
    )

    result = sandbox.probe("write_note", {})

    assert result.available is True
    assert sandbox.permissions_declared is True
    assert sandbox.resolve_path(
        "write_note", SandboxCapability.FS_WRITE, "notes/a.md"
    ) == (workspace / "notes" / "a.md").resolve()


def test_permission_outside_plugin_declaration_is_denied_with_distinct_code(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    ledger = InMemorySandboxLedger()
    sandbox = _sandbox(
        workspace,
        declarations={"write_note": {"fs.write"}},
        permissions={"fs.read"},
        ledger=ledger,
    )

    result = sandbox.probe("write_note", {})
    assert result.available is False
    assert result.error_code is SandboxErrorCode.PERMISSION_OUT_OF_SCOPE
    assert "未声明该权限" in result.reason

    with pytest.raises(SandboxDeniedError) as denied:
        sandbox.resolve_path("write_note", SandboxCapability.FS_WRITE, "a.txt")
    assert denied.value.code is SandboxErrorCode.PERMISSION_OUT_OF_SCOPE
    assert denied.value.code is not SandboxErrorCode.PATH_OUTSIDE_WORKSPACE
    assert denied.value.code is not SandboxErrorCode.COMMAND_TIMEOUT
    assert ledger.records[-1].error_code == SandboxErrorCode.PERMISSION_OUT_OF_SCOPE.value


def test_undeclared_permissions_allow_tool_that_needs_none(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    ledger = InMemorySandboxLedger()
    sandbox = _sandbox(
        workspace,
        declarations={"ping": set()},
        permissions=(),
        ledger=ledger,
    )

    result = sandbox.probe("ping", {})

    assert result.available is True
    assert result.coverage is SandboxCoverage.NOT_APPLICABLE
    assert result.backed is False
    assert sandbox.permissions_declared is False
    assert ledger.records == []


def test_undeclared_permissions_deny_tool_that_needs_one(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    ledger = InMemorySandboxLedger()
    sandbox = _sandbox(
        workspace,
        declarations={"read_note": {"fs.read"}},
        permissions=(),
        ledger=ledger,
    )

    result = sandbox.probe("read_note", {})
    assert result.available is False
    assert result.error_code is SandboxErrorCode.PERMISSION_UNDECLARED
    assert "未声明任何权限" in result.reason
    assert sandbox.permissions_declared is False

    with pytest.raises(SandboxDeniedError) as denied:
        sandbox.resolve_path("read_note", SandboxCapability.FS_READ, "a.txt")
    assert denied.value.code is SandboxErrorCode.PERMISSION_UNDECLARED
    assert ledger.records[-1].error_code == SandboxErrorCode.PERMISSION_UNDECLARED.value


class _BrokenLedger:
    """Ledger whose sink is unavailable; the decision must survive it."""

    def __init__(self) -> None:
        self.calls = 0

    def append(self, record: SandboxAuditRecord) -> None:
        self.calls += 1
        raise OSError("disk full")


def test_jsonl_ledger_reads_back_after_restart(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    ledger_path = tmp_path / "dsh-sandbox" / "denials.jsonl"
    first = _sandbox(
        workspace,
        permissions={"fs.write"},
        ledger=JsonlSandboxLedger(ledger_path),
    )
    with pytest.raises(SandboxDeniedError):
        first.resolve_path("write_note", SandboxCapability.FS_WRITE, "../escape.txt")

    # "Restart": only the file on disk carries state into this read.
    reloaded = load_denial_records(ledger_path)
    assert len(reloaded) == 1
    assert reloaded[0].plugin_id == "octop:demo-toolkit"
    assert reloaded[0].error_code == SandboxErrorCode.PATH_OUTSIDE_WORKSPACE.value

    second = _sandbox(
        workspace,
        permissions={"fs.write"},
        ledger=JsonlSandboxLedger(ledger_path),
    )
    with pytest.raises(SandboxDeniedError):
        second.resolve_path("write_note", SandboxCapability.FS_WRITE, "../escape.txt")
    assert len(load_denial_records(ledger_path)) == 2


def test_ledger_write_failure_keeps_denial_and_original_code(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    ledger = _BrokenLedger()
    sandbox = _sandbox(workspace, permissions={"fs.write"}, ledger=ledger)

    with caplog.at_level(logging.WARNING, logger="octop.infra.plugins.sandbox.gate"):
        with pytest.raises(SandboxDeniedError) as denied:
            sandbox.resolve_path("write_note", SandboxCapability.FS_WRITE, "../escape.txt")

    assert denied.value.code is SandboxErrorCode.PATH_OUTSIDE_WORKSPACE
    assert ledger.calls == 1
    assert any("审计写入失败" in record.getMessage() for record in caplog.records)


def _record(
    *,
    plugin_id: str,
    error_code: str,
    stage: str,
    timestamp: str,
) -> SandboxAuditRecord:
    return SandboxAuditRecord(
        record_id=f"{plugin_id}-{error_code}-{stage}-{timestamp}",
        timestamp=timestamp,
        plugin_id=plugin_id,
        tool_name="tool",
        operation="fs",
        capability="fs.write",
        target="a.txt",
        stage=stage,
        error_code=error_code,
        root_error_code=None,
        reason="测试",
    )


def test_summary_counts_by_plugin_code_and_stage() -> None:
    records = [
        _record(
            plugin_id="octop:a",
            error_code=SandboxErrorCode.PATH_OUTSIDE_WORKSPACE.value,
            stage="probe",
            timestamp="2026-11-11T10:00:00+00:00",
        ),
        _record(
            plugin_id="octop:a",
            error_code=SandboxErrorCode.PATH_OUTSIDE_WORKSPACE.value,
            stage="execute",
            timestamp="2026-11-12T10:00:00+00:00",
        ),
        _record(
            plugin_id="octop:b",
            error_code=SandboxErrorCode.COMMAND_TIMEOUT.value,
            stage="execute",
            timestamp="2026-11-12T11:00:00+00:00",
        ),
    ]

    window = summarize_denials(
        records,
        since="2026-11-12T00:00:00+00:00",
        until="2026-11-12T23:59:59+00:00",
    )
    assert window.total == 2
    assert window.by_stage == {"execute": 2}
    assert window.by_error_code == {
        SandboxErrorCode.COMMAND_TIMEOUT.value: 1,
        SandboxErrorCode.PATH_OUTSIDE_WORKSPACE.value: 1,
    }
    assert window.by_plugin[0].plugin_id == "octop:a"
    assert window.by_plugin[0].total == 1

    full = summarize_denials(records)
    assert full.total == 3
    assert [item.plugin_id for item in full.by_plugin] == ["octop:a", "octop:b"]
    assert full.by_plugin[0].by_stage == {"probe": 1, "execute": 1}
    text = format_denial_summary(full)
    assert "octop:a" in text
    assert "probe 1 次" in text


def test_overlong_target_and_reason_are_truncated_and_marked(tmp_path: Path) -> None:
    long_target = "command " + "x" * 500
    long_reason = "原因 " + "y" * 500
    record = new_audit_record(
        plugin_id="octop:a",
        tool_name="run",
        operation="exec",
        capability="exec",
        target=long_target,
        stage="execute",
        error_code=SandboxErrorCode.COMMAND_INVALID.value,
        root_error_code=None,
        reason=long_reason,
    )

    assert record.truncated is True
    assert record.target is not None
    assert record.target.endswith(TRUNCATION_MARKER)
    assert len(record.target) == MAX_TARGET_CHARS + len(TRUNCATION_MARKER)
    assert long_target not in record.target
    assert record.reason.endswith(TRUNCATION_MARKER)
    assert len(record.reason) == MAX_REASON_CHARS + len(TRUNCATION_MARKER)
    assert long_reason not in record.reason

    ledger_path = tmp_path / "denials.jsonl"
    JsonlSandboxLedger(ledger_path).append(record)
    reloaded = load_denial_records(ledger_path)
    assert reloaded[0].truncated is True
    assert reloaded[0].target == record.target


def test_successful_probe_leaves_check_trace(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    check_path = tmp_path / "checks.jsonl"
    sandbox = _sandbox(
        workspace,
        permissions={"fs.write"},
        inspections={"write_note": ToolInspection(path_args=("path",))},
        check_ledger=JsonlCheckLedger(check_path),
        check_flush_every=1,
    )

    result = sandbox.probe("write_note", {"path": "notes/a.md"})
    assert result.available is True
    assert result.coverage is SandboxCoverage.COVERED
    sandbox.resolve_path("write_note", SandboxCapability.FS_WRITE, "notes/a.md")
    sandbox.flush_checks()

    records = load_check_records(check_path)
    assert len(records) == 1
    assert records[0].plugin_id == "octop:demo-toolkit"
    assert records[0].tool_name == "write_note"
    assert records[0].stage == "probe"
    assert records[0].coverage == SandboxCoverage.COVERED.value
    assert records[0].checked == ("path",)
    assert records[0].count == 1


def test_check_and_denial_summaries_stay_separate(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    denial_path = tmp_path / "denials.jsonl"
    check_path = tmp_path / "checks.jsonl"
    sandbox = _sandbox(
        workspace,
        permissions={"fs.write"},
        inspections={"write_note": ToolInspection(path_args=("path",))},
        ledger=JsonlSandboxLedger(denial_path),
        check_ledger=JsonlCheckLedger(check_path),
        check_flush_every=1,
    )

    sandbox.probe("write_note", {"path": "notes/a.md"})
    denied = sandbox.probe("write_note", {"path": "../escape.txt"})
    assert denied.available is False
    assert denied.error_code is SandboxErrorCode.PATH_OUTSIDE_WORKSPACE
    sandbox.flush_checks()

    denials = summarize_denial_file(denial_path)
    checks = summarize_check_file(check_path)
    assert denials.total == 1
    assert checks.total == 1
    assert denials.by_error_code == {
        SandboxErrorCode.PATH_OUTSIDE_WORKSPACE.value: 1,
    }
    assert checks.by_coverage == {SandboxCoverage.COVERED.value: 1}


def test_check_aggregation_is_bounded_under_high_frequency(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    check_path = tmp_path / "checks.jsonl"
    sandbox = _sandbox(
        workspace,
        permissions={"fs.write"},
        inspections={"write_note": ToolInspection(path_args=("path",))},
        check_ledger=JsonlCheckLedger(check_path),
        check_flush_every=100,
    )

    for _ in range(1000):
        result = sandbox.probe("write_note", {"path": "notes/a.md"})
        assert result.available is True
    sandbox.flush_checks()

    lines = [
        line
        for line in check_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) <= 11
    summary = summarize_check_file(check_path)
    assert summary.total == 1000
    assert summary.by_coverage == {SandboxCoverage.COVERED.value: 1000}


async def test_absent_sandbox_default_mode_warns_and_allows(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="octop.infra.plugins.sandbox.absence"):
        gate = resolve_sandbox_gate(None, plugin_id="octop:demo-toolkit")

    assert gate is not None
    assert gate.mode is SandboxAbsenceMode.ALLOW
    assert "沙箱未启用" in caplog.text
    assert "路径与权限检查" in caplog.text

    result = gate.probe("write_note", {"path": "notes/a.md"})
    assert result.available is True
    assert result.coverage is SandboxCoverage.UNAVAILABLE
    assert result.backed is False
    assert result.inspected is False

    channel = SpyApprovalChannel()
    guardrail = ToolGuardrail(
        capability=gate.probe,
        approval=channel,
        assessor=_high_risk,
        approval_threshold=RiskLevel.MEDIUM,
    )
    decision = await guardrail.evaluate(
        GuardrailContext(
            call_id="call-absent",
            tool_name="write_note",
            arguments={"path": "notes/a.md"},
        )
    )
    assert decision.action == "allow"
    assert len(channel.requests) == 1


def test_absent_sandbox_strict_mode_denies_with_distinct_code() -> None:
    gate = resolve_sandbox_gate(
        None,
        mode="strict",
        plugin_id="octop:demo-toolkit",
        required_capabilities={"write_note": {"fs.write"}, "ping": set()},
    )

    assert gate is not None
    denied = gate.probe("write_note", {"path": "notes/a.md"})
    assert denied.available is False
    assert denied.error_code is SandboxErrorCode.NOT_ASSEMBLED
    assert SandboxErrorCode.NOT_ASSEMBLED.value in denied.reason
    assert "fs.write" in denied.reason

    # 不需要权限的工具在严格模式下仍按最小权限放行。
    assert gate.probe("ping").available is True

    # 未提供能力声明的工具无法证明"不需要权限"，按需要权限拒绝。
    unknown = gate.probe("not_declared")
    assert unknown.available is False
    assert unknown.error_code is SandboxErrorCode.NOT_ASSEMBLED
