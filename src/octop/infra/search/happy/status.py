"""只读运行状态：最近一次调用、计数、在途请求数。

刻意只依赖标准库：开关关闭时，状态查询不应导入 bs4/httpx 等重依赖。
"""

from __future__ import annotations

import threading
import time
from typing import Any

_lock = threading.Lock()
_state: dict[str, Any] = {
    "runs": 0,
    "fallbacks": 0,
    "errors": 0,
    "in_flight": 0,
    "last": None,
    "engines_last": {},
}


def mark_start(query: str) -> None:
    with _lock:
        _state["runs"] += 1
        _state["in_flight"] += 1
        _state["last"] = {
            "query": query,
            "started_at": time.time(),
            "status": "running",
        }


def mark_finish(
    *,
    status: str,
    elapsed_ms: int,
    query: str,
    returned: int = 0,
    engines_ok: list[str] | None = None,
    engines_empty: list[str] | None = None,
    engines_failed: list[str] | None = None,
    engine_stats: list[dict[str, Any]] | None = None,
    fallback: bool = False,
    error: str | None = None,
    source: str = "happysearch",
    degraded: bool = False,
    native_elapsed_ms: int | None = None,
    native_returned: int = 0,
    native_error: str | None = None,
) -> None:
    finished_at = time.time()
    with _lock:
        _state["in_flight"] = max(0, _state["in_flight"] - 1)
        if fallback:
            _state["fallbacks"] += 1
        if status == "error":
            _state["errors"] += 1
        for stat in engine_stats or []:
            engine = str(stat.get("engine") or "")
            if not engine:
                continue
            _state["engines_last"][engine] = {
                "status": stat.get("status"),
                "count": stat.get("count", 0),
                "elapsed_ms": stat.get("elapsed_ms", 0),
                "error": stat.get("error"),
                "at": finished_at,
            }
        _state["last"] = {
            "query": query,
            "finished_at": finished_at,
            "status": status,
            "source": source,
            "degraded": degraded,
            "elapsed_ms": elapsed_ms,
            "returned": returned,
            "engines_ok": engines_ok or [],
            "engines_empty": engines_empty or [],
            "engines_failed": engines_failed or [],
            "engine_stats": engine_stats or [],
            "fallback": fallback,
            "error": error,
            "native_elapsed_ms": native_elapsed_ms,
            "native_returned": native_returned,
            "native_error": native_error,
        }


def snapshot() -> dict[str, Any]:
    with _lock:
        return {
            "runs": _state["runs"],
            "fallbacks": _state["fallbacks"],
            "errors": _state["errors"],
            "in_flight": _state["in_flight"],
            "last": dict(_state["last"]) if _state["last"] else None,
            "engines_last": {
                name: dict(value) for name, value in _state["engines_last"].items()
            },
        }
