"""Turn assembly for consumers of the canonical stream.

The runtime may restart a step; every event before ``StepRestart`` belongs to a
discarded attempt. Feeding events through this builder and calling
:meth:`AssistantTurnBuilder.reset` on a restart yields exactly the settled turn
without duplicated text or tool calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from octop.infra.dsh.llm.types import (
    AssistantTurn,
    BlockEnd,
    BlockKind,
    BlockStart,
    ContentBlock,
    FinishChunk,
    ReasoningBlock,
    ReasoningDelta,
    StreamChunk,
    TextBlock,
    TextDelta,
    TokenUsage,
    ToolCallBlock,
    ToolCallDelta,
    UsageChunk,
)

__all__ = ["AssistantTurnBuilder"]


@dataclass(slots=True)
class _OpenBlock:
    kind: BlockKind
    call_id: str = ""
    name: str = ""
    parts: list[str] = field(default_factory=list)


class AssistantTurnBuilder:
    """Incrementally assembles stream chunks into one assistant turn."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Discard a partial attempt after ``StepRestart``."""
        self._open: dict[int, _OpenBlock] = {}
        self._closed: dict[int, ContentBlock] = {}
        self._usage: TokenUsage | None = None
        self._finish: FinishChunk | None = None

    def push(self, event: StreamChunk) -> None:
        if isinstance(event, BlockStart):
            self._open[event.index] = _OpenBlock(event.block_kind)
        elif isinstance(event, TextDelta):
            block = self._ensure(event.index, BlockKind.TEXT)
            block.parts.append(event.text)
        elif isinstance(event, ReasoningDelta):
            block = self._ensure(event.index, BlockKind.REASONING)
            block.parts.append(event.text)
        elif isinstance(event, ToolCallDelta):
            block = self._ensure(event.index, BlockKind.TOOL_CALL)
            if event.tool_call_id:
                block.call_id = event.tool_call_id
            if event.name:
                block.name = event.name
            block.parts.append(event.arguments_delta)
        elif isinstance(event, BlockEnd):
            self._closed[event.index] = event.block
        elif isinstance(event, UsageChunk):
            self._usage = event.usage
        elif isinstance(event, FinishChunk):
            self._finish = event

    def build(self) -> AssistantTurn:
        content: list[ContentBlock] = []
        for index in sorted(set(self._open) | set(self._closed)):
            closed = self._closed.get(index)
            content.append(closed if closed is not None else self._finish_open(index))
        finish = self._finish
        return AssistantTurn(
            content=tuple(content),
            usage=self._usage,
            finish_reason=finish.reason if finish is not None else None,
            incomplete=finish.incomplete if finish is not None else False,
            failure=finish.failure if finish is not None else None,
        )

    def _ensure(self, index: int, kind: BlockKind) -> _OpenBlock:
        existing = self._open.get(index)
        if existing is None:
            existing = _OpenBlock(kind)
            self._open[index] = existing
        return existing

    def _finish_open(self, index: int) -> ContentBlock:
        block = self._open[index]
        text = "".join(block.parts)
        if block.kind is BlockKind.TOOL_CALL:
            return ToolCallBlock(block.call_id, block.name, text)
        if block.kind is BlockKind.REASONING:
            return ReasoningBlock(text)
        return TextBlock(text)
