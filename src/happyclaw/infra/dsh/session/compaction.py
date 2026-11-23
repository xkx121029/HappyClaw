"""Three-stage compaction over the projected surface.

Order is fixed: **L1** prunes oversized tool results, **L2** offloads images and
large text into content-addressed blobs, **L3** replaces an early span with a
structured summary. A stage only runs when the surface is still above budget
after the previous stage, so the three stages can never fire out of order.

Every applied stage appends one event carrying the turn number, the source
event seqs, and the exact replacement (pruned summary, blob refs, or structured
summary). Replaying the log therefore answers "which turn compacted what".
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from happyclaw.infra.dsh.session.budget import UnitWeights, WeightedBudget, trim_head, trim_tail
from happyclaw.infra.dsh.session.events import EventType
from happyclaw.infra.dsh.session.log import SessionLog
from happyclaw.infra.dsh.session.surface import (
    SurfaceNode,
    content_text,
    content_units,
    project,
    surface_units,
)

__all__ = [
    "L1_MARKER",
    "BlobStore",
    "CompactionConfig",
    "CompactionEngine",
    "CompactionReport",
    "CompactionStep",
]

L1_MARKER = "\n\n[... L1 已裁剪：仅保留摘要与关键字段 ...]\n\n"

# Scalar fields worth keeping when a tool result is a JSON object.
L1_KEY_FIELDS = frozenset(
    {
        "count",
        "error",
        "exit_code",
        "id",
        "message",
        "name",
        "ok",
        "path",
        "status",
        "success",
        "title",
        "total",
        "url",
    }
)

DECISION_KEYWORDS = (
    "decided",
    "decision",
    "decide",
    "choose",
    "chose",
    "will use",
    "决定",
    "决策",
    "采用",
    "选择",
    "确定使用",
)
PENDING_KEYWORDS = (
    "todo",
    "pending",
    "next step",
    "remaining",
    "not yet",
    "待办",
    "未完成",
    "尚未",
    "还需要",
    "下一步",
)
_ROLE_BY_KIND = {
    "assistant_message": "assistant",
    "summary": "summary",
    "tool_call": "tool_call",
    "tool_result": "tool_result",
    "user_message": "user",
}
_REF_RE = re.compile(r"^blob://(?P<digest>[0-9a-f]{64})$")


@dataclass(frozen=True, slots=True)
class CompactionConfig:
    """Budgets and thresholds, all measured in weighted units."""

    max_context_units: float = 600.0
    l1_tool_result_units: float = 120.0
    l1_head_units: float = 40.0
    l1_tail_units: float = 10.0
    l2_block_units: float = 150.0
    l2_preview_units: float = 20.0
    l3_target_units: float = 200.0
    l3_retain_recent_nodes: int = 4
    l3_point_units: float = 30.0
    l3_item_units: float = 20.0
    weights: UnitWeights = UnitWeights()


@dataclass(frozen=True, slots=True)
class CompactionStep:
    """One applied compaction stage."""

    level: int
    event_seq: int
    source_seqs: tuple[int, ...]
    before_units: float
    after_units: float


@dataclass(frozen=True, slots=True)
class CompactionReport:
    """Outcome of one ``run_turn`` call."""

    turn: int
    initial_units: float
    final_units: float
    steps: tuple[CompactionStep, ...]
    within_budget: bool


class BlobStore:
    """Content-addressed storage for content removed by L2.

    zstd is not part of the Python standard library and the project does not
    add dependencies, so blobs use ``zlib``. The log itself stays plain JSONL:
    compressing an append-only, crash-tolerant journal would make torn-tail
    detection unreliable.
    """

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        """Directory holding ``<sha256>.zlib`` blobs."""
        return self._root

    def put(self, data: bytes) -> str:
        """Store ``data`` and return its ``blob://`` reference."""
        digest = hashlib.sha256(data).hexdigest()
        path = self._root / f"{digest}.zlib"
        if not path.exists():
            self._root.mkdir(parents=True, exist_ok=True)
            compressed = zlib.compress(data, level=6)
            try:
                with path.open("xb") as handle:
                    handle.write(compressed)
                    handle.flush()
                    os.fsync(handle.fileno())
            except FileExistsError:
                pass
        return f"blob://{digest}"

    def read(self, ref: str) -> bytes:
        """Read a blob by reference."""
        match = _REF_RE.match(ref)
        if match is None:
            raise ValueError(f"unsupported blob reference: {ref!r}")
        path = self._root / f"{match.group('digest')}.zlib"
        return zlib.decompress(path.read_bytes())


