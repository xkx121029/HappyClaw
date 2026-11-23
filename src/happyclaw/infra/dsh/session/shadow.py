"""Default-off shadow writer for real chat turns.

When ``HAPPYCLAW_DSH_SHADOW`` is truthy, the chat processor appends a DSH event log
next to the normal history write. The switch is checked per turn; when it is
off no shadow file is opened and no shadow code path runs.

Shadow writes are strictly best-effort: :func:`write_shadow_turn` swallows any
exception and logs one warning. A full disk, an unwritable directory, or a log
format problem can never fail the user's chat turn.

``python -m happyclaw.infra.dsh.session.shadow --replay-thread <id>`` feeds an
existing thread back through the same converter. It is used only for offline
verification; the live path is the processor hook.
"""

from __future__ import annotations

from happyclaw.infra.utils.env_alias import env_get, env_has

import argparse
import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from happyclaw.infra.db.repos.thread_messages import ThreadMessageInput
from happyclaw.infra.dsh.session.events import EventType
from happyclaw.infra.dsh.session.log import SessionLog
from happyclaw.infra.utils.paths import PathLayout

__all__ = [
    "ENV_ENABLED",
    "ENV_SHADOW_DIR",
    "ParsedMessage",
    "append_shadow_turn",
    "default_db_path",
    "list_threads",
    "parse_message",
    "read_thread_messages",
    "shadow_enabled",
    "shadow_root",
    "thread_shadow_dir",
    "write_shadow_turn",
]

logger = logging.getLogger(__name__)

ENV_ENABLED = "HAPPYCLAW_DSH_SHADOW"
ENV_SHADOW_DIR = "HAPPYCLAW_DSH_SHADOW_DIR"
DEFAULT_DIRNAME = "dsh-shadow"
_TRUTHY = frozenset({"1", "true", "yes", "on"})
_SAFE_THREAD_RE = re.compile(r"[^A-Za-z0-9._-]")

_lock = threading.RLock()
_logs: dict[Path, SessionLog] = {}


@dataclass(frozen=True, slots=True)
class ParsedMessage:
    """Canonical view of one persisted LangChain message."""

    kind: str
    text: str
    attachments: tuple[Any, ...]
    tool_calls: tuple[dict[str, Any], ...]
    call_id: str
    name: str
    content: str
    is_error: bool


def shadow_enabled() -> bool:
    """Return whether the shadow switch is on. Defaults to off."""
    return env_get("DSH_SHADOW", "").strip().lower() in _TRUTHY


def shadow_root() -> Path:
    """Resolve the shadow log root from ``HAPPYCLAW_DSH_SHADOW_DIR`` or the home."""
    raw = env_get("DSH_SHADOW_DIR", "").strip()
    if raw:
        return Path(raw).expanduser()
    return PathLayout.from_env().root / DEFAULT_DIRNAME


def thread_shadow_dir(thread_id: str, root: Path | None = None) -> Path:
    """Return the per-thread shadow directory, sanitizing unsafe path chars."""
    safe = _SAFE_THREAD_RE.sub("_", thread_id).strip("._") or "unknown"
    if safe != thread_id:
        digest = hashlib.sha256(thread_id.encode("utf-8")).hexdigest()[:8]
        safe = f"{safe}-{digest}"
    return (root or shadow_root()) / safe


def append_shadow_turn(
    thread_id: str,
    inputs: Sequence[ThreadMessageInput],
    *,
    root: Path | None = None,
) -> int:
    """Append one turn to the shadow log and return the number of new events.

    Raises on I/O or format errors; the live path must call
    :func:`write_shadow_turn`, which turns those errors into one warning.
    """
    if not inputs:
        return 0
    log = _log_for(thread_id, root)
    records = log.load()
    existing: Counter[str] = Counter()
    for record in records:
        key = record.data.get("shadow_key")
        if isinstance(key, str) and key:
            existing[key] += 1
    if not records:
        log.append(
            EventType.SESSION_START,
            {"session_id": thread_id, "source": "shadow"},
        )
    written = 0
    seen: Counter[str] = Counter()
    for item in inputs:
        key = _message_key(item)
        seen[key] += 1
        if seen[key] <= existing.get(key, 0):
            continue
        event = _event_for(item)
        if event is None:
            continue
        event_type, data = event
        data.update(
            {
                "created_at": item.created_at,
                "message_id": item.message_id or "",
                "shadow_key": key,
                "source": "shadow",
            }
        )
        log.append(event_type, data)
        written += 1
    return written


