"""HappySearch 免配置引擎编排：并发调用 -> 引擎级隔离 -> RRF 融合 -> 精排。

Vendored from HappySearch ``app/providers/free.py`` 与 ``app/services.py``
的 Web 检索路径 (MIT, commit c1f64f1)。改动：
- 不依赖 FastAPI / 全局 settings；配置由 :mod:`config` 注入。
- 增加全局在途引擎请求上限（进程内 Semaphore）。
- 单次搜索强制总预算，单引擎固定 3 秒。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from . import config
from .engines import ENGINE_META, ENGINES, EngineContext, build_headers
from .models import RawResult
from .ranker import normalize_url, rank

logger = logging.getLogger(__name__)

# 进程级并发闸门：限制同时打到第三方的引擎请求数，避免多 agent 叠加。
_engine_slots: asyncio.Semaphore | None = None


def _slots() -> asyncio.Semaphore:
    global _engine_slots
    if _engine_slots is None:
        _engine_slots = asyncio.Semaphore(config.max_concurrency())
    return _engine_slots


@dataclass
class SearchOutcome:
    query: str
    results: list[dict[str, Any]] = field(default_factory=list)
    engine_stats: list[dict[str, Any]] = field(default_factory=list)
    elapsed_ms: int = 0
    timed_out: bool = False
    error: str | None = None

    @property
    def engines_ok(self) -> list[str]:
        return [s["engine"] for s in self.engine_stats if s["status"] == "ok"]

    @property
    def engines_empty(self) -> list[str]:
        return [s["engine"] for s in self.engine_stats if s["status"] == "empty"]

    @property
    def engines_failed(self) -> list[str]:
        return [s["engine"] for s in self.engine_stats if s["status"] == "failed"]


def _fuse(outcomes: list[tuple[str, list[RawResult]]], limit: int) -> list[RawResult]:
    fused: dict[str, dict[str, Any]] = {}
    for engine, items in outcomes:
        weight = ENGINE_META.get(engine, ("", "", 0.8))[2]
        for idx, item in enumerate(items, start=1):
            key = normalize_url(item.url)
            if not key:
                continue
            entry = fused.setdefault(
                key, {"item": item, "rrf": 0.0, "engines": [], "raw_score": 0.0}
            )
            entry["rrf"] += weight / (60 + idx)
            entry["engines"].append(engine)
            if item.raw_score >= entry["raw_score"]:
                entry["raw_score"] = item.raw_score
                entry["item"] = item

    merged: list[RawResult] = []
    for rank_no, entry in enumerate(
        sorted(fused.values(), key=lambda e: e["rrf"], reverse=True)[:limit], start=1
    ):
        item: RawResult = entry["item"]
        item.rank_in_source = rank_no
        item.extra["engine"] = entry["engines"][0]
        item.extra["engines"] = list(dict.fromkeys(entry["engines"]))
        merged.append(item)
    return merged


async def _run_search(
    query: str,
    max_results: int,
    *,
    language: str,
    region: str,
    time_range: str,
    engines: list[str] | None,
) -> SearchOutcome:
    started = time.perf_counter()
    configured = engines if engines is not None else config.engines()
    names = [n for n in configured if n in ENGINES]
    unknown = [n for n in configured if n not in ENGINES]
    if unknown:
        logger.warning("忽略未知免配置引擎: %s", unknown)
    if not names:
        return SearchOutcome(
            query=query,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            error="没有可用的免配置引擎",
        )

    engine_timeout = config.engine_timeout()
    limit = min(max(max_results * 2, 10), 50)
    stats: list[dict[str, Any]] = []

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(engine_timeout),
        headers=build_headers(),
        follow_redirects=True,
    ) as client:
        ctx = EngineContext(
            client=client,
            query=query,
            limit=limit,
            language=language,
            region=region,
            time_range=time_range,
            searx_urls=config.searx_urls(),
        )

        async def one(name: str) -> tuple[str, list[RawResult], dict[str, Any]]:
            started_one = time.perf_counter()
            status, error, items = "ok", None, []
            try:
                async with _slots():
                    raw = await asyncio.wait_for(ENGINES[name](ctx), timeout=engine_timeout)
                items = [r for r in raw if r.url.startswith(("http://", "https://"))]
                if not items:
                    status = "empty"
            except Exception as exc:  # noqa: BLE001 - 单引擎失败必须隔离
                status, error = "failed", f"{type(exc).__name__}: {str(exc)[:120]}"
                logger.warning("happysearch engine failed: %s -> %s", name, error)
            stat = {
                "engine": name,
                "status": status,
                "count": len(items),
                "elapsed_ms": int((time.perf_counter() - started_one) * 1000),
                "error": error,
            }
            return name, items, stat

        outcomes = await asyncio.gather(*(one(name) for name in names), return_exceptions=True)

    merged_inputs: list[tuple[str, list[RawResult]]] = []
    for outcome in outcomes:
        if isinstance(outcome, BaseException):
            # one() 已捕获 Exception；这里兜底防止未预期异常连坐其他引擎
            logger.exception("happysearch unexpected engine failure during gather")
            continue
        name, items, stat = outcome
        stats.append(stat)
        merged_inputs.append((name, items))

    fused = _fuse(merged_inputs, max_results * 2)
    ranked = rank({"web": fused}, query, pool_size=max(max_results * 5, 50))
    results = []
    for item in ranked[:max_results]:
        item.pop("_sort_ts", None)
        item.pop("score_breakdown", None)
        results.append(item)

    return SearchOutcome(
        query=query,
        results=results,
        engine_stats=stats,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )


async def search(
    query: str,
    max_results: int = 5,
    *,
    language: str | None = None,
    region: str | None = None,
    time_range: str = "all",
    engines: list[str] | None = None,
    timeout_s: float | None = None,
) -> SearchOutcome:
    """执行一次完整搜索；总预算默认 8 秒，超时返回 ``timed_out=True``。"""
    query = (query or "").strip()
    if not query:
        return SearchOutcome(query=query, error="query 不能为空")
    max_results = max(1, min(int(max_results), 20))
    budget = timeout_s or config.total_timeout()
    try:
        return await asyncio.wait_for(
            _run_search(
                query,
                max_results,
                language=language or config.language(),
                region=region or config.region(),
                time_range=time_range,
                engines=engines,
            ),
            timeout=budget,
        )
    except asyncio.TimeoutError:
        return SearchOutcome(query=query, timed_out=True, error=f"检索超过 {budget:g}s 未完成")