class CompactionEngine:
    """Applies L1 -> L2 -> L3 to a session log when the surface is over budget."""

    def __init__(
        self,
        log: SessionLog,
        *,
        config: CompactionConfig | None = None,
        blobs: BlobStore | None = None,
    ) -> None:
        self._log = log
        self._config = config or CompactionConfig()
        self._blobs = blobs or BlobStore(log.root / "blobs")

    @property
    def config(self) -> CompactionConfig:
        """Current budget configuration."""
        return self._config

    def run_turn(self, turn: int) -> CompactionReport:
        """Compact until under budget or all three levels have run."""
        if turn < 0:
            raise ValueError("turn must be non-negative")
        nodes = project(self._log.load())
        initial = surface_units(nodes, self._config.weights)
        current = initial
        steps: list[CompactionStep] = []
        if current > self._config.max_context_units:
            plan = self._plan_l1(nodes, turn, current)
            if plan is not None:
                nodes, current, step = self._commit(plan, 1, current)
                steps.append(step)
        if current > self._config.max_context_units:
            plan = self._plan_l2(nodes, turn, current)
            if plan is not None:
                nodes, current, step = self._commit(plan, 2, current)
                steps.append(step)
        if current > self._config.max_context_units:
            plan = self._plan_l3(nodes, turn, current)
            if plan is not None:
                nodes, current, step = self._commit(plan, 3, current)
                steps.append(step)
        return CompactionReport(
            turn=turn,
            initial_units=initial,
            final_units=current,
            steps=tuple(steps),
            within_budget=current <= self._config.max_context_units,
        )

    def _commit(
        self,
        plan: tuple[EventType, dict[str, Any]],
        level: int,
        before_units: float,
    ) -> tuple[tuple[SurfaceNode, ...], float, CompactionStep]:
        event_type, data = plan
        record = self._log.append(event_type, data)
        nodes = project(self._log.load())
        after = surface_units(nodes, self._config.weights)
        step = CompactionStep(
            level=level,
            event_seq=record.seq,
            source_seqs=tuple(int(seq) for seq in data.get("source_seqs", [])),
            before_units=before_units,
            after_units=after,
        )
        return nodes, after, step

    def _plan_l1(
        self,
        nodes: tuple[SurfaceNode, ...],
        turn: int,
        before_units: float,
    ) -> tuple[EventType, dict[str, Any]] | None:
        config = self._config
        targets: dict[str, dict[str, Any]] = {}
        source_seqs: list[int] = []
        for node in nodes:
            if node.kind != "tool_result" or node.payload.get("pruned"):
                continue
            content = node.payload.get("content")
            original_units = content_units(content, config.weights)
            if original_units <= config.l1_tool_result_units:
                continue
            summary, kept_fields = self._prune_content(content)
            targets[str(node.seq)] = {
                "kept_fields": kept_fields,
                "original_units": original_units,
                "summary": summary,
            }
            source_seqs.append(node.seq)
        if not targets:
            return None
        return (
            EventType.COMPACTION_L1,
            {
                "before_units": before_units,
                "budget_units": config.max_context_units,
                "level": 1,
                "marker": L1_MARKER,
                "source_seqs": sorted(source_seqs),
                "targets": targets,
                "turn": turn,
            },
        )

    def _prune_content(self, content: Any) -> tuple[Any, dict[str, Any]]:
        config = self._config
        if isinstance(content, str):
            return self._head_tail(content), {}
        if isinstance(content, list):
            blocks: list[Any] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = str(block.get("text") or "")
                    blocks.append({"text": self._head_tail(text), "type": "text"})
                else:
                    blocks.append(block)
            return blocks, {}
        if isinstance(content, dict):
            kept: dict[str, Any] = {}
            for key in sorted(content):
                value = content[key]
                if key not in L1_KEY_FIELDS or not _is_scalar(value):
                    continue
                kept[key] = (
                    trim_head(value, config.l3_item_units, weights=config.weights)
                    if isinstance(value, str)
                    else value
                )
            rendered = json.dumps(kept, ensure_ascii=False, sort_keys=True)
            preview = trim_head(rendered, config.l1_head_units, weights=config.weights)
            fields = ", ".join(kept) if kept else "无"
            return f"{preview}{L1_MARKER}已保留字段: {fields}", kept
        if content is None:
            return "", {}
        return self._head_tail(str(content)), {}

    def _head_tail(self, text: str) -> str:
        config = self._config
        head = trim_head(text, config.l1_head_units, weights=config.weights)
        tail = trim_tail(text, config.l1_tail_units, weights=config.weights)
        return f"{head}{L1_MARKER}{tail}".strip()

    def _plan_l2(
        self,
        nodes: tuple[SurfaceNode, ...],
        turn: int,
        before_units: float,
    ) -> tuple[EventType, dict[str, Any]] | None:
        config = self._config
        targets: list[dict[str, Any]] = []
        source_seqs: set[int] = set()
        for node in nodes:
            if node.kind == "summary" or node.payload.get("offloaded"):
                continue
            targets.extend(self._plan_l2_text(node))
            targets.extend(self._plan_l2_content(node))
            targets.extend(self._plan_l2_attachments(node))
        for target in targets:
            source_seqs.add(int(target["seq"]))
        if not targets:
            return None
        return (
            EventType.COMPACTION_L2,
            {
                "before_units": before_units,
                "budget_units": config.max_context_units,
                "level": 2,
                "source_seqs": sorted(source_seqs),
                "targets": targets,
                "turn": turn,
            },
        )

    def _plan_l2_text(self, node: SurfaceNode) -> list[dict[str, Any]]:
        config = self._config
        text = node.payload.get("text")
        if not isinstance(text, str) or config.weights.measure(text) <= config.l2_block_units:
            return []
        return [self._offload_target(node, "text", "text_ref", text.encode("utf-8"), text, "text/plain")]

    def _plan_l2_content(self, node: SurfaceNode) -> list[dict[str, Any]]:
        config = self._config
        content = node.payload.get("content")
        if isinstance(content, str):
            if config.weights.measure(content) <= config.l2_block_units:
                return []
            return [
                self._offload_target(
                    node, "content", "text_ref", content.encode("utf-8"), content, "text/plain"
                )
            ]
        if isinstance(content, dict):
            units = content_units(content, config.weights)
            if units <= config.l2_block_units:
                return []
            body = json.dumps(content, ensure_ascii=False, sort_keys=True, default=str)
            return [
                self._offload_target(
                    node, "content", "text_ref", body.encode("utf-8"), content_text(content), "application/json"
                )
            ]
        if not isinstance(content, list):
            return []
        targets: list[dict[str, Any]] = []
        for position, block in enumerate(content):
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "image":
                body = json.dumps(block, ensure_ascii=False, sort_keys=True, default=str)
                targets.append(
                    self._offload_target(
                        node,
                        f"content[{position}]",
                        "image_ref",
                        body.encode("utf-8"),
                        "[图片已卸载]",
                        _media_type(block),
                    )
                )
            elif block_type == "text":
                text = str(block.get("text") or "")
                if config.weights.measure(text) > config.l2_block_units:
                    targets.append(
                        self._offload_target(
                            node,
                            f"content[{position}]",
                            "text_ref",
                            text.encode("utf-8"),
                            text,
                            "text/plain",
                        )
                    )
        return targets

    def _plan_l2_attachments(self, node: SurfaceNode) -> list[dict[str, Any]]:
        config = self._config
        attachments = node.payload.get("attachments")
        if not isinstance(attachments, list):
            return []
        targets: list[dict[str, Any]] = []
        for position, block in enumerate(attachments):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "image":
                body = json.dumps(block, ensure_ascii=False, sort_keys=True, default=str)
                targets.append(
                    self._offload_target(
                        node,
                        f"attachments[{position}]",
                        "image_ref",
                        body.encode("utf-8"),
                        "[图片已卸载]",
                        _media_type(block),
                    )
                )
            elif block.get("type") == "text":
                text = str(block.get("text") or "")
                if config.weights.measure(text) > config.l2_block_units:
                    targets.append(
                        self._offload_target(
                            node,
                            f"attachments[{position}]",
                            "text_ref",
                            text.encode("utf-8"),
                            text,
                            "text/plain",
                        )
                    )
        return targets

    def _offload_target(
        self,
        node: SurfaceNode,
        path: str,
        ref_kind: str,
        body: bytes,
        preview_source: str,
        media_type: str,
    ) -> dict[str, Any]:
        config = self._config
        return {
            "bytes": len(body),
            "media_type": media_type,
            "path": path,
            "preview": trim_head(preview_source, config.l2_preview_units, weights=config.weights),
            "ref": self._blobs.put(body),
            "ref_kind": ref_kind,
            "seq": node.seq,
        }

    def _plan_l3(
        self,
        nodes: tuple[SurfaceNode, ...],
        turn: int,
        before_units: float,
    ) -> tuple[EventType, dict[str, Any]] | None:
        config = self._config
        retain = max(0, config.l3_retain_recent_nodes)
        if len(nodes) <= retain:
            return None
        early = nodes[: len(nodes) - retain] if retain else nodes
        if not early:
            return None
        summary = self._build_summary(early)
        rendered = _render_summary(summary)
        rendered = self._fit_summary_budget(rendered, summary)
        retained = nodes[len(nodes) - retain :] if retain else ()
        return (
            EventType.COMPACTION_L3,
            {
                "before_units": before_units,
                "budget_units": config.max_context_units,
                "level": 3,
                "rendered": rendered,
                "retained_seqs": [node.seq for node in retained],
                "source_seqs": sorted(node.seq for node in early),
                "summarized_seqs": sorted(node.seq for node in early),
                "summary": summary,
                "summary_units": config.weights.measure(rendered),
                "turn": turn,
            },
        )

    def _build_summary(self, nodes: tuple[SurfaceNode, ...]) -> dict[str, list[str]]:
        config = self._config
        decisions: list[str] = []
        pending: list[str] = []
        points: list[str] = []
        for node in nodes:
            text = _node_text(node)
            for line in text.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                _append_unique(decisions, stripped, config.l3_item_units, config.weights, DECISION_KEYWORDS)
                _append_unique(pending, stripped, config.l3_item_units, config.weights, PENDING_KEYWORDS)
            point = trim_head(
                text.replace("\n", " ").strip(), config.l3_point_units, weights=config.weights
            )
            if point:
                points.append(f"[{_ROLE_BY_KIND.get(node.kind, node.kind)}] {point}")
        return {"decisions": decisions, "pending": pending, "points": points}

    def _fit_summary_budget(self, rendered: str, summary: dict[str, list[str]]) -> str:
        config = self._config
        budget = WeightedBudget(config.l3_target_units, config.weights)
        points = list(summary["points"])
        while points and budget.measure(_render_summary({**summary, "points": points})) > (
            budget.limit_units
        ):
            points.pop()
        rendered = _render_summary({**summary, "points": points})
        if not budget.fits(rendered):
            return budget.trim(rendered)
        return rendered


