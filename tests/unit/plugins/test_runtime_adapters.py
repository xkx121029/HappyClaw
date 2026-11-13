"""Unit tests for the unified plugin runtime adapters.

The Octop cases run against the real sample plugins under ``plugins/``; the DSH
cases run against the real ``sdk-minimal`` bundle from the local
``deepseek-harness`` checkout when it is present.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from octop.infra.plugins.runtime.contract import (
    ActivationContext,
    CapabilityKind,
    InvalidManifestError,
    MissingDependencyError,
    PermissionKind,
    PluginEnvelope,
    PluginErrorCode,
    PluginKind,
    PluginLoadError,
    PluginRequirement,
    PluginSource,
    PluginSourceKind,
    VersionConflictError,
)
from octop.infra.plugins.runtime.dsh_plugin import DshPluginLoader
from octop.infra.plugins.runtime.octop_plugin import OctopPluginLoader

_REPO_ROOT = Path(__file__).resolve().parents[3]
_OCTOP_PLUGINS = _REPO_ROOT / "plugins"
_DSH_SDK_MINIMAL = Path(
    "e:/HAPPYclaw/research/deepseek-harness/packages/bundle/sdk-minimal"
)

_requires_dsh_checkout = pytest.mark.skipif(
    not _DSH_SDK_MINIMAL.is_dir(),
    reason="local deepseek-harness checkout is not available",
)


def _write_dsh_bundle(
    parent: Path,
    package_name: str,
    version: str,
    insert_names: tuple[str, ...] = (),
    dependencies: dict[str, str] | None = None,
) -> Path:
    bundle_dir = parent / f"{package_name}-{version}"
    bundle_dir.mkdir(parents=True)
    payload: dict[str, object] = {
        "name": package_name,
        "version": version,
        "main": "index.js",
        "dsh": {"bundle": {"patch": "./cordis.patch.yml"}},
    }
    if dependencies:
        payload["dependencies"] = dependencies
    (bundle_dir / "package.json").write_text(json.dumps(payload), encoding="utf-8")

    if insert_names:
        lines = ["- insert:"]
        for index, name in enumerate(insert_names):
            lines.append(f"    - id: row-{index}")
            lines.append(f"      name: {json.dumps(name)}")
        patch_text = "\n".join(lines) + "\n"
    else:
        patch_text = "- insert: []\n"
    (bundle_dir / "cordis.patch.yml").write_text(patch_text, encoding="utf-8")
    return bundle_dir


def test_octop_discover_maps_real_plugins() -> None:
    envelopes = {item.id: item for item in OctopPluginLoader().discover(roots=[_OCTOP_PLUGINS])}

    toolkit = envelopes["octop:demo-toolkit"]
    assert toolkit.version == "0.1.0"
    assert toolkit.entry == "main.py"
    assert toolkit.capabilities == (CapabilityKind.TOOL,)
    assert toolkit.requires == ()
    assert toolkit.source.reference.endswith("plugin.yaml")
    assert toolkit.metadata["native_kind"] == "tool"

    greeting = envelopes["octop:demo-greeting-skill"]
    assert greeting.capabilities == (CapabilityKind.SKILL,)

    # A manifest that ships a frontend bundle contributes a panel as well.
    ui_card = envelopes["octop:demo-ui-card"]
    assert ui_card.capabilities == (CapabilityKind.TOOL, CapabilityKind.PANEL)
    assert ui_card.metadata["ui_entry"] == "ui/dist/index.js"


def test_octop_manifest_separates_plugin_and_python_requires(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "dependent"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.yaml").write_text(
        "id: dependent\n"
        "version: 1.0.0\n"
        "entry: main.py\n"
        "requires:\n"
        "  - octop:demo-toolkit>=0.1.0\n"
        "  - requests>=2.0\n",
        encoding="utf-8",
    )

    envelope = OctopPluginLoader().discover(roots=[tmp_path])[0]

    assert envelope.requires == (PluginRequirement("octop:demo-toolkit", ">=0.1.0"),)
    assert envelope.metadata["python_requires"] == ["requests>=2.0"]


def test_octop_invalid_plugin_requirement_is_not_silently_dropped(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "broken-dependency"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.yaml").write_text(
        "id: broken-dependency\n"
        "version: 1.0.0\n"
        "entry: main.py\n"
        "requires:\n"
        "  - octop:bad id\n",
        encoding="utf-8",
    )

    with pytest.raises(InvalidManifestError):
        OctopPluginLoader().discover(roots=[tmp_path], strict=True)


def test_octop_invalid_manifest_uses_stable_code(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "broken"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.yaml").write_text(
        "id: broken\nname: Broken\nkind: tool\nentry: main.py\n",
        encoding="utf-8",
    )

    with pytest.raises(InvalidManifestError) as raised:
        OctopPluginLoader().discover(roots=[tmp_path], strict=True)

    assert raised.value.code is PluginErrorCode.MANIFEST_INVALID
    assert raised.value.details["path"].endswith("plugin.yaml")


def test_octop_invalid_manifest_is_skipped_without_strict(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "broken"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.yaml").write_text(
        "id: broken\nversion: 1.0.0\nkind: nonsense\n",
        encoding="utf-8",
    )

    assert OctopPluginLoader().discover(roots=[tmp_path]) == []


@_requires_dsh_checkout
def test_dsh_discover_maps_real_sdk_minimal_bundle() -> None:
    envelopes = DshPluginLoader().discover(roots=[_DSH_SDK_MINIMAL])

    assert len(envelopes) == 1
    envelope = envelopes[0]
    assert envelope.id == "dsh:dsh-sdk-minimal"
    assert envelope.version == "0.2.2-rc.1"
    assert envelope.entry == "lib/index.js"
    # DSH manifests declare no capability: nothing may enter the gated field.
    assert envelope.capabilities == ()
    assert envelope.metadata["capabilities_declared"] is False
    assert envelope.metadata["capabilities_source"] == "undeclared"
    assert envelope.metadata["inferred_capabilities"] == ["service"]
    assert envelope.metadata["required_engines"] == {
        "node": ">=24.9.0",
        "source": "default",
    }

    rows = {row["id"]: row for row in envelope.metadata["entries"]}
    assert rows["agent-loop"]["inject"] == []
    assert rows["sdk-jsonrpc-server"]["inject"] == ["sdkAppStartup", "loader"]

    # Bundles own the packages they compose: no external bundle reference, so
    # ``requires`` stays empty and the composed packages are diagnostics only.
    assert envelope.requires == ()
    bundled = {
        item["name"]: item["constraint"] for item in envelope.metadata["bundled_plugins"]
    }
    assert "@deepseek-ai/dsh-agent" in bundled
    assert "@deepseek-ai/dsh-tools" in bundled
    assert all(isinstance(value, str) for value in bundled.values())

    # ``!!js`` values survive as data instead of being evaluated or coerced.
    assert rows["terminal-bash"]["disabled"] == {
        "$js": "process.platform === 'win32'"
    }
    assert rows["llm-deepseek"]["config"]["defaultContextWindow"] == {
        "$js": "Number(process.env.DSH_CONTEXT_WINDOW ?? 1000000)"
    }
    assert envelope.metadata["entry_graph"]["terminal-bash"]["injects"] == []


def test_dsh_requires_only_lists_external_bundles(tmp_path: Path) -> None:
    _write_dsh_bundle(
        tmp_path,
        "dsh-host",
        "1.0.0",
        insert_names=("@scope/dsh-inner", "dsh-peer"),
        dependencies={"@scope/dsh-inner": "workspace:*", "dsh-peer": "^2.0.0"},
    )
    _write_dsh_bundle(tmp_path, "dsh-peer", "2.0.0")

    envelopes = {item.id: item for item in DshPluginLoader().discover(roots=[tmp_path])}
    host = envelopes["dsh:dsh-host"]

    assert host.requires == (PluginRequirement("dsh:dsh-peer", "*"),)
    assert host.metadata["bundled_plugins"] == [
        {"name": "@scope/dsh-inner", "constraint": "*"}
    ]


def test_dsh_whole_row_patches_are_not_dependencies(tmp_path: Path) -> None:
    bundle_dir = _write_dsh_bundle(tmp_path, "dsh-patch-only", "1.0.0")
    (bundle_dir / "cordis.patch.yml").write_text(
        "- id: system-prompt\n  config:\n    x: 1\n",
        encoding="utf-8",
    )

    envelope = DshPluginLoader().discover(roots=[tmp_path])[0]

    assert envelope.requires == ()
    assert envelope.metadata["bundled_plugins"] == []


def test_dsh_invalid_package_uses_stable_code(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "no-version"
    bundle_dir.mkdir()
    (bundle_dir / "package.json").write_text(
        json.dumps({"name": "dsh-no-version", "main": "index.js"}),
        encoding="utf-8",
    )
    (bundle_dir / "cordis.patch.yml").write_text("- insert: []\n", encoding="utf-8")

    with pytest.raises(InvalidManifestError) as raised:
        DshPluginLoader().discover(roots=[tmp_path], strict=True)

    assert raised.value.code is PluginErrorCode.MANIFEST_INVALID
    assert raised.value.details["path"].endswith("package.json")


def test_dsh_duplicate_versions_conflict_on_strict_discovery(tmp_path: Path) -> None:
    _write_dsh_bundle(tmp_path, "dsh-duplicate", "1.0.0")
    _write_dsh_bundle(tmp_path, "dsh-duplicate", "1.1.0")

    with pytest.raises(VersionConflictError) as raised:
        DshPluginLoader().discover(roots=[tmp_path], strict=True)

    assert raised.value.code is PluginErrorCode.VERSION_CONFLICT


def test_duplicate_activation_is_idempotent_then_conflicts(tmp_path: Path) -> None:
    bundle_dir = _write_dsh_bundle(tmp_path, "runtime-probe", "1.0.0")
    (bundle_dir / "index.js").write_text("", encoding="utf-8")
    envelope = DshPluginLoader().discover(roots=[tmp_path])[0]
    ctx = ActivationContext(services={"node_version": "24.9.0"})
    loader = DshPluginLoader()

    first = loader.activate(envelope, ctx)
    second = loader.activate(envelope, ctx)
    assert first.activation_id == second.activation_id

    with pytest.raises(VersionConflictError) as raised:
        loader.activate(replace(envelope, version="1.1.0"), ctx)
    assert raised.value.code is PluginErrorCode.VERSION_CONFLICT

    loader.deactivate(first)
    loader.deactivate(first)

    # Deactivation really drops the record: activating again mints a new handle.
    third = loader.activate(envelope, ctx)
    assert third.activation_id != first.activation_id


def test_octop_undeclared_capabilities_stay_empty(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "bare"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.yaml").write_text(
        "id: bare\nversion: 1.0.0\nentry: main.py\n",
        encoding="utf-8",
    )

    envelope = OctopPluginLoader().discover(roots=[tmp_path])[0]

    assert envelope.capabilities == ()
    assert envelope.metadata["capabilities_declared"] is False
    assert envelope.metadata["capabilities_source"] == "undeclared"


def test_dsh_inferred_capabilities_only_live_in_metadata(tmp_path: Path) -> None:
    _write_dsh_bundle(tmp_path, "dsh-tool-suite", "1.0.0")

    envelope = DshPluginLoader().discover(roots=[tmp_path])[0]

    assert envelope.capabilities == ()
    assert envelope.metadata["capabilities_declared"] is False
    assert envelope.metadata["inferred_capabilities"] == ["tool"]


def test_dsh_declared_capabilities_are_honoured(tmp_path: Path) -> None:
    bundle_dir = _write_dsh_bundle(tmp_path, "dsh-declared", "1.0.0")
    manifest = json.loads((bundle_dir / "package.json").read_text(encoding="utf-8"))
    manifest["capabilities"] = ["tool"]
    (bundle_dir / "package.json").write_text(json.dumps(manifest), encoding="utf-8")

    envelope = DshPluginLoader().discover(roots=[tmp_path])[0]

    assert envelope.capabilities == (CapabilityKind.TOOL,)
    assert envelope.metadata["capabilities_declared"] is True
    assert envelope.metadata["capabilities_source"] == "manifest"


def test_dsh_missing_entry_reports_load_failed(tmp_path: Path) -> None:
    _write_dsh_bundle(tmp_path, "dsh-no-entry", "1.0.0")  # main=index.js, absent

    envelope = DshPluginLoader().discover(roots=[tmp_path])[0]

    with pytest.raises(PluginLoadError) as raised:
        DshPluginLoader().activate(
            envelope, ActivationContext(services={"node_version": "24.9.0"})
        )

    assert raised.value.code is PluginErrorCode.LOAD_FAILED
    details = raised.value.details
    assert details["reason"] == "entry_missing"
    assert details["entry"].endswith("index.js")
    assert details["directory"].endswith("dsh-no-entry-1.0.0")
    assert "package.json" in details["directory_preview"]


def test_dsh_engine_requirement_is_enforced(tmp_path: Path) -> None:
    bundle_dir = _write_dsh_bundle(tmp_path, "dsh-engine", "1.0.0")
    (bundle_dir / "index.js").write_text("", encoding="utf-8")
    envelope = DshPluginLoader().discover(roots=[tmp_path])[0]

    assert envelope.metadata["required_engines"] == {
        "node": ">=24.9.0",
        "source": "default",
    }

    with pytest.raises(PluginLoadError) as raised:
        DshPluginLoader().activate(
            envelope, ActivationContext(services={"node_version": "20.0.0"})
        )

    details = raised.value.details
    assert details["reason"] == "engine_unsatisfied"
    assert details["required"] == ">=24.9.0"
    assert details["actual"] == "20.0.0"


def test_missing_dependency_code_and_version_constraint() -> None:
    requirement = PluginRequirement("dsh:runtime-probe", ">=2.0")
    assert requirement.matches("2.1.0") is True
    assert requirement.matches("1.9.9") is False

    error = MissingDependencyError(
        "plugin dependency is not available",
        details={"plugin_id": "dsh:runtime-probe"},
    )
    assert error.code is PluginErrorCode.DEPENDENCY_MISSING
    assert error.to_dict() == {
        "code": "PLUGIN_DEPENDENCY_MISSING",
        "message": "plugin dependency is not available",
        "details": {"plugin_id": "dsh:runtime-probe"},
    }


def _make_envelope(**overrides: object) -> PluginEnvelope:
    values: dict[str, object] = {
        "id": "dsh:serialized",
        "kind": PluginKind.DSH,
        "version": "1.0.0",
        "entry": "index.js",
        "source": PluginSource(kind=PluginSourceKind.LOCAL, reference="tests"),
    }
    values.update(overrides)
    return PluginEnvelope(**values)  # type: ignore[arg-type]


def test_permissions_undeclared_are_empty_and_marked(tmp_path: Path) -> None:
    octop_dir = tmp_path / "octop-bare-permissions"
    octop_dir.mkdir()
    (octop_dir / "plugin.yaml").write_text(
        "id: bare-permissions\nversion: 1.0.0\nkind: tool\nentry: main.py\n",
        encoding="utf-8",
    )

    octop = OctopPluginLoader().discover(roots=[octop_dir])[0]

    # ``kind: tool`` is a capability, not a permission: nothing may be inferred.
    assert octop.permissions == ()
    assert octop.metadata["permissions_declared"] is False
    assert octop.metadata["permissions_source"] == "undeclared"

    _write_dsh_bundle(tmp_path, "dsh-bare-permissions", "1.0.0")
    dsh = DshPluginLoader().discover(roots=[tmp_path])[0]

    assert dsh.permissions == ()
    assert dsh.metadata["permissions_declared"] is False
    assert dsh.metadata["permissions_source"] == "undeclared"


def test_permissions_declared_are_parsed(tmp_path: Path) -> None:
    octop_dir = tmp_path / "octop-permissions"
    octop_dir.mkdir()
    (octop_dir / "plugin.yaml").write_text(
        "id: with-permissions\nversion: 1.0.0\nkind: tool\nentry: main.py\n"
        "permissions:\n  - fs.read\n  - fs.write\n",
        encoding="utf-8",
    )

    octop = OctopPluginLoader().discover(roots=[octop_dir])[0]

    assert octop.permissions == (PermissionKind.FS_READ, PermissionKind.FS_WRITE)
    assert octop.metadata["permissions_declared"] is True
    assert octop.metadata["permissions_source"] == "manifest"

    bundle_dir = _write_dsh_bundle(tmp_path, "dsh-permissions", "1.0.0")
    manifest = json.loads((bundle_dir / "package.json").read_text(encoding="utf-8"))
    manifest["permissions"] = ["network", "exec"]
    (bundle_dir / "package.json").write_text(json.dumps(manifest), encoding="utf-8")

    dsh = DshPluginLoader().discover(roots=[tmp_path])[0]

    assert dsh.permissions == (PermissionKind.NETWORK, PermissionKind.EXEC)
    assert dsh.metadata["permissions_declared"] is True
    assert dsh.metadata["permissions_source"] == "manifest"


def test_unknown_permission_is_a_manifest_error(tmp_path: Path) -> None:
    octop_dir = tmp_path / "octop-bad-permission"
    octop_dir.mkdir()
    (octop_dir / "plugin.yaml").write_text(
        "id: bad-permission\nversion: 1.0.0\nkind: tool\nentry: main.py\n"
        "permissions:\n  - fs.*\n",
        encoding="utf-8",
    )

    with pytest.raises(InvalidManifestError) as octop_error:
        OctopPluginLoader().discover(roots=[octop_dir], strict=True)

    assert octop_error.value.code is PluginErrorCode.MANIFEST_INVALID
    assert octop_error.value.details["permissions"] == ["fs.*"]
    assert octop_error.value.details["valid"] == [
        "exec",
        "fs.read",
        "fs.write",
        "network",
    ]

    bundle_dir = _write_dsh_bundle(tmp_path, "dsh-bad-permission", "1.0.0")
    manifest = json.loads((bundle_dir / "package.json").read_text(encoding="utf-8"))
    manifest["permissions"] = ["fs.*"]
    (bundle_dir / "package.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(InvalidManifestError) as dsh_error:
        DshPluginLoader().discover(roots=[tmp_path], strict=True)

    assert dsh_error.value.code is PluginErrorCode.MANIFEST_INVALID
    assert dsh_error.value.details["permissions"] == ["fs.*"]


def test_empty_permissions_serialize_as_least_privilege() -> None:
    payload = _make_envelope().to_dict()["permissions"]
    assert payload == {"declared": False, "items": [], "policy": "least_privilege"}

    declared = _make_envelope(
        permissions=(PermissionKind.NETWORK, PermissionKind.FS_READ)
    ).to_dict()["permissions"]
    # Items follow the enum order so a market-side diff is stable.
    assert declared == {
        "declared": True,
        "items": ["fs.read", "network"],
        "policy": "declared",
    }
