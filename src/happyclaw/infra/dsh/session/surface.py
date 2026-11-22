"""Deterministic projection from the event log to the visible conversation.

The projection is a pure fold over committed records. It has no clock, no
randomness, and no dependency on disk state, so replaying the same log twice
produces the same nodes and :func:`surface_json` produces byte-identical text.

Surface node kinds: ``user_message``, ``assistant_message``, ``tool_call``,
``tool_result`` and ``summary``. Compaction events rewrite earlier nodes in
place (L1/L2) or replace an early span with one summary node (L3); the original
events stay in the log for audit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable

from happyclaw.infra.dsh.session.budget import UnitWeights
from happyclaw.infra.dsh.session.events import EventType, LogRecord

__all__ = [
    "IMAGE_BLOCK_UNITS",
    "OFFLOAD_REF_UNITS",
    "SurfaceNode",
    "content_text",
    "content_units",
    "project",
    "surface_json",
    "surface_units",
]

# An image costs a fixed visual budget instead of the size of its base64 body.
IMAGE_BLOCK_UNITS = 50.0
# A reference block is cheap: only its marker is visible to the model.
OFFLOAD_REF_UNITS = 2.0


@dataclass(frozen=True, slots=True)
class SurfaceNode:
    """One visible conversation item."""

    seq: int
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready mapping with stable identity fields."""
        return {**self.payload, "kind": self.kind, "seq": self.seq}


def project(records: Iterable[LogRecord]) -> tuple[SurfaceNode, ...]:
    """Fold ``records`` into the current visible conversation."""
    nodes: list[SurfaceNode] = []
    index_by_seq: dict[int, int] = {}
    for record in records:
        node = _surface_node(record)
        if node is not None:
            nodes.append(node)
            index_by_seq[record.seq] = len(nodes) - 1
            continue
        if record.type == EventType.COMPACTION_L1.value:
            _apply_l1(nodes, index_by_seq, record)
        elif record.type == EventType.COMPACTION_L2.value:
            _apply_l2(nodes, index_by_seq, record)
        elif record.type == EventType.COMPACTION_L3.value:
            nodes, index_by_seq = _apply_l3(nodes, record)
    return tuple(nodes)


