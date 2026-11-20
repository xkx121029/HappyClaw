from __future__ import annotations

import json
from pathlib import Path

import pytest

from octop.infra.dsh.compat.errors import DshCompatCode, DshCompatError
from octop.infra.dsh.compat.registry import DshCompatRegistry


def _install(root: Path, name: str, *, with_entry: bool = True) -> Path:
    package = root / "dsh" / name / "2.0.0"
    (package / "lib").mkdir(parents=True)
    (package / "package.json").write_text(
        json.dumps({"name": name, "version": "2.0.0", "main": "lib/index.js"}),
        encoding="utf-8",
    )
    (root / "dsh" / name / "index.json").write_text(
        json.dumps({"current": {"version": "2.0.0"}}), encoding="utf-8"
    )
    if with_entry:
        (package / "lib" / "index.js").write_text(
            "export function apply(ctx) { ctx.head.title('demo'); }", encoding="utf-8"
        )
    return package


@pytest.fixture
def market(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "market"
    _install(root, "dsh-auto-memory")
    _install(root, "dsh-meme")
    monkeypatch.setenv("OCTOP_DSH_MARKET_ROOT", str(root))
    monkeypatch.setenv("OCTOP_DSH_COMPAT", "1")
    monkeypatch.setenv("OCTOP_DSH_COMPAT_PLUGINS", "dsh-auto-memory")
    return root


def test_refresh_discovers_versions_and_allow_list(market: Path) -> None:
    registry = DshCompatRegistry()
    states = {state.plugin_id: state for state in registry.refresh(force=True)}

    assert set(states) == {"dsh:dsh-auto-memory", "dsh:dsh-meme"}
    assert states["dsh:dsh-auto-memory"].version == "2.0.0"
    assert states["dsh:dsh-auto-memory"].allowed is True
    assert states["dsh:dsh-meme"].allowed is False
    assert states["dsh:dsh-meme"].client.code == DshCompatCode.CLIENT_MISSING.value


def test_status_hides_plugins_when_adapter_is_off(market: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = DshCompatRegistry()
    monkeypatch.delenv("OCTOP_DSH_COMPAT")
    registry.refresh(force=True)

    status = registry.status()

    assert status["enabled"] is False
    assert status["plugins"][0]["allowed"] is False


def test_start_refuses_when_not_allowed(market: Path) -> None:
    registry = DshCompatRegistry()
    state = registry.start("dsh:dsh-meme")

    assert state.host_state == "disabled"
    assert state.code == DshCompatCode.NOT_ALLOWED.value


def test_start_without_entry_fails_before_spawning_node(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "market"
    _install(root, "dsh-broken", with_entry=False)
    monkeypatch.setenv("OCTOP_DSH_MARKET_ROOT", str(root))
    monkeypatch.setenv("OCTOP_DSH_COMPAT", "1")
    monkeypatch.setenv("OCTOP_DSH_COMPAT_PLUGINS", "dsh:*")

    state = DshCompatRegistry().start("dsh:dsh-broken")

    assert state.host_state == "failed"
    assert state.code == DshCompatCode.ENTRY_SHAPE.value
    assert state.runtime is None


def test_unknown_plugin_raises_entry_shape(market: Path) -> None:
    with pytest.raises(DshCompatError) as excinfo:
        DshCompatRegistry().start("dsh:not-installed")
    assert excinfo.value.code == DshCompatCode.ENTRY_SHAPE


def test_ui_targets_only_lists_servable_clients(market: Path) -> None:
    registry = DshCompatRegistry()
    package = market / "dsh" / "dsh-auto-memory" / "2.0.0"
    (package / "lib" / "client.js").write_text(
        "window.__ModuleLoader__.load({ id: 'a', factory: () => ({}) });", encoding="utf-8"
    )
    registry.refresh(force=True)

    targets = registry.ui_targets()

    assert [target["plugin_id"] for target in targets] == ["dsh:dsh-auto-memory"]
    assert targets[0]["client_url"] == "/api/dsh-compat/ui/dsh-auto-memory/client.js"


def test_report_ui_updates_state(market: Path) -> None:
    registry = DshCompatRegistry()
    registry.refresh(force=True)

    registry.report_ui("dsh:dsh-auto-memory", "mounted", "")

    state = registry.state("dsh:dsh-auto-memory")
    assert state is not None
    assert state.ui_state == "mounted"
