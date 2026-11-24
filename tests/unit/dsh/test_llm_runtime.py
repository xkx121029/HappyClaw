"""Runtime behavior: step restarts, backoff, compression routing, cancellation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from happyclaw.infra.dsh.llm import (
    AssistantTurnBuilder,
    CancellationToken,
    FailureCode,
    FinishChunk,
    FinishReason,
    LlmRequest,
    LlmRuntime,
    ProviderFailure,
    RetryPolicy,
    Role,
    StepRestart,
    StepTracker,
    StreamChunk,
    TextBlock,
    TextDelta,
    TokenUsage,
    ToolCallDelta,
    UsageChunk,
    UsageDrift,
    text_message,
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
    """In-memory canonical provider; each script is one attempt."""

    name = "fake"

    def __init__(self, scripts: list[list[StreamChunk | ProviderFailure]]) -> None:
        self.scripts = list(scripts)
        self.requests: list[LlmRequest] = []
        self.streams: list[_CanonStream] = []

    def start(self, request: LlmRequest) -> _CanonStream:
        self.requests.append(request)
        stream = _CanonStream(self.scripts.pop(0))
        self.streams.append(stream)
        return stream


class RecordingSleeper:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


class Compressor:
    def __init__(self, result: LlmRequest | None) -> None:
        self.result = result
        self.calls: list[tuple[int, str]] = []

    async def compress(
        self,
        request: LlmRequest,
        failure: ProviderFailure,
        *,
        round: int,
    ) -> LlmRequest | None:
        self.calls.append((round, failure.code))
        return self.result


def _request(text: str = "hello") -> LlmRequest:
    return LlmRequest(
        provider="fake",
        model="fake-model",
        messages=(text_message(Role.USER, text),),
        max_tokens=32,
    )


def _policy(**overrides: Any) -> RetryPolicy:
    values: dict[str, Any] = {
        "max_attempts": 3,
        "initial_delay_s": 0.01,
        "max_delay_s": 0.05,
        "jitter_ratio": 0.0,
    }
    values.update(overrides)
    return RetryPolicy(**values)


async def _collect(
    runtime: LlmRuntime,
    request: LlmRequest,
    *,
    cancel: CancellationToken | None = None,
    step: StepTracker | None = None,
) -> tuple[list[Any], Any]:
    events: list[Any] = []
    builder = AssistantTurnBuilder()
    async for event in runtime.stream(request, cancel=cancel, step=step):
        events.append(event)
        if isinstance(event, StepRestart):
            builder.reset()
        elif isinstance(event, UsageDrift):
            continue
        else:
            builder.push(event)
    return events, builder.build()


async def test_transient_failure_restarts_the_whole_step() -> None:
    adapter = FakeAdapter(
        [
            [TextDelta(0, "par"), ProviderFailure(FailureCode.SERVER, "upstream 500", status=500)],
            [TextDelta(0, "ok"), FinishChunk(FinishReason.STOP)],
        ]
    )
    sleeper = RecordingSleeper()
    runtime = LlmRuntime(adapter, policy=_policy(), sleeper=sleeper)

    events, turn = await _collect(runtime, _request())

    restarts = [event for event in events if isinstance(event, StepRestart)]
    assert len(restarts) == 1
    assert restarts[0].reason == "retry"
    assert restarts[0].discarded_partial is True
    assert restarts[0].failure.code == FailureCode.SERVER
    assert len(adapter.requests) == 2
    assert len(sleeper.delays) == 1
    assert txt(turn) == "ok"
    assert turn.finish_reason is FinishReason.STOP


async def test_streamed_tool_call_delta_is_discarded_not_replayed() -> None:
    adapter = FakeAdapter(
        [
            [
                ToolCallDelta(0, "call_1", '{"pa', "read_file"),
                ProviderFailure(FailureCode.TRANSPORT, "socket closed"),
            ],
            [ToolCallDelta(0, "call_1", "{}", "read_file"), FinishChunk(FinishReason.TOOL_CALLS)],
        ]
    )
    tracker = StepTracker(step_id="s1")
    runtime = LlmRuntime(adapter, policy=_policy(), sleeper=RecordingSleeper())

    _, turn = await _collect(runtime, _request(), step=tracker)

    assert len(adapter.requests) == 2
    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0].arguments == "{}"
    assert turn.finish_reason is FinishReason.TOOL_CALLS


async def test_retry_is_refused_after_a_tool_call_executed() -> None:
    adapter = FakeAdapter(
        [[ProviderFailure(FailureCode.SERVER, "upstream 500", status=500)]],
    )
    tracker = StepTracker(step_id="s1")
    tracker.note_tool_started()
    runtime = LlmRuntime(adapter, policy=_policy(), sleeper=RecordingSleeper())

    events, turn = await _collect(runtime, _request(), step=tracker)

    assert len(adapter.requests) == 1
    assert not any(isinstance(event, StepRestart) for event in events)
    assert turn.finish_reason is FinishReason.ERROR
    assert turn.failure is not None
    assert turn.failure.code == FailureCode.STEP_COMMITTED


async def test_rate_limit_backoff_is_bounded_and_honors_retry_after() -> None:
    failure = ProviderFailure(
        FailureCode.RATE_LIMIT,
        "slow down",
        status=429,
        retry_after_s=10.0,
    )
    adapter = FakeAdapter([[failure], [failure], [failure]])
    sleeper = RecordingSleeper()
    runtime = LlmRuntime(
        adapter,
        policy=_policy(max_attempts=3, initial_delay_s=0.2, max_delay_s=0.5),
        sleeper=sleeper,
    )

    events, turn = await _collect(runtime, _request())

    assert len(adapter.requests) == 3
    assert sleeper.delays == [0.5, 0.5]
    assert turn.finish_reason is FinishReason.ERROR
    assert turn.failure is not None
    assert turn.failure.code == FailureCode.RATE_LIMIT
    assert turn.failure.details["attempts"] == 3
    restarts = [event for event in events if isinstance(event, StepRestart)]
    assert [restart.attempt for restart in restarts] == [1, 2]


async def test_invalid_request_is_reported_without_retry() -> None:
    adapter = FakeAdapter([[ProviderFailure(FailureCode.INVALID_REQUEST, "bad schema", status=400)]])
    sleeper = RecordingSleeper()
    runtime = LlmRuntime(adapter, policy=_policy(), sleeper=sleeper)

    _, turn = await _collect(runtime, _request())

    assert len(adapter.requests) == 1
    assert sleeper.delays == []
    assert turn.failure is not None
    assert turn.failure.code == FailureCode.INVALID_REQUEST


async def test_context_overflow_goes_to_compression_hook() -> None:
    original = _request("A" * 200)
    compressed = _request("short")
    compressor = Compressor(compressed)
    adapter = FakeAdapter(
        [
            [ProviderFailure(FailureCode.CONTEXT_WINDOW_EXCEEDED, "context too long")],
            [TextDelta(0, "ok"), FinishChunk(FinishReason.STOP)],
        ]
    )
    runtime = LlmRuntime(
        adapter,
        policy=_policy(),
        compressor=compressor,
        sleeper=RecordingSleeper(),
    )

    events, turn = await _collect(runtime, original)

    assert compressor.calls == [(1, FailureCode.CONTEXT_WINDOW_EXCEEDED)]
    assert adapter.requests[1] is compressed
    assert turn.finish_reason is FinishReason.STOP
    restarts = [event for event in events if isinstance(event, StepRestart)]
    assert restarts[0].reason == "compression"


async def test_context_overflow_without_hook_fails_fast() -> None:
    adapter = FakeAdapter(
        [[ProviderFailure(FailureCode.CONTEXT_WINDOW_EXCEEDED, "context too long")]]
    )
    runtime = LlmRuntime(adapter, policy=_policy(), sleeper=RecordingSleeper())

    _, turn = await _collect(runtime, _request())

    assert len(adapter.requests) == 1
    assert turn.finish_reason is FinishReason.ERROR
    assert turn.failure is not None
    assert turn.failure.code == FailureCode.CONTEXT_WINDOW_EXCEEDED


async def test_empty_response_is_treated_as_transient() -> None:
    adapter = FakeAdapter(
        [
            [FinishChunk(FinishReason.STOP)],
            [TextDelta(0, "ok"), FinishChunk(FinishReason.STOP)],
        ]
    )
    runtime = LlmRuntime(adapter, policy=_policy(), sleeper=RecordingSleeper())

    events, turn = await _collect(runtime, _request())

    restarts = [event for event in events if isinstance(event, StepRestart)]
    assert restarts[0].failure.code == FailureCode.EMPTY_RESPONSE
    assert len(adapter.requests) == 2
    assert txt(turn) == "ok"


async def test_cancel_mid_stream_marks_partial_output_and_closes_stream() -> None:
    adapter = FakeAdapter(
        [[TextDelta(0, "a"), TextDelta(0, "b"), FinishChunk(FinishReason.STOP)]]
    )
    runtime = LlmRuntime(adapter, policy=_policy())
    token = CancellationToken()
    tasks_before = asyncio.all_tasks()

    events: list[Any] = []
    async for event in runtime.stream(_request(), cancel=token):
        events.append(event)
        if isinstance(event, TextDelta):
            token.cancel()

    assert adapter.streams[0].closed is True
    assert isinstance(events[-1], FinishChunk)
    assert events[-1].reason is FinishReason.ABORTED
    assert events[-1].incomplete is True
    assert asyncio.all_tasks() == tasks_before


async def test_cancel_during_backoff_does_not_make_another_request() -> None:
    adapter = FakeAdapter([[ProviderFailure(FailureCode.SERVER, "upstream 500", status=500)]])
    token = CancellationToken()

    async def cancelling_sleep(delay: float) -> None:
        token.cancel()

    runtime = LlmRuntime(adapter, policy=_policy(), sleeper=cancelling_sleep)

    events, turn = await _collect(runtime, _request(), cancel=token)

    assert len(adapter.requests) == 1
    assert turn.finish_reason is FinishReason.ABORTED
    assert any(isinstance(event, StepRestart) for event in events)


async def test_usage_drift_is_reported_against_estimate() -> None:
    adapter = FakeAdapter(
        [
            [
                TextDelta(0, "hi"),
                UsageChunk(TokenUsage(input_tokens=400, output_tokens=2)),
                FinishChunk(FinishReason.STOP),
            ]
        ]
    )
    runtime = LlmRuntime(adapter, policy=_policy())

    events, _ = await _collect(runtime, _request())

    drifts = [event for event in events if isinstance(event, UsageDrift)]
    assert len(drifts) == 1
    assert drifts[0].provider_input_tokens == 400
    assert drifts[0].ratio > drifts[0].threshold


def txt(turn: Any) -> str:
    return "".join(
        block.text for block in turn.content if isinstance(block, TextBlock)
    )
