"""Local runtime activity for the desktop exit guard.

The desktop shell (``desktop/src/main/quit-guard.ts``) polls
``GET /api/runtime/activity`` before a user-initiated quit. It only understands
``{"busy": true, "counts": {"<kind>": <n>}}`` where kind is one of
``agent_turn`` / ``terminal`` (anything else is echoed verbatim). The extra flat
fields below are for the dashboard and logs; ``busy`` is always consistent with
``sum(counts.values()) > 0`` so the shell never shows an empty prompt.

Single-user mode: this endpoint is anonymous and only reports counters.
"""

from __future__ import annotations

import time
from typing import Any, cast

from fastapi import APIRouter, Depends

from happyclaw.api.deps import get_server

router = APIRouter()

_CACHE_TTL_SECONDS = 2.0
_CACHE_ATTR = "_runtime_activity_cache"


def _terminal_session_count() -> int:
    """Live PTY sessions (registry owned by the terminal router)."""
    try:
        from happyclaw.api.routers.terminal import _sessions

        return len(_sessions)
    except Exception:  # pragma: no cover - defensive
        return 0


def _collect(server: Any) -> dict[str, Any]:
    runtime = getattr(server, "app_runtime", None)
    hub_snapshot: dict[str, int] = {}
    running_agents = 0
    running_jobs = 0

    if runtime is not None:
        gateway = getattr(runtime, "gateway", None)
        hub = getattr(gateway, "ws_hub", None)
        if hub is not None:
            hub_snapshot = dict(getattr(hub, "runtime_snapshot", {}) or {})

        registry = getattr(runtime, "agent_registry", None)
        if registry is not None and hasattr(registry, "list_rows"):
            try:
                running_agents = sum(
                    1
                    for row in registry.list_rows()
                    if getattr(row, "state", None) in {"running", "working"}
                )
            except Exception:  # pragma: no cover - defensive
                running_agents = 0

        cron = getattr(runtime, "cron_manager", None)
        if cron is not None and hasattr(cron, "list_all"):
            try:
                running_jobs = sum(
                    1 for row in cron.list_all() if getattr(row, "last_status", None) == "running"
                )
            except Exception:  # pragma: no cover - defensive
                running_jobs = 0

    active_turns = hub_snapshot.get("active_turns", 0)
    dashboard_connections = hub_snapshot.get("connections", 0)
    threads_with_subscribers = hub_snapshot.get("threads_with_subscribers", 0)
    terminals = _terminal_session_count()

    # ``counts`` is the contract the desktop quit guard reads. ``agent_turn`` and
    # ``terminal`` are always present (0 when idle) so the renderer can read
    # ``counts.agent_turn`` without an undefined check. Other kinds only appear
    # when non-zero; ``busy`` stays consistent with ``sum(counts) > 0``.
    counts: dict[str, int] = {"agent_turn": active_turns, "terminal": terminals}
    if running_jobs > 0:
        counts["job"] = running_jobs

    return {
        "busy": sum(counts.values()) > 0,
        "counts": counts,
        "active_turns": active_turns,
        "dashboard_connections": dashboard_connections,
        "threads_with_subscribers": threads_with_subscribers,
        "terminal_sessions": terminals,
        "running_agents": running_agents,
        "running_jobs": running_jobs,
        "updated_at": int(time.time()),
    }


@router.get("/activity", summary="Backend activity for the desktop exit guard")
async def activity(server: Any = Depends(get_server)) -> dict[str, Any]:
    """Return whether the backend is busy; cached for two seconds."""
    now = time.monotonic()
    cached = getattr(server, _CACHE_ATTR, None)
    if cached is not None and now - cached[0] < _CACHE_TTL_SECONDS:
        return cast("dict[str, Any]", cached[1])
    payload = _collect(server)
    setattr(server, _CACHE_ATTR, (now, payload))
    return payload
