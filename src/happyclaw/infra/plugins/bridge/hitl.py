"""Bridge the approval contract onto Octop's existing HITL pause.

Octop's HITL is interrupt based: a middleware raises ``langgraph.types
.interrupt(payload)``, the graph pauses, the dashboard/IM layer renders
``hitl_required`` from that payload, and the user's decision comes back through
``POST /api/agents/{agent_id}/chat/hitl/resume`` as
``{"decisions": [{"type": "approve" | "reject", ...}]}``. This module converts
an :class:`ApprovalRequest` into that same payload and turns the resume value
back into an :class:`ApprovalOutcome`.

Failures are deny-only. The transport reports *why* it could not obtain a
decision through :class:`ApprovalChannelError`, and the guardrail maps the kind
to a stable code, so the agent can tell a timeout apart from a closed UI and a
dropped channel.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from happyclaw.infra.plugins.bridge.approval import ApprovalChannelError
from happyclaw.infra.plugins.bridge.contract import ApprovalOutcome, ApprovalRequest
from happyclaw.infra.plugins.bridge.errors import describe_exception

__all__ = [
    "DEFAULT_APPROVAL_TIMEOUT_S",
    "ApprovalTransport",
    "HitlApprovalChannel",
    "LangGraphInterruptTransport",
    "build_hitl_request",
]

# Mirrors ``HitlPendingStore.ttl_seconds`` so a decision the UI still accepts is
# never rejected by the channel's own deadline.
DEFAULT_APPROVAL_TIMEOUT_S = 30 * 60.0


def build_hitl_request(request: ApprovalRequest) -> dict[str, Any]:
    """Build the ``HITLRequest`` payload ``interrupt()`` already understands."""
    tool_name = request.tool_name or request.call_id
    return {
        "action_requests": [
            {
                "name": tool_name,
                "args": dict(request.arguments),
                "description": request.reason,
            }
        ],
        "review_configs": [
            {
                "action_name": tool_name,
                "allowed_decisions": ["approve", "reject"],
            }
        ],
    }


class ApprovalTransport(Protocol):
    """Asks a human and returns the raw resume payload (or raises)."""

    pause_exceptions: tuple[type[BaseException], ...]

    def ask(self, payload: Mapping[str, Any]) -> object: ...


def _graph_pause_exceptions() -> tuple[type[BaseException], ...]:
    try:
        from langgraph.errors import GraphBubbleUp
    except Exception:
        return ()
    return (GraphBubbleUp,)


def _load_interrupt() -> Callable[[object], object] | None:
    try:
        from langgraph.types import interrupt
    except Exception:
        return None
    return interrupt


class LangGraphInterruptTransport:
    """Default transport: the same ``interrupt()`` the HITL UI already renders.

    ``interrupt()`` raises ``GraphBubbleUp`` to pause the graph, so the type is
    surfaced through ``pause_exceptions`` for the guardrail to re-raise instead
    of turning a pause into a denial.
    """

    def __init__(self, interrupt_func: Callable[[object], object] | None = None) -> None:
        self._interrupt = interrupt_func
        self.pause_exceptions = _graph_pause_exceptions()

    def ask(self, payload: Mapping[str, Any]) -> object:
        func = self._interrupt or _load_interrupt()
        if func is None:
            raise ApprovalChannelError(
                "disconnected",
                "the HITL runtime is unavailable; no approval can be requested",
            )
        return func(dict(payload))


class HitlApprovalChannel:
    """``ApprovalChannel`` backed by the repository's HITL pause/resume path.

    A decision that only arrives after ``timeout_s`` is still a denial: the
    pending record may expire while the graph stays paused, and a late click
    must not resurrect the call.
    """

    def __init__(
        self,
        transport: ApprovalTransport | None = None,
        *,
        timeout_s: float | None = DEFAULT_APPROVAL_TIMEOUT_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.transport: ApprovalTransport = transport or LangGraphInterruptTransport()
        self.timeout_s = timeout_s
        self.clock = clock
        self.pause_exceptions = tuple(getattr(self.transport, "pause_exceptions", ()) or ())

    def request(self, request: ApprovalRequest) -> ApprovalOutcome:
        """Ask the user once; deny on reject, timeout, close, or disconnect."""
        if request.signal is not None and request.signal.is_set():
            raise ApprovalChannelError(
                "disconnected",
                "the requesting session is gone; the approval card was never shown",
            )

        payload = build_hitl_request(request)
        started = self.clock()
        try:
            raw = self.transport.ask(payload)
        except ApprovalChannelError:
            raise
        except TimeoutError as exc:
            raise ApprovalChannelError(
                "timeout",
                f"approval timed out: {describe_exception(exc)}",
            ) from None
        except Exception as exc:
            if isinstance(exc, self.pause_exceptions):
                raise
            raise ApprovalChannelError(
                "disconnected",
                f"HITL channel is unavailable: {describe_exception(exc)}",
            ) from None

        elapsed = self.clock() - started
        if self.timeout_s is not None and elapsed > self.timeout_s:
            raise ApprovalChannelError(
                "timeout",
                f"approval arrived after {elapsed:.0f}s, above the {self.timeout_s:.0f}s limit",
            )

        return _decode_decision(raw)


def _decode_decision(raw: object) -> ApprovalOutcome:
    if not isinstance(raw, Mapping):
        raise ApprovalChannelError(
            "closed",
            "the approval UI closed without a decision",
        )
    decisions = raw.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        raise ApprovalChannelError(
            "closed",
            "the approval UI closed without a decision",
        )
    first = decisions[0]
    if not isinstance(first, Mapping):
        raise ApprovalChannelError(
            "closed",
            "the approval UI returned an unreadable decision",
        )
    decision_type = str(first.get("type") or "").strip().lower()
    if decision_type == "approve":
        return ApprovalOutcome.ALLOWED_ONCE
    # We only advertise approve/reject. ``edit``/``respond``/unknown means the
    # host changed the contract behind our back, so fail closed.
    return ApprovalOutcome.REJECTED
