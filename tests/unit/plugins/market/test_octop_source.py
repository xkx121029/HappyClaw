"""Unit tests for the octop marketplace source (offline fixtures only)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from happyclaw.infra.plugins.market import (
    ChecksumMismatchError,
    IndexUnusableError,
    OctopSource,
)
from happyclaw.infra.plugins.market.digest import sha256_bytes
from happyclaw.infra.plugins.market.errors import PayloadError
from happyclaw.infra.plugins.runtime.contract import (
    CapabilityKind,
    PluginKind,
    PluginRequirement,
)

from .conftest import make_zip, octop_package


def test_fetch_index_normalizes_portal_rows(portal_items):
    source = OctopSource(loader=lambda: portal_items)
    entries = source.fetch_index()

    assert [entry.plugin_id for entry in entries] == ["octop:weather", "octop:demo-skill"]
    weather = entries[0]
    assert weather.source is PluginKind.OCTOP
    assert weather.name == "天气"
    assert weather.description == "查询城市天气"
    assert weather.capabilities == (CapabilityKind.TOOL,)
    assert weather.requires == (PluginRequirement("octop:http"),)
    assert weather.release().version == "1.2.0"
    assert weather.release().artifact.url == "https://mirror.example/weather-1.2.0.zip"
    assert weather.extra["native_id"] == "weather"

    demo = entries[1]
    assert demo.capabilities == (CapabilityKind.SKILL, CapabilityKind.PANEL)


def test_fetch_index_honours_language(portal_items):
    source = OctopSource(loader=lambda: portal_items, language="en")
    assert source.fetch_index()[0].name == "Weather"


def _item(*requires: str) -> dict:
    return {
        "id": "kitchen-sink",
        "version": "1.0.0",
        "kind": "tool",
        "download_url": "https://mirror.example/kitchen-sink-1.0.0.zip",
        "requires": list(requires),
    }


def test_requires_accepts_prefixed_ids_with_optional_constraints():
    source = OctopSource(
        loader=lambda: [_item("octop:mkt-auth", "octop:mkt-data>=1.0.0", "dsh:weather<3")]
    )

    entry = source.fetch_index()[0]

    assert entry.requires == (
        PluginRequirement("octop:mkt-auth"),
        PluginRequirement("octop:mkt-data", ">=1.0.0"),
        PluginRequirement("dsh:weather", "<3"),
    )


def test_one_bad_row_does_not_hide_the_rest(portal_items):
    source = OctopSource(loader=lambda: portal_items)

    entries = source.fetch_index()

    assert [entry.plugin_id for entry in entries] == ["octop:weather", "octop:demo-skill"]
    assert len(source.rejected) == 1
    rejected = source.rejected[0]
    assert rejected.plugin_id == "octop:broken-row"
    assert rejected.error_code == "PLUGIN_MANIFEST_INVALID"
    assert "download_url" in rejected.reason
    assert rejected.raw["id"] == "broken-row"


def test_all_rows_rejected_fails_with_readable_diagnostics():
    bare_name = _item("httpx>=0.27")
    bare_name["id"] = "weather"
    bad_constraint = _item("octop:mkt-base>>>1")

    with pytest.raises(IndexUnusableError) as excinfo:
        OctopSource(loader=lambda: [bare_name, bad_constraint]).fetch_index()

    error = excinfo.value
    assert error.code.value == "PLUGIN_INDEX_UNUSABLE"
    message = str(error)
    assert "全部被拒绝" in message
    assert "octop:weather" in message
    assert "生态前缀" in message
    assert ">=1.0.0" in message
    assert len(error.details["rejected"]) == 2


def test_broken_index_structure_fails_with_a_reason():
    source = OctopSource(loader=lambda: {"items": []})  # type: ignore[arg-type,return-value]

    with pytest.raises(IndexUnusableError) as excinfo:
        source.fetch_index()

    assert "结构损坏" in str(excinfo.value)


def test_diagnostics_lists_rejected_rows_with_fix_suggestions(portal_items):
    bare_name = _item("httpx>=0.27")
    source = OctopSource(loader=lambda: [*portal_items, bare_name])
    source.fetch_index()

    report = source.diagnostics()

    assert "portal:/api/market/plugins" in report
    assert "broken-row" in report
    assert "download_url" in report
    assert "httpx>=0.27" in report
    assert "python_requires" in report


def test_install_extracts_package_and_verifies(tmp_path, portal_items):
    data = octop_package()
    source = OctopSource(loader=lambda: portal_items, transport=lambda url: data)
    entry = source.fetch_index()[0]
    release = entry.release()
    release = replace(release, artifact=replace(release.artifact, sha256=sha256_bytes(data)))

    dest = tmp_path / "slot"
    payload = source.install(entry, dest, release=release)

    assert (dest / "plugin.yaml").is_file()
    assert (dest / "main.py").is_file()
    assert payload.entry_path == "main.py"
    assert payload.checksum_verified is True
    assert payload.archive_sha256 == sha256_bytes(data)
    source.verify(entry, payload, release=release)


def test_install_rejects_checksum_mismatch(tmp_path, portal_items):
    data = octop_package()
    source = OctopSource(loader=lambda: portal_items, transport=lambda url: data)
    entry = source.fetch_index()[0]
    release = replace(entry.release(), artifact=replace(entry.release().artifact, sha256="0" * 64))

    with pytest.raises(ChecksumMismatchError):
        source.install(entry, tmp_path / "slot", release=release)

    assert not (tmp_path / "slot" / "plugin.yaml").exists()


def test_install_rejects_manifest_identity_mismatch(tmp_path, portal_items):
    data = make_zip(
        {
            "plugin.yaml": "id: somebody-else\nversion: 1.2.0\nkind: tool\nentry: main.py\n",
            "main.py": "print('x')\n",
        }
    )
    source = OctopSource(loader=lambda: portal_items, transport=lambda url: data)
    entry = source.fetch_index()[0]

    with pytest.raises(PayloadError):
        source.install(entry, tmp_path / "slot")
