from __future__ import annotations

import pytest

from octop.infra.dsh.compat import prompt


class _FakeRegistry:
    def __init__(self, sections: list[str] | Exception) -> None:
        self._sections = sections

    def prompt_sections(self, **_kwargs: object) -> list[str]:
        if isinstance(self._sections, Exception):
            raise self._sections
        return self._sections


def test_prompt_block_joins_sections(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prompt, "compat_enabled", lambda: True)
    monkeypatch.setattr(prompt, "get_registry", lambda: _FakeRegistry(["  A  ", "", "B"]))

    assert prompt.compat_prompt_block() == "A\n\nB"


def test_prompt_block_empty_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prompt, "compat_enabled", lambda: False)
    monkeypatch.setattr(prompt, "get_registry", lambda: _FakeRegistry(["A"]))

    assert prompt.compat_prompt_block() == ""


def test_prompt_block_swallows_plugin_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prompt, "compat_enabled", lambda: True)
    monkeypatch.setattr(prompt, "get_registry", lambda: _FakeRegistry(RuntimeError("boom")))

    assert prompt.compat_prompt_block() == ""
