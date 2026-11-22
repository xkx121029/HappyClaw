"""Dry-run plans and capability-expansion confirmation for upgrades."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from happyclaw.infra.plugins.market import (
    CapabilityExpansionError,
    MarketplaceIndex,
    verify_install,
)

from .conftest import dsh_tarball
from .test_pipeline import NPM_URL, build_index


def capability_index(tmp_path: Path) -> MarketplaceIndex:
    """1.0.0 declares ``tool``; 2.0.0 adds ``hook`` (a wider permission surface)."""
    blobs = {
        NPM_URL.format(version="1.0.0"): dsh_tarball(
            "weather", "1.0.0", capabilities=("tool",)
        ),
        NPM_URL.format(version="2.0.0"): dsh_tarball(
            "weather", "2.0.0", capabilities=("tool", "hook")
        ),
    }
    return build_index(tmp_path, dsh_versions=("1.0.0", "2.0.0"), blobs=blobs)


def current_version(root: Path) -> str:
    ledger = json.loads((root / "dsh" / "weather" / "index.json").read_text(encoding="utf-8"))
    return str(ledger["current"]["version"])


def test_plan_install_describes_without_writing(tmp_path):
    root = tmp_path / "plugins"
    index = capability_index(tmp_path)

    plan = index.plan("install", "dsh:weather", root)

    assert plan.operation == "install"
    assert plan.status == "install"
    assert plan.current_version is None
    assert plan.target_version == "2.0.0"
    assert plan.slots_added == ("2.0.0",)
    assert plan.slots_removed == ()
    assert plan.file_delta > 0
    assert plan.capabilities_before == ()
    assert plan.capabilities_after == ("hook", "tool")
    assert plan.added_capabilities == ("hook", "tool")
    assert plan.expands_capabilities is False
    assert plan.dependency_impacts == ()

    # A dry run leaves no plugin tree, ledger or staging directory behind.
    assert not root.exists()


def test_upgrade_refuses_expanded_capabilities_without_confirmation(tmp_path):
    root = tmp_path / "plugins"
    index = capability_index(tmp_path)
    index.install("dsh:weather", root, version="1.0.0")

    plan = index.plan("upgrade", "dsh:weather", root)
    assert plan.status == "upgrade"
    assert plan.current_version == "1.0.0"
    assert plan.target_version == "2.0.0"
    assert plan.capabilities_before == ("tool",)
    assert plan.capabilities_after == ("hook", "tool")
    assert plan.added_capabilities == ("hook",)
    assert plan.removed_capabilities == ()
    assert plan.expands_capabilities is True

    with pytest.raises(CapabilityExpansionError) as excinfo:
        index.upgrade("dsh:weather", root)

    assert excinfo.value.code.value == "PLUGIN_CAPABILITY_EXPANSION"
    assert "hook" in str(excinfo.value)
    assert "allow_capability_expansion=True" in str(excinfo.value)
    assert current_version(root) == "1.0.0"
    assert not (root / "dsh" / "weather" / "2.0.0").exists()
    verify_install("dsh:weather", root)


def test_confirmed_upgrade_grants_new_capabilities(tmp_path):
    root = tmp_path / "plugins"
    index = capability_index(tmp_path)
    index.install("dsh:weather", root, version="1.0.0")

    result = index.upgrade("dsh:weather", root, allow_capability_expansion=True)

    assert result.previous_version == "1.0.0"
    assert result.version == "2.0.0"
    assert result.envelope["capabilities"] == ["tool", "hook"]
    assert current_version(root) == "2.0.0"
    verify_install("dsh:weather", root)


def test_narrowing_needs_no_confirmation_but_shows_in_plan(tmp_path):
    root = tmp_path / "plugins"
    index = capability_index(tmp_path)
    index.install("dsh:weather", root)  # 2.0.0, tool + hook

    plan = index.plan("upgrade", "dsh:weather", root, version="1.0.0")
    assert plan.status == "downgrade"
    assert plan.capabilities_before == ("hook", "tool")
    assert plan.capabilities_after == ("tool",)
    assert plan.removed_capabilities == ("hook",)
    assert plan.added_capabilities == ()
    assert plan.narrows_capabilities is True
    assert plan.expands_capabilities is False

    result = index.upgrade("dsh:weather", root, version="1.0.0")
    assert result.downgraded is True
    assert result.envelope["capabilities"] == ["tool"]
    assert current_version(root) == "1.0.0"
    verify_install("dsh:weather", root)
