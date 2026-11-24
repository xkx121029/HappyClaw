"""User-defined MCP servers: save, patch and probe."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from happyclaw.api.deps import current_user, get_server
from happyclaw.api.routers.connectors.common import (
    _connector_service,
    _raise_name_taken,
    _schedule_connector_reload,
)
from happyclaw.api.routers.connectors.schemas import (
    CustomMcpPutBody,
    CustomMcpServerPatchBody,
    CustomMcpTestBody,
)
from happyclaw.infra.connectors.custom_mcp import (
    CUSTOM_MCP_KIND,
    oauth_configured,
    redact_servers_for_api,
)
from happyclaw.infra.connectors.probe import probe_custom_mcp_server
from happyclaw.infra.connectors.service import ConnectorNameTakenError
from happyclaw.infra.errors import ErrorCode, HappyclawError

router = APIRouter()


@router.get("/connectors/custom-mcp", summary="Get custom MCP servers")
async def get_custom_mcp(
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Return the user's custom MCP server map (langchain-mcp-adapters shape)."""
    servers = _connector_service(server).get_custom_servers_for_api(user.id)
    return {"servers": servers}


@router.put("/connectors/custom-mcp", summary="Save custom MCP servers")
async def put_custom_mcp(
    body: CustomMcpPutBody,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Replace the user's custom MCP servers document and reload agents."""
    svc = _connector_service(server)
    try:
        servers = svc.put_custom_servers(user.id, body.servers)
    except ConnectorNameTakenError as exc:
        _raise_name_taken(str(exc))
    except ValueError as exc:
        raise HappyclawError(ErrorCode.CONNECTOR_INVALID_CREDENTIALS, str(exc)) from exc
    server.services.audit_repo.write(
        actor=user.username,
        action="connector.custom_mcp.save",
        target=CUSTOM_MCP_KIND,
        payload=str(len(servers)),
    )
    _schedule_connector_reload(
        server,
        user.id,
        all_users=any(
            isinstance(spec, dict) and spec.get("shared") is True for spec in servers.values()
        ),
    )
    return {"servers": redact_servers_for_api(servers)}


@router.patch(
    "/connectors/custom-mcp/servers/{server_name}",
    summary="Patch one custom MCP server",
)
async def patch_custom_mcp_server(
    server_name: str,
    body: CustomMcpServerPatchBody,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Update ``enabled`` and/or ``default_open`` for one custom MCP server."""
    svc = _connector_service(server)
    try:
        servers = svc.patch_custom_server(
            user.id,
            server_name,
            enabled=body.enabled,
            default_open=body.default_open,
            shared=body.shared,
        )
    except KeyError as exc:
        raise HappyclawError(
            ErrorCode.CONNECTOR_NOT_FOUND, f"custom MCP server {server_name!r} not found"
        ) from exc
    except ValueError as exc:
        raise HappyclawError(ErrorCode.CONNECTOR_INVALID_CREDENTIALS, str(exc)) from exc
    _schedule_connector_reload(server, user.id, all_users=body.shared is not None)
    return {"servers": redact_servers_for_api(servers)}


@router.post("/connectors/custom-mcp/test", summary="Probe a custom MCP server")
async def test_custom_mcp(
    body: CustomMcpTestBody,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Probe connectivity for one custom MCP server (saved name or inline spec)."""
    svc = _connector_service(server)
    spec: dict[str, Any] | None = None
    if body.server is not None:
        spec = dict(body.server)
    elif body.name:
        saved = svc.get_custom_servers(user.id)
        raw = saved.get(body.name)
        if not isinstance(raw, dict):
            raise HappyclawError(
                ErrorCode.CONNECTOR_NOT_FOUND, f"custom MCP server {body.name!r} not found"
            )
        spec = dict(raw)
    else:
        raise HappyclawError(
            ErrorCode.CONNECTOR_INVALID_CREDENTIALS,
            "provide name or server spec to probe",
        )
    result = await probe_custom_mcp_server(spec)
    if body.name:
        try:
            if result.get("oauth", {}).get("available") and not oauth_configured(spec):
                svc.note_custom_server_oauth_required(user.id, body.name, required=True)
            elif result.get("ok") or not result.get("oauth", {}).get("available"):
                svc.note_custom_server_oauth_required(user.id, body.name, required=False)
        except KeyError:
            pass
    return result
