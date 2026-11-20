from __future__ import annotations

import json
from pathlib import Path

import pytest

import octop.infra.market.http as market_http
from octop.infra.agents.plugins.bundled import default_bundled_plugins_root
from octop.infra.agents.plugins.manager import PluginManager
from octop.infra.agents.plugins.seed import seed_bundled_plugins
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.market import PortalMarketError, clear_market_cache


def _catalog_ids() -> set[str]:
    root = default_bundled_plugins_root()
    found: set[str] = set()
    for child in root.iterdir():
        if not child.is_dir() or child.name.startswith("_"):
            continue
        if (child / "plugin.yaml").is_file():
            found.add(child.name)
    return found


def test_in_tree_plugin_catalog_ships_task_progress_monitor() -> None:
    assert "task-progress-monitor" in _catalog_ids()


def test_seed_does_not_auto_install_real_catalog(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    config_path = tmp_path / "config.json"
    copied = seed_bundled_plugins(
        bundled_root=default_bundled_plugins_root(),
        plugins_dir=plugins_dir,
        config_path=config_path,
    )
    assert copied == []
    assert list(plugins_dir.iterdir()) == [] if plugins_dir.exists() else True


def test_install_path_copies_fixture_plugin(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    config_path = tmp_path / "config.json"
    mgr = PluginManager(plugins_dir=plugins_dir, config_path=config_path)
    sample = Path(__file__).resolve().parents[1] / "fixtures" / "plugins" / "echo-tool"
    loaded = mgr.install_path(sample)
    assert loaded.manifest.id == sample.name
    assert (plugins_dir / sample.name / "plugin.yaml").is_file()


def test_list_market_falls_back_to_bundled_plugins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCTOP_PORTAL_ORIGIN", "")
    clear_market_cache()
    mgr = PluginManager(plugins_dir=tmp_path / "plugins", config_path=tmp_path / "config.json")
    rows = mgr.list_market()
    row = next(item for item in rows if item["id"] == "task-progress-monitor")
    assert row["source"] == "bundled"
    assert row["install_kind"] == "bundled"
    assert row["installed"] is False
    assert row["ui"]["surfaces"][0]["slot"] == "home.sidebar"


def test_list_market_network_failure_is_not_a_market_outage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCTOP_PORTAL_ORIGIN", "https://octop.cloud")
    clear_market_cache()

    def fake_fetch(url: str, *, limit: int) -> bytes:
        del url, limit
        raise PortalMarketError("unreachable: down", network=True)

    monkeypatch.setattr(market_http, "fetch_bytes", fake_fetch)
    mgr = PluginManager(plugins_dir=tmp_path / "plugins", config_path=tmp_path / "config.json")
    rows = mgr.list_market()
    assert any(item["id"] == "task-progress-monitor" for item in rows)


def test_list_market_raises_when_catalog_and_bundled_are_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import octop.infra.agents.plugins.manager as plugin_manager_module

    empty = tmp_path / "empty-bundled"
    empty.mkdir()
    monkeypatch.setattr(
        plugin_manager_module, "default_bundled_plugins_root", lambda: empty
    )
    monkeypatch.setenv("OCTOP_PORTAL_ORIGIN", "")
    clear_market_cache()
    mgr = PluginManager(plugins_dir=tmp_path / "plugins", config_path=tmp_path / "config.json")
    with pytest.raises(OctopError) as raised:
        mgr.list_market()
    assert raised.value.code is ErrorCode.PLUGIN_MARKET_FAILED


def test_install_bundled_plugin_exposes_ui_surfaces(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    mgr = PluginManager(
        plugins_dir=plugins_dir, config_path=tmp_path / "config.json"
    )
    loaded = mgr.install_bundled("task-progress-monitor")
    assert loaded.manifest.id == "task-progress-monitor"
    assert (plugins_dir / "task-progress-monitor" / "ui" / "dist" / "index.js").is_file()
    row = next(
        item for item in mgr.list_installed() if item["id"] == "task-progress-monitor"
    )
    assert row["ui"]["surfaces"] == [
        {
            "id": "task-progress",
            "slot": "home.sidebar",
            "title": "实时任务进度",
            "supported": True,
            "reason_code": None,
        }
    ]
    mgr.uninstall("task-progress-monitor")
    assert not (plugins_dir / "task-progress-monitor").exists()


def test_install_from_market_does_not_copy_bundled_plugin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCTOP_PORTAL_ORIGIN", "https://octop.cloud")
    clear_market_cache()

    def fake_fetch(url: str, *, limit: int) -> bytes:
        del url, limit
        return json.dumps({"success": True, "data": {"items": []}}).encode()

    monkeypatch.setattr(market_http, "fetch_bytes", fake_fetch)
    plugins_dir = tmp_path / "plugins"
    mgr = PluginManager(plugins_dir=plugins_dir, config_path=tmp_path / "config.json")
    with pytest.raises(OctopError) as raised:
        mgr.install_from_market("fortune")
    assert raised.value.code is ErrorCode.NOT_FOUND
    assert not (plugins_dir / "fortune").exists()
