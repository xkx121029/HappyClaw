"""原生 searchfree 工具的运行状态（仅标准库、进程内、只读快照）。"""

from __future__ import annotations

import threading
import time
from typing import Any

_lock = threading.Lock()
_state: dict[str, Any] = {
    "runs": 0,
    "errors": 0,
    "in_flight": 0,
    "last": None,
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
    error: str | None = None,
) -> None:
    with _lock:
        _state["in_flight"] = max(0, _state["in_flight"] - 1)
        if status == "error":
            _state["errors"] += 1
        _state["last"] = {
            "query": query,
            "finished_at": time.time(),
            "status": status,
            "elapsed_ms": elapsed_ms,
            "returned": returned,
            "error": error,
        }


def snapshot() -> dict[str, Any]:
    with _lock:
        return {
            "runs": _state["runs"],
            "errors": _state["errors"],
            "in_flight": _state["in_flight"],
            "last": dict(_state["last"]) if _state["last"] else None,
        }
