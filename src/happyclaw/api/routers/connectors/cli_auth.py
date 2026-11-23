"""Host CLI install status plus Feishu / Agent Mail device-code logins."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from happyclaw.api.deps import current_user, get_server, require_permission
from happyclaw.api.routers.connectors.common import _connector_service, _schedule_connector_reload
from happyclaw.api.routers.connectors.schemas import (
    AgentlyAuthResponse,
    FeishuUserAuthCompleteBody,
    FeishuUserAuthStartBody,
)
from happyclaw.infra.connectors.gateway.cli_install import (
    cli_install_status,
    get_cli_install_spec,
    install_connector_cli,
)
from happyclaw.infra.errors import ErrorCode, HappyclawError
from happyclaw.infra.utils.locale import resolve_request_locale

router = APIRouter()

@router.get(
    "/connectors/{kind}/cli-status",
    summary="Host CLI install status for CLI connectors",
)
async def connector_cli_status(
    kind: str,
    user: Any = Depends(current_user),
) -> dict[str, Any]:
    """Report whether the host binary is on PATH (no side effects)."""
    del user
    if get_cli_install_spec(kind) is None:
        raise HappyclawError(
            ErrorCode.CONNECTOR_KIND_UNSUPPORTED,
            f"kind {kind!r} does not support CLI install",
        )
    try:
        return await asyncio.to_thread(cli_install_status, kind)
    except ValueError as exc:
        raise HappyclawError(ErrorCode.CONNECTOR_KIND_UNSUPPORTED, str(exc)) from exc


@router.post(
    "/connectors/{kind}/install-cli",
    summary="Install host CLI for CLI connectors (admin)",
)
async def connector_install_cli(
    kind: str,
    _: Any = Depends(require_permission("connectors")),
) -> dict[str, Any]:
    """Run ``npm install -g`` for the connector CLI on the Octop host (admin only).

    Always returns a structured body (even on failure) including ``install_command``
    and documentation URLs so the UI can guide manual install.
    """
    if get_cli_install_spec(kind) is None:
        raise HappyclawError(
            ErrorCode.CONNECTOR_KIND_UNSUPPORTED,
            f"kind {kind!r} does not support CLI install",
        )
    return await asyncio.to_thread(install_connector_cli, kind)


@router.post(
    "/connectors/feishu-cli/user-auth/start",
    summary="Start Feishu CLI user device-code login",
)
async def feishu_cli_user_auth_start(
    body: FeishuUserAuthStartBody,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Begin OAuth device-code login (no local HTTPS callback required)."""
    del user
    svc = _connector_service(server)
    try:
        return await svc.start_feishu_user_auth(
            app_id=body.app_id,
            app_secret=body.app_secret,
            cli_config_key=body.cli_config_key,
            domains=body.domains,
        )
    except ValueError as exc:
        raise HappyclawError(
            ErrorCode.CONNECTOR_INVALID_CREDENTIALS,
            str(exc),
            details={"reason": str(exc)},
        ) from exc


