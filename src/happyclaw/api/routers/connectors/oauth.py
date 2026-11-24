"""Browser OAuth: start, legacy start, callback and pending polling."""

from __future__ import annotations

import json
import logging
import secrets
from html import escape
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

from happyclaw.api.common.public_base import resolve_public_base
from happyclaw.api.deps import current_user, get_server
from happyclaw.api.routers.connectors.common import (
    _connector_service,
    _is_public_http_uri,
    _schedule_connector_reload,
)
from happyclaw.api.routers.connectors.schemas import OAuthStartBody, OAuthStartLegacyBody
from happyclaw.i18n import tr
from happyclaw.infra.auth.sso.redirect_after import sanitize_redirect_after
from happyclaw.infra.connectors.custom_mcp import CUSTOM_MCP_KIND, oauth_client_from_spec
from happyclaw.infra.connectors.oauth import (
    delete_oauth_ctx,
    exchange_oauth_code,
    load_oauth_ctx,
    oauth_ready_for_kind,
    save_oauth_ctx,
    start_oauth_for_target,
)
from happyclaw.infra.connectors.oauth.registry import (
    oauth_state_kind_for_target,
    oauth_target_requires_https,
)
from happyclaw.infra.connectors.service import ConnectorService
from happyclaw.infra.errors import ErrorCode, HappyclawError
from happyclaw.infra.utils.locale import resolve_request_locale
from happyclaw.infra.utils.ulid import new_ulid

logger = logging.getLogger(__name__)

router = APIRouter()


def _oauth_callback_html(
    request: Request,
    message_key: str,
    *,
    status_code: int = 200,
    **fmt: Any,
) -> HTMLResponse:
    locale = resolve_request_locale(request)
    message = tr(f"connector.oauth.{message_key}", locale, **fmt)
    return HTMLResponse(f"<html><body>{escape(message)}</body></html>", status_code=status_code)


def _resolve_custom_mcp_oauth_target(
    svc: ConnectorService, user_id: int, server_name: str
) -> tuple[str, dict[str, Any]]:
    """MCP URL and saved OAuth client (``{}`` when none) of a custom server."""
    saved = svc.get_custom_servers(user_id)
    raw = saved.get(server_name)
    if not isinstance(raw, dict):
        raise HappyclawError(
            ErrorCode.CONNECTOR_NOT_FOUND,
            f"custom MCP server {server_name!r} not found; save configuration before OAuth",
        )
    if str(raw.get("transport") or "") not in ("streamable_http", "http"):
        raise HappyclawError(
            ErrorCode.CONNECTOR_KIND_UNSUPPORTED,
            "OAuth is only supported for streamable HTTP custom MCP servers",
        )
    mcp_url = str(raw.get("url") or "").strip()
    if not mcp_url:
        raise HappyclawError(ErrorCode.CONNECTOR_INVALID_CREDENTIALS, "server url is required")
    return mcp_url, oauth_client_from_spec(raw)


async def _begin_oauth_flow(
    *,
    request: Request,
    user: Any,
    server: Any,
    target: dict[str, Any],
    redirect_after: str | None,
) -> dict[str, Any]:
    target_type = str(target.get("type") or "").strip()
    if target_type == "catalog":
        kind = str(target.get("kind") or "").strip()
        if not oauth_ready_for_kind(kind, server.services.settings_repo):
            raise HappyclawError(
                ErrorCode.CONNECTOR_INVALID_CREDENTIALS,
                f"OAuth for {kind} is not available",
            )
    elif target_type != "custom_mcp":
        raise HappyclawError(ErrorCode.CONNECTOR_INVALID_CREDENTIALS, "unsupported oauth target")

    state = secrets.token_urlsafe(24)
    state_id = new_ulid()
    base = resolve_public_base(request)
    redirect_uri = f"{base}/api/connectors/oauth/callback"
    if oauth_target_requires_https(target) and _is_public_http_uri(redirect_uri):
        label = str(target.get("kind") or target.get("server_name") or "MCP")
        raise HappyclawError(
            ErrorCode.CONNECTOR_OAUTH_HTTPS_REQUIRED,
            f"{label} OAuth callbacks require HTTPS for non-loopback addresses",
        )

    mcp_url: str | None = None
    oauth_client: dict[str, Any] | None = None
    if target_type == "custom_mcp":
        server_name = str(target.get("server_name") or "").strip()
        if not server_name:
            raise HappyclawError(
                ErrorCode.CONNECTOR_INVALID_CREDENTIALS,
                "custom_mcp target requires server_name",
            )
        mcp_url, oauth_client = _resolve_custom_mcp_oauth_target(
            _connector_service(server), user.id, server_name
        )

    try:
        authorize_url, verifier, ctx = await start_oauth_for_target(
            target=target,
            redirect_uri=redirect_uri,
            state=state,
            settings_repo=server.services.settings_repo,
            mcp_url=mcp_url,
            oauth_client=oauth_client,
        )
    except ValueError as exc:
        raise HappyclawError(ErrorCode.CONNECTOR_INVALID_CREDENTIALS, str(exc)) from exc
    except Exception as exc:
        logger.exception("oauth start failed for target %s", target)
        raise HappyclawError(ErrorCode.CONNECTOR_INVALID_CREDENTIALS, str(exc)) from exc

    server.services.repos.connector_repo.create_oauth_state(
        state_id=state_id,
        state=state,
        user_id=user.id,
        kind=oauth_state_kind_for_target(target),
        code_verifier=verifier,
        redirect_after=redirect_after,
    )
    save_oauth_ctx(server.services.settings_repo, state_id, ctx)
    return {"authorize_url": authorize_url, "state_id": state_id}


