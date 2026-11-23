"""Failure routing, bounded backoff, and the step-boundary retry guard.

A retry is only ever allowed at the start of an assistant step. The runtime
itself never executes tools, so a failed model request has no side effects to
undo; the unsafe case is a caller that already ran a tool from the step being
retried. ``StepTracker`` records that fact and the runtime refuses to restart
such a step.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import StrEnum

from happyclaw.infra.dsh.llm.errors import FailureCode, ProviderFailure

__all__ = [
    "FailureAction",
    "RetryPolicy",
    "StepCommittedError",
    "StepTracker",
    "backoff_delay",
    "route_failure",
]


class FailureAction(StrEnum):
    RETRY = "retry"
    COMPRESS = "compress"
    FAIL = "fail"


DEFAULT_RETRYABLE_CODES: frozenset[str] = frozenset(
    {
        FailureCode.EMPTY_RESPONSE,
        FailureCode.RATE_LIMIT,
        FailureCode.SERVER,
        FailureCode.TIMEOUT,
        FailureCode.TRANSPORT,
    }
)

DEFAULT_COMPRESSIBLE_CODES: frozenset[str] = frozenset({FailureCode.CONTEXT_WINDOW_EXCEEDED})


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded transient retry policy for one provider route.

    ``max_attempts`` counts the first request, so ``3`` means at most two
    retries. Both the attempt count and every delay are capped.
    """

    max_attempts: int = 3
    initial_delay_s: float = 0.5
    max_delay_s: float = 8.0
    jitter_ratio: float = 0.0
    max_compressions: int = 2
    retryable_codes: frozenset[str] = field(default_factory=lambda: DEFAULT_RETRYABLE_CODES)
    compressible_codes: frozenset[str] = field(
        default_factory=lambda: DEFAULT_COMPRESSIBLE_CODES
    )

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.initial_delay_s <= 0 or self.max_delay_s <= 0:
            raise ValueError("backoff delays must be positive")
        if self.initial_delay_s > self.max_delay_s:
            raise ValueError("initial_delay_s must not exceed max_delay_s")
        if not 0.0 <= self.jitter_ratio <= 1.0:
            raise ValueError("jitter_ratio must be between 0 and 1")
        if self.max_compressions < 0:
            raise ValueError("max_compressions must not be negative")


def route_failure(policy: RetryPolicy, failure: ProviderFailure) -> FailureAction:
    """Decide what one failure means: retry, compress, or report.

    Cancellation never reaches here (the runtime handles it first); every
    unlisted code fails fast so a bad request or credential is not replayed.
    """
    if failure.code in policy.compressible_codes:
        return FailureAction.COMPRESS
    if failure.code in policy.retryable_codes:
        return FailureAction.RETRY
    return FailureAction.FAIL


def backoff_delay(
    policy: RetryPolicy,
    failed_attempt: int,
    *,
    retry_after_s: float | None = None,
    rng: random.Random | None = None,
) -> float:
    """Return the delay before the next attempt, honoring provider guidance.

    ``failed_attempt`` is 1-based. The exponential base doubles per failure,
    the provider's ``retry_after_s`` can raise it, and the policy ceiling wins
    over both.
    """
    if failed_attempt < 1:
        raise ValueError("failed_attempt must be at least 1")
    base = policy.initial_delay_s * (2.0 ** (failed_attempt - 1))
    if retry_after_s is not None and retry_after_s > base:
        base = retry_after_s
    delay = min(base, policy.max_delay_s)
    if policy.jitter_ratio > 0:
        generator = rng or random.Random()
        spread = delay * policy.jitter_ratio
        delay = max(0.0, delay + generator.uniform(-spread, spread))
    return delay


class StepCommittedError(RuntimeError):
    """A caller executed a tool from the step that a retry would replay."""


@dataclass(slots=True)
class StepTracker:
    """Tracks side effects performed while one assistant step is in flight.

    The loop's tool executor calls :meth:`note_tool_started` before running a
    tool. A retry is safe only while this stays ``0``: replaying the model
    request cannot repeat an executed tool, and no tool result is re-submitted.
    """

    step_id: str = ""
    tool_calls_started: int = 0

    @property
    def can_retry(self) -> bool:
        return self.tool_calls_started == 0

    def note_tool_started(self) -> None:
        self.tool_calls_started += 1

    def reset(self) -> None:
        self.tool_calls_started = 0

    def require_retryable(self) -> None:
        if not self.can_retry:
            raise StepCommittedError(
                f"step {self.step_id!r} already executed {self.tool_calls_started} tool call(s)"
            )
