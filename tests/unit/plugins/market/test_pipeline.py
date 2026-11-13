"""End-to-end pipeline tests: normalization, conflict rules, install, verify."""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from pathlib import Path

import pytest

from octop.infra.plugins.market import (
    ChecksumMismatchError,
    DshSource,
    InstallConflictError,
    MarketplaceIndex,
    OctopSource,
    plugin_dir_name,
    verify_install,
)
from octop.infra.plugins.market.errors import MarketError
from octop.infra.plugins.runtime.contract import PluginKind

from .conftest import dsh_tarball, octop_package

OCTOP_URL = "https://mirror.example/weather-{version}.zip"
NPM_URL = "https://registry.npmjs.org/weather/-/weather-{version}.tgz"


def octop_item(version: str = "1.0.0", *, sha256: str | None = None) -> dict:
    item = {
        "id": "weather",
        "version": version,
        "name": {"zh": "天气", "en": "Weather"},
        "description": {"zh": "查询天气", "en": "Weather lookup"},
        "kind": "tool",
        "download_url": OCTOP_URL.format(version=version),
    }
    if sha256 is not None:
        item["sha256"] = sha256
    return item


def dsh_document(*versions: str) -> dict:
    return {
        "format": 1,
        "title": {"en": "Test Index", "zh": "测试索引"},
        "plugins": [
            {
                "name": "weather",
                "title": {"en": "Weather"},
                "versions": [
                    {
                        "version": version,
                        "publishTimestamp": 1762900000,
                        "source": {"type": "npm"},
                        "engines": {"dsh": ">=0.2.0"},
                    }
                    for version in versions
                ],
            }
        ],
    }


def build_index(
    tmp_path: Path,
    *,
    octop_items: list[dict] | None = None,
    dsh_versions: tuple[str, ...] = (),
    blobs: Mapping[str, bytes] | None = None,
    fail_after: int | None = None,
) -> MarketplaceIndex:
    calls = {"count": 0}
    payloads = dict(blobs or {})

    def transport(url: str) -> bytes:
        calls["count"] += 1
        if fail_after is not None and calls["count"] > fail_after:
            raise AssertionError(f"unexpected network access: {url}")
        try:
            return payloads[url]
        except KeyError:  # pragma: no cover - fixture bug
            raise AssertionError(f"missing fixture bytes for {url}") from None

    sources: list = []
    if octop_items is not None:
        sources.append(OctopSource(loader=lambda: octop_items, transport=transport))
    if dsh_versions:
        index_path = tmp_path / "dsh-index.json"
        index_path.write_text(json.dumps(dsh_document(*dsh_versions)), encoding="utf-8")
        sources.append(DshSource(index_path, transport=transport))
    return MarketplaceIndex(sources)


def test_one_unusable_catalog_does_not_hide_the_other(tmp_path):
    broken_row = {
        "id": "weather",
        "version": "1.0.0",
        "download_url": OCTOP_URL.format(version="1.0.0"),
        "requires": ["httpx>=0.27"],
    }
    index_path = tmp_path / "dsh-index.json"
    index_path.write_text(json.dumps(dsh_document("1.0.0")), encoding="utf-8")
    index = MarketplaceIndex(
        [OctopSource(loader=lambda: [broken_row]), DshSource(index_path)]
    )

    entries = index.fetch()

    assert [entry.plugin_id for entry in entries] == ["dsh:weather"]
    assert [item.plugin_id for item in index.rejected()] == ["octop:weather"]
    assert "python_requires" in index.diagnostics()


def test_octop_wins_tie_and_envelope_matches_contract(tmp_path):
    blobs = {
        OCTOP_URL.format(version="1.0.0"): octop_package("weather", "1.0.0"),
        NPM_URL.format(version="1.0.0"): dsh_tarball("weather", "1.0.0"),
    }
    index = build_index(
        tmp_path,
        octop_items=[octop_item("1.0.0")],
        dsh_versions=("1.0.0",),
        blobs=blobs,
    )

    entries = index.fetch()
    assert [entry.plugin_id for entry in entries] == ["octop:weather"]
    conflicts = index.conflicts()
    assert len(conflicts) == 1
    assert conflicts[0].winner.source is PluginKind.OCTOP
    assert conflicts[0].losers[0].source is PluginKind.DSH

    result = index.install("octop:weather", tmp_path / "plugins")
    assert result.status == "installed"
    assert result.alternate_sources == ("dsh",)
    envelope = result.envelope
    assert envelope["id"] == "octop:weather"
    assert envelope["kind"] == "octop"
    assert envelope["version"] == "1.0.0"
    assert envelope["entry"] == "main.py"
    assert envelope["source"]["kind"] == "market"
    assert envelope["requires"] == []
    assert envelope["permissions"] == {
        "declared": False,
        "items": [],
        "policy": "least_privilege",
    }
    assert envelope["capabilities"] == ["tool"]
    assert envelope["metadata"]["native_id"] == "weather"
    assert envelope["metadata"]["market"]["source"] == "octop"
    assert envelope["metadata"]["artifact"]["checksum_verified"] is False
    assert (result.install_dir / "plugin.json").is_file()
    assert (result.install_dir / ".market.json").is_file()
    verify_install("octop:weather", tmp_path / "plugins")


