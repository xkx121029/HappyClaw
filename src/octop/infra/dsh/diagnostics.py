"""Process-local ledger of the most recent DSH load and execution failures.

The S2 tool assembly and the S10 runtime already return typed codes on the
call path; this module keeps the *last* one of each kind so the DSH status
endpoint can answer "why did it fail" without replaying a request or scanning
logs. It is intentionally small:

* in-memory only (the server is single-user and single-process);
* bounded (``MAX_FAILURES`` records) and de-duplicated by identity, keeping the
  newest timestamp for a recurring failure;
* store-only — it never raises, so recording cannot break a tool call.

Records are plain dicts because they are served by the HTTP layer verbatim.
"""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any

MAX_FAILURES = 50
MAX_REASON_CHARS = 600

_LOCK = Lock()
_FAILURES: list[dict[str, Any]] = []


def _signature(record: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(record.get("kind") or ""),
        str(record.get("plugin_id") or ""),
        str(record.get("code") or ""),
        str(record.get("reason") or ""),
    )


def record_failure(
    *,
    kind: str,
    plugin_id: str,
    code: str,
    reason: str = "",
    detail: str = "",
) -> dict[str, Any]:
    """Remember one ``load`` or ``execute`` failure and return the record."""

    record = {
        "at": datetime.now(timezone.utc).isoformat(),
        "kind": "execute" if kind == "execute" else "load",
        "plugin_id": str(plugin_id or ""),
        "code": str(code or ""),
        "reason": str(reason or "")[:MAX_REASON_CHARS],
        "detail": str(detail or "")[:MAX_REASON_CHARS],
    }
    signature = _signature(record)
    with _LOCK:
        _FAILURES[:] = [item for item in _FAILURES if _signature(item) != signature]
        _FAILURES.insert(0, record)
        del _FAILURES[MAX_FAILURES:]
    return dict(record)


def latest_failure() -> dict[str, Any] | None:
    """The newest recorded failure, or None when nothing has failed yet."""

    with _LOCK:
        return dict(_FAILURES[0]) if _FAILURES else None


def recent_failures(limit: int = 10) -> list[dict[str, Any]]:
    """Newest-first failures, capped at ``limit`` (and the bounded store)."""

    if limit <= 0:
        return []
    with _LOCK:
        return [dict(item) for item in _FAILURES[: min(limit, MAX_FAILURES)]]


def clear_failures() -> None:
    """Drop every record. Used by status tests and a manual reset."""

    with _LOCK:
        _FAILURES.clear()


__all__ = [
    "MAX_FAILURES",
    "clear_failures",
    "latest_failure",
    "record_failure",
    "recent_failures",
]
