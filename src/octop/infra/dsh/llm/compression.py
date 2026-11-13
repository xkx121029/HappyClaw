"""Bridge the LLM compression hook to the session line's three-stage compaction.

This module deliberately contains no compaction logic of its own. On context
overflow it runs :class:`~octop.infra.dsh.session.compaction.CompactionEngine`
over the caller's real :class:`SessionLog` (which writes the existing
``compaction/*`` events), re-projects the compacted surface, and rebuilds the
request.

Contract with the caller:

* the request must be derived from the same session log (normally via
  ``project(log.load())``), so compaction and reassembly see one conversation;
* messages that are not in the log yet (for example the in-flight user turn)
  are passed explicitly as ``tail_messages``;
* the hook never invents a second compaction strategy and never edits the
  session package.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from octop.infra.dsh.llm.errors import FailureCode, ProviderFailure
from octop.infra.dsh.llm.types import (
    LlmRequest,
    Message,
    Role,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
)
from octop.infra.dsh.session import (
    CompactionConfig,
    CompactionEngine,
    SessionLog,
    SurfaceNode,
    content_text,
    project,
)

__all__ = ["SessionCompressionHook", "messages_from_surface"]


def _arguments_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return "{}"
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _tool_call(value: Any) -> ToolCallBlock | None:
    if not isinstance(value, Mapping):
        return None
    call_id = value.get("id") or value.get("call_id")
    name = value.get("name")
    if not isinstance(call_id, str) or not call_id or not isinstance(name, str) or not name:
        return None
    return ToolCallBlock(call_id, name, _arguments_text(value.get("arguments")))


def _append_user(messages: list[Message], blocks: tuple[TextBlock, ...]) -> None:
    if messages and messages[-1].role is Role.USER:
        messages[-1] = Message(Role.USER, messages[-1].content + blocks)
        return
    messages.append(Message(Role.USER, blocks))


def messages_from_surface(nodes: tuple[SurfaceNode, ...]) -> tuple[Message, ...]:
    """Rebuild chat messages from the current visible surface.

    The mapping is intentionally lossless for text and tool traffic:
    ``summary`` becomes a leading user message marked as history, assistant
    text and tool calls are merged into one assistant message, and tool results
    stay addressable by their original call ids. Attachments are not modeled by
    this seam (no multimodal routing); they are represented by a text marker so
    the model still knows they existed.
    """
    messages: list[Message] = []
    for node in nodes:
        payload = node.payload
        if node.kind == "user_message":
            text = str(payload.get("text") or "")
            attachments = payload.get("attachments")
            if isinstance(attachments, list) and attachments:
                text = f"{text}\n[附件 {len(attachments)} 个，当前接入层不支持多模态]".strip()
            if text:
                _append_user(messages, (TextBlock(text),))
        elif node.kind == "assistant_message":
            blocks: list[TextBlock | ToolCallBlock] = []
            text = str(payload.get("text") or "")
            if text:
                blocks.append(TextBlock(text))
            calls = payload.get("tool_calls")
            if isinstance(calls, list):
                for candidate in calls:
                    call = _tool_call(candidate)
                    if call is not None:
                        blocks.append(call)
            if not blocks:
                continue
            content = tuple(blocks)
            if messages and messages[-1].role is Role.ASSISTANT:
                messages[-1] = Message(Role.ASSISTANT, messages[-1].content + content)
            else:
                messages.append(Message(Role.ASSISTANT, content))
        elif node.kind == "tool_call":
            call = _tool_call(
                {
                    "id": payload.get("call_id"),
                    "name": payload.get("name"),
                    "arguments": payload.get("arguments"),
                }
            )
            if call is None:
                continue
            if messages and messages[-1].role is Role.ASSISTANT:
                messages[-1] = Message(Role.ASSISTANT, messages[-1].content + (call,))
            else:
                messages.append(Message(Role.ASSISTANT, (call,)))
        elif node.kind == "tool_result":
            call_id = str(payload.get("call_id") or "")
            if not call_id:
                continue
            messages.append(
                Message(
                    Role.TOOL,
                    (
                        ToolResultBlock(
                            tool_call_id=call_id,
                            content=content_text(payload.get("content")),
                            is_error=bool(payload.get("is_error", False)),
                        ),
                    ),
                )
            )
        elif node.kind == "summary":
            text = str(payload.get("text") or "")
            if text:
                _append_user(messages, (TextBlock(f"[历史摘要]\n{text}"),))
    return tuple(messages)


class SessionCompressionHook:
    """Compression hook backed by ``session.compaction``.

    ``turn`` labels the compaction events. ``max_rounds`` bounds how many
    consecutive compactions may leave the surface over budget: the first one is
    allowed to retry the provider, the second consecutive miss fails with
    ``COMPRESSION_INSUFFICIENT``. Every call records a trace (turn, round,
    levels, event seqs, units) on the returned request metadata so the log and
    the request can be correlated.
    """

    def __init__(
        self,
        log: SessionLog,
        *,
        turn: int,
        config: CompactionConfig | None = None,
        tail_messages: tuple[Message, ...] = (),
        max_rounds: int = 2,
    ) -> None:
        if turn < 0:
            raise ValueError("turn must be non-negative")
        if max_rounds < 1:
            raise ValueError("max_rounds must be at least 1")
        self._log = log
        self._turn = turn
        self._config = config or CompactionConfig()
        self._engine = CompactionEngine(log, config=self._config)
        self._tail_messages = tail_messages
        self._max_rounds = max_rounds

    async def compress(
        self,
        request: LlmRequest,
        failure: ProviderFailure,
        *,
        round: int,
    ) -> LlmRequest | None:
        report = self._engine.run_turn(self._turn)
        trace: dict[str, Any] = {
            "compression_id": f"cmp:{self._turn}:{round}",
            "turn": self._turn,
            "round": round,
            "initial_units": report.initial_units,
            "final_units": report.final_units,
            "budget_units": self._config.max_context_units,
            "within_budget": report.within_budget,
            "levels": [step.level for step in report.steps],
            "event_seqs": [step.event_seq for step in report.steps],
            "source_seqs": sorted({seq for step in report.steps for seq in step.source_seqs}),
            "provider_failure_code": failure.code,
        }

        if not report.steps:
            raise ProviderFailure(
                FailureCode.COMPRESSION_INSUFFICIENT,
                "compaction found nothing left to shrink",
                details={"trace": trace},
            )
        if not report.within_budget and round >= self._max_rounds:
            raise ProviderFailure(
                FailureCode.COMPRESSION_INSUFFICIENT,
                f"surface is still over budget after {round} compaction rounds",
                details={"trace": trace},
            )

        nodes = project(self._log.load())
        messages = messages_from_surface(nodes) + self._tail_messages
        history = list(request.metadata.get("compression_trace") or [])
        history.append(trace)
        metadata = {
            **request.metadata,
            "compression_id": trace["compression_id"],
            "compression_trace": tuple(history),
        }
        return replace(request, messages=messages, metadata=metadata)