def test_installed_envelope_round_trips_declared_permissions(tmp_path):
    blobs = {
        OCTOP_URL.format(version="1.0.0"): octop_package(
            "weather", "1.0.0", permissions=("fs.read", "network")
        ),
    }
    index = build_index(tmp_path, octop_items=[octop_item("1.0.0")], blobs=blobs)

    result = index.install("octop:weather", tmp_path / "plugins")

    expected = {"declared": True, "items": ["fs.read", "network"], "policy": "declared"}
    assert result.envelope["permissions"] == expected
    written = json.loads((result.install_dir / "plugin.json").read_text(encoding="utf-8"))
    assert written["permissions"] == expected
    verify_install("octop:weather", tmp_path / "plugins")


def test_python_requirements_land_in_metadata_not_requires(tmp_path):
    item = octop_item("1.0.0")
    item["python_requires"] = ["httpx>=0.27"]
    blobs = {OCTOP_URL.format(version="1.0.0"): octop_package("weather", "1.0.0")}
    index = build_index(tmp_path, octop_items=[item], blobs=blobs)

    result = index.install("octop:weather", tmp_path / "plugins")

    assert result.envelope["requires"] == []
    assert result.envelope["metadata"]["python_requires"] == ["httpx>=0.27"]
    assert result.envelope["metadata"]["package"]["requires_raw"] == []


def test_higher_version_from_dsh_wins(tmp_path):
    blobs = {
        OCTOP_URL.format(version="1.0.0"): octop_package("weather", "1.0.0"),
        NPM_URL.format(version="2.0.0"): dsh_tarball("weather", "2.0.0"),
    }
    index = build_index(
        tmp_path,
        octop_items=[octop_item("1.0.0")],
        dsh_versions=("1.0.0", "2.0.0"),
        blobs=blobs,
    )
    winner = index.fetch()[0]
    assert winner.plugin_id == "dsh:weather"
    assert winner.version == "2.0.0"

    result = index.install("dsh:weather", tmp_path / "plugins")
    assert result.envelope["id"] == "dsh:weather"
    assert result.envelope["kind"] == "dsh"


def test_reinstall_same_version_is_offline_noop(tmp_path):
    blobs = {
        OCTOP_URL.format(version="1.0.0"): octop_package("weather", "1.0.0"),
    }
    index = build_index(tmp_path, octop_items=[octop_item("1.0.0")], blobs=blobs)
    first = index.install("octop:weather", tmp_path / "plugins")
    assert first.status == "installed"

    offline = build_index(
        tmp_path,
        octop_items=[octop_item("1.0.0")],
        blobs=blobs,
        fail_after=0,
    )
    second = offline.install("octop:weather", tmp_path / "plugins")
    assert second.status == "unchanged"
    assert second.install_dir == first.install_dir
    assert second.envelope["version"] == "1.0.0"


def test_downgrade_requires_force_and_keeps_old_slot(tmp_path):
    blobs = {
        NPM_URL.format(version="1.0.0"): dsh_tarball("weather", "1.0.0"),
        NPM_URL.format(version="2.0.0"): dsh_tarball("weather", "2.0.0"),
    }
    index = build_index(tmp_path, dsh_versions=("1.0.0", "2.0.0"), blobs=blobs)
    latest = index.install("dsh:weather", tmp_path / "plugins")
    assert latest.version == "2.0.0"

    with pytest.raises(InstallConflictError) as excinfo:
        index.install("dsh:weather", tmp_path / "plugins", version="1.0.0")
    assert excinfo.value.code.value == "PLUGIN_VERSION_CONFLICT"

    forced = index.install("dsh:weather", tmp_path / "plugins", version="1.0.0", force=True)
    assert forced.status == "replaced"
    slots = sorted(
        path.name for path in (tmp_path / "plugins" / "dsh" / "weather").iterdir() if path.is_dir()
    )
    assert len(slots) == 2
    assert "2.0.0" in slots and "1.0.0" in slots


