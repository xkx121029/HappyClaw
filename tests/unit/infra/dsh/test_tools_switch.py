"""S2 switch: off means no import, no discovery, no change to the tool list."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest
from tests.dsh_integration.fixtures.tools import fixture_tool
from tests.unit.infra.dsh.plugin_fixtures import write_package

from happyclaw.config import HappyclawConfig
from happyclaw.infra.agents.manager import AgentManager
from happyclaw.infra.db.migrate import run_migrations
from happyclaw.infra.db.pool import SqlitePool
from happyclaw.infra.db.repos.agents import AgentRow
from happyclaw.infra.db.services import build_shared_services
from happyclaw.infra.dsh.tools.gate import SKIP_NO_PROVIDER
from happyclaw.infra.utils.paths import PathLayout


@pytest.fixture
def manager(tmp_path: Path) -> AgentManager:
    paths = PathLayout(tmp_path / ".octop")
    paths.ensure_root()
    db = SqlitePool(paths.db)
    run_migrations(db)
    services = build_shared_services(db=db, paths=paths, config=HappyclawConfig())
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
        module for module in list(sys.modules) if module.startswith("happyclaw.infra.dsh.tools")
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

    assert manager._dsh_tools_status is None
    assert not any(name.startswith("dsh__") for name in names)
    assert not any(module.startswith("happyclaw.infra.dsh.tools") for module in sys.modules)


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
    monkeypatch.delenv("OCTOP_DSH_MARKET_ROOT", raising=False)

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
