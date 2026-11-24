"""Stable provider-neutral failure codes and error classification.

Routing decisions read ``ProviderFailure.code`` only; message text is
diagnostic. HTTP classification lives here so every adapter reports the same
code for the same status.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

__all__ = [
    "FailureCode",
    "ProviderFailure",
    "TransportError",
    "classify_http_failure",
    "failure_from_error_payload",
    "is_context_overflow_text",
    "is_quota_exceeded_text",
]


class FailureCode:
    """Namespace for failure code strings (not an enum: adapters may add one)."""

    RATE_LIMIT = "RATE_LIMIT"
    CONTEXT_WINDOW_EXCEEDED = "CONTEXT_WINDOW_EXCEEDED"
    INVALID_REQUEST = "INVALID_REQUEST"
    AUTHENTICATION = "AUTHENTICATION"
    INVALID_CREDENTIAL = "INVALID_CREDENTIAL"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    SERVER = "SERVER"
    TIMEOUT = "TIMEOUT"
    TRANSPORT = "TRANSPORT"
    EMPTY_RESPONSE = "EMPTY_RESPONSE"
    COMPRESSION_INSUFFICIENT = "COMPRESSION_INSUFFICIENT"
    CANCELLED = "CANCELLED"
    STEP_COMMITTED = "STEP_COMMITTED"
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"
    UNKNOWN = "UNKNOWN"


_CONTEXT_OVERFLOW = re.compile(
    r"context[\s_-](?:length|window)[\s_-]*(?:exceed|overflow|limit)"
    r"|maximum\s+(?:allowed\s+)?context\s+(?:length|window)"
    r"|(?:input|prompt|request|messages?)\s+(?:is\s+|are\s+)?too\s+(?:long|large)"
    r"\s+for\s+(?:this|the)\s+model"
    r"|exceed(?:s|ed)?\s+(?:the\s+)?(?:model(?:'s)?\s+)?context"
    r"|too\s+many\s+tokens",
    re.IGNORECASE | re.DOTALL,
)

_QUOTA_EXCEEDED = re.compile(
    r"insufficient[\s_-]+(?:quota|balance|credits?)"
    r"|(?:quota|usage[\s_-]+limit)[\s_-]+(?:exceeded|exhausted|reached)"
    r"|(?:balance|credits?)[\s_-]+(?:exhausted|depleted)"
    r"|out[\s_-]+of[\s_-]+(?:credits?|budget)",
    re.IGNORECASE,
)

_AUTH = re.compile(
    r"invalid[\s_-]+(?:api[\s_-]?key|token|credential)"
    r"|unauthorized|authentication\s+failed|incorrect\s+api[\s_-]?key",
    re.IGNORECASE,
)


class ProviderFailure(Exception):
    """One model-request failure with a stable, routable code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int | None = None,
        retry_after_s: float | None = None,
        request_id: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.retry_after_s = retry_after_s
        self.request_id = request_id
        self.details: dict[str, Any] = dict(details or {})

    def with_attempts(self, attempts: int) -> ProviderFailure:
        """Return a copy that names how many attempts the budget allowed."""
        details = dict(self.details)
        details["attempts"] = attempts
        return ProviderFailure(
            self.code,
            f"{self.message} (retry budget exhausted after {attempts} attempts)",
            status=self.status,
            retry_after_s=self.retry_after_s,
            request_id=self.request_id,
            details=details,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "status": self.status,
            "retry_after_s": self.retry_after_s,
            "request_id": self.request_id,
            "details": dict(self.details),
        }

    def __str__(self) -> str:
        return self.message


class TransportError(ProviderFailure):
    """A transport-level failure (HTTP status, socket, timeout)."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        retry_after_s: float | None = None,
        request_id: str | None = None,
        body: str | None = None,
    ) -> None:
        classified = classify_http_failure(
            status,
            body if body is not None else message,
            retry_after_s=retry_after_s,
            request_id=request_id,
        )
        super().__init__(
            classified.code,
            message,
            status=status,
            retry_after_s=retry_after_s,
            request_id=request_id,
        )
        if body:
            self.details["body"] = body[:2000]


def is_context_overflow_text(text: str) -> bool:
    return _CONTEXT_OVERFLOW.search(text or "") is not None


def is_quota_exceeded_text(text: str) -> bool:
    return _QUOTA_EXCEEDED.search(text or "") is not None


def classify_http_failure(
    status: int | None,
    body: str = "",
    *,
    retry_after_s: float | None = None,
    request_id: str | None = None,
) -> ProviderFailure:
    """Map one HTTP failure to a provider-neutral code.

    Order matters: a 429 that mentions quota is still a rate limit today, but
    quota wording wins on 402/403 because retrying cannot fix an empty balance.
    """
    text = body or ""
    if status == 429:
        code = (
            FailureCode.QUOTA_EXCEEDED if is_quota_exceeded_text(text) else FailureCode.RATE_LIMIT
        )
    elif status in (401, 403):
        code = FailureCode.AUTHENTICATION
    elif status == 402 or is_quota_exceeded_text(text):
        code = FailureCode.QUOTA_EXCEEDED
    elif status in (408, 504):
        code = FailureCode.TIMEOUT
    elif status is not None and 500 <= status <= 599:
        code = FailureCode.SERVER
    elif is_context_overflow_text(text):
        code = FailureCode.CONTEXT_WINDOW_EXCEEDED
    elif status in (400, 404, 409, 413, 415, 422):
        code = FailureCode.INVALID_CREDENTIAL if _AUTH.search(text) else FailureCode.INVALID_REQUEST
    else:
        code = FailureCode.UNKNOWN
    return ProviderFailure(
        code,
        f"provider request failed{f' with HTTP {status}' if status is not None else ''}",
        status=status,
        retry_after_s=retry_after_s,
        request_id=request_id,
    )


def failure_from_error_payload(
    payload: Mapping[str, Any],
    *,
    status: int | None = None,
    retry_after_s: float | None = None,
) -> ProviderFailure:
    """Build a failure from a provider's in-band JSON error object."""
    error = payload.get("error")
    if isinstance(error, Mapping):
        message = str(error.get("message") or error.get("detail") or error)
        code = str(error.get("code") or error.get("type") or "")
    else:
        message = str(payload.get("message") or payload.get("detail") or error or payload)
        code = str(payload.get("code") or payload.get("type") or "")
    if is_context_overflow_text(message):
        failure_code = FailureCode.CONTEXT_WINDOW_EXCEEDED
    elif is_quota_exceeded_text(message):
        failure_code = FailureCode.QUOTA_EXCEEDED
    elif status is not None:
        failure_code = classify_http_failure(status, message).code
    elif _AUTH.search(message):
        failure_code = FailureCode.AUTHENTICATION
    else:
        failure_code = FailureCode.UNKNOWN
    return ProviderFailure(
        failure_code,
        message,
        status=status,
        retry_after_s=retry_after_s,
        details={"provider_code": code} if code else None,
    )
