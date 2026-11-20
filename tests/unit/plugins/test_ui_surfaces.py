from __future__ import annotations

from pathlib import Path

import pytest

from octop.infra.agents.plugins.manager import (
    PLUGIN_UI_SLOTS,
    PluginManager,
    _parse_ui_surfaces,
    parse_plugin_ui_meta,
)
from octop.infra.errors import OctopError


def _write_plugin(root: Path, ui_body: str) -> Path:
    plugin_dir = root / "surface-demo"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.yaml").write_text(
        "id: surface-demo\nversion: 0.1.0\nname: Surface Demo\nkind: tool\n"
        "entry: main.py\nui:\n  entry: ui/dist/index.js\n" + ui_body,
        encoding="utf-8",
    )
    (plugin_dir / "main.py").write_text("def setup(ctx):\n    pass\n", encoding="utf-8")
    ui_dir = plugin_dir / "ui" / "dist"
    ui_dir.mkdir(parents=True)
    (ui_dir / "index.js").write_text("export function setup() {}\n", encoding="utf-8")
    return plugin_dir


def test_parse_ui_surfaces_keeps_supported_slot() -> None:
    assert _parse_ui_surfaces(
        [{"id": "card", "slot": "home.sidebar", "title": "卡片"}]
    ) == [
        {
            "id": "card",
            "slot": "home.sidebar",
            "title": "卡片",
            "supported": True,
            "reason_code": None,
        }
    ]


def test_parse_ui_surfaces_reports_unknown_slot_and_duplicates() -> None:
    parsed = _parse_ui_surfaces(
        [
            {"id": "card", "slot": "home.sidebar"},
            {"id": "card", "slot": "chat.messages.top"},
            {"id": "floating", "slot": "does.not.exist"},
            {"id": "../escape", "slot": "home.sidebar"},
        ]
    )
    assert [item["id"] for item in parsed] == ["card", "card", "floating"]
    assert parsed[0]["supported"] is True
    assert parsed[1]["supported"] is False
    assert parsed[1]["reason_code"] == "SURFACE_DUPLICATE_ID"
    assert parsed[2]["supported"] is False
    assert parsed[2]["reason_code"] == "SURFACE_SLOT_UNKNOWN"


def test_parse_plugin_ui_meta_reads_surfaces(tmp_path: Path) -> None:
    plugin_dir = _write_plugin(
        tmp_path,
        "  surfaces:\n    - id: card\n      slot: home.sidebar\n      title: 实时\n",
    )
    meta = parse_plugin_ui_meta(plugin_dir)
    assert meta is not None
    assert meta["entry"] == "ui/dist/index.js"
    assert meta["surfaces"][0]["title"] == "实时"
    assert meta["surfaces"][0]["supported"] is True


def test_plugin_ui_slots_are_the_ones_the_dashboard_mounts() -> None:
    assert PLUGIN_UI_SLOTS == (
        "home.sidebar",
        "chat.messages.top",
        "conversation.view",
        "conversation.input.left",
        "conversation.input.overlay",
        "settings.section",
    )


def test_install_bundled_rejects_path_traversal(tmp_path: Path) -> None:
    mgr = PluginManager(
        plugins_dir=tmp_path / "plugins", config_path=tmp_path / "config.json"
    )
    with pytest.raises(OctopError):
        mgr.install_bundled("../outside")
