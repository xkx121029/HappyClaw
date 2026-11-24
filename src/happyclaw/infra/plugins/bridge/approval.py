"""Three-layer guardrail for DSH tools: capability → approval → policy.

The guardrail is deliberately *not* a command blacklist. Safety comes from
whether an execution backend actually exists and whether a human authorized the
specific action; pattern-matching command strings is bypassable and gives a
false sense of security. See ``2026-11-12/dsh-integration/outputs/approval.md``.

Layer order and failure posture:

1. **Capability boundary** — no backend, or a failed probe, denies outright.
   There is no fallback to a less isolated execution path.
2. **Approval** — anything at or above the risk threshold needs a one-time
   grant. No approval channel means denial, never a default allow. A grant is
   bound to a ``call_id`` and can only be consumed once.
3. **Policy hooks** — monotonic: hooks may deny, never re-allow. An ``allow``
   verdict can never override an approval rejection or an earlier denial.

Every evaluation writes one :class:`ApprovalRecord` (actor, tool, arguments,
risk, decision, reason); approval channel failures are recorded too.
"""

from __future__ import annotations

import contextlib
import inspect
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from typing import Any, Literal, Protocol
from uuid import uuid4

from happyclaw.infra.plugins.bridge.contract import ApprovalOutcome, ApprovalRequest
from happyclaw.infra.plugins.bridge.contract_types import AbortSignal
from happyclaw.infra.plugins.bridge.errors import (
    DshToolErrorCode,
    describe_exception,
)


class RiskLevel(IntEnum):
    """Ordered risk levels; higher values need stronger justification."""

    LOW = 0
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3


@dataclass(frozen=True)
class RiskAssessment:
    level: RiskLevel = RiskLevel.LOW
    reason: str = ""


@dataclass(frozen=True)
class CapabilityDecision:
    available: bool
    reason: str = ""


SANDBOX_COVERAGE_COVERED = "covered"
SANDBOX_COVERAGE_NOT_APPLICABLE = "not_applicable"
SANDBOX_COVERAGE_UNAVAILABLE = "unavailable"
SANDBOX_COVERAGE_UNKNOWN = "unknown"

_COVERAGE_VALUES = frozenset(
    {
        SANDBOX_COVERAGE_COVERED,
        SANDBOX_COVERAGE_NOT_APPLICABLE,
        SANDBOX_COVERAGE_UNAVAILABLE,
    }
)


@dataclass(frozen=True)
class SandboxBacking:
    """What the capability probe actually inspected, kept for traceability.

    A plain :class:`CapabilityDecision` carries no coverage information, so it
    is reported as ``unknown`` with ``backed=False``: not reading coverage must
    never be mistaken for a passing check. Sandbox probes that subclass
    ``CapabilityDecision`` expose ``coverage`` / ``backed`` / ``inspected`` and
    are read by duck typing, which keeps this package independent of
    ``plugins/sandbox``.

    ``inspected`` separates "a check plan existed and ran" from "there was
    nothing to check at all": the former can still end with ``checked == ()``
    when none of the declared arguments were present.
    """

    coverage: str = SANDBOX_COVERAGE_UNKNOWN
    backed: bool = False
    inspected: bool = False
    checked: tuple[str, ...] = ()
    reason: str = ""

    @classmethod
    def from_probe(cls, raw: object) -> SandboxBacking:
        if raw is None:
            return cls()
        coverage_raw = getattr(raw, "coverage", None)
        coverage = str(getattr(coverage_raw, "value", coverage_raw) or "").strip().lower()
        if coverage not in _COVERAGE_VALUES:
            coverage = SANDBOX_COVERAGE_UNKNOWN
        checked_raw = getattr(raw, "checked", ())
        checked = (
            tuple(str(item) for item in checked_raw)
            if isinstance(checked_raw, (list, tuple))
            else ()
        )
        inspected_flag = getattr(raw, "inspected", None)
        inspected = inspected_flag if isinstance(inspected_flag, bool) else False
        backed_flag = getattr(raw, "backed", None)
        if isinstance(backed_flag, bool):
            backed = backed_flag
        else:
            backed = coverage == SANDBOX_COVERAGE_COVERED and bool(getattr(raw, "available", False))
        reason = str(getattr(raw, "reason", "") or "").strip()
        return cls(
            coverage=coverage,
            backed=backed,
            inspected=inspected,
            checked=checked,
            reason=reason,
        )


