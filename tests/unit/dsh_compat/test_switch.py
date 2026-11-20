from __future__ import annotations

import pytest

from octop.infra.dsh.compat import switch
from octop.infra.dsh.compat.errors import DshCompatCode, DshCompatError
from octop.infra.dsh.compat.switch import allowed_plugins, compat_enabled, plugin_allowed


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(switch.ENV_COMPAT, raising=False)
    monkeypatch.delenv(switch.ENV_PLUGINS, raising=False)


@pytest.mark.parametrize("value", ["1", "true", "YES", "on", " On "])
def test_compat_enabled_truthy(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(switch.ENV_COMPAT, value)
    assert compat_enabled() is True


@pytest.mark.parametrize("value", ["", "0", "false", "off", "nope"])
def test_compat_enabled_falsey(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(switch.ENV_COMPAT, value)
    assert compat_enabled() is False


def test_disabled_blocks_every_plugin() -> None:
    assert plugin_allowed("dsh:dsh-auto-memory", "dsh:*") is False


def test_allowed_plugins_parser_is_trimmed() -> None:
    assert allowed_plugins(" a , b ,, ") == frozenset({"a", "b"})


def test_wildcard_allows_all(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(switch.ENV_COMPAT, "1")
    monkeypatch.setenv(switch.ENV_PLUGINS, "dsh:*")
    assert plugin_allowed("dsh:dsh-auto-memory")
    assert plugin_allowed("dsh:whatever")


def test_allow_list_accepts_bare_and_canonical(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(switch.ENV_COMPAT, "1")
    monkeypatch.setenv(switch.ENV_PLUGINS, "dsh-auto-memory")
    assert plugin_allowed("dsh:dsh-auto-memory")
    assert plugin_allowed("dsh-auto-memory")
    assert not plugin_allowed("dsh:dsh-meme")


def test_errors_serialise_with_code() -> None:
    error = DshCompatError(DshCompatCode.SLOT_UNSUPPORTED, "no slot", details={"slot": "settings.section"})
    payload = error.to_dict()
    assert payload["code"] == "SLOT_UNSUPPORTED"
    assert payload["details"] == {"slot": "settings.section"}
