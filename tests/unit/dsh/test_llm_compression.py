"""Compression hook wired to the session line's three-stage compaction."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from octop.infra.dsh.llm import (
    AssistantTurnBuilder,
    FailureCode,
    FinishChunk,
    FinishReason,
    LlmRequest,
    LlmRuntime,
    ProviderFailure,
    RetryPolicy,
    SessionCompressionHook,
    StepRestart,
    StreamChunk,
    TextDelta,
)
from octop.infra.dsh.llm.compression import messages_from_surface
from octop.infra.dsh.session import (
    CompactionConfig,
    EventType,
    SessionLog,
    project,
)


class _CanonStream:
    def __init__(self, items: list[StreamChunk | ProviderFailure]) -> None:
        self._items = items
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[StreamChunk]:
        for item in self._items:
            if isinstance(item, ProviderFailure):
                raise item
            yield item

    async def aclose(self) -> None:
        self.closed = True


class FakeAdapter:
    name = "fake"

    def __init__(self, scripts: list[list[StreamChunk | ProviderFailure]]) -> None:
        self.scripts = list(scripts)
        self.requests: list[LlmRequest] = []

    def start(self, request: LlmRequest) -> _CanonStream:
        self.requests.append(request)
        return _CanonStream(self.scripts.pop(0))


def _clock() -> str:
    return "2026-11-12T00:00:00.000Z"


def _config() -> CompactionConfig:
    return CompactionConfig(
        max_context_units=500,
        l1_tool_result_units=100,
        l1_head_units=20,
        l1_tail_units=5,
        l2_block_units=100,
        l2_preview_units=10,
        l3_target_units=120,
        l3_retain_recent_nodes=2,
        l3_point_units=10,
        l3_item_units=8,
    )


def _impossible_config() -> CompactionConfig:
    return CompactionConfig(
        max_context_units=10,
        l1_tool_result_units=8,
        l1_head_units=2,
        l1_tail_units=1,
        l2_block_units=8,
        l2_preview_units=2,
        l3_target_units=50,
        l3_retain_recent_nodes=2,
        l3_point_units=10,
        l3_item_units=8,
    )


def _build_log(root: Path, *, size: int = 24) -> SessionLog:
    log = SessionLog(root, clock=_clock)
    log.append(EventType.SESSION_START, {"session_id": "s-llm-compact"})
    log.append(EventType.USER_MESSAGE, {"text": "开始"})
    log.append(EventType.ASSISTANT_MESSAGE, {"text": "调用工具，决定采用磁盘扫描"})
    log.append(EventType.TOOL_CALL, {"call_id": "c1", "name": "disk_usage", "arguments": {}})
    log.append(
        EventType.TOOL_RESULT,
        {"call_id": "c1", "content": "工" * 500, "is_error": False, "name": "disk_usage"},
    )
    log.append(EventType.ASSISTANT_MESSAGE, {"text": "结果很大"})
    log.append(EventType.USER_MESSAGE, {"text": "大" * 200})
    for index in range(size):
        event = EventType.USER_MESSAGE if index % 2 == 0 else EventType.ASSISTANT_MESSAGE
        log.append(event, {"text": f"短{index}" + "字" * 24})
    log.append(EventType.SESSION_END, {})
    return log


def _request(log: SessionLog, *, turn: int) -> LlmRequest:
    return LlmRequest(
        provider="fake",
        model="fake-model",
        system="sys",
        messages=messages_from_surface(project(log.load())),
        max_tokens=64,
        metadata={"turn": turn},
    )


def _policy() -> RetryPolicy:
    return RetryPolicy(max_attempts=2, initial_delay_s=0.01, max_delay_s=0.02, jitter_ratio=0.0)


async def _collect(
    runtime: LlmRuntime,
    request: LlmRequest,
) -> tuple[list[Any], Any]:
    events: list[Any] = []
    builder = AssistantTurnBuilder()
    async for event in runtime.stream(request):
        events.append(event)
        if isinstance(event, StepRestart):
            builder.reset()
        else:
            builder.push(event)
    return events, builder.build()


async def test_overflow_compacts_and_retries_with_reassembled_request(tmp_path: Path) -> None:
    turn = 11
    log = _build_log(tmp_path / "session")
    original = _request(log, turn=turn)
    adapter = FakeAdapter(
        [
            [ProviderFailure(FailureCode.CONTEXT_WINDOW_EXCEEDED, "context too long")],
            [TextDelta(0, "ok"), FinishChunk(FinishReason.STOP)],
        ]
    )
    hook = SessionCompressionHook(log, turn=turn, config=_config())
    runtime = LlmRuntime(adapter, policy=_policy(), compressor=hook)

    events, result = await _collect(runtime, original)

    assert len(adapter.requests) == 2
    retried = adapter.requests[1]
    assert retried.messages != original.messages
    assert "工" * 500 not in "".join(
        block.text for message in retried.messages for block in message.content if hasattr(block, "text")
    )
    trace = retried.metadata["compression_trace"][0]
    assert trace["turn"] == turn
    assert trace["levels"] == [1, 2, 3]
    assert trace["within_budget"] is True
    assert result.finish_reason is FinishReason.STOP
    assert any(isinstance(event, StepRestart) for event in events)


async def test_compression_still_over_budget_stops_with_explicit_error(tmp_path: Path) -> None:
    turn = 12
    log = _build_log(tmp_path / "session", size=6)
    original = _request(log, turn=turn)
    overflow = ProviderFailure(FailureCode.CONTEXT_WINDOW_EXCEEDED, "context too long")
    adapter = FakeAdapter([[overflow], [overflow]])
    hook = SessionCompressionHook(
        log,
        turn=turn,
        config=_impossible_config(),
        max_rounds=2,
    )
    runtime = LlmRuntime(
        adapter,
        policy=RetryPolicy(
            max_attempts=2,
            initial_delay_s=0.01,
            max_delay_s=0.02,
            jitter_ratio=0.0,
            max_compressions=3,
        ),
        compressor=hook,
    )

    _, result = await _collect(runtime, original)

    assert len(adapter.requests) == 2
    assert result.finish_reason is FinishReason.ERROR
    assert result.failure is not None
    assert result.failure.code == FailureCode.COMPRESSION_INSUFFICIENT
    assert result.failure.details["trace"]["round"] == 2
    assert result.failure.details["trace"]["within_budget"] is False
    assert adapter.requests[1].metadata["compression_trace"][0]["within_budget"] is False


async def test_compaction_events_match_request_trace(tmp_path: Path) -> None:
    turn = 13
    log = _build_log(tmp_path / "session")
    original = _request(log, turn=turn)
    adapter = FakeAdapter(
        [
            [ProviderFailure(FailureCode.CONTEXT_WINDOW_EXCEEDED, "context too long")],
            [TextDelta(0, "ok"), FinishChunk(FinishReason.STOP)],
        ]
    )
    hook = SessionCompressionHook(log, turn=turn, config=_config())
    runtime = LlmRuntime(adapter, policy=_policy(), compressor=hook)

    await _collect(runtime, original)

    records = log.load()
    compaction = [record for record in records if record.type.startswith("compaction/")]
    trace = adapter.requests[1].metadata["compression_trace"][0]
    assert [record.seq for record in compaction] == list(trace["event_seqs"])
    assert [record.data["turn"] for record in compaction] == [turn, turn, turn]
    assert adapter.requests[1].metadata["compression_id"] == f"cmp:{turn}:1"
    assert trace["round"] == 1
