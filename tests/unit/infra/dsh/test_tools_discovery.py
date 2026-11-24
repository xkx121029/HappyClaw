"""S2 discovery: market current slot + local dirs, read-only, never raises."""

from __future__ import annotations

from pathlib import Path

from tests.unit.infra.dsh.plugin_fixtures import write_market_plugin, write_package

from happyclaw.infra.dsh.tools.discovery import discover_dsh_plugins
from happyclaw.infra.dsh.tools.gate import (
    SKIP_DUPLICATE,
    SKIP_INSTALL_BROKEN,
    SKIP_MARKET_ROOT_MISSING,
    SKIP_MARKET_SLOT_UNREADABLE,
    SKIP_NOT_TOOL,
    SKIP_UNSAFE_PERMISSION,
)


def _reasons(skipped: list) -> list[str]:
    return [skip.reason for skip in skipped]


def test_market_current_slot_is_discovered(tmp_path: Path) -> None:
    slot = write_market_plugin(tmp_path, "demo")

    found, skipped = discover_dsh_plugins(market_root=tmp_path)

    assert [plugin.plugin_id for plugin in found] == ["dsh:demo"]
    assert found[0].origin == "market"
    assert found[0].location == str(slot)
    assert skipped == []


def test_local_copy_of_market_plugin_is_reported_as_duplicate(tmp_path: Path) -> None:
    write_market_plugin(tmp_path / "market", "demo")
    local_root = tmp_path / "local"
    write_package(local_root / "demo", "demo")

    found, skipped = discover_dsh_plugins(
        market_root=tmp_path / "market",
        local_roots=[local_root],
    )

    assert [plugin.plugin_id for plugin in found] == ["dsh:demo"]
    assert found[0].origin == "market"
    duplicates = [skip for skip in skipped if skip.reason == SKIP_DUPLICATE]
    assert len(duplicates) == 1
    assert duplicates[0].plugin_id == "dsh:demo"
    assert duplicates[0].origin == "local"


def test_missing_market_root_is_a_skip_not_an_error(tmp_path: Path) -> None:
    found, skipped = discover_dsh_plugins(market_root=tmp_path / "absent")

    assert found == []
    assert _reasons(skipped) == [SKIP_MARKET_ROOT_MISSING]
    assert skipped[0].detail == str(tmp_path / "absent")


def test_ledger_without_current_slot_is_reported(tmp_path: Path) -> None:
    # Package present, no index.json: the adapter silently drops the root, so
    # discovery must enumerate the directory to say why nothing was mounted.
    write_package(tmp_path / "dsh" / "orphan" / "1.0.0", "orphan")

    found, skipped = discover_dsh_plugins(market_root=tmp_path)

    assert found == []
    assert _reasons(skipped) == [SKIP_MARKET_SLOT_UNREADABLE]
    assert skipped[0].plugin_id == "dsh:orphan"


def test_broken_ledger_json_is_reported(tmp_path: Path) -> None:
    plugin_root = tmp_path / "dsh" / "bad"
    write_package(plugin_root / "1.0.0", "bad")
    (plugin_root / "index.json").write_text("{not json", encoding="utf-8")

    found, skipped = discover_dsh_plugins(market_root=tmp_path)

    assert found == []
    assert _reasons(skipped) == [SKIP_MARKET_SLOT_UNREADABLE]


def test_ledger_pointing_at_missing_slot_is_reported(tmp_path: Path) -> None:
    write_market_plugin(tmp_path, "demo", version="1.0.0", slot="9.9.9")

    found, skipped = discover_dsh_plugins(market_root=tmp_path)

    assert found == []
    assert _reasons(skipped) == [SKIP_INSTALL_BROKEN]
    assert skipped[0].plugin_id == "dsh:demo"


def test_plugin_without_tool_capability_is_not_a_candidate(tmp_path: Path) -> None:
    write_market_plugin(tmp_path, "skill-only", capabilities=("skill",))

    found, skipped = discover_dsh_plugins(market_root=tmp_path)

    assert found == []
    assert _reasons(skipped) == [SKIP_NOT_TOOL]


def test_fs_read_only_plugin_is_admitted(tmp_path: Path) -> None:
    local_root = tmp_path / "local"
    write_package(local_root / "reader", "reader", permissions=("fs.read",))

    found, skipped = discover_dsh_plugins(local_roots=[local_root])

    assert [plugin.plugin_id for plugin in found] == ["dsh:reader"]
    assert skipped == []


def test_write_or_egress_plugin_never_becomes_a_candidate(tmp_path: Path) -> None:
    write_market_plugin(
        tmp_path,
        "writer",
        permissions=("fs.read", "network", "exec"),
    )

    found, skipped = discover_dsh_plugins(market_root=tmp_path)

    assert found == []
    assert _reasons(skipped) == [SKIP_UNSAFE_PERMISSION]
    assert skipped[0].plugin_id == "dsh:writer"
    assert skipped[0].detail == "exec,network"


def test_discovery_does_not_write_to_disk(tmp_path: Path) -> None:
    write_market_plugin(tmp_path, "demo")
    before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))

    discover_dsh_plugins(market_root=tmp_path)

    after = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    assert after == before