@router.post(
    "/connectors/feishu-cli/user-auth/complete",
    summary="Complete Feishu CLI user device-code login",
)
async def feishu_cli_user_auth_complete(
    body: FeishuUserAuthCompleteBody,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Finish device-code login and switch default identity to user."""
    del user
    svc = _connector_service(server)
    try:
        return await svc.complete_feishu_user_auth(
            app_id=body.app_id,
            app_secret=body.app_secret,
            device_code=body.device_code,
            cli_config_key=body.cli_config_key or "",
        )
    except ValueError as exc:
        raise HappyclawError(
            ErrorCode.CONNECTOR_INVALID_CREDENTIALS,
            str(exc),
            details={"reason": str(exc)},
        ) from exc


class FeishuUserAuthInstanceCompleteBody(BaseModel):
    device_code: str
    cli_config_key: str | None = None


@router.post(
    "/connector-instances/{instance_id}/agently-auth/start",
    response_model=AgentlyAuthResponse,
    summary="Start CLI device authorization",
    description=(
        "Owner only. Agent Mail or DingTalk CLI instances. "
        "Starts one bounded background login for this saved instance."
    ),
)
async def agently_auth_start(
    instance_id: str,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> AgentlyAuthResponse:
    result = await _connector_service(server).agently_auth_for_instance(
        instance_id, user.id, "start", locale=resolve_request_locale(request)
    )
    return AgentlyAuthResponse(**result)


@router.get(
    "/connector-instances/{instance_id}/agently-auth/status",
    response_model=AgentlyAuthResponse,
    summary="Read CLI authorization status",
    description=(
        "Owner only. Agent Mail or DingTalk CLI instances. "
        "Poll a device login or check stored authorization without exposing tokens."
    ),
)
async def agently_auth_status(
    instance_id: str,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> AgentlyAuthResponse:
    result = await _connector_service(server).agently_auth_for_instance(
        instance_id, user.id, "status", locale=resolve_request_locale(request)
    )
    if result["status"] == "authorized":
        assert server.app_runtime is not None
        await server.app_runtime.cron_manager.resume_mail_watch(instance_id)
    return AgentlyAuthResponse(**result)


@router.post(
    "/connector-instances/{instance_id}/agently-auth/logout",
    response_model=AgentlyAuthResponse,
    summary="Log out of a CLI connector",
    description=(
        "Owner only. Agent Mail or DingTalk CLI instances. "
        "Cancels pending login, clears the CLI grant and attempts revocation."
    ),
)
async def agently_auth_logout(
    instance_id: str,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> AgentlyAuthResponse:
    result = await _connector_service(server).agently_auth_for_instance(
        instance_id, user.id, "logout", locale=resolve_request_locale(request)
    )
    assert server.app_runtime is not None
    await server.app_runtime.cron_manager.stop_mail_watch(instance_id)
    return AgentlyAuthResponse(**result)


@router.post(
    "/connector-instances/{instance_id}/agently-auth/refresh",
    response_model=AgentlyAuthResponse,
    summary="Refresh CLI authorization",
    description=(
        "Owner only. Agent Mail or DingTalk CLI instances. "
        "Refreshes the saved CLI grant and returns sanitized authorization status."
    ),
)
async def agently_auth_refresh(
    instance_id: str,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> AgentlyAuthResponse:
    result = await _connector_service(server).agently_auth_for_instance(
        instance_id, user.id, "refresh", locale=resolve_request_locale(request)
    )
    return AgentlyAuthResponse(**result)


@router.post(
    "/connector-instances/{instance_id}/feishu-user-auth/start",
    summary="Start Feishu user login for an existing connector instance",
)
async def feishu_cli_user_auth_start_instance(
    instance_id: str,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Same as start, but App Secret is read from the stored instance."""
    svc = _connector_service(server)
    try:
        return await svc.start_feishu_user_auth_for_instance(instance_id, user.id)
    except ValueError as exc:
        raise HappyclawError(
            ErrorCode.CONNECTOR_INVALID_CREDENTIALS,
            str(exc),
            details={"reason": str(exc)},
        ) from exc


@router.post(
    "/connector-instances/{instance_id}/feishu-user-auth/complete",
    summary="Complete Feishu user login for an existing connector instance",
)
async def feishu_cli_user_auth_complete_instance(
    instance_id: str,
    body: FeishuUserAuthInstanceCompleteBody,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    svc = _connector_service(server)
    try:
        result = await svc.complete_feishu_user_auth_for_instance(
            instance_id,
            user.id,
            device_code=body.device_code,
            cli_config_key=body.cli_config_key,
        )
    except ValueError as exc:
        raise HappyclawError(
            ErrorCode.CONNECTOR_INVALID_CREDENTIALS,
            str(exc),
            details={"reason": str(exc)},
        ) from exc
    _schedule_connector_reload(server, user.id)
    return result