def test_same_native_id_installs_side_by_side(tmp_path):
    blobs = {
        OCTOP_URL.format(version="1.0.0"): octop_package("weather", "1.0.0"),
        NPM_URL.format(version="1.0.0"): dsh_tarball("weather", "1.0.0"),
    }
    index = build_index(
        tmp_path,
        octop_items=[octop_item("1.0.0")],
        dsh_versions=("1.0.0",),
        blobs=blobs,
    )
    root = tmp_path / "plugins"
    octop_result = index.install("octop:weather", root)
    dsh_result = index.install("dsh:weather", root)

    assert octop_result.install_dir == root / "octop" / "weather" / "1.0.0"
    assert dsh_result.install_dir == root / "dsh" / "weather" / "1.0.0"

    assert (octop_result.install_dir / "plugin.yaml").is_file()
    assert (octop_result.install_dir / "main.py").is_file()
    assert not (octop_result.install_dir / "package.json").exists()
    assert (dsh_result.install_dir / "package.json").is_file()
    assert (dsh_result.install_dir / "index.js").is_file()
    assert not (dsh_result.install_dir / "plugin.yaml").exists()

    octop_ledger = json.loads(
        (root / "octop" / "weather" / "index.json").read_text(encoding="utf-8")
    )
    dsh_ledger = json.loads(
        (root / "dsh" / "weather" / "index.json").read_text(encoding="utf-8")
    )
    assert octop_ledger["plugin_id"] == "octop:weather"
    assert dsh_ledger["plugin_id"] == "dsh:weather"
    assert octop_ledger["current"]["slot"] == "1.0.0"
    assert dsh_ledger["current"]["slot"] == "1.0.0"

    octop_digest = octop_result.envelope["metadata"]["content"]["sha256"]
    dsh_digest = dsh_result.envelope["metadata"]["content"]["sha256"]
    assert octop_digest != dsh_digest
    verify_install("octop:weather", root)
    verify_install("dsh:weather", root)


def test_upgrade_and_uninstall_stay_inside_one_ecosystem(tmp_path):
    blobs = {
        OCTOP_URL.format(version="1.0.0"): octop_package("weather", "1.0.0"),
        NPM_URL.format(version="1.0.0"): dsh_tarball("weather", "1.0.0"),
        NPM_URL.format(version="2.0.0"): dsh_tarball("weather", "2.0.0"),
    }
    index = build_index(
        tmp_path,
        octop_items=[octop_item("1.0.0")],
        dsh_versions=("1.0.0", "2.0.0"),
        blobs=blobs,
    )
    root = tmp_path / "plugins"
    octop_result = index.install("octop:weather", root)
    index.install("dsh:weather", root, version="1.0.0")
    octop_slot = root / "octop" / "weather" / "1.0.0"
    octop_digest = octop_result.envelope["metadata"]["content"]["sha256"]

    # Upgrading the DSH plugin only adds a new slot under dsh/.
    upgraded = index.install("dsh:weather", root)
    assert upgraded.version == "2.0.0"
    assert upgraded.install_dir == root / "dsh" / "weather" / "2.0.0"
    assert (root / "dsh" / "weather" / "1.0.0").is_dir()
    verify_install("octop:weather", root)
    assert (octop_slot / "main.py").read_text(encoding="utf-8") == (
        "def main() -> str:\n    return 'ok'\n"
    )
    assert octop_result.envelope["metadata"]["content"]["sha256"] == octop_digest

    # Hosts uninstall by removing one ecosystem's plugin directory; the other
    # subtree keeps its files and ledger intact.
    shutil.rmtree(root / "octop" / "weather")
    assert not (root / "octop" / "weather").exists()
    verify_install("dsh:weather", root)
    assert (root / "dsh" / "weather" / "2.0.0" / "package.json").is_file()

    shutil.rmtree(root / "dsh" / "weather")
    assert not (root / "dsh" / "weather").exists()


def test_checksum_mismatch_rejects_install(tmp_path):
    item = octop_item("1.0.0", sha256="0" * 64)
    blobs = {OCTOP_URL.format(version="1.0.0"): octop_package("weather", "1.0.0")}
    index = build_index(tmp_path, octop_items=[item], blobs=blobs)

    with pytest.raises(ChecksumMismatchError) as excinfo:
        index.install("octop:weather", tmp_path / "plugins")
    assert excinfo.value.code.value == "PLUGIN_CHECKSUM_MISMATCH"
    plugin_root = tmp_path / "plugins" / "octop" / "weather"
    assert not (plugin_root / "index.json").exists()
    assert list(plugin_root.iterdir()) == []


def test_verify_install_detects_tampering(tmp_path):
    blobs = {OCTOP_URL.format(version="1.0.0"): octop_package("weather", "1.0.0")}
    index = build_index(tmp_path, octop_items=[octop_item("1.0.0")], blobs=blobs)
    result = index.install("octop:weather", tmp_path / "plugins")
    verify_install("octop:weather", tmp_path / "plugins")

    (result.install_dir / "main.py").write_text("print('tampered')\n", encoding="utf-8")
    with pytest.raises(MarketError):
        verify_install("octop:weather", tmp_path / "plugins")


def test_scoped_ids_get_safe_directory_names():
    assert plugin_dir_name("dsh:example__plugin") == Path("dsh") / "example__plugin"
    assert plugin_dir_name("octop:con") == Path("octop") / "_con"
    assert plugin_dir_name("octop:weather") != plugin_dir_name("dsh:weather")
    with pytest.raises(MarketError):
        plugin_dir_name("weather")