@router.post("/connectors/oauth/start", summary="Start OAuth flow (unified)")
async def oauth_start_unified(
    body: OAuthStartBody,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Begin browser OAuth for a catalog connector or custom MCP server."""
    if not body.target or not isinstance(body.target, dict):
        raise HappyclawError(ErrorCode.CONNECTOR_INVALID_CREDENTIALS, "oauth target is required")
    return await _begin_oauth_flow(
        request=request,
        user=user,
        server=server,
        target=body.target,
        redirect_after=body.redirect_after,
    )


@router.post("/connectors/oauth/{kind}/start", summary="Start OAuth flow (legacy)")
async def oauth_start_legacy(
    kind: str,
    body: OAuthStartLegacyBody,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Legacy catalog-only alias for :func:`oauth_start_unified`."""
    return await _begin_oauth_flow(
        request=request,
        user=user,
        server=server,
        target={"type": "catalog", "kind": kind},
        redirect_after=body.redirect_after,
    )


@router.get("/connectors/oauth/callback", summary="OAuth callback")
async def oauth_callback(
    request: Request,
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    server: Any = Depends(get_server),
) -> HTMLResponse:
    """OAuth redirect target. Exchanges the code and stores credentials. No JWT required."""
    if error:
        return _oauth_callback_html(
            request,
            "callback_auth_failed",
            status_code=400,
            error=error,
        )
    if not code or not state:
        return _oauth_callback_html(
            request,
            "callback_missing_params",
            status_code=400,
        )

    repo = server.services.repos.connector_repo
    row = repo.consume_oauth_state(state)
    if row is None:
        return _oauth_callback_html(
            request,
            "callback_invalid_state",
            status_code=400,
        )

    base = resolve_public_base(request)
    redirect_uri = f"{base}/api/connectors/oauth/callback"

    try:
        tokens = await exchange_oauth_code(
            kind=row.kind,
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=row.code_verifier,
            settings_repo=server.services.settings_repo,
            state_id=row.state_id,
        )
        ctx = load_oauth_ctx(server.services.settings_repo, row.state_id)
        if ctx.get("client_id"):
            tokens["oauth_client_id"] = ctx["client_id"]
        if ctx.get("client_secret"):
            tokens["oauth_client_secret"] = ctx["client_secret"]
        if ctx.get("token_endpoint"):
            tokens["oauth_token_endpoint"] = ctx["token_endpoint"]
        delete_oauth_ctx(server.services.settings_repo, row.state_id)
    except Exception as exc:
        logger.exception("oauth callback failed for %s", row.kind)
        return _oauth_callback_html(
            request,
            "callback_token_exchange_failed",
            status_code=400,
            detail=str(exc),
        )

    pending_payload: dict[str, Any] = {
        "user_id": row.user_id,
        "kind": row.kind,
        "tokens": tokens,
    }
    if row.kind == CUSTOM_MCP_KIND:
        server_name = str(ctx.get("server_name") or "")
        issuer = str(ctx.get("issuer") or "")
        resource = str(ctx.get("resource") or "").strip() or None
        try:
            svc = _connector_service(server)
            svc.apply_custom_server_oauth(
                row.user_id,
                server_name,
                tokens,
                issuer=issuer,
                resource=resource,
            )
            _schedule_connector_reload(server, row.user_id)
            pending_payload["server_name"] = server_name
            pending_payload["applied"] = True
        except Exception as exc:
            logger.exception("custom MCP oauth apply failed")
            return _oauth_callback_html(
                request,
                "callback_save_failed",
                status_code=400,
                detail=str(exc),
            )

    # Store tokens in a short-lived settings key for frontend pickup, or auto-create instance.
    pending_key = f"connector.oauth.pending.{row.state_id}"
    server.services.settings_repo.set(
        pending_key,
        json.dumps(pending_payload),
    )
    redirect = urlsplit(sanitize_redirect_after(row.redirect_after, default="/connectors"))
    query = [
        (key, value)
        for key, value in parse_qsl(redirect.query, keep_blank_values=True)
        if key != "oauth_state"
    ]
    query.append(("oauth_state", row.state_id))
    redirect_target = redirect._replace(query=urlencode(query)).geturl()
    locale = resolve_request_locale(request)
    success_message = tr("connector.oauth.callback_success", locale)
    # JSON-encode for the JS string literal (quotes/backslashes/newlines) and
    # escape "<" so a stored "</script>" cannot terminate the script element.
    target = json.dumps(redirect_target).replace("<", "\\u003c")
    html = f"""<!DOCTYPE html><html><body>
<script>
  if (window.opener) {{
    window.opener.postMessage({{ type: 'octop:connector-oauth', state_id: {json.dumps(row.state_id)} }}, window.location.origin);
    window.close();
  }} else {{
    window.location.href = {target};
  }}
</script>
<p>{escape(success_message)}</p>
</body></html>"""
    return HTMLResponse(html)


@router.get("/connectors/oauth/pending/{state_id}", summary="Poll OAuth result")
async def oauth_pending(
    state_id: str,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Poll after OAuth redirect until credentials are ready for instance creation."""
    key = f"connector.oauth.pending.{state_id}"
    raw = server.services.settings_repo.get(key)
    if not raw:
        raise HappyclawError(ErrorCode.NOT_FOUND, "pending oauth not found")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HappyclawError(ErrorCode.INTERNAL_ERROR, "corrupt pending oauth") from exc
    if int(data.get("user_id") or 0) != user.id:
        raise HappyclawError(ErrorCode.FORBIDDEN, "not your oauth session")
    server.services.settings_repo.delete(key)
    return {
        "kind": data.get("kind"),
        "tokens": data.get("tokens") or {},
        "server_name": data.get("server_name"),
        "applied": data.get("applied"),
    }