@dataclass(frozen=True)
class PolicyVerdict:
    """A policy hook's opinion. ``allowed`` never loosens an earlier denial."""

    allowed: bool
    reason: str = ""


@dataclass(frozen=True)
class GuardrailContext:
    call_id: str
    tool_name: str
    arguments: Mapping[str, Any]
    actor: str = "local-user"
    signal: AbortSignal | None = None


@dataclass(frozen=True)
class GuardrailDecision:
    action: Literal["allow", "deny"]
    reason: str = ""
    code: DshToolErrorCode | None = None
    risk: RiskAssessment = field(default_factory=RiskAssessment)
    approval: ApprovalOutcome | None = None
    backing: SandboxBacking = field(default_factory=SandboxBacking)

    @classmethod
    def allow(
        cls,
        *,
        risk: RiskAssessment,
        approval: ApprovalOutcome | None,
        backing: SandboxBacking | None = None,
    ) -> GuardrailDecision:
        return cls(
            "allow",
            risk=risk,
            approval=approval,
            backing=backing or SandboxBacking(),
        )

    @classmethod
    def deny(
        cls,
        code: DshToolErrorCode,
        reason: str,
        *,
        risk: RiskAssessment,
        approval: ApprovalOutcome | None = None,
        backing: SandboxBacking | None = None,
    ) -> GuardrailDecision:
        return cls(
            "deny",
            reason=reason,
            code=code,
            risk=risk,
            approval=approval,
            backing=backing or SandboxBacking(),
        )


class ApprovalDecision(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    FAILED = "failed"


@dataclass(frozen=True)
class ApprovalRecord:
    """Auditable outcome of one guardrail evaluation."""

    record_id: str
    timestamp: str
    actor: str
    call_id: str
    tool_name: str
    arguments: dict[str, Any]
    risk_level: str
    approval_required: bool
    decision: ApprovalDecision
    approval_outcome: str | None
    error_code: str | None
    sandbox_backed: bool
    sandbox_inspected: bool
    sandbox_coverage: str
    sandbox_checked: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "timestamp": self.timestamp,
            "actor": self.actor,
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "risk_level": self.risk_level,
            "approval_required": self.approval_required,
            "decision": self.decision.value,
            "approval_outcome": self.approval_outcome,
            "error_code": self.error_code,
            "sandbox_backed": self.sandbox_backed,
            "sandbox_inspected": self.sandbox_inspected,
            "sandbox_coverage": self.sandbox_coverage,
            "sandbox_checked": list(self.sandbox_checked),
            "reason": self.reason,
        }


ApprovalFailureKind = Literal["timeout", "closed", "disconnected"]

_APPROVAL_FAILURE_CODES: dict[str, DshToolErrorCode] = {
    "timeout": DshToolErrorCode.TOOL_APPROVAL_TIMEOUT,
    "closed": DshToolErrorCode.TOOL_APPROVAL_CLOSED,
    "disconnected": DshToolErrorCode.TOOL_APPROVAL_DISCONNECTED,
}


class ApprovalChannelError(Exception):
    """A channel could not produce a decision; the call must be denied.

    ``kind`` is one of ``timeout`` / ``closed`` / ``disconnected`` and maps to a
    stable error code, so the agent can tell the three cases apart.
    """

    def __init__(self, kind: ApprovalFailureKind, reason: str) -> None:
        self.kind = kind
        self.reason = reason
        super().__init__(reason)


