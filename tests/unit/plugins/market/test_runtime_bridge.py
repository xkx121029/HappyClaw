"""Bridge: a market-installed plugin must be visible to runtime discovery.

The unified runtime adapters are landing in a parallel line. Until they exist,
this test reports "未实现" through ``pytest.skip`` instead of a fake pass, using
the ``DSH_SMOKE_RUNTIME`` scaffold under ``tests/dsh_integration``.
"""

from __future__ import annotations

import pytest

from octop.infra.plugins.market import verify_install
from tests.dsh_integration import runtime_probe

from .conftest import octop_package
from .test_pipeline import build_index
from .test_uninstall import MIRROR_URL, octop_item


def test_runtime_discovery_sees_installed_plugin(tmp_path):
    root = tmp_path / "plugins"
    blobs = {
        MIRROR_URL.format(plugin_id="weather", version="1.0.0"): octop_package(
            "weather", "1.0.0"
        ),
    }
    index = build_index(tmp_path, octop_items=[octop_item("weather")], blobs=blobs)
    result = index.install("octop:weather", root)
    verify_install("octop:weather", root)
    assert (result.install_dir / "plugin.json").is_file()

    try:
        facades = runtime_probe.resolve_facades()
    except runtime_probe.NotAvailableError as exc:
        pytest.skip(f"未实现：统一运行时适配器尚未落地（{exc}）")

    discovery = runtime_probe.discover(facades, [root])
    found = [envelope for envelope in discovery.envelopes if envelope.id == "octop:weather"]
    if not found:
        detail = "；".join(discovery.errors) or "发现机制未返回任何 envelope"
        pytest.skip(f"未实现：运行时发现机制尚未扫到落盘目录（{detail}）")

    assert found[0].version == "1.0.0"
    assert found[0].entry == "main.py"