def surface_json(nodes: Iterable[SurfaceNode]) -> str:
    """Serialize the surface canonically for byte-for-byte replay checks."""
    return json.dumps(
        [node.to_dict() for node in nodes],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def surface_units(nodes: Iterable[SurfaceNode], weights: UnitWeights = UnitWeights()) -> float:
    """Return the weighted size of everything still visible."""
    total = 0.0
    for node in nodes:
        payload = node.payload
        text = payload.get("text")
        if isinstance(text, str):
            total += weights.measure(text)
        if "content" in payload:
            total += content_units(payload["content"], weights)
        if "attachments" in payload:
            total += content_units(payload["attachments"], weights)
        if "tool_calls" in payload:
            total += content_units(payload["tool_calls"], weights)
        if node.kind == "tool_call":
            total += weights.measure(str(payload.get("name") or ""))
            total += content_units(payload.get("arguments"), weights)
    return round(total, 3)


def content_units(content: Any, weights: UnitWeights = UnitWeights()) -> float:
    """Measure text blocks with weighted units and images with a fixed price."""
    if content is None:
        return 0.0
    if isinstance(content, str):
        return weights.measure(content)
    if isinstance(content, list):
        total = 0.0
        for block in content:
            if isinstance(block, str):
                total += weights.measure(block)
                continue
            if not isinstance(block, dict):
                total += weights.measure(str(block))
                continue
            block_type = block.get("type")
            if block_type == "image":
                total += IMAGE_BLOCK_UNITS
            elif block_type == "text":
                total += weights.measure(str(block.get("text") or ""))
            elif block_type == "offload_ref":
                total += OFFLOAD_REF_UNITS
            else:
                total += weights.measure(_dump(block))
        return round(total, 3)
    if isinstance(content, dict):
        block_type = content.get("type")
        if block_type == "image":
            return IMAGE_BLOCK_UNITS
        if block_type == "text":
            return weights.measure(str(content.get("text") or ""))
        return weights.measure(_dump(content))
    return weights.measure(str(content))


def content_text(content: Any) -> str:
    """Render content as plain text for summaries and previews."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                block_type = block.get("type")
                if block_type == "text":
                    parts.append(str(block.get("text") or ""))
                elif block_type == "image":
                    parts.append("[图片]")
                elif block_type == "offload_ref":
                    parts.append(f"[已卸载引用 {block.get('ref') or ''}]")
                else:
                    parts.append(_dump(block))
            else:
                parts.append(str(block))
        return "\n".join(part for part in parts if part)
    if isinstance(content, dict):
        block_type = content.get("type")
        if block_type == "text":
            return str(content.get("text") or "")
        if block_type == "image":
            return "[图片]"
        return _dump(content)
    return str(content)


def _surface_node(record: LogRecord) -> SurfaceNode | None:
    if record.type == EventType.USER_MESSAGE.value:
        return SurfaceNode(
            seq=record.seq,
            kind="user_message",
            payload={
                "attachments": _as_list(record.data.get("attachments")),
                "created_at": record.data.get("created_at"),
                "message_id": _as_text(record.data.get("message_id")),
                "text": _as_text(record.data.get("text")),
            },
        )
    if record.type == EventType.ASSISTANT_MESSAGE.value:
        return SurfaceNode(
            seq=record.seq,
            kind="assistant_message",
            payload={
                "created_at": record.data.get("created_at"),
                "message_id": _as_text(record.data.get("message_id")),
                "text": _as_text(record.data.get("text")),
                "tool_calls": _as_list(record.data.get("tool_calls")),
            },
        )
    if record.type == EventType.TOOL_CALL.value:
        return SurfaceNode(
            seq=record.seq,
            kind="tool_call",
            payload={
                "arguments": record.data.get("arguments"),
                "call_id": _as_text(record.data.get("call_id")),
                "name": _as_text(record.data.get("name")),
            },
        )
    if record.type == EventType.TOOL_RESULT.value:
        return SurfaceNode(
            seq=record.seq,
            kind="tool_result",
            payload={
                "call_id": _as_text(record.data.get("call_id")),
                "content": record.data.get("content"),
                "created_at": record.data.get("created_at"),
                "is_error": bool(record.data.get("is_error", False)),
                "message_id": _as_text(record.data.get("message_id")),
                "name": _as_text(record.data.get("name")),
            },
        )
    return None


def _apply_l1(
    nodes: list[SurfaceNode],
    index_by_seq: dict[int, int],
    record: LogRecord,
) -> None:
    targets = record.data.get("targets")
    if not isinstance(targets, dict):
        return
    for key in sorted(targets, key=_seq_sort_key):
        index = index_by_seq.get(_as_int(key, -1))
        if index is None:
            continue
        patch = targets[key]
        if not isinstance(patch, dict):
            continue
        node = nodes[index]
        payload = dict(node.payload)
        payload["content"] = patch.get("summary", "")
        payload["kept_fields"] = patch.get("kept_fields") or {}
        payload["prune_event_seq"] = record.seq
        payload["prune_level"] = "l1"
        payload["pruned"] = True
        nodes[index] = SurfaceNode(seq=node.seq, kind=node.kind, payload=payload)


def _apply_l2(
    nodes: list[SurfaceNode],
    index_by_seq: dict[int, int],
    record: LogRecord,
) -> None:
    targets = record.data.get("targets")
    if not isinstance(targets, list):
        return
    for target in targets:
        if not isinstance(target, dict):
            continue
        index = index_by_seq.get(_as_int(target.get("seq"), -1))
        if index is None:
            continue
        node = nodes[index]
        payload = dict(node.payload)
        path = str(target.get("path") or "")
        placeholder = {
            "bytes": int(target.get("bytes") or 0),
            "preview": str(target.get("preview") or ""),
            "ref": str(target.get("ref") or ""),
            "ref_kind": str(target.get("ref_kind") or "text_ref"),
            "type": "offload_ref",
        }
        if path == "text":
            payload["offloaded"] = True
            payload["offload_event_seq"] = record.seq
            payload["offload_ref"] = placeholder["ref"]
            payload["text"] = (
                f"[已卸载 {placeholder['ref_kind']} {placeholder['ref']} "
                f"bytes={placeholder['bytes']} 预览: {placeholder['preview']}]"
            )
        elif path == "content":
            payload["content"] = placeholder
            payload["offloaded"] = True
            payload["offload_event_seq"] = record.seq
        elif path.startswith("content[") and path.endswith("]"):
            blocks = _as_list(payload.get("content"))
            position = _as_int(path[len("content[") : -1], -1)
            if 0 <= position < len(blocks):
                blocks[position] = placeholder
                payload["content"] = blocks
                payload["offloaded"] = True
                payload["offload_event_seq"] = record.seq
        elif path.startswith("attachments[") and path.endswith("]"):
            attachments = _as_list(payload.get("attachments"))
            position = _as_int(path[len("attachments[") : -1], -1)
            if 0 <= position < len(attachments):
                attachments[position] = placeholder
                payload["attachments"] = attachments
                payload["offloaded"] = True
                payload["offload_event_seq"] = record.seq
        nodes[index] = SurfaceNode(seq=node.seq, kind=node.kind, payload=payload)


def _apply_l3(
    nodes: list[SurfaceNode],
    record: LogRecord,
) -> tuple[list[SurfaceNode], dict[int, int]]:
    data = record.data
    summarized = {_as_int(seq, -1) for seq in _as_list(data.get("summarized_seqs"))}
    summary_node = SurfaceNode(
        seq=record.seq,
        kind="summary",
        payload={
            "compaction_seq": record.seq,
            "summary": data.get("summary") or {},
            "summarized_seqs": sorted(seq for seq in summarized if seq >= 0),
            "text": _as_text(data.get("rendered")),
        },
    )
    positions = [index for index, node in enumerate(nodes) if node.seq in summarized]
    if not positions:
        nodes = [*nodes, summary_node]
    else:
        insert_at = positions[0]
        remaining = [node for node in nodes if node.seq not in summarized]
        remaining.insert(insert_at, summary_node)
        nodes = remaining
    return nodes, {node.seq: index for index, node in enumerate(nodes)}


def _as_text(value: Any) -> str:
    return value if isinstance(value, str) else ("" if value is None else str(value))


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _seq_sort_key(value: Any) -> int:
    return _as_int(value, -1)


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
