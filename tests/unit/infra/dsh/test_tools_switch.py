"""S2 switch: off means no import, no discovery, no change to the tool list."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

from octop.config import OctopConfig
from octop.infra.agents.manager import AgentManager
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.agents import AgentRow
from octop.infra.db.services import build_shared_services
from octop.infra.dsh.tools.gate import SKIP_NO_PROVIDER, SKIP_RUNTIME_NO_WORKSPACE
from octop.infra.utils.paths import PathLayout

from tests.dsh_integration.fixtures.tools import fixture_tool
from tests.unit.infra.dsh.plugin_fixtures import write_package


@pytest.fixture
def manager(tmp_path: Path) -> AgentManager:
    paths = PathLayout(tmp_path / ".octop")
    paths.ensure_root()
    db = SqlitePool(paths.db)
    run_migrations(db)
    services = build_shared_services(db=db, paths=paths, config=OctopConfig())
    return AgentManager(repos=services.repos, paths=services.paths)


def _row() -> AgentRow:
    return AgentRow(
        id=1,
        agent_id="01AGENT",
        user_id=1,
        name="bot",
        description=None,
        persona_mbti=None,
        default_model=None,
        system_prompt=None,
        enabled=1,
        config_json=None,
        last_state=None,
        last_error=None,
        created_at=0,
        updated_at=0,
    )


def _tool_names(config: object) -> list[str]:
    tools = getattr(config, "tools", None) or []
    return [str(getattr(tool, "name", "")) for tool in tools]


def _forget_tools_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [
        module for module in list(sys.modules) if module.startswith("octop.infra.dsh.tools")
    ]:
        monkeypatch.delitem(sys.modules, name, raising=False)


def test_switch_off_does_not_import_or_change_tools(
    manager: AgentManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OCTOP_DSH_RUNTIME", raising=False)
    monkeypatch.delenv("OCTOP_DSH_TOOLS", raising=False)
    monkeypatch.delenv("OCTOP_DSH_MARKET_ROOT", raising=False)
    monkeypatch.delenv("OCTOP_DSH_TOOL_ROOTS", raising=False)
    _forget_tools_modules(monkeypatch)

    names = _tool_names(manager._build_harness_config(_row()))

    assert manager.dsh._tools_status is None
    assert not any(name.startswith("dsh__") for name in names)
    assert not any(
        module.startswith("octop.infra.dsh.tools") for module in sys.modules
    )


def test_switch_on_without_provider_adds_nothing_but_reports_reason(
    manager: AgentManager,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline = _tool_names(manager._build_harness_config(_row()))

    root = tmp_path / "local"
    write_package(root / "demo", "demo")
    monkeypatch.setenv("OCTOP_DSH_RUNTIME", "1")
    monkeypatch.setenv("OCTOP_DSH_TOOLS", "1")
    monkeypatch.setenv("OCTOP_DSH_TOOL_ROOTS", str(root))
    # An existing (empty) market root keeps discovery from adding a
    # ``market_root_missing`` skip; this case is about the missing provider.
    market = tmp_path / "market"
    market.mkdir()
    monkeypatch.setenv("OCTOP_DSH_MARKET_ROOT", str(market))

    names = _tool_names(manager._build_harness_config(_row()))

    assert names == baseline
    status = manager.dsh_tools_status()
    assert status["enabled"] is True
    assert status["mounted"] == []
    assert [skip["reason"] for skip in status["skipped"]] == [SKIP_NO_PROVIDER]
    assert status["skipped"][0]["plugin_id"] == "dsh:demo"


def test_switch_on_with_provider_mounts_prefixed_tool(
    manager: AgentManager,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline = set(_tool_names(manager._build_harness_config(_row())))

    root = tmp_path / "local"
    write_package(root / "demo", "demo")
    monkeypatch.setenv("OCTOP_DSH_RUNTIME", "1")
    monkeypatch.setenv("OCTOP_DSH_TOOLS", "1")
    monkeypatch.setenv("OCTOP_DSH_TOOL_ROOTS", str(root))
    monkeypatch.delenv("OCTOP_DSH_MARKET_ROOT", raising=False)
    manager.register_dsh_tool_provider(
        "dsh:demo",
        lambda envelope: [replace(fixture_tool.build_definition(), name="echo")],
    )

    names = _tool_names(manager._build_harness_config(_row()))

    assert "dsh__demo__echo" in names
    assert set(names) - baseline == {"dsh__demo__echo"}
    status = manager.dsh_tools_status()
    assert status["mounted"] == ["dsh:demo"]
    assert status["tools"] == ["dsh__demo__echo"]


def _enable_exec(monkeypatch: pytest.MonkeyPatch, root: Path, granted: str) -> None:
    monkeypatch.setenv("OCTOP_DSH_RUNTIME", "1")
    monkeypatch.setenv("OCTOP_DSH_TOOLS", "1")
    monkeypatch.setenv("OCTOP_DSH_EXEC", "1")
    monkeypatch.setenv("OCTOP_DSH_EXEC_PLUGINS", granted)
    monkeypatch.setenv("OCTOP_DSH_TOOL_ROOTS", str(root))
    monkeypatch.delenv("OCTOP_DSH_MARKET_ROOT", raising=False)


def test_exec_stage_mounts_granted_bundle_without_provider(
    manager: AgentManager,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The app's own config builder is the entry point, and it needs no provider."""

    root = tmp_path / "local"
    write_package(root / "demo", "demo")
    _enable_exec(monkeypatch, root, "dsh:demo")

    config = manager._build_harness_config(_row())
    names = _tool_names(config)

    assert "dsh__demo__startup" in names
    status = manager.dsh_tools_status()
    assert status["runtime"] == ["dsh:demo"]
    assert status["mounted"] == ["dsh:demo"]
    assert status["tools"] == ["dsh__demo__startup"]
    assert manager.dsh._tool_providers == {}


def test_exec_switch_off_mounts_nothing(
    manager: AgentManager,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "local"
    write_package(root / "demo", "demo")
    _enable_exec(monkeypatch, root, "dsh:demo")
    monkeypatch.delenv("OCTOP_DSH_EXEC")
    _forget_tools_modules(monkeypatch)

    names = _tool_names(manager._build_harness_config(_row()))

    assert not any(name.startswith("dsh__") for name in names)
    assert manager.dsh_tools_status()["runtime"] == []


def test_exec_stage_ignores_plugin_outside_grant_list(
    manager: AgentManager,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "local"
    write_package(root / "demo", "demo")
    _enable_exec(monkeypatch, root, "dsh:something-else")

    names = _tool_names(manager._build_harness_config(_row()))

    assert not any(name.startswith("dsh__demo__") for name in names)
    status = manager.dsh_tools_status()
    assert status["runtime"] == []
    assert status["mounted"] == []


def test_exec_stage_skips_when_workspace_is_unresolvable(
    manager: AgentManager,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "local"
    write_package(root / "demo", "demo")
    _enable_exec(monkeypatch, root, "dsh:demo")
    # Same as above: point the market root at an existing empty directory so
    # only the workspace skip is left in the list.
    market = tmp_path / "market"
    market.mkdir()
    monkeypatch.setenv("OCTOP_DSH_MARKET_ROOT", str(market))
    monkeypatch.setattr(manager, "_dsh_sandbox_root", lambda row: None)

    names = _tool_names(manager._build_harness_config(_row()))

    assert not any(name.startswith("dsh__demo__") for name in names)
    status = manager.dsh_tools_status()
    assert [skip["reason"] for skip in status["skipped"]] == [
        SKIP_RUNTIME_NO_WORKSPACE
    ]
    assert status["runtime"] == []

