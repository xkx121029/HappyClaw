"""结合模式：去重、融合排序、单边失败、双败。"""

from __future__ import annotations

import asyncio
import time

import pytest

from octop.infra.search import happy_tool
from octop.infra.search.happy.search import SearchOutcome
from octop.infra.search.native_tool import NativeOutcome


def _happy(items: list[dict]) -> SearchOutcome:
    return SearchOutcome(query="q", results=items, elapsed_ms=1)


def _native(items: list[dict]) -> NativeOutcome:
    return NativeOutcome(query="q", results=items, elapsed_ms=1)


async def test_combined_dedupes_and_fuses(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _happy_search(*args, **kwargs):  # noqa: ANN002, ANN003
        return _happy(
            [
                {
                    "title": "A",
                    "url": "https://Example.com/a?utm_source=x",
                    "snippet": "short",
                    "engine": "bing_html",
                    "score": 0.9,
                    "domain": "example.com",
                },
                {
                    "title": "H",
                    "url": "https://example.com/only-happy",
                    "snippet": "happy",
                    "engine": "bing_html",
                    "score": 0.8,
                    "domain": "example.com",
                },
            ]
        )

    async def _native_search(*args, **kwargs):  # noqa: ANN002, ANN003
        return _native(
            [
                {
                    "title": "A2",
                    "url": "https://example.com/a",
                    "snippet": "a much longer snippet from native",
                },
                {
                    "title": "N",
                    "url": "https://example.com/only-native",
                    "snippet": "native",
                },
            ]
        )

    monkeypatch.setattr(happy_tool, "search", _happy_search)
    monkeypatch.setattr(happy_tool, "run_searchfree", _native_search)

    payload = await happy_tool.run_happysearch("q", 5, mode="both")

    assert payload["mode"] == "both"
    assert payload["degraded"] is False
    assert len(payload["results"]) == 3
    first = payload["results"][0]
    assert first["url"] == "https://Example.com/a?utm_source=x"
    assert first["source"] == "both"
    assert set(first["sources"]) == {"happysearch", "searchfree"}
    assert first["snippet"] == "a much longer snippet from native"
    assert payload["sources"]["happysearch"]["returned"] == 2
    assert payload["sources"]["searchfree"]["returned"] == 2


async def test_combined_single_side_failure_uses_other(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _happy_search(*args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("happy down")

    async def _native_search(*args, **kwargs):  # noqa: ANN002, ANN003
        return _native([{"title": "N", "url": "https://example.com/n", "snippet": "n"}])

    monkeypatch.setattr(happy_tool, "search", _happy_search)
    monkeypatch.setattr(happy_tool, "run_searchfree", _native_search)

    payload = await happy_tool.run_happysearch("q", 5, mode="both")

    assert payload["degraded"] is True
    assert payload["error"] is None
    assert [item["source"] for item in payload["results"]] == ["searchfree"]
    assert payload["sources"]["happysearch"]["ok"] is False
    assert "happy down" in (payload["sources"]["happysearch"]["error"] or "")


async def test_combined_native_failure_uses_happy(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _happy_search(*args, **kwargs):  # noqa: ANN002, ANN003
        return _happy([{"title": "H", "url": "https://example.com/h", "snippet": "h"}])

    async def _native_search(*args, **kwargs):  # noqa: ANN002, ANN003
        return NativeOutcome(query="q", results=[], error="timeout")

    monkeypatch.setattr(happy_tool, "search", _happy_search)
    monkeypatch.setattr(happy_tool, "run_searchfree", _native_search)

    payload = await happy_tool.run_happysearch("q", 5, mode="both")

    assert payload["degraded"] is True
    assert [item["source"] for item in payload["results"]] == ["happysearch"]


async def test_combined_both_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _happy_search(*args, **kwargs):  # noqa: ANN002, ANN003
        return SearchOutcome(query="q", results=[], error="happy empty")

    async def _native_search(*args, **kwargs):  # noqa: ANN002, ANN003
        return NativeOutcome(query="q", results=[], error="native empty")

    monkeypatch.setattr(happy_tool, "search", _happy_search)
    monkeypatch.setattr(happy_tool, "run_searchfree", _native_search)

    payload = await happy_tool.run_happysearch("q", 5, mode="both")

    assert payload["results"] == []
    assert payload["error"]
    assert "happy empty" in payload["error"]
    assert "native empty" in payload["error"]


async def test_combined_runs_concurrently(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _slow(*args, **kwargs):  # noqa: ANN002, ANN003
        await asyncio.sleep(0.1)
        return _happy([{"title": "H", "url": "https://example.com/h", "snippet": "h"}])

    async def _slow_native(*args, **kwargs):  # noqa: ANN002, ANN003
        await asyncio.sleep(0.1)
        return _native([{"title": "N", "url": "https://example.com/n", "snippet": "n"}])

    monkeypatch.setattr(happy_tool, "search", _slow)
    monkeypatch.setattr(happy_tool, "run_searchfree", _slow_native)
    monkeypatch.setattr(happy_tool.config, "total_timeout", lambda: 2.0)

    started = time.perf_counter()
    await happy_tool.run_happysearch("q", 5, mode="both")
    elapsed = time.perf_counter() - started

    assert elapsed < 0.19
