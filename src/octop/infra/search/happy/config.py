"""HappySearch 嵌入式配置（仅标准库，便于开关关闭时零重依赖导入）。

所有开关均可用环境变量覆盖：
- ``OCTOP_HAPPYSEARCH_TOOL``：总开关，默认关闭。
- ``OCTOP_HAPPYSEARCH_ENGINES``：逗号分隔的引擎白名单，``all`` 表示全部。
- ``OCTOP_HAPPYSEARCH_TIMEOUT``：单次搜索总预算，默认 8 秒。
- ``OCTOP_HAPPYSEARCH_ENGINE_TIMEOUT``：单引擎超时，默认 3 秒。
- ``OCTOP_HAPPYSEARCH_CONCURRENCY``：全局同时在途引擎请求上限，默认 8。
- ``OCTOP_HAPPYSEARCH_LANGUAGE`` / ``OCTOP_HAPPYSEARCH_REGION``：默认 zh / cn。
- ``OCTOP_HAPPYSEARCH_SEARX_URLS``：SearXNG 公共实例列表。
"""

from __future__ import annotations

import os

DEFAULT_ENGINES = (
    "ddg_html",
    "ddg_lite",
    "ddg_instant",
    "wikipedia",
    "bing_html",
    "bing_rss",
    "so360_html",
    "baidu_html",
    "mojeek",
    "searx",
    "hn",
    "arxiv",
    "google_news",
    "bing_news",
)

DEFAULT_SEARX_URLS = (
    "https://searx.be",
    "https://priv.au",
    "https://search.bus-hit.me",
)

_TRUE = ("1", "true", "yes", "on")


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def enabled() -> bool:
    return _bool("OCTOP_HAPPYSEARCH_TOOL", False)


def total_timeout() -> float:
    return max(1.0, _float("OCTOP_HAPPYSEARCH_TIMEOUT", 8.0))


def engine_timeout() -> float:
    return max(0.5, _float("OCTOP_HAPPYSEARCH_ENGINE_TIMEOUT", 3.0))


def max_concurrency() -> int:
    return max(1, _int("OCTOP_HAPPYSEARCH_CONCURRENCY", 8))


def language() -> str:
    return (os.getenv("OCTOP_HAPPYSEARCH_LANGUAGE") or "zh").strip()[:8]


def region() -> str:
    return (os.getenv("OCTOP_HAPPYSEARCH_REGION") or "cn").strip()[:8]


def engines() -> list[str]:
    raw = os.getenv("OCTOP_HAPPYSEARCH_ENGINES", "").strip()
    if not raw:
        return list(DEFAULT_ENGINES)
    names: list[str] = []
    for part in raw.split(","):
        name = part.strip().lower()
        if not name:
            continue
        if name == "all":
            return list(DEFAULT_ENGINES)
        if name in DEFAULT_ENGINES and name not in names:
            names.append(name)
    return names or list(DEFAULT_ENGINES)


def searx_urls() -> tuple[str, ...]:
    raw = os.getenv("OCTOP_HAPPYSEARCH_SEARX_URLS", "").strip()
    if not raw:
        return DEFAULT_SEARX_URLS
    urls = tuple(x.strip().rstrip("/") for x in raw.split(",") if x.strip())
    return urls or DEFAULT_SEARX_URLS


def snapshot() -> dict:
    """配置快照：只读、无副作用，供状态查询使用。"""
    return {
        "enabled": enabled(),
        "engines": engines(),
        "timeout_s": total_timeout(),
        "engine_timeout_s": engine_timeout(),
        "max_concurrency": max_concurrency(),
        "language": language(),
        "region": region(),
        "searx_urls": list(searx_urls()),
    }
