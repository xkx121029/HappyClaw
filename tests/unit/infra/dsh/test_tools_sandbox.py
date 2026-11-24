"""S4: the capability probe is a real sandbox, not a rubber stamp.

Covers the five behaviours the stage promised:

* a path escape is refused by the sandbox and never reaches approval;
* a capability the plugin did not declare is refused;
* a missing sandbox is loud (one warning), recorded as ``unavailable``, and can
  be switched from allow to a distinct strict denial;
* a covered call is actually backed, and the approval record says so;
* "checked but nothing covered" is distinguishable from "never checked".
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
from tests.unit.infra.dsh.plugin_fixtures import write_package

from happyclaw.infra.dsh.tools import build_dsh_plugin_tools
from happyclaw.infra.plugins.bridge import (
    ApprovalOutcome,
    InMemoryApprovalLedger,
    ToolDefinition,
    ToolOutputSpec,
    text_content,
)
from happyclaw.infra.plugins.sandbox import SandboxErrorCode, ToolInspection

TOOL = "dsh_fixture_report"


class _Channel:
    """Approval channel that records requests and approves once."""

    pause_exceptions: tuple[type[BaseException], ...] = ()

    def __init__(self, outcome: ApprovalOutcome = ApprovalOutcome.ALLOWED_ONCE) -> None:
        self.outcome = outcome
        self.requests: list[Any] = []

    def request(self, request: Any) -> ApprovalOutcome:
        self.requests.append(request)
        return self.outcome


def _definition(executed: list[dict[str, Any]]) -> ToolDefinition:
    def execute(arguments: Any, context: Any) -> dict[str, Any]:
        executed.append(dict(arguments))
        return {"ok": True, "message": "ran", "checks": []}

    return ToolDefinition(
        name=TOOL,
        description="Fixture tool with an optional path argument.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["message"],
            "additionalProperties": False,
        },
        output=ToolOutputSpec(
            schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "message": {"type": "string"},
                    "checks": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["ok", "message", "checks"],
                "additionalProperties": False,
            },
            render=lambda _args, value: text_content(str(value.get("message", ""))),
        ),
        execute=execute,
    )


def _build(
    tmp_path: Path,
    *,
    name: str,
    permissions: tuple[str, ...] | None,
    executed: list[dict[str, Any]],
    sandbox_root: Path | None = None,
    absence: str | None = "allow",
    hitl: bool = False,
    approval: Any = None,
    ledger: Any = None,
    declarations: dict[str, Any] | None = None,
    inspections: dict[str, Any] | None = None,
) -> Any:
    root = tmp_path / "local"
    write_package(root / name, name, permissions=permissions)
    return build_dsh_plugin_tools(
        scope="AGT1",
        local_roots=[root],
        providers={f"dsh:{name}": lambda _envelope: [_definition(executed)]},
        hitl=hitl,
        approval=approval,
        ledger=ledger,
        sandbox_root=sandbox_root,
        capability_declarations=declarations,
        inspections=inspections,
        sandbox_absence=absence,
    )


async def _invoke(build: Any, arguments: dict[str, Any]) -> str:
    return str(await build.tools[0].ainvoke(arguments))


async def test_path_escape_is_denied_before_approval(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    executed: list[dict[str, Any]] = []
    channel = _Channel()
    ledger = InMemoryApprovalLedger()
    build = _build(
        tmp_path,
        name="escape",
        permissions=("fs.read",),
        executed=executed,
        sandbox_root=workspace,
        hitl=True,
        approval=channel,
        ledger=ledger,
        inspections={
            "dsh:escape": {TOOL: ToolInspection(path_args=("path",))},
        },
    )

    text = await _invoke(build, {"path": "../escape.txt", "message": "x"})

    assert "SANDBOX_PATH_OUTSIDE_WORKSPACE" in text
    assert executed == []
    assert channel.requests == []
    record = ledger.records[-1]
    assert record.error_code == "TOOL_SANDBOX_DENIED"
    assert record.sandbox_inspected is True


async def test_undeclared_permission_is_denied(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    executed: list[dict[str, Any]] = []
    channel = _Channel()
    ledger = InMemoryApprovalLedger()
    build = _build(
        tmp_path,
        name="undeclared",
        permissions=(),
        executed=executed,
        sandbox_root=workspace,
        hitl=True,
        approval=channel,
        ledger=ledger,
        declarations={"dsh:undeclared": {TOOL: ("fs.read",)}},
    )

    text = await _invoke(build, {"path": "notes/a.md", "message": "x"})

    assert "SANDBOX_PERMISSION_UNDECLARED" in text
    assert executed == []
    assert channel.requests == []
    assert ledger.records[-1].sandbox_backed is False


async def test_absent_sandbox_warns_once_and_records_unavailable(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    executed: list[dict[str, Any]] = []
    channel = _Channel()
    ledger = InMemoryApprovalLedger()
    with caplog.at_level(logging.WARNING):
        build = _build(
            tmp_path,
            name="absentallow",
            permissions=("fs.read",),
            executed=executed,
            sandbox_root=None,
            absence="allow",
            hitl=True,
            approval=channel,
            ledger=ledger,
        )

    await _invoke(build, {"message": "x"})

    assert executed == [{"message": "x"}]
    assert len(channel.requests) == 1
    assert any("沙箱未启用" in record.message for record in caplog.records)
    report = build.report()
    assert report["sandbox"]["mode"] == "allow"
    assert report["sandbox"]["assembled"] is False
    record = ledger.records[-1]
    assert record.sandbox_coverage == "unavailable"
    assert record.sandbox_backed is False
    assert record.sandbox_inspected is False


async def test_absent_sandbox_strict_denies_with_its_own_code(
    tmp_path: Path,
) -> None:
    executed: list[dict[str, Any]] = []
    channel = _Channel()
    ledger = InMemoryApprovalLedger()
    build = _build(
        tmp_path,
        name="absentstrict",
        permissions=("fs.read",),
        executed=executed,
        sandbox_root=None,
        absence="strict",
        hitl=True,
        approval=channel,
        ledger=ledger,
    )

    text = await _invoke(build, {"message": "x"})

    assert "沙箱未启用" in text
    assert executed == []
    assert channel.requests == []
    record = ledger.records[-1]
    assert record.error_code == "TOOL_SANDBOX_NOT_ASSEMBLED"
    assert record.sandbox_coverage == "unavailable"
    assert build.report()["sandbox"]["mode"] == "strict"


async def test_covered_call_is_backed_and_recorded(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    executed: list[dict[str, Any]] = []
    channel = _Channel()
    ledger = InMemoryApprovalLedger()
    build = _build(
        tmp_path,
        name="covered",
        permissions=("fs.read",),
        executed=executed,
        sandbox_root=workspace,
        hitl=True,
        approval=channel,
        ledger=ledger,
        inspections={"dsh:covered": {TOOL: ToolInspection(path_args=("path",))}},
    )

    await _invoke(build, {"path": "notes/a.md", "message": "x"})

    assert executed == [{"path": "notes/a.md", "message": "x"}]
    record = ledger.records[-1]
    assert record.sandbox_backed is True
    assert record.sandbox_coverage == "covered"
    assert record.sandbox_checked == ("path",)
    assert record.sandbox_inspected is True
    assert build.report()["sandbox"]["assembled"] is True


async def test_checked_nothing_differs_from_never_checked(tmp_path: Path) -> None:
    """A declared plan with no matching argument is not the same as no plan."""

    workspace = tmp_path / "ws"
    workspace.mkdir()
    plan_ledger = InMemoryApprovalLedger()
    planned = _build(
        tmp_path / "with-plan",
        name="planned",
        permissions=("fs.read",),
        executed=[],
        sandbox_root=workspace,
        hitl=False,
        ledger=plan_ledger,
        inspections={"dsh:planned": {TOOL: ToolInspection(path_args=("path",))}},
    )
    await _invoke(planned, {"message": "x"})
    planned_record = plan_ledger.records[-1]

    bare_ledger = InMemoryApprovalLedger()
    bare = _build(
        tmp_path / "without-plan",
        name="bare",
        permissions=("fs.read",),
        executed=[],
        sandbox_root=workspace,
        hitl=False,
        ledger=bare_ledger,
    )
    await _invoke(bare, {"message": "x"})
    bare_record = bare_ledger.records[-1]

    assert planned_record.sandbox_checked == ()
    assert planned_record.sandbox_inspected is True
    assert planned_record.sandbox_coverage == "not_applicable"
    assert bare_record.sandbox_checked == ()
    assert bare_record.sandbox_inspected is False
    assert bare_record.sandbox_coverage == "not_applicable"


def test_invalid_absence_policy_falls_back_to_strict(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        build = _build(
            tmp_path,
            name="bogus",
            permissions=("fs.read",),
            executed=[],
            sandbox_root=None,
            absence="bogus",
            hitl=False,
        )

    assert build.report()["sandbox"]["mode"] == "strict"
    assert any("invalid" in record.message for record in caplog.records)


def test_sandbox_error_codes_are_distinct() -> None:
    assert SandboxErrorCode.PATH_OUTSIDE_WORKSPACE.value != SandboxErrorCode.NOT_ASSEMBLED.value
