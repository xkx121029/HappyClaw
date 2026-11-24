"""Read-only comparison between a shadow log and the product history table.

Usage::

    python -m happyclaw.infra.dsh.session.verify \\
        --thread-id thr_xxx \\
        --db E:\\HAPPYclaw\\octop-qa-home\\octop.db \\
        --shadow-dir E:\\HAPPYclaw\\2026-11-12\\dsh-integration\\shadow-data

The command projects the shadow log with :func:`project`, reads the same
thread from ``thread_messages`` through a read-only SQLite URI, and aligns the
two sequences. It writes nothing: no schema change, no log rewrite, no rows.

Exit codes: ``0`` consistent, ``1`` differences found, ``2`` unreadable input.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from happyclaw.infra.dsh.session.log import LogCorruptionError, SessionLog
from happyclaw.infra.dsh.session.shadow import (
    default_db_path,
    parse_message,
    read_thread_messages,
    shadow_root,
    thread_shadow_dir,
)
from happyclaw.infra.dsh.session.surface import project

__all__ = ["ComparisonResult", "Entry", "compare", "main"]

_CLIP_CHARS = 240


@dataclass(frozen=True, slots=True)
class Entry:
    """One comparable conversation item, reduced to the fields both sides own."""

    kind: str
    fields: dict[str, Any]

    @property
    def key(self) -> tuple[str, str]:
        return self.kind, _canonical(self.fields)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "fields": self.fields}


@dataclass(slots=True)
class ComparisonResult:
    thread_id: str
    existing_count: int = 0
    shadow_count: int = 0
    existing_by_kind: Counter[str] | None = None
    shadow_by_kind: Counter[str] | None = None
    differences: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def consistent(self) -> bool:
        return not self.differences

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "consistent": self.consistent,
            "existing_count": self.existing_count,
            "shadow_count": self.shadow_count,
            "existing_by_kind": dict(sorted((self.existing_by_kind or {}).items())),
            "shadow_by_kind": dict(sorted((self.shadow_by_kind or {}).items())),
            "differences": list(self.differences or []),
            "notes": list(self.notes or []),
        }


def compare(
    thread_id: str,
    *,
    db_path: Path,
    shadow_dir: Path,
) -> ComparisonResult:
    """Compare the shadow projection against ``thread_messages`` for one thread."""
    existing = _existing_entries(db_path, thread_id)
    shadow, shadow_records = _shadow_entries(thread_id, shadow_dir)
    result = ComparisonResult(
        thread_id=thread_id,
        existing_count=len(existing),
        shadow_count=len(shadow),
        existing_by_kind=Counter(entry.kind for entry in existing),
        shadow_by_kind=Counter(entry.kind for entry in shadow),
        differences=[],
        notes=[],
    )
    if shadow_records == 0:
        result.notes.append(
            f"no shadow log records under {thread_shadow_dir(thread_id, shadow_dir)}"
        )
        result.differences.append({"kind": "missing_shadow_log"})
        return result
    result.differences = _align(existing, shadow)
    return result


def _existing_entries(db_path: Path, thread_id: str) -> list[Entry]:
    entries: list[Entry] = []
    for message in read_thread_messages(db_path, thread_id):
        parsed = parse_message(message.message_json, message.role, message.message_id)
        if parsed is None:
            continue
        if parsed.kind == "user":
            entries.append(
                Entry("user", {"text": parsed.text, "attachments": list(parsed.attachments)})
            )
        elif parsed.kind == "assistant":
            entries.append(
                Entry(
                    "assistant",
                    {"text": parsed.text, "tool_calls": list(parsed.tool_calls)},
                )
            )
        else:
            entries.append(
                Entry(
                    "tool",
                    {
                        "call_id": parsed.call_id,
                        "content": parsed.content,
                        "is_error": parsed.is_error,
                        "name": parsed.name,
                    },
                )
            )
    return entries


def _shadow_entries(thread_id: str, shadow_dir: Path) -> tuple[list[Entry], int]:
    log = SessionLog(thread_shadow_dir(thread_id, shadow_dir))
    records = log.load()
    entries: list[Entry] = []
    for node in project(records):
        payload = node.payload
        if node.kind == "user_message":
            entries.append(
                Entry(
                    "user",
                    {
                        "text": payload.get("text") or "",
                        "attachments": list(payload.get("attachments") or []),
                    },
                )
            )
        elif node.kind == "assistant_message":
            entries.append(
                Entry(
                    "assistant",
                    {
                        "text": payload.get("text") or "",
                        "tool_calls": list(payload.get("tool_calls") or []),
                    },
                )
            )
        elif node.kind == "tool_result":
            entries.append(
                Entry(
                    "tool",
                    {
                        "call_id": payload.get("call_id") or "",
                        "content": payload.get("content"),
                        "is_error": bool(payload.get("is_error", False)),
                        "name": payload.get("name") or "",
                    },
                )
            )
        elif node.kind == "tool_call":
            entries.append(
                Entry(
                    "tool_call",
                    {
                        "arguments": payload.get("arguments"),
                        "call_id": payload.get("call_id") or "",
                        "name": payload.get("name") or "",
                    },
                )
            )
        else:
            entries.append(
                Entry(
                    "summary",
                    {
                        "summarized_seqs": list(payload.get("summarized_seqs") or []),
                        "text": payload.get("text") or "",
                    },
                )
            )
    return entries, len(records)


def _align(existing: Sequence[Entry], shadow: Sequence[Entry]) -> list[dict[str, Any]]:
    """Match entries by exact key, then field-diff the replaced positions."""
    matcher = SequenceMatcher(
        a=[entry.key for entry in existing],
        b=[entry.key for entry in shadow],
        autojunk=False,
    )
    differences: list[dict[str, Any]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "delete":
            for index in range(i1, i2):
                differences.append(
                    {
                        "kind": "missing_in_shadow",
                        "existing_index": index,
                        "entry": existing[index].to_dict(),
                    }
                )
            continue
        if tag == "insert":
            for index in range(j1, j2):
                differences.append(
                    {
                        "kind": "extra_in_shadow",
                        "shadow_index": index,
                        "entry": shadow[index].to_dict(),
                    }
                )
            continue
        paired = min(i2 - i1, j2 - j1)
        for offset in range(paired):
            existing_index = i1 + offset
            shadow_index = j1 + offset
            left = existing[existing_index]
            right = shadow[shadow_index]
            differences.append(
                {
                    "kind": "field_mismatch",
                    "existing_index": existing_index,
                    "shadow_index": shadow_index,
                    "fields": _field_diff(left.fields, right.fields),
                    "entry": {"existing": left.to_dict(), "shadow": right.to_dict()},
                }
            )
        for index in range(i1 + paired, i2):
            differences.append(
                {
                    "kind": "missing_in_shadow",
                    "existing_index": index,
                    "entry": existing[index].to_dict(),
                }
            )
        for index in range(j1 + paired, j2):
            differences.append(
                {
                    "kind": "extra_in_shadow",
                    "shadow_index": index,
                    "entry": shadow[index].to_dict(),
                }
            )
    return differences


def _field_diff(
    existing: dict[str, Any],
    shadow: dict[str, Any],
) -> dict[str, Any]:
    names = sorted(set(existing) | set(shadow))
    return {
        name: {
            "existing": _display(existing.get(name)),
            "shadow": _display(shadow.get(name)),
        }
        for name in names
        if existing.get(name) != shadow.get(name)
    }


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _display(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = value if isinstance(value, str) else _canonical(value)
    if len(text) <= _CLIP_CHARS:
        return text
    return f"{text[:_CLIP_CHARS]}…（共 {len(text)} 字符）"


def _render(result: ComparisonResult) -> str:
    lines = [f"thread:   {result.thread_id}"]
    lines.append(f"existing: {result.existing_count} 条 ({_kind_summary(result.existing_by_kind)})")
    lines.append(f"shadow:   {result.shadow_count} 条 ({_kind_summary(result.shadow_by_kind)})")
    if result.consistent:
        lines.append("result:   CONSISTENT — 投影与现有历史逐条一致")
    else:
        lines.append(f"result:   {len(result.differences or [])} 处差异")
    for index, difference in enumerate(result.differences or [], start=1):
        lines.append(f"[{index}] {difference.get('kind')}")
        if difference.get("kind") == "field_mismatch":
            lines.append(
                f"    existing#{difference.get('existing_index')} "
                f"<-> shadow#{difference.get('shadow_index')}"
            )
            for name, values in (difference.get("fields") or {}).items():
                lines.append(f"    {name}:")
                lines.append(f"      existing: {values.get('existing')!r}")
                lines.append(f"      shadow:   {values.get('shadow')!r}")
        elif difference.get("kind") == "missing_in_shadow":
            lines.append(f"    existing#{difference.get('existing_index')}")
            lines.append(f"    {difference.get('entry')}")
        elif difference.get("kind") == "extra_in_shadow":
            lines.append(f"    shadow#{difference.get('shadow_index')}")
            lines.append(f"    {difference.get('entry')}")
    for note in result.notes or []:
        lines.append(f"note:     {note}")
    return "\n".join(lines)


def _kind_summary(counts: Counter[str] | None) -> str:
    if not counts:
        return "empty"
    return ", ".join(f"{kind}={count}" for kind, count in sorted(counts.items()))


def main(argv: Sequence[str] | None = None) -> int:
    """Run the read-only check and print a text or JSON report."""
    parser = argparse.ArgumentParser(
        description="Compare a DSH shadow log with the product thread_messages table"
    )
    parser.add_argument("--thread-id", required=True)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--shadow-dir", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    db_path = args.db or default_db_path()
    shadow_dir = args.shadow_dir or shadow_root()
    try:
        result = compare(args.thread_id, db_path=db_path, shadow_dir=shadow_dir)
    except (OSError, sqlite3.Error, LogCorruptionError) as exc:
        print(f"cannot verify thread {args.thread_id}: {exc}")
        return 2
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, default=str))
    else:
        print(_render(result))
    return 0 if result.consistent else 1


if __name__ == "__main__":
    raise SystemExit(main())
