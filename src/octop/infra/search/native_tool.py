"""把 Octop 原生 ``searchfree`` 包装成可观测的 LangChain 工具。

工具名保持 ``searchfree_search``，输出形状与 harness 原工具一致
（JSON 数组字符串，空结果返回 ``No results found.``，错误返回
``Error: ...``）。差异只有：调用会被记录到进程内状态，供设置页查看。
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import tool

from . import native_status

_DEFAULT_TIMEOUT_S = 8.0


@dataclass
class NativeOutcome:
    query: str
    results: list[dict[str, Any]] = field(default_factory=list)
    elapsed_ms: int = 0
    error: str | None = None
    text: str = ""


def _consume_task_result(task: asyncio.Task[Any]) -> None:
    """吞掉被放弃任务的异常，避免 event loop 报 unhandled exception。"""
    if task.cancelled():
        return
    try:
        task.exception()
    except Exception:  # noqa: BLE001 - 回调边界
        pass


def _parse_response(text: str) -> tuple[list[dict[str, Any]], str | None]:
    stripped = text.strip()
    if stripped.startswith("Error:"):
        return [], stripped
    if not stripped or stripped == "No results found.":
        return [], None
    try:
        data = json.loads(stripped)
    except ValueError:
        return [], f"searchfree returned non-JSON: {stripped[:120]}"
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)], None
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        return [item for item in data["results"] if isinstance(item, dict)], None
    return [], "searchfree returned an unexpected response shape"


async def run_searchfree(
    query: str,
    max_results: int = 5,
    *,
    timeout_s: float | None = None,
    search_depth: str = "basic",
) -> NativeOutcome:
    """执行一次原生 searchfree 搜索并记录运行状态。"""
    query = (query or "").strip()
    if not query:
        return NativeOutcome(query=query, error="query 不能为空")

    budget = max(0.2, timeout_s or _DEFAULT_TIMEOUT_S)
    started = time.perf_counter()
    elapsed_ms = 0
    native_status.mark_start(query)
    status = "ok"
    error: str | None = None
    results: list[dict[str, Any]] = []

    task: asyncio.Task[Any] | None = None
    try:
        from octop_harness.builtin.tools.web_search.searchfree import (  # noqa: PLC0415
            searchfree_search as harness_searchfree,
        )

        task = asyncio.create_task(
            harness_searchfree.ainvoke(
                {
                    "query": query,
                    "max_results": max(1, min(int(max_results), 20)),
                    "search_depth": search_depth,
                }
            )
        )
        # shield + wait_for：到点立即返回，不等底层 httpx 取消完成，
        # 保证工具总预算不会被第三方请求拖长。
        raw = await asyncio.wait_for(asyncio.shield(task), timeout=budget)
        text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
        results, error = _parse_response(text)
        if error:
            status = "error"
    except asyncio.TimeoutError:
        status = "error"
        error = f"searchfree 超过 {budget:g}s 未返回"
        if task is not None:
            task.cancel()
            task.add_done_callback(_consume_task_result)
    except Exception as exc:  # noqa: BLE001 - 工具边界不能把异常抛给 agent
        status = "error"
        error = f"{type(exc).__name__}: {str(exc)[:200]}"
    finally:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        native_status.mark_finish(
            status=status,
            elapsed_ms=elapsed_ms,
            query=query,
            returned=len(results),
            error=error,
        )

    return NativeOutcome(
        query=query,
        results=results[: max(1, min(int(max_results), 20))],
        elapsed_ms=elapsed_ms,
        error=error,
    )


@tool
async def searchfree_search(
    query: str,
    max_results: int = 5,
    search_depth: str = "basic",
) -> str:
    """通过免费的 ``searchfree.site`` 接口搜索公开网页。

    无需 API Key，单次请求直连第三方；失败时原样返回错误，不回退到
    HappySearch。需要多引擎聚合或失败兜底时请改用 ``happysearch_search``。

    Args:
        query: 搜索关键词。
        max_results: 返回条数，默认 5，最大 20。
        search_depth: ``basic``（默认）或 ``advanced``。
    """
    outcome = await run_searchfree(
        query,
        max_results,
        search_depth=search_depth,
    )
    if outcome.error:
        return outcome.error if outcome.error.startswith("Error:") else f"Error: {outcome.error}"
    if not outcome.results:
        return "No results found."
    return json.dumps(outcome.results, ensure_ascii=False)


def searchfree_status() -> dict[str, Any]:
    """只读状态快照；不触发网络请求。"""
    return {"enabled": True, "runtime": native_status.snapshot()}


def build_searchfree_tool() -> Any:
    return searchfree_search


__all__ = [
    "NativeOutcome",
    "build_searchfree_tool",
    "run_searchfree",
    "searchfree_search",
    "searchfree_status",
]
