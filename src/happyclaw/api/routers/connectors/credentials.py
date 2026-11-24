"""Credential probe and pasted auth-code exchange (no persisted instance)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request

from happyclaw.api.deps import current_user, get_server
from happyclaw.api.routers.connectors.common import _prepare_credentials
from happyclaw.api.routers.connectors.schemas import ExchangeAuthCodeBody, TestCredentialsBody
from happyclaw.infra.connectors.catalog import get_catalog_entry
from happyclaw.infra.connectors.oauth import auth_info_for_kind, exchange_pasted_auth_code
from happyclaw.infra.connectors.probe import prepare_probe_credentials, probe_connector
from happyclaw.infra.errors import ErrorCode, HappyclawError
from happyclaw.infra.utils.locale import resolve_request_locale

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/connectors/test-credentials", summary="Test credentials")
async def test_credentials(
    body: TestCredentialsBody,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Validate credentials before creating an instance (no persistence)."""
    del user
    entry = get_catalog_entry(body.kind)
    if entry is None:
        raise HappyclawError(ErrorCode.CONNECTOR_KIND_UNSUPPORTED, f"unknown kind {body.kind!r}")
    if entry.phase != "available":
        raise HappyclawError(ErrorCode.CONNECTOR_KIND_UNSUPPORTED, f"{body.kind} not available")
    try:
        cred_payload = await prepare_probe_credentials(
            body.kind,
            body.credentials,
            full_prepare=lambda k, c: _prepare_credentials(k, c, server.services.settings_repo),
        )
    except ValueError as exc:
        raise HappyclawError(
            ErrorCode.CONNECTOR_INVALID_CREDENTIALS,
            str(exc),
            details={"reason": str(exc)},
        ) from exc
    if body.kind in {"agently-cli", "ragflow"}:
        cred_payload["_locale"] = resolve_request_locale(request)
    try:
        return await probe_connector(
            entry,
            cred_payload,
            instance_id="probe",
            config=server.services.config,
        )
    except Exception as exc:
        logger.exception("connector credential test failed for %s", body.kind)
        return {"ok": False, "error": str(exc)}


@router.get("/connectors/auth/{kind}/info", summary="Connector auth info")
async def auth_info(
    kind: str,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, str | None]:
    """Return auth flow metadata (OAuth URLs, required fields) for a connector kind."""
    del user
    if get_catalog_entry(kind) is None:
        raise HappyclawError(ErrorCode.CONNECTOR_KIND_UNSUPPORTED, f"unknown kind {kind!r}")
    info = auth_info_for_kind(
        kind, server.services.settings_repo, locale=resolve_request_locale(request)
    )
    return info


@router.get("/connectors/auth/{kind}/authorize-url", summary="OAuth authorize URL")
async def auth_authorize_url(
    kind: str,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, str | None]:
    """Build the provider authorization URL for manual or embedded OAuth."""
    del user
    if get_catalog_entry(kind) is None:
        raise HappyclawError(ErrorCode.CONNECTOR_KIND_UNSUPPORTED, f"unknown kind {kind!r}")
    info = auth_info_for_kind(kind, server.services.settings_repo)
    return {"authorize_url": info.get("authorize_url")}


@router.post("/connectors/auth/{kind}/exchange-code", summary="Exchange auth code")
async def auth_exchange_code(
    kind: str,
    body: ExchangeAuthCodeBody,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Exchange a pasted authorization code for connector credentials (device/OOB flow)."""
    del user
    entry = get_catalog_entry(kind)
    if entry is None:
        raise HappyclawError(ErrorCode.CONNECTOR_KIND_UNSUPPORTED, f"unknown kind {kind!r}")
    if entry.auth_kind != "auth_code":
        raise HappyclawError(ErrorCode.CONNECTOR_KIND_UNSUPPORTED, f"{kind} does not use auth code")
    try:
        extra: dict[str, Any] = {}
        if body.bkn:
            extra["bkn"] = body.bkn
        if body.knowledge_base_id:
            extra["knowledge_base_id"] = body.knowledge_base_id
        tokens = await exchange_pasted_auth_code(
            kind=kind,
            code=body.code,
            settings_repo=server.services.settings_repo,
            extra=extra or None,
        )
    except ValueError as exc:
        raise HappyclawError(ErrorCode.CONNECTOR_INVALID_CREDENTIALS, str(exc)) from exc
    return {"credentials": tokens}
