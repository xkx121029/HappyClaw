"""Unit tests for the DSH marketplace source (offline fixtures only)."""

from __future__ import annotations

import copy
from collections.abc import Callable

import pytest

from octop.infra.plugins.market import DshSource, IndexFormatError
from octop.infra.plugins.runtime.contract import PluginKind

from .conftest import dsh_git_zip, dsh_tarball

GIT_COMMIT = "0123456789abcdef0123456789abcdef01234567"


def test_fetch_index_normalizes_dsh_rows(dsh_index_document, write_index):
    source = DshSource(write_index(dsh_index_document))
    entries = source.fetch_index()

    assert [entry.plugin_id for entry in entries] == [
        "dsh:dsh-plugin-weather",
        "dsh:example__dsh-git-plugin",
    ]
    weather = entries[0]
    assert weather.source is PluginKind.DSH
    assert weather.name == "天气"
    assert weather.capabilities == ()
    assert weather.tags == ("tools", "weather", "data")
    assert weather.extra["package_name"] == "dsh-plugin-weather"
    assert weather.extra["native_id"] == "dsh-plugin-weather"

    # Stable releases win over a newer prerelease.
    release = weather.release()
    assert release.version == "1.0.0"
    assert release.artifact.url == (
        "https://registry.npmjs.org/dsh-plugin-weather/-/dsh-plugin-weather-1.0.0.tgz"
    )
    assert release.artifact.media_type == "application/gzip"
    assert release.requires == {"dsh": ">=0.2.0"}

    git_entry = entries[1]
    assert git_entry.release().artifact.url == (
        f"https://github.com/example/monorepo/archive/{GIT_COMMIT}.zip"
    )
    assert git_entry.release().extra["git_path"] == "packages/plugin"


def test_install_npm_tarball(tmp_path, dsh_index_document, write_index):
    data = dsh_tarball()
    source = DshSource(
        write_index(dsh_index_document),
        transport=lambda url: data,
    )
    entry = source.fetch_index()[0]
    payload = source.install(entry, tmp_path / "slot")

    assert (tmp_path / "slot" / "package.json").is_file()
    assert (tmp_path / "slot" / "index.js").is_file()
    assert payload.entry_path == "index.js"
    assert payload.checksum_verified is False
    source.verify(entry, payload)


def test_install_git_archive_with_sub_path(tmp_path, dsh_index_document, write_index):
    data = dsh_git_zip(commit=GIT_COMMIT)
    source = DshSource(write_index(dsh_index_document), transport=lambda url: data)
    entry = source.fetch_index()[1]
    payload = source.install(entry, tmp_path / "slot")

    assert (tmp_path / "slot" / "package.json").is_file()
    assert payload.entry_path == "index.js"


def _mutate_format(document):
    document["format"] = 2


def _mutate_missing_en(document):
    document["title"] = {"zh": "标题"}


def _mutate_uppercase_name(document):
    document["plugins"][0]["name"] = "Dsh-Plugin-Weather"


def _mutate_duplicate_name(document):
    document["plugins"][1]["name"] = document["plugins"][0]["name"]


def _mutate_bad_commit(document):
    document["plugins"][1]["versions"][0]["source"]["commit"] = "abc"


def _mutate_unknown_source_type(document):
    document["plugins"][0]["versions"][0]["source"] = {"type": "http"}


def _mutate_missing_engine(document):
    document["plugins"][0]["versions"][0]["engines"] = {}


def _mutate_duplicate_version(document):
    document["plugins"][0]["versions"][1]["version"] = "1.0.0"


def _mutate_bad_timestamp(document):
    document["plugins"][0]["versions"][0]["publishTimestamp"] = -1


@pytest.mark.parametrize(
    ("mutate", "path"),
    [
        (_mutate_format, "$.format"),
        (_mutate_missing_en, "$.title"),
        (_mutate_uppercase_name, "$.plugins[0].name"),
        (_mutate_duplicate_name, "$.plugins[1].name"),
        (_mutate_bad_commit, "$.plugins[1].versions[0].source.commit"),
        (_mutate_unknown_source_type, "$.plugins[0].versions[0].source.type"),
        (_mutate_missing_engine, "$.plugins[0].versions[0].engines.dsh"),
        (_mutate_duplicate_version, "$.plugins[0].versions[1].version"),
        (_mutate_bad_timestamp, "$.plugins[0].versions[0].publishTimestamp"),
    ],
)
def test_invalid_index_rejected(
    dsh_index_document,
    write_index: Callable[[dict], object],
    mutate,
    path,
):
    document = copy.deepcopy(dsh_index_document)
    mutate(document)
    source = DshSource(write_index(document))

    with pytest.raises(IndexFormatError) as excinfo:
        source.fetch_index()
    assert path in str(excinfo.value)