def write_shadow_turn(thread_id: str, inputs: Sequence[ThreadMessageInput]) -> None:
    """Best-effort shadow append that never raises into the chat path."""
    try:
        append_shadow_turn(thread_id, inputs)
    except Exception:
        logger.warning(
            "DSH shadow log write failed for thread=%s (chat turn unaffected)",
            thread_id,
            exc_info=True,
        )


def parse_message(
    message_json: str,
    role: str,
    message_id: str | None = None,
) -> ParsedMessage | None:
    """Parse a persisted message into the same shape used by shadow events."""
    try:
        payload = json.loads(message_json)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    data = data if isinstance(data, dict) else {}
    raw_role = (role or payload.get("type") or "").lower()
    if raw_role in {"human", "user"}:
        text, attachments = _content_parts(data.get("content"))
        return ParsedMessage(
            kind="user",
            text=text,
            attachments=tuple(attachments),
            tool_calls=(),
            call_id="",
            name="",
            content="",
            is_error=False,
        )
    if raw_role in {"ai", "assistant"}:
        text, _attachments = _content_parts(data.get("content"))
        additional = data.get("additional_kwargs")
        additional = additional if isinstance(additional, dict) else {}
        raw_calls = data.get("tool_calls") or additional.get("tool_calls") or []
        return ParsedMessage(
            kind="assistant",
            text=text,
            attachments=(),
            tool_calls=tuple(_normalize_tool_calls(raw_calls)),
            call_id="",
            name="",
            content="",
            is_error=False,
        )
    if raw_role == "tool":
        content, _attachments = _content_parts(data.get("content"))
        additional = data.get("additional_kwargs")
        additional = additional if isinstance(additional, dict) else {}
        return ParsedMessage(
            kind="tool",
            text="",
            attachments=(),
            tool_calls=(),
            call_id=str(data.get("tool_call_id") or message_id or ""),
            name=str(data.get("name") or additional.get("name") or ""),
            content=content,
            is_error=bool(
                data.get("is_error")
                or additional.get("is_error")
                or data.get("status") == "error"
            ),
        )
    return None


def read_thread_messages(db_path: Path, thread_id: str) -> list[ThreadMessageInput]:
    """Read one thread's persisted messages using a read-only SQLite handle."""
    connection = _connect_read_only(db_path)
    try:
        if not _has_table(connection, "thread_messages"):
            raise RuntimeError(f"database has no thread_messages table: {db_path}")
        rows = connection.execute(
            "select message_id, role, message_json, created_at "
            "from thread_messages where thread_id=? order by seq",
            (thread_id,),
        ).fetchall()
    finally:
        connection.close()
    return [
        ThreadMessageInput(
            message_id=str(row["message_id"]) if row["message_id"] else None,
            role=str(row["role"]),
            message_json=str(row["message_json"]),
            created_at=int(row["created_at"]),
        )
        for row in rows
    ]


def list_threads(db_path: Path) -> list[tuple[str, int]]:
    """Return ``(thread_id, message_count)`` pairs, most populated first."""
    connection = _connect_read_only(db_path)
    try:
        if not _has_table(connection, "thread_messages"):
            raise RuntimeError(f"database has no thread_messages table: {db_path}")
        rows = connection.execute(
            "select thread_id, count(*) as messages from thread_messages "
            "group by thread_id order by messages desc, thread_id"
        ).fetchall()
    finally:
        connection.close()
    return [(str(row["thread_id"]), int(row["messages"])) for row in rows]


def default_db_path() -> Path:
    """Resolve the product database path without creating or migrating it."""
    return PathLayout.from_env().db


