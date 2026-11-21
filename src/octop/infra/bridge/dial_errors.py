"""Translate WebSocket handshake rejections into bridge errors."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode

from octop.infra.bridge.connections import (
    MAX_CONNECTIONS_PER_USER,
)
from octop.infra.errors import ErrorCode, OctopError

_DIAL_ERROR_PREFIX = "octop:apiErrors."

_PERMANENT_DIAL_CODES = frozenset(
    {
        ErrorCode.BRIDGE_SELF_CONNECT,
        ErrorCode.BRIDGE_PEER_FORBIDDEN,
        ErrorCode.BRIDGE_PEER_CONNECTION_OWNED,
        ErrorCode.BRIDGE_CONNECTION_LIMIT,
        ErrorCode.BRIDGE_AUTH_FAILED,
    }
)


def _handshake_http_status(exc: BaseException) -> int | None:
    """HTTP status from a WebSocket client handshake rejection, if any."""
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def _close_frame(exc: BaseException) -> Any:
    return getattr(exc, "rcvd", None) or getattr(exc, "sent", None)


def _close_code(exc: BaseException) -> int | None:
    frame = _close_frame(exc)
    code = getattr(frame, "code", None)
    return code if isinstance(code, int) else None


def _close_reason(exc: BaseException) -> str:
    frame = _close_frame(exc)
    reason = getattr(frame, "reason", None)
    if isinstance(reason, bytes):
        reason = reason.decode("utf-8", errors="replace")
    return str(reason or "").strip()


def bridge_failure_from_dial(exc: BaseException) -> OctopError:
    """Map a peer WebSocket close into a user-facing bridge error.

    The raw ``websockets`` text (``received 4003 (private use) ...``) is not
    something to show in the dashboard.
    """
    reason = _close_reason(exc).lower()
    code = _close_code(exc)
    if code == 4004 or "self connect" in reason:
        return OctopError(
            ErrorCode.BRIDGE_SELF_CONNECT,
            "cannot link this HappyClaw instance to itself",
        )
    if code == 4003 and "permission" in reason:
        return OctopError(
            ErrorCode.BRIDGE_PEER_FORBIDDEN,
            "peer account lacks cloud collab permission",
        )
    if code == 4003 and "owned by another" in reason:
        return OctopError(
            ErrorCode.BRIDGE_PEER_CONNECTION_OWNED,
            "connection owned by another user on the peer",
        )
    if code == 4008 or "connection limit" in reason:
        return OctopError(
            ErrorCode.BRIDGE_CONNECTION_LIMIT,
            f"at most {MAX_CONNECTIONS_PER_USER} cloud collab connections",
            details={"limit": MAX_CONNECTIONS_PER_USER},
        )
    if code == 4001:
        return OctopError(ErrorCode.BRIDGE_AUTH_FAILED, "peer rejected credentials")
    return OctopError(ErrorCode.BRIDGE_PEER_UNREACHABLE, _annotate_bridge_dial_error(exc))


def dial_error_note(exc: BaseException) -> str:
    """Persist a bridge dial failure. Known cases use an ``octop:`` i18n key.

    Interpolation values (for example the connection ``limit``) ride in the
    query so the dashboard and the API toast can format the same sentence.
    """
    failure = bridge_failure_from_dial(exc)
    if failure.code is not ErrorCode.BRIDGE_PEER_UNREACHABLE:
        note = f"{_DIAL_ERROR_PREFIX}{failure.code.value}"
        if failure.details:
            note = f"{note}?{urlencode(failure.details)}"
        return note
    reason = _close_reason(exc)
    if reason:
        return reason
    return _annotate_bridge_dial_error(exc)


def error_from_dial_note(note: str | None) -> OctopError | None:
    text = (note or "").strip()
    if not text.startswith(_DIAL_ERROR_PREFIX):
        return None
    body = text[len(_DIAL_ERROR_PREFIX) :]
    name, _, query = body.partition("?")
    try:
        code = ErrorCode(name)
    except ValueError:
        return None
    details: dict[str, Any] = {}
    for key, value in parse_qsl(query, keep_blank_values=False):
        details[key] = int(value) if key == "limit" and value.isdigit() else value
    return OctopError(code, name, details=details)


def _should_refresh_peer_token(exc: BaseException) -> bool:
    """True when the peer refused the socket before hello — usually a bad token.

    Uvicorn turns ``websocket.close()`` before ``accept()`` into HTTP 403 with
    an empty body. That is not evidence the ``/api/bridge/ws`` route is missing.
    """
    if _handshake_http_status(exc) in {401, 403}:
        return True
    return _close_code(exc) == 4001


def _annotate_bridge_dial_error(exc: BaseException) -> str:
    detail = str(exc)
    status = _handshake_http_status(exc)
    if status == 404:
        return f"{detail}; peer may not support Bridge yet (needs HappyClaw with /api/bridge/ws)"
    if status == 403:
        return (
            f"{detail}; the peer refused the WebSocket handshake. "
            "That is a rejected token or a proxy, not a missing /api/bridge/ws route."
        )
    return detail
