"""Immutable event records for the DSH session log.

Every line in a generation file is one JSON object with a monotonically
increasing ``seq`` and a ``type``. ``data`` carries the event payload. The
serialized form is canonical (sorted keys, no insignificant whitespace) so a
log can be diffed and replayed byte for byte.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

__all__ = [
    "COMPACTION_EVENT_TYPES",
    "SCHEMA_VERSION",
    "EventType",
    "LogFormatError",
    "LogRecord",
]

SCHEMA_VERSION = 1


class EventType(StrEnum):
    """Event discriminators understood by the projector and compactor."""

    SESSION_START = "session/start"
    SESSION_END = "session/end"
    USER_MESSAGE = "user/message"
    ASSISTANT_MESSAGE = "assistant/message"
    TOOL_CALL = "tool/call"
    TOOL_RESULT = "tool/result"
    COMPACTION_L1 = "compaction/l1"
    COMPACTION_L2 = "compaction/l2"
    COMPACTION_L3 = "compaction/l3"


COMPACTION_EVENT_TYPES: dict[EventType, int] = {
    EventType.COMPACTION_L1: 1,
    EventType.COMPACTION_L2: 2,
    EventType.COMPACTION_L3: 3,
}


class LogFormatError(ValueError):
    """A record line is not a valid session-log record."""


@dataclass(frozen=True, slots=True)
class LogRecord:
    """One durable event.

    ``seq`` starts at zero and grows by exactly one per record. ``type`` stays a
    plain string so forward-compatible readers can ignore unknown event types
    instead of failing.
    """

    seq: int
    type: str
    data: dict[str, Any]
    ts: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.seq, int) or isinstance(self.seq, bool) or self.seq < 0:
            raise LogFormatError(f"seq must be a non-negative integer, got {self.seq!r}")
        if not isinstance(self.type, str) or not self.type.strip():
            raise LogFormatError("type must be a non-empty string")
        if not isinstance(self.data, dict):
            raise LogFormatError("data must be a JSON object")
        if self.ts is not None and not isinstance(self.ts, str):
            raise LogFormatError("ts must be a string when present")

    def to_dict(self) -> dict[str, Any]:
        """Return the canonical JSON-ready mapping, omitting an absent ``ts``."""
        payload: dict[str, Any] = {"seq": self.seq, "type": self.type, "data": self.data}
        if self.ts is not None:
            payload["ts"] = self.ts
        return payload

    def to_json(self) -> str:
        """Serialize to one canonical JSON line (without the trailing newline)."""
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

    @classmethod
    def from_json(cls, line: str) -> LogRecord:
        """Parse one JSON line or raise :class:`LogFormatError`."""
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LogFormatError(f"record is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise LogFormatError("record must be a JSON object")
        try:
            seq = payload["seq"]
            event_type = payload["type"]
            data = payload["data"]
        except KeyError as exc:
            raise LogFormatError(f"record is missing {exc.args[0]!r}") from exc
        return cls(
            seq=seq,
            type=event_type,
            data=data,
            ts=payload.get("ts"),
        )

    @classmethod
    def make(
        cls,
        seq: int,
        event_type: EventType | str,
        data: Mapping[str, Any] | None = None,
        *,
        ts: str | None = None,
    ) -> LogRecord:
        """Build a record from an event type and payload."""
        return cls(seq=seq, type=str(event_type), data=dict(data or {}), ts=ts)
