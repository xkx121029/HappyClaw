"""把 HappySearch 暴露为 LangChain 工具 ``happysearch_search``。

支持两种运行模式（由设置页的搜索来源决定）：

- ``happysearch``：多引擎聚合；超时/全空/全引擎失败时内部回退到
  ``searchfree``，但不会把 ``searchfree_search`` 作为第二个工具暴露给模型。
- ``both``：HappySearch 与原生 searchfree 并发，按归一化链接去重后用
  RRF 分数融合排序，逐条标注来源；单边失败/全空时自动使用另一边。

两种模式都会把运行状态写入 :mod:`status`，供 ``/api/search/status`` 查询。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from langchain_core.tools import tool

from .happy import config, status
from .happy.ranker import normalize_url
from .happy.search import SearchOutcome, search
from .native_tool import NativeOutcome, run_searchfree

logger = logging.getLogger(__name__)

_FALLBACK_RESERVE_S = 2.0


def happysearch_status(enabled: bool | None = None) -> dict[str, Any]:
    """只读状态快照；不触发引擎与网络请求。"""
    return {
        "enabled": config.enabled() if enabled is None else enabled,
        "config": config.snapshot(),
        "runtime": status.snapshot(),
    }


async def _searchfree_fallback(
    query: str,
    max_results: int,
    *,
    timeout_s: float,
    reason: str,
) -> dict[str, Any]:
    """调用原生 searchfree 回退，保持与旧搜索路径一致的结果形状。"""
    native = await run_searchfree(query, max_results, timeout_s=timeout_s)
    payload: dict[str, Any] = {
        "provider": "searchfree",
        "source": "searchfree",
        "fallback": True,
        "fallback_reason": reason,
        "results": native.results,
        "elapsed_ms": native.elapsed_ms,
    }
    if native.error:
        payload["error"] = native.error
    return payload


def _payload_from_outcome(outcome: SearchOutcome) -> dict[str, Any]:
    return {
        "provider": "happysearch",
        "source": "happysearch",
        "mode": "happysearch",
        "fallback": False,
        "query": outcome.query,
        "elapsed_ms": outcome.elapsed_ms,
        "results": [
            {
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "snippet": item.get("snippet") or "",
                "source": "happysearch",
                "sources": ["happysearch"],
                "engine": item.get("engine"),
                "score": item.get("score"),
                "published_at": item.get("published_at"),
                "domain": item.get("domain"),
            }
            for item in outcome.results
        ],
        "engines": {
            "ok": outcome.engines_ok,
            "empty": outcome.engines_empty,
            "failed": outcome.engines_failed,
            "stats": outcome.engine_stats,
        },
    }


def _normalized_item(raw: dict[str, Any], source_name: str) -> dict[str, Any]:
    snippet = raw.get("snippet") or raw.get("content") or ""
    return {
        "title": raw.get("title") or "",
        "url": raw.get("url") or "",
        "snippet": snippet,
        "source": source_name,
        "sources": [source_name],
        "fused_score": 0.0,
        "engine": raw.get("engine"),
        "score": raw.get("score"),
        "published_at": raw.get("published_at"),
        "domain": raw.get("domain"),
    }


def _fuse_sources(
    happy_items: list[dict[str, Any]],
    native_items: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    """按归一化链接去重，用 RRF 分数融合两路结果。"""
    fused: dict[str, dict[str, Any]] = {}
    for source_name, items in (("happysearch", happy_items), ("searchfree", native_items)):
        for rank, raw in enumerate(items, start=1):
            url = str(raw.get("url") or "")
            key = normalize_url(url)
            if not key:
                continue
            entry = fused.setdefault(
                key,
                {
                    "item": _normalized_item(raw, source_name),
                    "score": 0.0,
                    "sources": [],
                },
            )
            entry["score"] += 1.0 / (60 + rank)
            if source_name not in entry["sources"]:
                entry["sources"].append(source_name)
            raw_snippet = str(raw.get("snippet") or raw.get("content") or "")
            if len(raw_snippet) > len(str(entry["item"].get("snippet") or "")):
                entry["item"]["snippet"] = raw_snippet
            if not entry["item"].get("title") and raw.get("title"):
                entry["item"]["title"] = raw.get("title")

    merged: list[dict[str, Any]] = []
    for entry in sorted(fused.values(), key=lambda value: value["score"], reverse=True):
        item = entry["item"]
        sources = entry["sources"]
        item["sources"] = sources
        item["source"] = "both" if len(sources) > 1 else sources[0]
        item["fused_score"] = round(float(entry["score"]), 6)
        merged.append(item)
    return merged[:limit]


def _single_source(
    items: list[dict[str, Any]],
    source_name: str,
    limit: int,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for rank, raw in enumerate(items[:limit], start=1):
        item = _normalized_item(raw, source_name)
        item["fused_score"] = round(1.0 / (60 + rank), 6)
        merged.append(item)
    return merged


def _error_text(value: BaseException | None) -> str | None:
    if value is None:
        return None
    return f"{type(value).__name__}: {str(value)[:200]}"


async def _run_combined(
    query: str,
    max_results: int,
    *,
    total_budget: float,
) -> dict[str, Any]:
    """HappySearch + searchfree 并发；单边失败不影响另一边。"""
    started = time.perf_counter()
    budget = max(1.0, total_budget)
    status.mark_start(query)

    happy_outcome: SearchOutcome | None = None
    native_outcome: NativeOutcome | None = None
    happy_error: str | None = None
    native_error: str | None = None
    results: list[dict[str, Any]] = []
    degraded = False
    final_status = "ok"
    error: str | None = None

    try:
        gathered = await asyncio.gather(
            search(query, max_results * 2, timeout_s=budget),
            run_searchfree(query, max_results * 2, timeout_s=budget),
            return_exceptions=True,
        )
        happy_result, native_result = gathered

        if isinstance(happy_result, BaseException):
            happy_error = _error_text(happy_result)
        else:
            happy_outcome = happy_result
            happy_error = happy_outcome.error

        if isinstance(native_result, BaseException):
            native_error = _error_text(native_result)
        else:
            native_outcome = native_result
            native_error = native_outcome.error

        happy_items = happy_outcome.results if happy_outcome else []
        native_items = native_outcome.results if native_outcome else []

        if happy_items and native_items:
            results = _fuse_sources(happy_items, native_items, max_results)
        elif happy_items:
            degraded = True
            results = _single_source(happy_items, "happysearch", max_results)
        elif native_items:
            degraded = True
            results = _single_source(native_items, "searchfree", max_results)
        else:
            final_status = "error"
            error = "；".join(part for part in (happy_error, native_error) if part) or (
                "两路搜索均无结果"
            )
    except Exception as exc:  # noqa: BLE001 - 工具边界不能把异常抛给 agent
        logger.exception("combined search failed")
        final_status = "error"
        error = _error_text(exc)
    finally:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        status.mark_finish(
            status=final_status,
            elapsed_ms=elapsed_ms,
            query=query,
            returned=len(results),
            engines_ok=happy_outcome.engines_ok if happy_outcome else [],
            engines_empty=happy_outcome.engines_empty if happy_outcome else [],
            engines_failed=happy_outcome.engines_failed if happy_outcome else [],
            engine_stats=happy_outcome.engine_stats if happy_outcome else [],
            fallback=False,
            error=error,
            source="both",
            degraded=degraded,
            native_elapsed_ms=native_outcome.elapsed_ms if native_outcome else None,
            native_returned=len(native_outcome.results) if native_outcome else 0,
            native_error=native_error,
        )

    return {
        "provider": "happysearch",
        "source": "both",
        "mode": "both",
        "fallback": False,
        "degraded": degraded,
        "query": query,
        "elapsed_ms": elapsed_ms,
        "results": results,
        "sources": {
            "happysearch": {
                "ok": bool(happy_outcome and happy_outcome.results),
                "returned": len(happy_outcome.results) if happy_outcome else 0,
                "elapsed_ms": happy_outcome.elapsed_ms if happy_outcome else None,
                "error": happy_error,
            },
            "searchfree": {
                "ok": bool(native_outcome and native_outcome.results),
                "returned": len(native_outcome.results) if native_outcome else 0,
                "elapsed_ms": native_outcome.elapsed_ms if native_outcome else None,
                "error": native_error,
            },
        },
        "error": error,
    }


async def run_happysearch(
    query: str,
    max_results: int = 5,
    *,
    mode: str = "happysearch",
) -> dict[str, Any]:
    """执行一次搜索（含回退/融合），返回可直接 JSON 化的结构。"""
    total_budget = config.total_timeout()
    if mode == "both":
        return await _run_combined(query, max_results, total_budget=total_budget)

    primary_budget = max(1.0, total_budget - _FALLBACK_RESERVE_S)
    started = time.perf_counter()
    status.mark_start(query)

    fallback = False
    final_status = "ok"
    error: str | None = None
    returned = 0
    outcome: SearchOutcome | None = None
    payload: dict[str, Any]

    try:
        outcome = await search(query, max_results, timeout_s=primary_budget)
        if outcome.results:
            payload = _payload_from_outcome(outcome)
            returned = len(outcome.results)
        else:
            if outcome.error:
                reason = outcome.error
            elif outcome.engines_failed and not outcome.engines_ok:
                reason = f"{len(outcome.engines_failed)} 个引擎全部失败"
            else:
                reason = "多引擎搜索无结果"
            remaining = max(0.2, total_budget - (time.perf_counter() - started))
            fallback = True
            payload = await _searchfree_fallback(
                query, max_results, timeout_s=remaining, reason=reason
            )
            returned = len(payload.get("results") or [])
            if payload.get("error"):
                final_status = "error"
                error = payload["error"]
    except Exception as exc:  # noqa: BLE001 - 工具边界不能把异常抛给 agent
        logger.exception("happysearch tool failed")
        final_status = "error"
        error = _error_text(exc)
        payload = {
            "provider": "happysearch",
            "source": "happysearch",
            "mode": "happysearch",
            "fallback": False,
            "query": query,
            "results": [],
            "error": error,
        }
    finally:
        status.mark_finish(
            status=final_status,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            query=query,
            returned=returned,
            engines_ok=outcome.engines_ok if outcome else [],
            engines_empty=outcome.engines_empty if outcome else [],
            engines_failed=outcome.engines_failed if outcome else [],
            engine_stats=outcome.engine_stats if outcome else [],
            fallback=fallback,
            error=error,
            source="searchfree" if fallback else "happysearch",
        )

    return payload


@tool
async def happysearch_search(query: str, max_results: int = 5) -> str:
    """多引擎中文优先搜索（HappySearch 内核）。

    并发调用百度、360、Bing、DuckDuckGo、维基百科等免 Key 引擎，做 RRF
    融合与加权精排，返回标题、链接、摘要。总预算 8 秒；超时、全部引擎
    失败或无结果时自动回退到原生 searchfree，返回中会标记
    ``fallback=true``。

    Args:
        query: 搜索关键词，中文长尾查询优先使用本工具。
        max_results: 返回条数，默认 5，最大 20。
    """
    payload = await run_happysearch(query, max_results, mode="happysearch")
    return json.dumps(payload, ensure_ascii=False)


def build_happysearch_tool(mode: str = "happysearch") -> Any:
    if mode != "both":
        return happysearch_search

    @tool("happysearch_search")
    async def _combined(query: str, max_results: int = 5) -> str:
        """HappySearch + 原生 searchfree 联合搜索。

        两路并发请求，按归一化链接去重后用 RRF 分数融合排序，每条结果
        标注 ``source``（happysearch / searchfree / both）。单边失败或全空
        时自动使用另一边并标记 ``degraded=true``；两边都失败才返回错误。
        总预算 8 秒，不会因为并发两路而翻倍。

        Args:
            query: 搜索关键词。
            max_results: 返回条数，默认 5，最大 20。
        """
        payload = await run_happysearch(query, max_results, mode="both")
        return json.dumps(payload, ensure_ascii=False)

    return _combined


__all__ = [
    "build_happysearch_tool",
    "happysearch_search",
    "happysearch_status",
    "run_happysearch",
]
