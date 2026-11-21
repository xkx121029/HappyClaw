"""DSH index source persistence in ``config.json``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from octop.infra.agents.plugins.constants import DSH_DEFAULT_SOURCES, DSH_SOURCES_LIMIT
from octop.infra.agents.plugins.manager import PluginManager
from octop.infra.errors import ErrorCode, OctopError


def make_manager(tmp_path: Path) -> PluginManager:
    return PluginManager(
        plugins_dir=tmp_path / "plugins",
        config_path=tmp_path / "config.json",
    )


def test_defaults_apply_until_a_list_is_saved(tmp_path):
    manager = make_manager(tmp_path)
    assert manager.dsh_source_urls() == list(DSH_DEFAULT_SOURCES)

    added = manager.add_dsh_source("https://mine.example/index.json")
    assert added == [*DSH_DEFAULT_SOURCES, "https://mine.example/index.json"]

    for url in DSH_DEFAULT_SOURCES:
        remaining = manager.remove_dsh_source(url)
    assert remaining == ["https://mine.example/index.json"]
    assert make_manager(tmp_path).dsh_source_urls() == [
        "https://mine.example/index.json"
    ]

    # Removing the last user source stores an explicit empty list: the
    # built-in defaults must not silently come back.
    assert manager.remove_dsh_source("https://mine.example/index.json") == []
    assert make_manager(tmp_path).dsh_source_urls() == []


def test_add_is_trimmed_deduped_and_preserves_other_keys(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"theme": "dark", "plugin_market": {"dsh_sources": []}}),
        encoding="utf-8",
    )
    manager = make_manager(tmp_path)

    first = manager.add_dsh_source("  https://one.example/index.json  ")
    again = manager.add_dsh_source("https://one.example/index.json")

    assert first == ["https://one.example/index.json"]
    assert again == first
    data = json.loads(config.read_text(encoding="utf-8"))
    assert data["theme"] == "dark"
    assert data["plugin_market"]["dsh_sources"] == first

    # A fresh manager sees the persisted value, not process state.
    assert make_manager(tmp_path).dsh_source_urls() == first


def test_local_file_source_must_exist(tmp_path):
    index = tmp_path / "index.json"
    index.write_text("{}", encoding="utf-8")
    manager = make_manager(tmp_path)

    assert str(index) in manager.add_dsh_source(str(index))
    with pytest.raises(OctopError) as missing:
        manager.add_dsh_source(str(tmp_path / "absent.json"))
    assert missing.value.code is ErrorCode.PLUGIN_MARKET_SOURCE_INVALID


def test_rejects_relative_and_non_http_addresses(tmp_path):
    manager = make_manager(tmp_path)
    for value in ("", "   ", "index.json", "ftp://example/index.json"):
        with pytest.raises(OctopError) as exc:
            manager.add_dsh_source(value)
        assert exc.value.code is ErrorCode.PLUGIN_MARKET_SOURCE_INVALID


def test_limit_and_remove(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"plugin_market": {"dsh_sources": []}}), encoding="utf-8"
    )
    manager = make_manager(tmp_path)
    for position in range(DSH_SOURCES_LIMIT):
        manager.add_dsh_source(f"https://host.example/{position}.json")

    with pytest.raises(OctopError) as exc:
        manager.add_dsh_source("https://host.example/overflow.json")
    assert exc.value.code is ErrorCode.PLUGIN_MARKET_SOURCE_INVALID

    remaining = manager.remove_dsh_source("https://host.example/0.json")
    assert len(remaining) == DSH_SOURCES_LIMIT - 1
    assert "https://host.example/0.json" not in remaining
    # Removing an unknown value is a no-op.
    assert manager.remove_dsh_source("https://host.example/none.json") == remaining
