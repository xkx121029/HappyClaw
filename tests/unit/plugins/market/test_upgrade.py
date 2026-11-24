"""Upgrade behaviour: atomic switch, downgrade guard, dependency and schema checks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from happyclaw.infra.plugins.market import (
    Artifact,
    CapabilityKind,
    ConfigSchemaChangedError,
    DependencyConstraintError,
    HappyclawSource,
    InstallConflictError,
    MarketEntry,
    MarketError,
    MarketplaceIndex,
    PluginKind,
    PluginRelease,
    PluginRequirement,
    install_entry,
    verify_install,
)

from .conftest import dsh_tarball, octop_package
from .test_pipeline import NPM_URL, build_index

GUARD_URL = "https://mirror.example/guard-1.0.0.zip"


def read_ledger(plugin_root: Path) -> dict:
    return json.loads((plugin_root / "index.json").read_text(encoding="utf-8"))


def upgrade_index(tmp_path: Path, *, config_schema: dict | None = None) -> MarketplaceIndex:
    """Two DSH releases sharing one config schema unless the test overrides it."""
    blobs = {
        NPM_URL.format(version=version): dsh_tarball(
            "weather", version, config_schema=config_schema
        )
        for version in ("1.0.0", "2.0.0")
    }
    return build_index(tmp_path, dsh_versions=("1.0.0", "2.0.0"), blobs=blobs)


def install_guard(root: Path) -> None:
    """Install an octop plugin that pins ``dsh:weather`` below 2.0.0."""
    entry = MarketEntry(
        plugin_id="octop:guard",
        source=PluginKind.OCTOP,
        name="guard",
        description="fixture guard",
        capabilities=(CapabilityKind.TOOL,),
        releases=(PluginRelease("1.0.0", Artifact(url=GUARD_URL)),),
        requires=(PluginRequirement("dsh:weather", "<2"),),
    )
    source = HappyclawSource(
        loader=lambda: [],
        transport=lambda url: octop_package("guard", "1.0.0"),
    )
    install_entry(entry, entry.release(), source, root)


def test_upgrade_switches_current_and_keeps_old_slot_runnable(tmp_path):
    root = tmp_path / "plugins"
    index = upgrade_index(tmp_path)
    first = index.install("dsh:weather", root, version="1.0.0")

    result = index.upgrade("dsh:weather", root)

    assert result.previous_version == "1.0.0"
    assert result.version == "2.0.0"
    assert result.status == "replaced"
    assert result.downgraded is False
    assert result.install_dir == root / "dsh" / "weather" / "2.0.0"

    plugin_root = root / "dsh" / "weather"
    assert read_ledger(plugin_root)["current"]["version"] == "2.0.0"

    # The previous version is still a complete, loadable slot.
    old_envelope = json.loads((first.install_dir / "plugin.json").read_text(encoding="utf-8"))
    assert old_envelope["version"] == "1.0.0"
    assert (first.install_dir / "package.json").is_file()
    verify_install("dsh:weather", root)


def test_upgrade_restores_previous_version_when_switch_fails(tmp_path, monkeypatch):
    root = tmp_path / "plugins"
    index = upgrade_index(tmp_path)
    first = index.install("dsh:weather", root, version="1.0.0")
    plugin_root = root / "dsh" / "weather"
    ledger_before = (plugin_root / "index.json").read_text(encoding="utf-8")

    def fail_write(plugin_root: Path, ledger: dict) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(
        "happyclaw.infra.plugins.market.pipeline._write_ledger",
        fail_write,
    )

    with pytest.raises(MarketError) as excinfo:
        index.upgrade("dsh:weather", root)

    assert "已保留 1.0.0" in str(excinfo.value)
    assert (plugin_root / "index.json").read_text(encoding="utf-8") == ledger_before
    assert not (plugin_root / "2.0.0").exists()
    assert list(plugin_root.glob(".staging-*")) == []
    assert first.install_dir.is_dir()
    verify_install("dsh:weather", root)


def test_upgrade_never_downgrades_without_explicit_version(tmp_path):
    root = tmp_path / "plugins"
    blobs = {
        NPM_URL.format(version="1.0.0"): dsh_tarball("weather", "1.0.0"),
        NPM_URL.format(version="2.0.0"): dsh_tarball("weather", "2.0.0"),
    }
    index = build_index(tmp_path, dsh_versions=("1.0.0", "2.0.0"), blobs=blobs)
    index.install("dsh:weather", root)
    older = build_index(tmp_path, dsh_versions=("1.0.0",), blobs=blobs)

    with pytest.raises(InstallConflictError) as excinfo:
        older.upgrade("dsh:weather", root)
    assert "默认不降级" in str(excinfo.value)
    assert excinfo.value.code.value == "PLUGIN_VERSION_CONFLICT"
    assert read_ledger(root / "dsh" / "weather")["current"]["version"] == "2.0.0"

    downgraded = older.upgrade("dsh:weather", root, version="1.0.0")
    assert downgraded.previous_version == "2.0.0"
    assert downgraded.version == "1.0.0"
    assert downgraded.downgraded is True
    assert read_ledger(root / "dsh" / "weather")["current"]["version"] == "1.0.0"
    verify_install("dsh:weather", root)


def test_upgrade_rejected_when_it_breaks_another_plugin_constraint(tmp_path):
    root = tmp_path / "plugins"
    index = upgrade_index(tmp_path)
    index.install("dsh:weather", root, version="1.0.0")
    install_guard(root)
    plugin_root = root / "dsh" / "weather"

    with pytest.raises(DependencyConstraintError) as excinfo:
        index.upgrade("dsh:weather", root)

    message = str(excinfo.value)
    assert "octop:guard" in message
    assert "<2" in message
    assert excinfo.value.code.value == "PLUGIN_VERSION_CONFLICT"
    assert excinfo.value.mismatched == (("octop:guard", "1.0.0", "<2"),)
    assert read_ledger(plugin_root)["current"]["version"] == "1.0.0"
    assert not (plugin_root / "2.0.0").exists()
    verify_install("dsh:weather", root)
    verify_install("octop:guard", root)


def test_upgrade_reports_config_schema_change_on_downgrade(tmp_path):
    root = tmp_path / "plugins"
    blobs = {
        NPM_URL.format(version="2.0.0"): dsh_tarball(
            "weather", "2.0.0", config_schema={"token": "string"}
        ),
        NPM_URL.format(version="1.0.0"): dsh_tarball(
            "weather", "1.0.0", config_schema={"api_key": "string"}
        ),
    }
    index = build_index(tmp_path, dsh_versions=("1.0.0", "2.0.0"), blobs=blobs)
    index.install("dsh:weather", root)
    plugin_root = root / "dsh" / "weather"

    with pytest.raises(ConfigSchemaChangedError) as excinfo:
        index.upgrade("dsh:weather", root, version="1.0.0")

    error = excinfo.value
    assert error.code.value == "PLUGIN_CONFIG_SCHEMA_CHANGED"
    assert error.added == ("api_key",)
    assert error.removed == ("token",)
    assert "token" in str(error) and "api_key" in str(error)
    assert read_ledger(plugin_root)["current"]["version"] == "2.0.0"
    assert not (plugin_root / "1.0.0").exists()
    verify_install("dsh:weather", root)
