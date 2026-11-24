"""Uninstall behaviour: current fallback, dependency guard, rollback, isolation."""

from __future__ import annotations

from pathlib import Path

import pytest

from happyclaw.infra.plugins.market import (
    DependencyInUseError,
    MarketError,
    uninstall,
    verify_install,
)

from .conftest import dsh_tarball, octop_package
from .test_pipeline import NPM_URL, build_index

MIRROR_URL = "https://mirror.example/{plugin_id}-{version}.zip"


def octop_item(plugin_id: str, *, requires: tuple[str, ...] = ()) -> dict:
    return {
        "id": plugin_id,
        "version": "1.0.0",
        "name": {"zh": plugin_id, "en": plugin_id},
        "description": {"zh": "fixture", "en": "fixture"},
        "kind": "tool",
        "download_url": MIRROR_URL.format(plugin_id=plugin_id, version="1.0.0"),
        "requires": list(requires),
    }


def test_uninstall_current_falls_back_to_highest_remaining(tmp_path):
    root = tmp_path / "plugins"
    blobs = {
        NPM_URL.format(version="1.0.0"): dsh_tarball("weather", "1.0.0"),
        NPM_URL.format(version="2.0.0"): dsh_tarball("weather", "2.0.0"),
    }
    index = build_index(tmp_path, dsh_versions=("1.0.0", "2.0.0"), blobs=blobs)
    index.install("dsh:weather", root, version="1.0.0")
    index.install("dsh:weather", root)

    removed = uninstall("dsh:weather", root)
    assert removed.version == "2.0.0"
    assert removed.current_version == "1.0.0"
    assert removed.remaining_versions == ("1.0.0",)
    assert not removed.install_dir.exists()
    plugin_root = root / "dsh" / "weather"
    assert not (plugin_root / "2.0.0").exists()
    assert (plugin_root / "1.0.0").is_dir()
    verify_install("dsh:weather", root)

    last = uninstall("dsh:weather", root)
    assert last.current_version is None
    assert last.remaining_versions == ()
    assert not plugin_root.exists()
    with pytest.raises(MarketError):
        verify_install("dsh:weather", root)


def test_uninstall_refuses_version_another_plugin_requires(tmp_path):
    root = tmp_path / "plugins"
    blobs = {
        MIRROR_URL.format(plugin_id="core", version="1.0.0"): octop_package("core", "1.0.0"),
        MIRROR_URL.format(plugin_id="weather", version="1.0.0"): octop_package("weather", "1.0.0"),
    }
    index = build_index(
        tmp_path,
        octop_items=[octop_item("core"), octop_item("weather", requires=("octop:core",))],
        blobs=blobs,
    )
    index.install("octop:core", root)
    index.install("octop:weather", root)

    with pytest.raises(DependencyInUseError) as excinfo:
        uninstall("octop:core", root)

    message = str(excinfo.value)
    assert "无法卸载" in message
    assert "octop:weather" in message
    assert excinfo.value.code.value == "PLUGIN_DEPENDENCY_IN_USE"
    verify_install("octop:core", root)
    verify_install("octop:weather", root)

    # Removing the dependent first unblocks the dependency.
    uninstall("octop:weather", root)
    uninstall("octop:core", root)
    assert not (root / "octop" / "core").exists()


def test_uninstall_rolls_back_when_ledger_write_fails(tmp_path, monkeypatch):
    root = tmp_path / "plugins"
    blobs = {
        MIRROR_URL.format(plugin_id="weather", version="1.0.0"): octop_package("weather", "1.0.0"),
    }
    index = build_index(tmp_path, octop_items=[octop_item("weather")], blobs=blobs)
    result = index.install("octop:weather", root)
    plugin_root = root / "octop" / "weather"
    ledger_before = (plugin_root / "index.json").read_text(encoding="utf-8")

    def fail_write(plugin_root: Path, ledger: dict) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(
        "happyclaw.infra.plugins.market.pipeline._write_ledger",
        fail_write,
    )

    with pytest.raises(OSError):
        uninstall("octop:weather", root)

    assert result.install_dir.is_dir()
    assert list(plugin_root.glob(".trash-*")) == []
    assert (plugin_root / "index.json").read_text(encoding="utf-8") == ledger_before
    verify_install("octop:weather", root)


def test_uninstall_only_touches_its_own_ecosystem(tmp_path):
    root = tmp_path / "plugins"
    blobs = {
        MIRROR_URL.format(plugin_id="weather", version="1.0.0"): octop_package("weather", "1.0.0"),
        NPM_URL.format(version="1.0.0"): dsh_tarball("weather", "1.0.0"),
    }
    index = build_index(
        tmp_path,
        octop_items=[octop_item("weather")],
        dsh_versions=("1.0.0",),
        blobs=blobs,
    )
    index.install("octop:weather", root)
    index.install("dsh:weather", root)

    uninstall("octop:weather", root)

    assert not (root / "octop" / "weather").exists()
    assert (root / "dsh" / "weather" / "1.0.0" / "package.json").is_file()
    assert (root / "dsh" / "weather" / "index.json").is_file()
    verify_install("dsh:weather", root)
