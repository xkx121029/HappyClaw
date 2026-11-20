"""HappySearch 嵌入式工具的离线单测（不访问外网）。"""

from __future__ import annotations

import json

import pytest

from octop.infra.search import happy_tool
from octop.infra.search.happy import status
from octop.infra.search.happy import search as happy_search
from octop.infra.search.happy.models import RawResult
from octop.infra.search.happy.search import SearchOutcome


class _Repo:
    def __init__(self, value: str | None = None) -> None:
        self.value = value

    def get(self, key: str) -> str | None:  # noqa: ARG002
        return self.value

    def set(self, key: str, value: str) -> None:  # noqa: ARG002
        self.value = value


async def _fake_ok(ctx):  # noqa: ANN001
    return [
        RawResult(
            title="结果一",
            url="https://example.com/a",
            snippet="摘要一",
            source="web",
            raw_score=0.9,
        ),
        RawResult(
            title="结果二",
            url="https://example.com/b",
            snippet="摘要二",
            source="web",
            raw_score=0.8,
        ),
    ]


class _NoopAsyncClient:
    """fake engine 不发请求；Windows 上 `httpx.AsyncClient()` 构造要 2–3s（证书库），
    会把整体 2s 预算耗光。这里只桩掉客户端构造，超时与断言保持原样。"""

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        pass

    async def __aenter__(self):  # noqa: ANN204
        return self

    async def __aexit__(self, *exc) -> bool:  # noqa: ANN002
        return False


async def test_search_fuses_and_ranks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(happy_search.ENGINES, "fake_ok", _fake_ok)
    monkeypatch.setitem(happy_search.ENGINE_META, "fake_ok", ("fake", "api", 1.0))
    monkeypatch.setattr(happy_search.httpx, "AsyncClient", _NoopAsyncClient)

    outcome = await happy_search.search("测试", 2, engines=["fake_ok"], timeout_s=2)

    assert outcome.error is None
    assert [r["url"] for r in outcome.results] == [
        "https://example.com/a",
        "https://example.com/b",
    ]
    assert outcome.results[0]["engine"] == "fake_ok"
    assert outcome.engines_ok == ["fake_ok"]
    assert outcome.engine_stats[0]["status"] == "ok"


async def test_empty_results_fall_back_to_searchfree(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _empty(*args, **kwargs):  # noqa: ANN002, ANN003
        return SearchOutcome(query="空查询", results=[], error="forced empty")

    async def _fallback(query, max_results, *, timeout_s, reason):  # noqa: ANN001
        return {
            "provider": "searchfree",
            "fallback": True,
            "fallback_reason": reason,
            "results": [{"title": "回退结果", "url": "https://fallback.example", "snippet": "ok"}],
            "elapsed_ms": 1,
        }

    monkeypatch.setattr(happy_tool, "search", _empty)
    monkeypatch.setattr(happy_tool, "_searchfree_fallback", _fallback)

    payload = await happy_tool.run_happysearch("空查询", 3)

    assert payload["fallback"] is True
    assert payload["provider"] == "searchfree"
    assert payload["results"][0]["url"] == "https://fallback.example"
    last = status.snapshot()["last"]
    assert last is not None
    assert last["fallback"] is True
    assert last["query"] == "空查询"


async def test_tool_returns_json(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _payload(  # noqa: ANN001
        query: str,
        max_results: int = 5,
        *,
        mode: str = "happysearch",
    ):
        return {"provider": "happysearch", "fallback": False, "results": []}

    monkeypatch.setattr(happy_tool, "run_happysearch", _payload)
    raw = await happy_tool.happysearch_search.ainvoke({"query": "测试", "max_results": 3})
    assert json.loads(raw)["provider"] == "happysearch"


def test_status_is_read_only_and_reports_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCTOP_HAPPYSEARCH_TOOL", "1")
    snapshot = happy_tool.happysearch_status()
    assert snapshot["enabled"] is True
    assert snapshot["config"]["timeout_s"] == 8.0
    assert "last" in snapshot["runtime"]


def test_manager_mounts_exactly_one_free_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    from octop.infra.agents import manager as manager_module

    monkeypatch.delenv("OCTOP_HAPPYSEARCH_TOOL", raising=False)
    monkeypatch.delenv("OCTOP_SEARCH_SOURCE", raising=False)

    default_tools = manager_module._search_tools(_Repo(), {})
    assert [t.name for t in default_tools] == ["happysearch_search"]

    native_tools = manager_module._search_tools(_Repo("searchfree"), {})
    assert [t.name for t in native_tools] == ["searchfree_search"]

    both_tools = manager_module._search_tools(_Repo("both"), {})
    assert [t.name for t in both_tools] == ["happysearch_search"]

    for tools in (default_tools, native_tools, both_tools):
        assert len(tools) == 1

    assert manager_module._search_tools(_Repo("both"), {"web_search_tools": False}) == []


def test_catalog_availability_follows_source(monkeypatch: pytest.MonkeyPatch) -> None:
    from octop.infra.agents.settings.tool_catalog import builtin_tool_available

    monkeypatch.delenv("OCTOP_HAPPYSEARCH_TOOL", raising=False)

    assert builtin_tool_available("happysearch_search", agent_cfg={}) is True
    assert builtin_tool_available("searchfree_search", agent_cfg={}) is False

    assert (
        builtin_tool_available(
            "happysearch_search", agent_cfg={}, search_source="searchfree"
        )
        is False
    )
    assert (
        builtin_tool_available(
            "searchfree_search", agent_cfg={}, search_source="searchfree"
        )
        is True
    )
    assert (
        builtin_tool_available("happysearch_search", agent_cfg={}, search_source="both")
        is True
    )
    assert (
        builtin_tool_available("searchfree_search", agent_cfg={}, search_source="both")
        is False
    )
    assert (
        builtin_tool_available(
            "happysearch_search",
            agent_cfg={"web_search_tools": False},
            search_source="both",
        )
        is False
    )
