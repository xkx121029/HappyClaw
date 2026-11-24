"""Append-only ledgers for the plugin sandbox.

Two separate streams:

* :class:`SandboxAuditRecord` — one record per *denial*. Denials are rare and
  individually interesting.
* :class:`SandboxCheckRecord` — aggregated traces of *allowed* probes. Allowed
  calls are the common path, so they are bucketed and counted instead of logged
  one by one; otherwise "not denied" and "never checked" look the same after the
  fact. The two streams are written to different files so denial summaries
  cannot be skewed by allowed-check volume.

A ledger write failure never changes the security decision: the decision has
already been made and must not be softened by an unavailable audit sink.

Records are privacy-bounded before they reach any sink: ``target`` (a path or a
joined command) and ``reason`` are clipped to a fixed length and marked as
truncated, so a persisted ledger never stores a complete command line or a
complete host path. Durable JSONL sinks live in
:mod:`happyclaw.infra.plugins.sandbox.ledger`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, overload
from uuid import uuid4

__all__ = [
    "MAX_REASON_CHARS",
    "MAX_TARGET_CHARS",
    "TRUNCATION_MARKER",
    "InMemoryCheckLedger",
    "InMemorySandboxLedger",
    "SandboxAuditRecord",
    "SandboxCheckLedger",
    "SandboxCheckRecord",
    "SandboxLedger",
    "clip_text",
    "new_audit_record",
    "new_check_record",
]

MAX_TARGET_CHARS = 160
MAX_REASON_CHARS = 240
TRUNCATION_MARKER = "…[已截断]"


@overload
def clip_text(value: None, limit: int) -> tuple[None, bool]: ...


@overload
def clip_text(value: str, limit: int) -> tuple[str, bool]: ...


@overload
def clip_text(value: str | None, limit: int) -> tuple[str | None, bool]: ...


def clip_text(value: str | None, limit: int) -> tuple[str | None, bool]:
    """Collapse whitespace and clip one human-readable field.

    Returns ``(text, truncated)``. ``None`` stays ``None``. The marker makes a
    clipped value obvious to a human reader; the boolean makes it obvious to
    code and to the summary.
    """

    if value is None:
        return None, False
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text, False
    return f"{text[:limit]}{TRUNCATION_MARKER}", True


@dataclass(frozen=True, slots=True)
class SandboxAuditRecord:
    """One sandbox denial, traceable back to plugin, tool, and capability.

    ``stage`` says where the denial happened (``probe`` before approval,
    ``execute`` during the tool call). ``error_code`` is
    ``SANDBOX_EARLY_CHECK_MISS`` when execution refused something the probe had
    let through; ``root_error_code`` then keeps the underlying reason, so the
    effectiveness of moving checks earlier can be measured. ``truncated`` is
    true when ``target`` or ``reason`` was clipped for privacy.
    """

    record_id: str
    timestamp: str
    plugin_id: str
    tool_name: str
    operation: str
    capability: str | None
    target: str | None
    stage: str
    error_code: str
    root_error_code: str | None
    reason: str
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "timestamp": self.timestamp,
            "plugin_id": self.plugin_id,
            "tool_name": self.tool_name,
            "operation": self.operation,
            "capability": self.capability,
            "target": self.target,
            "stage": self.stage,
            "error_code": self.error_code,
            "root_error_code": self.root_error_code,
            "reason": self.reason,
            "truncated": self.truncated,
        }


def new_audit_record(
    *,
    plugin_id: str,
    tool_name: str,
    operation: str,
    capability: str | None,
    target: str | None,
    stage: str,
    error_code: str,
    root_error_code: str | None,
    reason: str,
) -> SandboxAuditRecord:
    clipped_target, target_cut = clip_text(target, MAX_TARGET_CHARS)
    clipped_reason, reason_cut = clip_text(reason, MAX_REASON_CHARS)
    return SandboxAuditRecord(
        record_id=uuid4().hex,
        timestamp=datetime.now(UTC).isoformat(),
        plugin_id=plugin_id,
        tool_name=tool_name,
        operation=operation,
        capability=capability,
        target=clipped_target,
        stage=stage,
        error_code=error_code,
        root_error_code=root_error_code,
        reason=clipped_reason,
        truncated=target_cut or reason_cut,
    )


class SandboxLedger(Protocol):
    def append(self, record: SandboxAuditRecord) -> None: ...


class InMemorySandboxLedger:
    """Process-local sink; swap for a durable ledger in production."""

    def __init__(self) -> None:
        self.records: list[SandboxAuditRecord] = []

    def append(self, record: SandboxAuditRecord) -> None:
        self.records.append(record)


@dataclass(frozen=True, slots=True)
class SandboxCheckRecord:
    """One aggregated trace of *allowed* checks for a plugin/tool.

    Denials are per-event; allowed checks are aggregated so a high-frequency
    tool does not flood the ledger. ``count`` is how many probes landed in this
    bucket during ``window_start`` .. ``window_end``. ``coverage`` and
    ``checked`` say whether the probe actually inspected anything, which is the
    difference between "not denied" and "never checked".
    """

    record_id: str
    window_start: str
    window_end: str
    plugin_id: str
    tool_name: str
    stage: str
    coverage: str
    checked: tuple[str, ...]
    count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "plugin_id": self.plugin_id,
            "tool_name": self.tool_name,
            "stage": self.stage,
            "coverage": self.coverage,
            "checked": list(self.checked),
            "count": self.count,
        }


class SandboxCheckLedger(Protocol):
    """Sink for aggregated allowed-check traces."""

    def append(self, record: SandboxCheckRecord) -> None: ...


class InMemoryCheckLedger:
    """Process-local sink for tests and dry runs."""

    def __init__(self) -> None:
        self.records: list[SandboxCheckRecord] = []

    def append(self, record: SandboxCheckRecord) -> None:
        self.records.append(record)


def new_check_record(
    *,
    plugin_id: str,
    tool_name: str,
    stage: str,
    coverage: str,
    checked: tuple[str, ...],
    count: int,
    window_start: str,
    window_end: str,
) -> SandboxCheckRecord:
    return SandboxCheckRecord(
        record_id=uuid4().hex,
        window_start=window_start,
        window_end=window_end,
        plugin_id=plugin_id,
        tool_name=tool_name,
        stage=stage,
        coverage=coverage,
        checked=tuple(checked),
        count=count,
    )
