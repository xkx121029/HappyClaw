"""S10: invoking a granted bundle really runs it, and every failure is typed.

The tests never spawn Node. They assert the parts that decide *whether* a
process may run and *what* reaches it:

* the three host preconditions each fail with their own code;
* the command handed to the sandbox carries the node binary, the entry URL and
  the sandbox's own cwd / timeout / output cap;
* a runner result maps onto a published service or a typed failure;
* a granted bundle is mounted without a ``tool`` capability, and is still
  refused when there is no workspace to confine the command.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from octop.infra.dsh.tools import build_dsh_plugin_tools
from octop.infra.dsh.tools import runtime as runtime_module
from octop.infra.dsh.tools.runtime import (
    CAPABILITY,
    RESULT_MARKER,
    ExecGrant,
    RuntimeTools,
    exec_declarations,
    exec_permissions,
    resolve_exec_plugins,
)
from octop.infra.plugins.bridge.errors import DshToolError, DshToolErrorCode
from octop.infra.plugins.runtime.contract import (
    PluginEnvelope,
    PluginKind,
    PluginSource,
    PluginSourceKind,
)
from octop.infra.plugins.sandbox.command import CommandOutcome

PLUGIN = "dsh:fixture-bundle"
ENTRY = "lib/index.js"
_PATCH = "- insert:\n    - id: fixture\n      name: fixture-plugin\n"


def _write_package(
    tmp_path: Path, *, entry: str = ENTRY, create_entry: bool = True
) -> Path:
    """Write a minimal DSH bundle package and return its ``package.json`` path."""

    package = tmp_path / "local" / "fixture-bundle"
    package.mkdir(parents=True, exist_ok=True)
    (package / "package.json").write_text(
        json.dumps(
            {
                "name": "fixture-bundle",
                "version": "0.2.2-rc.1",
                "main": entry,
                "dsh": {"bundle": {"patch": "./cordis.patch.yml"}},
                "engines": {"node": ">=24.9.0"},
            }
        ),
        encoding="utf-8",
    )
    (package / "cordis.patch.yml").write_text(_PATCH, encoding="utf-8")
    if create_entry:
        target = package / entry
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("export default {};\n", encoding="utf-8")
    return package / "package.json"


def _envelope(package_json: Path) -> PluginEnvelope:
    return PluginEnvelope(
        id=PLUGIN,
        kind=PluginKind.DSH,
        version="0.2.2-rc.1",
        entry=ENTRY,
        source=PluginSource(PluginSourceKind.LOCAL, str(package_json)),
        metadata={"required_engines": {"node": ">=24.9.0"}},
    )


def _cordis(tmp_path: Path) -> Path:
    """The vendored Cordis entry ``find_cordis_entry`` walks up to find."""

    entry = tmp_path / "vendor" / "cordis" / "lib" / "index.js"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text("export class Context {}\n", encoding="utf-8")
    return entry


class _Sandbox:
    """Fake sandbox: records the request and replays one prepared outcome."""

    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.payload = payload
        self.calls: list[tuple[str, Any]] = []

    def run_command(self, tool_name: str, request: Any) -> CommandOutcome:
        self.calls.append((tool_name, request))
        stdout = b""
        if self.payload is not None:
            stdout = (RESULT_MARKER + json.dumps(self.payload) + "\n").encode()
        return CommandOutcome(
            exit_code=0,
            stdout=stdout,
            stderr=b"",
            truncated=False,
            dropped_bytes=0,
            timeout_s=float(request.timeout_s or 0),
        )


def _tools(tmp_path: Path, sandbox: Any) -> RuntimeTools:
    tools = RuntimeTools(grant=ExecGrant(plugin_id=PLUGIN, workspace_root=tmp_path))
    tools.bind({"startup": f"dsh__{PLUGIN}__startup"}, sandbox)
    return tools


def _invoke(tools: RuntimeTools, envelope: PluginEnvelope, **arguments: Any) -> Any:
    return tools._invoke(envelope, arguments)


def test_exec_plugins_parsing() -> None:
    assert resolve_exec_plugins(" dsh:a , dsh:b ,,") == frozenset({"dsh:a", "dsh:b"})
    assert resolve_exec_plugins("") == frozenset()


def test_exec_permission_is_host_granted_only(tmp_path: Path) -> None:
    envelope = _envelope(_write_package(tmp_path))
    permissions = exec_permissions(envelope)

    assert "exec" in {kind.value for kind in permissions}
    assert envelope.permissions == (), "the grant must not widen the envelope"
    assert exec_declarations(envelope, ["dsh__x__startup"]) == {
        "dsh__x__startup": ("exec",)
    }


def test_missing_package_reports_not_loaded(tmp_path: Path) -> None:
    envelope = _envelope(tmp_path / "gone" / "package.json")

    with pytest.raises(DshToolError) as caught:
        _invoke(_tools(tmp_path, _Sandbox()), envelope)

    assert caught.value.code is DshToolErrorCode.TOOL_RUNTIME_PLUGIN_NOT_LOADED


def test_missing_entry_reports_entry_missing(tmp_path: Path) -> None:
    envelope = _envelope(_write_package(tmp_path, create_entry=False))
    sandbox = _Sandbox()

    with pytest.raises(DshToolError) as caught:
        _invoke(_tools(tmp_path, sandbox), envelope)

    assert caught.value.code is DshToolErrorCode.TOOL_RUNTIME_ENTRY_MISSING
    assert sandbox.calls == [], "nothing may run when the entry is absent"


def test_node_missing_reports_engine_unsatisfied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    envelope = _envelope(_write_package(tmp_path))
    monkeypatch.setattr(runtime_module, "host_node_version", lambda _exe="": None)

    with pytest.raises(DshToolError) as caught:
        _invoke(_tools(tmp_path, _Sandbox()), envelope)

    assert caught.value.code is DshToolErrorCode.TOOL_RUNTIME_ENGINE_UNSATISFIED


def test_old_node_reports_engine_unsatisfied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    envelope = _envelope(_write_package(tmp_path))
    monkeypatch.setattr(runtime_module, "host_node_version", lambda _exe="": "22.11.0")

    with pytest.raises(DshToolError) as caught:
        _invoke(_tools(tmp_path, _Sandbox()), envelope)

    assert caught.value.code is DshToolErrorCode.TOOL_RUNTIME_ENGINE_UNSATISFIED


def test_missing_sandbox_refuses_to_execute(tmp_path: Path) -> None:
    envelope = _envelope(_write_package(tmp_path))

    with pytest.raises(DshToolError) as caught:
        _invoke(_tools(tmp_path, None), envelope)

    assert caught.value.code is DshToolErrorCode.TOOL_CAPABILITY_UNAVAILABLE


def test_missing_cordis_reports_runtime_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    envelope = _envelope(_write_package(tmp_path))
    monkeypatch.setattr(runtime_module, "host_node_version", lambda _exe="": "24.11.1")
    monkeypatch.delenv("DSH_HARNESS_ROOT", raising=False)
    sandbox = _Sandbox()

    with pytest.raises(DshToolError) as caught:
        _invoke(_tools(tmp_path, sandbox), envelope)

    assert caught.value.code is DshToolErrorCode.TOOL_RUNTIME_FAILED
    assert sandbox.calls == []


def test_success_goes_through_the_sandbox_and_returns_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    envelope = _envelope(_write_package(tmp_path))
    _cordis(tmp_path)
    monkeypatch.setattr(runtime_module, "host_node_version", lambda _exe="": "24.11.1")
    sandbox = _Sandbox(
        {"ok": True, "published": {"acpAppStartup": {"accepted": True}}, "registrySize": 1}
    )

    result = _invoke(
        _tools(tmp_path, sandbox), envelope, arguments=["--help"], timeout_s=5
    )

    assert result["plugin"] == PLUGIN
    assert result["capability"] == CAPABILITY
    assert result["published"] == {"acpAppStartup": {"accepted": True}}
    assert result["registry_size"] == 1
    assert result["duration_ms"] >= 0

    tool_name, request = sandbox.calls[0]
    assert tool_name == f"dsh__{PLUGIN}__startup"
    assert request.cwd == str(tmp_path)
    assert request.timeout_s == 5
    assert request.max_output_bytes == runtime_module.MAX_OUTPUT_BYTES
    assert request.argv[1:3] == ("--input-type=module", "-e")
    payload = json.loads(request.argv[4])
    assert payload["entryUrl"].endswith(ENTRY)
    assert payload["cordisUrl"].endswith("vendor/cordis/lib/index.js")
    assert payload["arguments"] == ["--help"]


def test_service_missing_maps_to_its_own_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    envelope = _envelope(_write_package(tmp_path))
    _cordis(tmp_path)
    monkeypatch.setattr(runtime_module, "host_node_version", lambda _exe="": "24.11.1")
    sandbox = _Sandbox({"ok": False, "code": "service_missing", "missing": ["appExit"]})

    with pytest.raises(DshToolError) as caught:
        _invoke(_tools(tmp_path, sandbox), envelope)

    assert caught.value.code is DshToolErrorCode.TOOL_RUNTIME_SERVICE_MISSING
    assert "appExit" in caught.value.message


def test_import_failure_maps_to_not_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    envelope = _envelope(_write_package(tmp_path))
    _cordis(tmp_path)
    monkeypatch.setattr(runtime_module, "host_node_version", lambda _exe="": "24.11.1")
    sandbox = _Sandbox({"ok": False, "code": "import_failed", "message": "boom"})

    with pytest.raises(DshToolError) as caught:
        _invoke(_tools(tmp_path, sandbox), envelope)

    assert caught.value.code is DshToolErrorCode.TOOL_RUNTIME_PLUGIN_NOT_LOADED


def test_no_runner_output_is_a_failure_not_a_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    envelope = _envelope(_write_package(tmp_path))
    _cordis(tmp_path)
    monkeypatch.setattr(runtime_module, "host_node_version", lambda _exe="": "24.11.1")

    with pytest.raises(DshToolError) as caught:
        _invoke(_tools(tmp_path, _Sandbox(None)), envelope)

    assert caught.value.code is DshToolErrorCode.TOOL_RUNTIME_FAILED


def test_granted_bundle_mounts_without_tool_capability(tmp_path: Path) -> None:
    """A grant is what admits the bundle; the manifest still says nothing."""

    package_json = _write_package(tmp_path)
    workspace = tmp_path / "ws"
    workspace.mkdir()

    plain = build_dsh_plugin_tools(
        scope="AGT1",
        local_roots=[package_json.parent],
        providers={},
        hitl=False,
        sandbox_root=workspace,
    )
    granted = build_dsh_plugin_tools(
        scope="AGT1",
        local_roots=[package_json.parent],
        providers={},
        hitl=False,
        sandbox_root=workspace,
        runtime={
            PLUGIN: RuntimeTools(
                grant=ExecGrant(plugin_id=PLUGIN, workspace_root=workspace)
            )
        },
    )

    assert plain.tools == []
    assert [skip.reason for skip in plain.skipped] == ["not_tool_capability"]
    assert granted.mounted == [PLUGIN]
    assert granted.report()["runtime"] == [PLUGIN]
    assert [str(tool.name) for tool in granted.tools] == ["dsh__fixture-bundle__startup"]


def test_unknown_exec_grant_is_reported(tmp_path: Path) -> None:
    """A grant for an id discovery never saw must not vanish silently."""

    build = build_dsh_plugin_tools(
        scope="AGT1",
        local_roots=[],
        providers={},
        hitl=False,
        sandbox_root=tmp_path,
        runtime={
            "dsh:no-such-bundle": RuntimeTools(
                grant=ExecGrant(plugin_id="dsh:no-such-bundle", workspace_root=tmp_path)
            )
        },
    )

    assert build.tools == []
    assert [skip.reason for skip in build.skipped] == ["runtime_grant_not_found"]
    assert build.skipped[0].plugin_id == "dsh:no-such-bundle"


def test_runtime_without_workspace_is_skipped(tmp_path: Path) -> None:
    package_json = _write_package(tmp_path)

    build = build_dsh_plugin_tools(
        scope="AGT1",
        local_roots=[package_json.parent],
        providers={},
        hitl=False,
        sandbox_root=None,
        runtime={
            PLUGIN: RuntimeTools(
                grant=ExecGrant(plugin_id=PLUGIN, workspace_root=tmp_path)
            )
        },
    )

    assert build.tools == []
    assert [skip.reason for skip in build.skipped] == ["runtime_requires_workspace"]
