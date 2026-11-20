from __future__ import annotations

import json
from pathlib import Path

from octop.infra.dsh.compat.client_asset import client_asset, resolve_client_file, slot_map
from octop.infra.dsh.compat.errors import DshCompatCode
from octop.infra.dsh.compat.probe import classify_static, map_slot

HOST_ENTRY = """
export const inject = ['webServer', 'tools'];

export function apply(ctx) {
  ctx.tools.register({ name: 'demo_tool', execute: async () => ({ ok: true }) });
  ctx.webServer.register({ method: 'GET', path: '/demo', handler: async () => ({}) });
}
"""

CLIENT_ENTRY = """
window.__ModuleLoader__.load({
  id: '@demo/plugin',
  factory: (require) => {
    const React = require('react');
    const jsxRuntime = require('react/jsx-runtime');
    const exports = { inject: ['slots'], apply: (ctx) => {} };
    return exports;
  },
});
ctx.slots.inject('sidebar.footer.action', () => {});
ctx.slots.register({ name: 'settings.section', id: 'settings' }, () => null);
"""


def _package(tmp_path: Path, name: str = "dsh-demo", **manifest: object) -> Path:
    root = tmp_path / "dsh" / name / "1.0.0"
    root.mkdir(parents=True)
    data = {
        "name": name,
        "version": "1.0.0",
        "main": "lib/index.js",
        "dsh": {"client": {"entry": "lib/client.js"}},
    }
    data.update(manifest)
    (root / "package.json").write_text(json.dumps(data), encoding="utf-8")
    (root / "lib").mkdir()
    return root


def test_map_slot_covers_host_slots_only() -> None:
    assert map_slot("sidebar.footer.action") == "home.sidebar"
    assert map_slot("shell.overlay") == "chat.messages.top"
    assert map_slot("conversation.header.leading") == "chat.messages.top"
    assert map_slot("conversation.input.left") == "conversation.input.left"
    assert map_slot("conversation.input.overlay") == "conversation.input.overlay"
    assert map_slot("conversation.view") == "conversation.view"
    assert map_slot("settings.section") == "settings.section"
    assert map_slot("plugins.bundle.config") == "settings.section"
    assert map_slot("main") is None
    assert slot_map()["conversation.input.left"] == "conversation.input.left"


def test_classify_static_reads_manifest_entries_and_slots(tmp_path: Path) -> None:
    root = _package(tmp_path)
    (root / "lib" / "index.js").write_text(HOST_ENTRY, encoding="utf-8")
    (root / "lib" / "client.js").write_text(CLIENT_ENTRY, encoding="utf-8")

    facts = classify_static(root)

    assert facts.plugin_id == "dsh:dsh-demo"
    assert facts.entry_shape == "esm"
    assert facts.main_exists and facts.client_exists
    assert facts.host_inject == ("webServer", "tools")
    assert "tools" in facts.host_ctx
    assert set(facts.ui_slots) == {"sidebar.footer.action", "settings.section"}
    assert facts.mapped_slots == ("home.sidebar", "settings.section")
    assert facts.unsupported_slots == ()
    assert DshCompatCode.SLOT_UNSUPPORTED.value not in facts.reasons


def test_missing_entry_with_typescript_sources_needs_build(tmp_path: Path) -> None:
    root = _package(tmp_path, name="dsh-ts")
    (root / "src").mkdir()
    (root / "src" / "index.ts").write_text("export const apply = () => {};", encoding="utf-8")

    facts = classify_static(root)

    assert facts.needs_build is True
    assert facts.code == DshCompatCode.NEEDS_BUILD.value


def test_native_module_is_flagged_not_promised(tmp_path: Path) -> None:
    root = _package(tmp_path, name="dsh-native")
    (root / "lib" / "index.js").write_text(
        "const db = require('better-sqlite3');\nexports.apply = () => {};\n",
        encoding="utf-8",
    )
    (root / "lib" / "client.js").write_text(CLIENT_ENTRY, encoding="utf-8")

    facts = classify_static(root)

    assert "better-sqlite3" in facts.native_modules
    assert DshCompatCode.NATIVE_MODULE.value in facts.reasons


def test_declared_client_that_is_absent_is_entry_shape(tmp_path: Path) -> None:
    root = _package(tmp_path, name="dsh-noclient")
    (root / "lib" / "index.js").write_text(HOST_ENTRY, encoding="utf-8")

    facts = classify_static(root)
    asset = client_asset(facts)

    assert facts.client_declared is True
    assert facts.client_exists is False
    assert asset.exists is False
    assert asset.code == DshCompatCode.CLIENT_MISSING.value


def test_client_asset_accepts_module_loader_only(tmp_path: Path) -> None:
    root = _package(tmp_path, name="dsh-plain")
    (root / "lib" / "index.js").write_text(HOST_ENTRY, encoding="utf-8")
    (root / "lib" / "client.js").write_text("export default function Client() {}", encoding="utf-8")

    facts = classify_static(root)
    asset = client_asset(facts)

    assert asset.shape == "esm"
    assert asset.code == DshCompatCode.BUNDLE_UNSUPPORTED.value


def test_non_react_require_marks_missing_api(tmp_path: Path) -> None:
    root = _package(tmp_path, name="dsh-extra")
    (root / "lib" / "index.js").write_text(HOST_ENTRY, encoding="utf-8")
    (root / "lib" / "client.js").write_text(
        "const _ = require('lodash');\nwindow.__ModuleLoader__.load({ id: 'x', factory: () => ({}) });",
        encoding="utf-8",
    )

    asset = client_asset(classify_static(root))

    assert asset.unsupported_requires == ("lodash",)
    assert asset.code == DshCompatCode.MISSING_API.value


def test_resolve_client_file_rejects_escape_and_non_js(tmp_path: Path) -> None:
    root = _package(tmp_path, name="dsh-paths")
    (root / "lib" / "client.js").write_text(CLIENT_ENTRY, encoding="utf-8")
    (root / "lib" / "notes.txt").write_text("x", encoding="utf-8")

    assert resolve_client_file(root, "lib/client.js") == (root / "lib" / "client.js").resolve()
    assert resolve_client_file(root, "lib/notes.txt") is None
    assert resolve_client_file(root, "../../escape.js") is None
    assert resolve_client_file(root, "lib/missing.js") is None