def _log_for(thread_id: str, root: Path | None) -> SessionLog:
    path = thread_shadow_dir(thread_id, root)
    with _lock:
        log = _logs.get(path)
        if log is None:
            log = SessionLog(path)
            _logs[path] = log
        return log


def _event_for(item: ThreadMessageInput) -> tuple[EventType, dict[str, Any]] | None:
    parsed = parse_message(item.message_json, item.role, item.message_id)
    if parsed is None:
        return None
    if parsed.kind == "user":
        return EventType.USER_MESSAGE, {
            "attachments": list(parsed.attachments),
            "text": parsed.text,
        }
    if parsed.kind == "assistant":
        return EventType.ASSISTANT_MESSAGE, {
            "text": parsed.text,
            "tool_calls": list(parsed.tool_calls),
        }
    return EventType.TOOL_RESULT, {
        "call_id": parsed.call_id,
        "content": parsed.content,
        "is_error": parsed.is_error,
        "name": parsed.name,
    }


def _message_key(item: ThreadMessageInput) -> str:
    if item.message_id:
        return f"id:{item.message_id}"
    digest = hashlib.sha256(
        f"{item.role}\x00{item.created_at}\x00{item.message_json}".encode("utf-8")
    ).hexdigest()[:24]
    return f"anon:{digest}"


def _content_parts(content: Any) -> tuple[str, list[Any]]:
    if isinstance(content, str):
        return content, []
    if isinstance(content, list):
        texts: list[str] = []
        attachments: list[Any] = []
        for block in content:
            if isinstance(block, str):
                texts.append(block)
            elif isinstance(block, dict):
                block_type = block.get("type")
                if block_type in {"text", "text_delta"}:
                    texts.append(str(block.get("text") or ""))
                elif block_type in {"image", "image_url", "input_image"}:
                    attachments.append(block)
                elif isinstance(block.get("text"), str):
                    texts.append(block["text"])
                else:
                    attachments.append(block)
            else:
                texts.append(str(block))
        return "\n".join(text for text in texts if text), attachments
    if isinstance(content, dict):
        if isinstance(content.get("text"), str):
            return content["text"], []
        return "", [content]
    return ("" if content is None else str(content)), []


def _normalize_tool_calls(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    normalized: list[dict[str, Any]] = []
    for call in raw:
        if not isinstance(call, dict):
            continue
        function = call.get("function")
        function = function if isinstance(function, dict) else {}
        arguments = call.get("args", call.get("arguments", function.get("arguments")))
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                pass
        normalized.append(
            {
                "arguments": arguments,
                "call_id": call.get("id") or call.get("call_id") or "",
                "name": call.get("name") or function.get("name") or "",
            }
        )
    return normalized


def _connect_read_only(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"database not found: {db_path}")
    connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _has_table(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "select 1 from sqlite_master where type='table' and name=?",
        (name,),
    ).fetchone()
    return row is not None


def main(argv: Sequence[str] | None = None) -> int:
    """Replay an existing thread into the shadow log (requires the switch)."""
    parser = argparse.ArgumentParser(description="Replay a thread into the DSH shadow log")
    parser.add_argument("--thread-id", default="")
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--shadow-dir", type=Path, default=None)
    parser.add_argument("--list-threads", action="store_true")
    args = parser.parse_args(argv)
    db_path = args.db or default_db_path()

    if args.list_threads:
        for thread_id, count in list_threads(db_path):
            print(f"{thread_id}\t{count}")
        return 0
    if not args.thread_id:
        parser.error("--thread-id is required unless --list-threads is used")
    if not shadow_enabled():
        print(f"{ENV_ENABLED} is off; set it to 1 to enable shadow writing")
        return 2

    inputs = read_thread_messages(db_path, args.thread_id)
    written = append_shadow_turn(args.thread_id, inputs, root=args.shadow_dir)
    target = thread_shadow_dir(args.thread_id, args.shadow_dir)
    print(f"replayed thread={args.thread_id} messages={len(inputs)} new_events={written}")
    print(f"shadow_dir={target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