class ApprovalLedger(Protocol):
    def append(self, record: ApprovalRecord) -> None: ...


class InMemoryApprovalLedger:
    """Simple append-only sink; swap for a durable ledger in production."""

    def __init__(self) -> None:
        self.records: list[ApprovalRecord] = []

    def append(self, record: ApprovalRecord) -> None:
        self.records.append(record)


class ApprovalChannel(Protocol):
    def request(self, request: ApprovalRequest) -> object: ...


class Guardrail(Protocol):
    async def evaluate(self, context: GuardrailContext) -> GuardrailDecision: ...


CapabilityProbe = Callable[[str, Mapping[str, Any]], object]
RiskAssessor = Callable[[str, Mapping[str, Any]], object]
PolicyHook = Callable[[GuardrailContext, RiskLevel], object]


@dataclass(frozen=True)
class _CapabilityOutcome:
    error: tuple[DshToolErrorCode, str] | None = None
    backing: SandboxBacking = field(default_factory=SandboxBacking)


@dataclass(frozen=True)
class _RiskOutcome:
    risk: RiskAssessment
    error: tuple[DshToolErrorCode, str] | None = None


class ToolGuardrail:
    """Evaluates capability, approval, and monotonic policy for one call."""

    def __init__(
        self,
        *,
        capability: CapabilityProbe | None,
        approval: ApprovalChannel | None = None,
        assessor: RiskAssessor | None = None,
        policy_hooks: Sequence[PolicyHook] = (),
        ledger: ApprovalLedger | None = None,
        baseline_risk: RiskLevel = RiskLevel.LOW,
        approval_threshold: RiskLevel = RiskLevel.MEDIUM,
        passthrough_exceptions: tuple[type[BaseException], ...] = (),
        require_sandbox_backing: bool = False,
    ) -> None:
        self.capability = capability
        self.approval = approval
        self.assessor = assessor
        self.policy_hooks = tuple(policy_hooks)
        self.ledger: ApprovalLedger = ledger or InMemoryApprovalLedger()
        self.baseline_risk = baseline_risk
        self.approval_threshold = approval_threshold
        # Strict mode: a call that needs approval but was not actually inspected
        # by the sandbox is refused instead of being sent to a human.
        self.require_sandbox_backing = require_sandbox_backing
        # Graph pauses (e.g. langgraph's GraphBubbleUp) must reach the runtime
        # instead of being recorded as a denial.
        self.passthrough_exceptions = tuple(passthrough_exceptions)
        if not self.passthrough_exceptions and approval is not None:
            # 审批通道自带的暂停异常（如 langgraph 的 GraphBubbleUp）必须默认可穿透，
            # 否则 interrupt() 会被当成审批失败并记录为拒绝，HITL 永远无法暂停。
            self.passthrough_exceptions = tuple(getattr(approval, "pause_exceptions", ()) or ())
        self._consumed_calls: set[str] = set()

    async def evaluate(self, context: GuardrailContext) -> GuardrailDecision:
        risk = RiskAssessment(self.baseline_risk)

        capability = await self._check_capability(context)
        backing = capability.backing
        if capability.error is not None:
            return self._deny(
                context,
                capability.error[0],
                capability.error[1],
                risk=risk,
                approval_required=False,
                backing=backing,
            )

        assessment = await self._assess(context)
        risk = assessment.risk
        if assessment.error is not None:
            return self._deny(
                context,
                assessment.error[0],
                assessment.error[1],
                risk=risk,
                approval_required=False,
                backing=backing,
            )

        approval_required = risk.level >= self.approval_threshold
        if self.require_sandbox_backing and approval_required and not backing.backed:
            return self._deny(
                context,
                DshToolErrorCode.TOOL_SANDBOX_BACKING_MISSING,
                f"strict mode refuses calls needing approval without sandbox backing "
                f"(coverage={backing.coverage}"
                + (f", checked={', '.join(backing.checked)}" if backing.checked else "")
                + ")",
                risk=risk,
                approval_required=True,
                backing=backing,
            )

        approval_outcome: ApprovalOutcome | None = None
        if approval_required:
            denied = await self._request_approval(context, risk, backing)
            if isinstance(denied, GuardrailDecision):
                return denied
            approval_outcome = denied
            self._consumed_calls.add(context.call_id)

        policy_reason = await self._run_policy_hooks(context, risk)
        if policy_reason is not None:
            return self._deny(
                context,
                DshToolErrorCode.TOOL_DENIED,
                policy_reason,
                risk=risk,
                approval_outcome=approval_outcome,
                approval_required=approval_required,
                backing=backing,
            )

        return self._allow(
            context,
            risk,
            approval_outcome,
            approval_required=approval_required,
            backing=backing,
        )

    async def _check_capability(
        self,
        context: GuardrailContext,
    ) -> _CapabilityOutcome:
        if self.capability is None:
            return _CapabilityOutcome(
                (
                    DshToolErrorCode.TOOL_CAPABILITY_UNAVAILABLE,
                    "no execution backend is configured; refusing to dispatch",
                )
            )
        try:
            raw = await _resolve(self.capability(context.tool_name, context.arguments))
        except Exception as exc:
            return _CapabilityOutcome(
                (
                    DshToolErrorCode.TOOL_CAPABILITY_UNAVAILABLE,
                    f"capability probe failed: {describe_exception(exc)}",
                )
            )
        backing = SandboxBacking.from_probe(raw)
        if not isinstance(raw, CapabilityDecision):
            return _CapabilityOutcome(
                (
                    DshToolErrorCode.TOOL_CAPABILITY_UNAVAILABLE,
                    "capability probe returned an invalid result; refusing to dispatch",
                ),
                backing,
            )
        if not raw.available:
            reason = raw.reason.strip() or "execution backend is unavailable"
            # A sandbox probe may carry a more precise bridge code (denied vs
            # not assembled). Plain ``CapabilityDecision`` values keep the
            # generic code, so existing probes behave exactly as before.
            bridge_code = getattr(raw, "bridge_code", None)
            code = (
                bridge_code
                if isinstance(bridge_code, DshToolErrorCode)
                else DshToolErrorCode.TOOL_CAPABILITY_UNAVAILABLE
            )
            return _CapabilityOutcome((code, reason), backing)
        return _CapabilityOutcome(None, backing)

    async def _assess(self, context: GuardrailContext) -> _RiskOutcome:
        if self.assessor is None:
            return _RiskOutcome(RiskAssessment(self.baseline_risk))
        try:
            raw = await _resolve(self.assessor(context.tool_name, context.arguments))
        except Exception as exc:
            return _RiskOutcome(
                RiskAssessment(self.baseline_risk),
                (
                    DshToolErrorCode.TOOL_EXECUTION_FAILED,
                    f"risk assessor failed: {describe_exception(exc)}",
                ),
            )
        if not isinstance(raw, RiskAssessment):
            return _RiskOutcome(
                RiskAssessment(self.baseline_risk),
                (
                    DshToolErrorCode.TOOL_EXECUTION_FAILED,
                    "risk assessor returned an invalid assessment",
                ),
            )
        try:
            level = raw.level if isinstance(raw.level, RiskLevel) else RiskLevel(int(raw.level))
        except (TypeError, ValueError):
            return _RiskOutcome(
                RiskAssessment(self.baseline_risk),
                (
                    DshToolErrorCode.TOOL_EXECUTION_FAILED,
                    "risk assessor returned an unknown risk level",
                ),
            )
        risk = RiskAssessment(level, raw.reason.strip())
        if level > self.baseline_risk and not risk.reason:
            return _RiskOutcome(
                risk,
                (
                    DshToolErrorCode.TOOL_RISK_ESCALATION_INVALID,
                    f"risk escalated to {level.name} without a user-visible reason",
                ),
            )
        return _RiskOutcome(risk)

    async def _request_approval(
        self,
        context: GuardrailContext,
        risk: RiskAssessment,
        backing: SandboxBacking,
    ) -> ApprovalOutcome | GuardrailDecision:
        if context.call_id in self._consumed_calls:
            return self._deny(
                context,
                DshToolErrorCode.TOOL_APPROVAL_DENIED,
                "one-time approval for this call was already consumed",
                risk=risk,
                approval_required=True,
                backing=backing,
            )
        if self.approval is None:
            return self._deny(
                context,
                DshToolErrorCode.TOOL_APPROVAL_UNAVAILABLE,
                "no approval channel is configured; refusing to run",
                risk=risk,
                approval_required=True,
                backing=backing,
            )

        request = ApprovalRequest(
            call_id=context.call_id,
            reason=_approval_reason(context.tool_name, risk),
            signal=context.signal,
            tool_name=context.tool_name,
            arguments=dict(context.arguments),
            sandbox_backed=backing.backed,
            sandbox_coverage=backing.coverage,
        )
        try:
            raw = await _resolve(self.approval.request(request))
        except ApprovalChannelError as exc:
            return self._deny(
                context,
                _APPROVAL_FAILURE_CODES.get(
                    exc.kind,
                    DshToolErrorCode.TOOL_APPROVAL_UNAVAILABLE,
                ),
                exc.reason or f"approval {exc.kind}",
                risk=risk,
                approval_required=True,
                failed=True,
                backing=backing,
            )
        except Exception as exc:
            if isinstance(exc, self.passthrough_exceptions):
                raise
            return self._deny(
                context,
                DshToolErrorCode.TOOL_APPROVAL_UNAVAILABLE,
                f"approval channel failed: {describe_exception(exc)}",
                risk=risk,
                approval_required=True,
                failed=True,
                backing=backing,
            )

        try:
            outcome = raw if isinstance(raw, ApprovalOutcome) else ApprovalOutcome(str(raw))
        except ValueError:
            return self._deny(
                context,
                DshToolErrorCode.TOOL_APPROVAL_DENIED,
                "approval channel returned an unknown outcome",
                risk=risk,
                approval_required=True,
                backing=backing,
            )

        if outcome is ApprovalOutcome.ALLOWED_ONCE:
            return outcome
        if outcome is ApprovalOutcome.CANCELLED:
            return self._deny(
                context,
                DshToolErrorCode.TOOL_ABORTED,
                risk.reason or "approval cancelled",
                risk=risk,
                approval_outcome=outcome,
                approval_required=True,
                backing=backing,
            )
        if outcome is ApprovalOutcome.UNAVAILABLE:
            return self._deny(
                context,
                DshToolErrorCode.TOOL_APPROVAL_UNAVAILABLE,
                risk.reason or "approval channel unavailable",
                risk=risk,
                approval_outcome=outcome,
                approval_required=True,
                backing=backing,
            )
        return self._deny(
            context,
            DshToolErrorCode.TOOL_APPROVAL_DENIED,
            risk.reason or "approval rejected",
            risk=risk,
            approval_outcome=outcome,
            approval_required=True,
            backing=backing,
        )

    async def _run_policy_hooks(
        self,
        context: GuardrailContext,
        risk: RiskAssessment,
    ) -> str | None:
        reasons: list[str] = []
        for hook in self.policy_hooks:
            try:
                verdict = await _resolve(hook(context, risk.level))
            except Exception as exc:
                reasons.append(f"policy hook failed: {describe_exception(exc)}")
                continue
            if verdict is None:
                continue
            if isinstance(verdict, str):
                if verdict.strip():
                    reasons.append(verdict.strip())
                continue
            if isinstance(verdict, PolicyVerdict):
                if verdict.allowed:
                    # Monotonic: an allow verdict never loosens anything.
                    continue
                reasons.append(verdict.reason.strip() or "policy hook denied without a reason")
                continue
            reasons.append("policy hook returned an invalid verdict")
        return "; ".join(reasons) if reasons else None

    def _allow(
        self,
        context: GuardrailContext,
        risk: RiskAssessment,
        approval: ApprovalOutcome | None,
        *,
        approval_required: bool,
        backing: SandboxBacking,
    ) -> GuardrailDecision:
        self._record(
            context,
            risk,
            decision=ApprovalDecision.ALLOWED,
            approval_required=approval_required,
            approval=approval,
            error_code=None,
            reason=risk.reason or "allowed",
            backing=backing,
        )
        return GuardrailDecision.allow(risk=risk, approval=approval, backing=backing)

    def _deny(
        self,
        context: GuardrailContext,
        code: DshToolErrorCode,
        reason: str,
        *,
        risk: RiskAssessment,
        approval_required: bool,
        backing: SandboxBacking | None = None,
        approval_outcome: ApprovalOutcome | None = None,
        failed: bool = False,
    ) -> GuardrailDecision:
        backing = backing or SandboxBacking()
        self._record(
            context,
            risk,
            decision=ApprovalDecision.FAILED if failed else ApprovalDecision.DENIED,
            approval_required=approval_required,
            approval=approval_outcome,
            error_code=code.value,
            reason=reason,
            backing=backing,
        )
        return GuardrailDecision.deny(
            code,
            reason,
            risk=risk,
            approval=approval_outcome,
            backing=backing,
        )

    def _record(
        self,
        context: GuardrailContext,
        risk: RiskAssessment,
        *,
        decision: ApprovalDecision,
        approval_required: bool,
        approval: ApprovalOutcome | None,
        error_code: str | None,
        reason: str,
        backing: SandboxBacking,
    ) -> None:
        record = ApprovalRecord(
            record_id=uuid4().hex,
            timestamp=datetime.now(UTC).isoformat(),
            actor=context.actor,
            call_id=context.call_id,
            tool_name=context.tool_name,
            arguments=_arguments_snapshot(context.arguments),
            risk_level=risk.level.name,
            approval_required=approval_required,
            decision=decision,
            approval_outcome=approval.value if approval is not None else None,
            error_code=error_code,
            sandbox_backed=backing.backed,
            sandbox_inspected=backing.inspected,
            sandbox_coverage=backing.coverage,
            sandbox_checked=backing.checked,
            reason=reason,
        )
        with contextlib.suppress(Exception):
            # An audit sink failure must not change the security decision.
            self.ledger.append(record)


