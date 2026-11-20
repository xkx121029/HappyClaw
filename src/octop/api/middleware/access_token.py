"""Optional shared-secret gate for phones and cross-origin dashboards.

HappyClaw runs for one local owner and normally trusts loopback access alone.
Once the HTTP surface is bound beyond ``127.0.0.1`` (or a dashboard hosted on
another origin starts calling it), that trust no longer holds. Setting
``OCTOP_ACCESS_TOKEN`` — or ``access_token`` in ``config.json`` — turns this
gate on. An empty/absent secret keeps the historical no-auth behaviour.

Clients may present the secret as:

* ``X-Octop-Token: <secret>`` — the dashboard's phone client.
* ``Authorization: Bearer <secret>`` — curl and simple scripts.
* ``?octop_token=<secret>`` — browser WebSockets, which cannot set headers.

``/api/health`` stays public: a client must be able to probe an address before
it has anywhere to store a credential.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import parse_qs

from octop.i18n import tr
from octop.infra.utils.locale import normalize_locale

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]

TOKEN_HEADER = "X-Octop-Token"
TOKEN_HEADER_BYTES = b"x-octop-token"
TOKEN_QUERY_KEY = "octop_token"

# Reachable without a credential: liveness plus the read-only API docs.
_PUBLIC_PATHS = frozenset({"/api/health", "/api/docs", "/api/openapi.json"})

# 手机配对必须能在没有共享密钥时完成：手机只可能知道地址，还不知道密钥。
# 请求/轮询/审批页各自带一次性凭据，设备 WebSocket 用批准后下发的设备令牌。
_CONNECTOR_PUBLIC_PREFIXES = ("/api/connector/pair/request", "/api/connector/ws")
_CONNECTOR_PUBLIC_SUFFIXES = ("/review", "/approve", "/reject", "/cancel")


def _connector_public(path: str) -> bool:
    if path.startswith(_CONNECTOR_PUBLIC_PREFIXES):
        return True
    return path.startswith("/api/connector/pair/") and path.endswith(_CONNECTOR_PUBLIC_SUFFIXES)


_INSTALL_ATTR = "_octop_access_token_installed"


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1").strip()
    return None


def _bearer_token(scope: Scope) -> str | None:
    raw = _header(scope, b"authorization")
    if not raw or not raw.lower().startswith("bearer "):
        return None
    return raw[len("bearer ") :].strip() or None


def _query_token(scope: Scope) -> str | None:
    raw = scope.get("query_string", b"")
    if not raw:
        return None
    values = parse_qs(raw.decode("latin-1")).get(TOKEN_QUERY_KEY)
    if not values:
        return None
    return values[0].strip() or None


def presented_token(scope: Scope) -> str | None:
    """Credential the caller supplied, whichever transport it used."""
    return _header(scope, TOKEN_HEADER_BYTES) or _bearer_token(scope) or _query_token(scope)


def _request_locale(scope: Scope) -> str:
    raw = _header(scope, b"accept-language")
    if not raw:
        return "zh"
    first = raw.split(",")[0].strip().split(";")[0]
    return normalize_locale(first)


class AccessTokenMiddleware:
    """Reject unauthenticated API traffic when a shared secret is configured."""

    def __init__(self, app: Any, token: str) -> None:
        self.app = app
        self._token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path") or "")
        if not path.startswith("/api/") or path in _PUBLIC_PATHS or _connector_public(path):
            await self.app(scope, receive, send)
            return
        # CORS preflights never carry the credential; let CORSMiddleware answer.
        if scope["type"] == "http" and scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        provided = presented_token(scope)
        if provided is not None and secrets.compare_digest(provided, self._token):
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return

        locale = _request_locale(scope)
        code = "ACCESS_TOKEN_INVALID" if provided else "ACCESS_TOKEN_REQUIRED"
        message_key = "accessToken.invalid" if provided else "accessToken.required"
        body = json.dumps(
            {
                "ok": False,
                "code": code,
                "message": tr(message_key, locale),
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode()),
                    (b"www-authenticate", b'Bearer realm="octop"'),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def install(app: Any, server: Any) -> None:
    """Install the gate when the running config carries a secret."""
    if getattr(app, _INSTALL_ATTR, False):
        return
    setattr(app, _INSTALL_ATTR, True)

    cfg = server.services.config if server.services is not None else getattr(server, "config", None)
    token = (getattr(cfg, "access_token", None) or "").strip()
    if not token:
        return
    app.add_middleware(AccessTokenMiddleware, token=token)
