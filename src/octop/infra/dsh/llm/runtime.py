"""Retry, compression, and cancellation orchestration around one adapter.

The runtime owns the step boundary. One attempt is one complete model request;
when it fails transiently the whole attempt is discarded and re-requested from
the step start, never resumed mid-stream. Consumers see ``StepRestart`` and must
reset their partial assembly.

No background task is created here. Cancellation is cooperative through
``CancellationToken``; the in-flight provider stream is always closed, and the
last emitted ``FinishChunk`` is marked incomplete when output had already
started.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from octop.infra.dsh.llm.adapter import ChunkStream, ProviderAdapter
from octop.infra.dsh.llm.errors import FailureCode, ProviderFailure
from octop.infra.dsh.llm.retry import (
    FailureAction,
    RetryPolicy,
    StepTracker,
    backoff_delay,
    route_failure,
)
from octop.infra.dsh.llm.tokens import TokenAuditPolicy, audit_input_usage, estimate_request
from octop.infra.dsh.llm.types import (
    FinishChunk,
    FinishReason,
    LlmRequest,
    RuntimeEvent,
    StepRestart,
    TextDelta,
    ReasoningDelta,
    ToolCallDelta,
    UsageChunk,
)

__all__ = ["CancellationToken", "CompressionHook", "LlmRuntime"]


class CancellationToken:
    """Cooperative cancellation flag; one token per conversation turn."""

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = asyncio.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    async def wait(self) -> None:
        await self._event.wait()


class CompressionHook(Protocol):
    """Compresses an over-long request and returns the replacement.

    Returning ``None`` means compression is unavailable or declined; the
    context failure is then reported as-is. The implementation is out of scope
    for this layer, which only guarantees the call site and budget.
    """

    async def compress(
        self,
        request: LlmRequest,
        failure: ProviderFailure,
        *,
        round: int,
    ) -> LlmRequest | None: ...


@dataclass(slots=True)
class _AttemptState:
    emitted: bool = False


class LlmRuntime:
    """Runs one request to a settled turn with bounded, step-safe recovery."""

    def __init__(
        self,
        adapter: ProviderAdapter,
        *,
        policy: RetryPolicy | None = None,
        compressor: CompressionHook | None = None,
        audit_policy: TokenAuditPolicy | None = None,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._adapter = adapter
        self._policy = policy or RetryPolicy()
        self._compressor = compressor
        self._audit_policy = audit_policy or TokenAuditPolicy()
        self._sleeper = sleeper
        self._rng = rng

    @property
    def policy(self) -> RetryPolicy:
        return self._policy

    async def stream(
        self,
        request: LlmRequest,
        *,
        cancel: CancellationToken | None = None,
        step: StepTracker | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Yield canonical events for one step, retried at its start only."""
        policy = self._policy
        current = request
        attempt = 0
        compressions = 0

        while True:
            if cancel is not None and cancel.cancelled:
                yield FinishChunk(FinishReason.ABORTED)
                return

            attempt += 1
            state = _AttemptState()
            stream: ChunkStream | None = None
            try:
                stream = self._adapter.start(current)
                async for chunk in stream:
                    if cancel is not None and cancel.cancelled:
                        yield FinishChunk(FinishReason.ABORTED, incomplete=state.emitted)
                        return

                    if isinstance(chunk, UsageChunk):
                        yield chunk
                        drift = audit_input_usage(
                            estimate_request(current), chunk.usage, self._audit_policy
                        )
                        if drift is not None:
                            yield drift
                        continue

                    if isinstance(chunk, FinishChunk):
                        if chunk.reason in (FinishReason.STOP, FinishReason.TOOL_CALLS):
                            if not state.emitted:
                                raise ProviderFailure(
                                    FailureCode.EMPTY_RESPONSE,
                                    "provider finished without any content",
                                )
                        yield chunk
                        return

                    if isinstance(chunk, (TextDelta, ReasoningDelta)) and chunk.text:
                        state.emitted = True
                    elif isinstance(chunk, ToolCallDelta):
                        if chunk.name or chunk.arguments_delta:
                            state.emitted = True
                    yield chunk

            except ProviderFailure as failure:
                action = route_failure(policy, failure)
                if action is FailureAction.RETRY and attempt < policy.max_attempts:
                    if step is not None and not step.can_retry:
                        yield FinishChunk(
                            FinishReason.ERROR,
                            incomplete=state.emitted,
                            failure=ProviderFailure(
                                FailureCode.STEP_COMMITTED,
                                "cannot replay a step whose tool call already started",
                            ),
                        )
                        return
                    delay = backoff_delay(
                        policy,
                        attempt,
                        retry_after_s=failure.retry_after_s,
                        rng=self._rng,
                    )
                    yield StepRestart(
                        attempt=attempt,
                        reason="retry",
                        failure=failure,
                        discarded_partial=state.emitted,
                    )
                    if not await self._wait(delay, cancel):
                        yield FinishChunk(FinishReason.ABORTED, incomplete=state.emitted)
                        return
                    continue

                if (
                    action is FailureAction.COMPRESS
                    and self._compressor is not None
                    and compressions < policy.max_compressions
                ):
                    if step is not None and not step.can_retry:
                        yield FinishChunk(
                            FinishReason.ERROR,
                            incomplete=state.emitted,
                            failure=ProviderFailure(
                                FailureCode.STEP_COMMITTED,
                                "cannot replay a step whose tool call already started",
                            ),
                        )
                        return
                    yield StepRestart(
                        attempt=attempt,
                        reason="compression",
                        failure=failure,
                        discarded_partial=state.emitted,
                    )
                    try:
                        compressed = await self._compressor.compress(
                            current, failure, round=compressions + 1
                        )
                    except ProviderFailure as hook_failure:
                        yield FinishChunk(
                            FinishReason.ERROR,
                            incomplete=state.emitted,
                            failure=hook_failure,
                        )
                        return
                    if compressed is None:
                        yield FinishChunk(
                            FinishReason.ERROR,
                            incomplete=state.emitted,
                            failure=ProviderFailure(
                                FailureCode.COMPRESSION_INSUFFICIENT,
                                "compression hook declined to produce a smaller request",
                                details={
                                    "compression_rounds": compressions,
                                    "last_failure_code": failure.code,
                                },
                            ),
                        )
                        return
                    current = compressed
                    compressions += 1
                    attempt = 0
                    continue

                if action is FailureAction.COMPRESS and self._compressor is not None:
                    yield FinishChunk(
                        FinishReason.ERROR,
                        incomplete=state.emitted,
                        failure=ProviderFailure(
                            FailureCode.COMPRESSION_INSUFFICIENT,
                            "request is still too long after the compression budget was used",
                            details={
                                "compression_rounds": compressions,
                                "max_compressions": policy.max_compressions,
                                "last_failure_code": failure.code,
                            },
                        ),
                    )
                    return

                exhausted = (
                    failure.with_attempts(attempt)
                    if action is FailureAction.RETRY
                    else failure
                )
                yield FinishChunk(
                    FinishReason.ERROR,
                    incomplete=state.emitted,
                    failure=exhausted,
                )
                return

            finally:
                if stream is not None:
                    await stream.aclose()

    async def _wait(self, delay: float, cancel: CancellationToken | None) -> bool:
        """Sleep before a retry; return False when the turn was cancelled."""
        if self._sleeper is not None:
            await self._sleeper(delay)
            return cancel is None or not cancel.cancelled
        if cancel is None:
            await asyncio.sleep(delay)
            return True
        try:
            await asyncio.wait_for(cancel.wait(), timeout=delay)
        except TimeoutError:
            return True
        return False
