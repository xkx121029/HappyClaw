"""Turning market exceptions into payloads / OctopErrors."""

from __future__ import annotations

from typing import Any

from octop.infra.errors import ErrorCode, OctopError


def _market_error_payload(exc: Exception) -> dict[str, Any]:
    """Structured market failure for the UI: stable code + original details."""

    from octop.infra.plugins.market.errors import IndexFormatError

    details = dict(getattr(exc, "details", {}) or {})
    code: Any = "PLUGIN_MANIFEST_INVALID"
    if not isinstance(exc, IndexFormatError):
        raw_code = getattr(exc, "code", None)
        code = getattr(raw_code, "value", raw_code)
    return {
        "code": str(details.get("market_code") or code or "PLUGIN_MARKET_UNAVAILABLE"),
        "message": str(exc),
        "details": details,
    }


def _market_octop_error(exc: Exception) -> OctopError:
    """Wrap a market exception without losing its code, path or dependents."""

    details = dict(getattr(exc, "details", {}) or {})
    raw_code = getattr(exc, "code", None)
    code = getattr(raw_code, "value", raw_code)
    if code:
        details.setdefault("market_code", str(code))
    reason = str(exc)
    path = details.get("path")
    if path and str(path) not in reason:
        reason = f"{reason}（{path}）"
    return OctopError(ErrorCode.PLUGIN_INSTALL_FAILED, reason, details=details)