def _approval_reason(tool_name: str, risk: RiskAssessment) -> str:
    detail = risk.reason or "requires approval"
    return f"[{risk.level.name}] {tool_name}: {detail}"


def _arguments_snapshot(arguments: Mapping[str, Any]) -> dict[str, Any]:
    try:
        dumped = json.dumps(dict(arguments), ensure_ascii=False, allow_nan=False)
        snapshot = json.loads(dumped)
    except (TypeError, ValueError):
        return {"__unserializable__": True}
    return snapshot if isinstance(snapshot, dict) else {}


async def _resolve(value: object) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


__all__ = [
    "SANDBOX_COVERAGE_COVERED",
    "SANDBOX_COVERAGE_NOT_APPLICABLE",
    "SANDBOX_COVERAGE_UNAVAILABLE",
    "SANDBOX_COVERAGE_UNKNOWN",
    "ApprovalChannel",
    "ApprovalChannelError",
    "ApprovalDecision",
    "ApprovalLedger",
    "ApprovalRecord",
    "CapabilityDecision",
    "CapabilityProbe",
    "Guardrail",
    "GuardrailContext",
    "GuardrailDecision",
    "InMemoryApprovalLedger",
    "PolicyHook",
    "PolicyVerdict",
    "RiskAssessment",
    "RiskAssessor",
    "RiskLevel",
    "SandboxBacking",
    "ToolGuardrail",
]