def _node_text(node: SurfaceNode) -> str:
    payload = node.payload
    text = payload.get("text")
    if isinstance(text, str) and text:
        return text
    if "content" in payload:
        return content_text(payload.get("content"))
    if node.kind == "tool_call":
        return f"{payload.get('name') or ''} {content_text(payload.get('arguments'))}".strip()
    return ""


def _render_summary(summary: dict[str, list[str]]) -> str:
    lines = ["## 结构化摘要"]
    for title, key in (
        ("决策", "decisions"),
        ("未完成事项", "pending"),
        ("早期对话要点", "points"),
    ):
        items = [f"- {item}" for item in summary[key]] or ["- （无）"]
        lines.extend(["", f"### {title}", *items])
    return "\n".join(lines)


def _append_unique(
    target: list[str],
    line: str,
    item_units: float,
    weights: UnitWeights,
    keywords: tuple[str, ...],
) -> None:
    if not any(keyword in line.lower() for keyword in keywords):
        return
    item = trim_head(line, item_units, weights=weights)
    if item and item not in target:
        target.append(item)


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _media_type(block: dict[str, Any]) -> str:
    source = block.get("source")
    if isinstance(source, dict):
        media_type = source.get("media_type")
        if isinstance(media_type, str) and media_type:
            return media_type
    return "image/png"
