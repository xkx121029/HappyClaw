"""搜索来源解析与持久化的离线单测。"""

from __future__ import annotations

import asyncio
import types

import pytest

from octop.infra.search import source


class _Repo:
    def __init__(self, value: str | None = None) -> None:
        self.value = value
        self.writes: list[tuple[str, str]] = []

    def get(self, key: str) -> str | None:  # noqa: ARG002
        return self.value

    def set(self, key: str, value: str) -> None:
        self.value = value
        self.writes.append((key, value))


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(source.SOURCE_ENV, raising=False)
    monkeypatch.delenv("OCTOP_HAPPYSEARCH_TOOL", raising=False)


def test_default_is_happysearch(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    state = source.load_source(_Repo())
    assert state.effective == "happysearch"
    assert state.origin == "default"
    assert state.stored is None


def test_save_and_read_back(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    repo = _Repo()
    saved = source.save_source(repo, "both")
    assert saved.effective == "both"
    assert saved.stored == "both"
    assert saved.origin == "settings"
    assert repo.writes == [(source.SEARCH_SOURCE_KEY, "both")]

    loaded = source.load_source(repo)
    assert loaded.effective == "both"
    assert loaded.origin == "settings"


def test_env_overrides_persisted(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    repo = _Repo("searchfree")
    monkeypatch.setenv(source.SOURCE_ENV, "both")
    state = source.load_source(repo)
    assert state.effective == "both"
    assert state.origin == "env"
    assert state.stored == "searchfree"


def test_legacy_happy_switch_maps_to_native(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("OCTOP_HAPPYSEARCH_TOOL", "0")
    state = source.load_source(_Repo())
    assert state.effective == "searchfree"
    assert state.origin == "env"


def test_invalid_values_are_rejected() -> None:
    with pytest.raises(ValueError):
        source.save_source(_Repo(), "unknown")
    with pytest.raises(ValueError):
        source.save_source(_Repo(), "")


def test_harness_policy_excludes_searchfree(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setattr(
        source,
        "_provider_requirements",
        lambda: {"tavily": ("TAVILY_API_KEY",), "you": ("YDC_API_KEY",)},
    )
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-x")
    monkeypatch.delenv("YDC_API_KEY", raising=False)

    state = source.SourceState("happysearch", None, None, "default")
    assert source.commercial_providers() == ["tavily"]
    assert source.harness_policy(state, agent_cfg={}) == ["tavily"]
    assert "searchfree" not in source.harness_policy(state, agent_cfg={})
    assert source.harness_policy(state, agent_cfg={"web_search_tools": False}) is False


def test_visible_tools_are_mutually_exclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setattr(source, "_provider_requirements", lambda: {})
    states = {
        "happysearch": source.SourceState("happysearch", None, None, "default"),
        "searchfree": source.SourceState("searchfree", None, None, "settings"),
        "both": source.SourceState("both", None, None, "settings"),
    }
    for name, state in states.items():
        visible = source.visible_tool_names(state, agent_cfg={})
        free = [item for item in visible if item in ("happysearch_search", "searchfree_search")]
        expected = "searchfree_search" if name == "searchfree" else "happysearch_search"
        assert free == [expected]
    assert source.visible_tool_names(states["both"], agent_cfg={"web_search_tools": False}) == []


class _Audit:
    def __init__(self) -> None:
        self.writes: list[dict] = []

    def write(self, **kwargs) -> None:  # noqa: ANN003
        self.writes.append(kwargs)


class _AgentRegistry:
    def __init__(self) -> None:
        self.reloads = 0

    async def reload_all(self) -> None:
        self.reloads += 1


class _Runtime:
    def __init__(self) -> None:
        self.agent_registry = _AgentRegistry()


class _Server:
    def __init__(self, repo: _Repo, runtime: _Runtime | None) -> None:
        self.services = types.SimpleNamespace(settings_repo=repo, audit_repo=_Audit())
        self.app_runtime = runtime


def test_settings_route_persists_and_reloads(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    from octop.api.routers import settings as settings_router

    repo = _Repo()
    runtime = _Runtime()
    server = _Server(repo, runtime)
    admin = types.SimpleNamespace(username="tester")

    view = asyncio.run(
        settings_router.put_search_source_settings(
            body=settings_router.SearchSourcePut(source="both"),
            admin=admin,
            server=server,
        )
    )
    assert view.effective == "both"
    assert view.stored == "both"
    assert view.applied is True
    assert runtime.agent_registry.reloads == 1

    read_back = asyncio.run(
        settings_router.get_search_source_settings(_admin=admin, server=server)
    )
    assert read_back.effective == "both"
    assert read_back.origin == "settings"


def test_settings_route_reports_pending_without_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    from octop.api.routers import settings as settings_router

    server = _Server(_Repo(), None)
    view = asyncio.run(
        settings_router.put_search_source_settings(
            body=settings_router.SearchSourcePut(source="searchfree"),
            admin=types.SimpleNamespace(username="tester"),
            server=server,
        )
    )
    assert view.effective == "searchfree"
    assert view.applied is False


def test_status_route_exposes_one_free_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    from octop.api.routers import search as search_router

    repo = _Repo("both")
    result = asyncio.run(
        search_router.search_status(
            _=types.SimpleNamespace(username="tester"),
            server=_Server(repo, None),
        )
    )
    assert result["source"]["effective"] == "both"
    assert result["tools_visible"] == ["happysearch_search"]
    assert result["searchfree"]["enabled"] is True
    assert "runtime" in result["happysearch"]
