"""Connector-instance CRUD, connection probe and OAuth token refresh."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request

from happyclaw.api.deps import current_user, get_server
from happyclaw.api.routers.connectors.common import (
    _apply_connector_visibility,
    _assert_can_manage_connector,
    _connector_service,
    _credentials_preview,
    _custom_name_exists,
    _instance_to_dict,
    _merge_credentials,
    _prepare_credentials,
    _raise_name_taken,
    _resolve_custom_target,
    _schedule_connector_reload,
    _shared_and_visibility,
    _validate_connector_visibility,
)
from happyclaw.api.routers.connectors.schemas import CreateInstanceBody, PatchInstanceBody
from happyclaw.infra.connectors.builder import mcp_server_name
from happyclaw.infra.connectors.catalog import get_catalog_entry
from happyclaw.infra.connectors.custom_mcp import CUSTOM_MCP_KIND, is_custom_mcp_kind
from happyclaw.infra.connectors.default_open import build_instance_config_json
from happyclaw.infra.connectors.gateway.cli_dirs import cleanup_creds_cli_dirs
from happyclaw.infra.connectors.gateway.feishu_user_auth import live_user_auth_preview
from happyclaw.infra.connectors.probe import probe_connector, probe_custom_mcp_server
from happyclaw.infra.db.repos.connectors import ConnectorRepo
from happyclaw.infra.errors import ErrorCode, HappyclawError
from happyclaw.infra.users.groups import RESOURCE_CONNECTOR, GroupAccess
from happyclaw.infra.utils.locale import resolve_request_locale
from happyclaw.infra.utils.ulid import new_ulid

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/connector-instances", summary="List connector instances")
async def list_instances(
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> list[dict[str, Any]]:
    """List the current user's connected accounts (custom MCP expanded per server)."""
    access = GroupAccess(server.services.repos)
    rows = _connector_service(server).list_instances_for_api(user.id)
    for item in rows:
        owner_id = int(item.get("owner_user_id") or user.id)
        owner = server.services.user_repo.get(owner_id)
        item["owner_username"] = owner.username if owner is not None else None
        item["owner_display_name"] = (
            owner.display_name or owner.username if owner is not None else None
        )
        item["can_manage"] = owner_id == user.id
        instance_id = str(item.get("instance_id") or "")
        if instance_id and not instance_id.startswith("custom:"):
            item.update(
                access.visibility(
                    RESOURCE_CONNECTOR,
                    instance_id,
                    shared=bool(item.get("shared")),
                )
            )
    return rows


@router.get("/connector-instances/{instance_id}", summary="Get connector instance")
async def get_instance(
    instance_id: str,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Return one connector instance with config and a redacted credentials preview."""
    repo = server.services.repos.connector_repo
    inst = repo.get(instance_id)
    if inst is None:
        raise HappyclawError(ErrorCode.CONNECTOR_NOT_FOUND, f"instance {instance_id!r} not found")
    _assert_can_manage_connector(inst, user)

    data = _instance_to_dict(inst, access=GroupAccess(server.services.repos))
    config: dict[str, Any] = {}
    if inst.config_json:
        try:
            parsed = json.loads(inst.config_json)
            if isinstance(parsed, dict):
                config = parsed
        except json.JSONDecodeError:
            config = {}
    data["config"] = config
    if inst.has_credentials:
        svc = _connector_service(server)
        creds = svc.decrypt(instance_id)
        data["credentials_preview"] = _credentials_preview(inst.kind, creds)
        if inst.kind == "feishu-cli" and data["credentials_preview"].get("user_auth_configured"):
            live = await asyncio.to_thread(live_user_auth_preview, creds)
            data["credentials_preview"].update(live)
    else:
        data["credentials_preview"] = {}
    return data


@router.post("/connector-instances", status_code=201, summary="Create connector instance")
async def create_instance(
    body: CreateInstanceBody,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Connect a third-party account as a new named instance."""
    if is_custom_mcp_kind(body.kind):
        raise HappyclawError(
            ErrorCode.CONNECTOR_KIND_UNSUPPORTED,
            "use PUT /connectors/custom-mcp for custom MCP servers",
        )
    entry = get_catalog_entry(body.kind)
    if entry is None:
        raise HappyclawError(ErrorCode.CONNECTOR_KIND_UNSUPPORTED, f"unknown kind {body.kind!r}")
    if entry.phase != "available":
        raise HappyclawError(ErrorCode.CONNECTOR_KIND_UNSUPPORTED, f"{body.kind} not available")

    repo = server.services.repos.connector_repo
    svc = _connector_service(server)
    display_name = body.display_name.strip()
    if not display_name:
        raise HappyclawError(ErrorCode.CONNECTOR_INVALID_CREDENTIALS, "display_name is required")
    description = (
        body.description.strip()
        if body.description is not None
        else entry.description.resolve(resolve_request_locale(request))
    )
    if not description:
        raise HappyclawError(ErrorCode.CONNECTOR_INVALID_CREDENTIALS, "description is required")
    if repo.name_exists(user.id, display_name) or _custom_name_exists(svc, user.id, display_name):
        _raise_name_taken(display_name)
    cred_input = dict(body.credentials)

    try:
        cred_payload = await _prepare_credentials(
            body.kind, cred_input, server.services.settings_repo
        )
    except ValueError as exc:
        raise HappyclawError(
            ErrorCode.CONNECTOR_INVALID_CREDENTIALS,
            str(exc),
            details={"reason": str(exc)},
        ) from exc

    instance_id = new_ulid()
    shared, visibility, group_ids = _shared_and_visibility(
        visibility=body.visibility,
        group_ids=body.group_ids,
        shared=body.shared,
    )
    _validate_connector_visibility(server, visibility=visibility, group_ids=group_ids)
    repo.create(
        instance_id=instance_id,
        user_id=user.id,
        kind=body.kind,
        display_name=display_name,
        mcp_server_name=mcp_server_name(body.kind, instance_id),
        shared=shared,
        config_json=build_instance_config_json(
            kind=body.kind,
            default_open=bool(body.default_open),
            email=cred_payload.get("email"),
            description=description,
        ),
    )
    svc.encrypt_and_store(instance_id=instance_id, payload=cred_payload)
    _apply_connector_visibility(server, instance_id, visibility=visibility, group_ids=group_ids)
    server.services.audit_repo.write(
        actor=user.username,
        action="connector.instance.create",
        target=instance_id,
        payload=body.kind,
    )
    inst = repo.get(instance_id)
    assert inst is not None
    _schedule_connector_reload(
        server,
        user.id,
        all_users=shared,
        mail_instance_id=instance_id if body.kind == "agently-cli" else None,
    )
    return _instance_to_dict(inst, access=GroupAccess(server.services.repos))


@router.patch("/connector-instances/{instance_id}", summary="Update connector instance")
async def patch_instance(
    instance_id: str,
    body: PatchInstanceBody,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Edit a connector instance without replacing its identity."""
    custom_target = _resolve_custom_target(instance_id, user=user, server=server)
    if custom_target is not None:
        custom_user_id, synthetic_name = custom_target
        svc = _connector_service(server)
        if body.status is None and body.default_open is None and body.shared is None:
            raise HappyclawError(
                ErrorCode.CONNECTOR_INVALID_CREDENTIALS,
                "status or default_open is required",
            )
        try:
            if body.status is not None:
                status = body.status.strip()
                if status not in ("active", "disabled"):
                    raise HappyclawError(
                        ErrorCode.CONNECTOR_INVALID_CREDENTIALS,
                        "status must be active or disabled",
                    )
                svc.patch_custom_server_enabled(
                    custom_user_id, synthetic_name, enabled=(status == "active")
                )
            if body.default_open is not None:
                svc.patch_custom_server_default_open(
                    custom_user_id, synthetic_name, default_open=bool(body.default_open)
                )
            if body.shared is not None:
                svc.patch_custom_server(custom_user_id, synthetic_name, shared=body.shared)
        except KeyError as exc:
            raise HappyclawError(
                ErrorCode.CONNECTOR_NOT_FOUND, f"instance {instance_id!r} not found"
            ) from exc
        except ValueError as exc:
            raise HappyclawError(ErrorCode.CONNECTOR_INVALID_CREDENTIALS, str(exc)) from exc
        _schedule_connector_reload(server, custom_user_id, all_users=True)
        for item in svc.list_instances_for_api(custom_user_id):
            if item["instance_id"] in {instance_id, f"custom:{synthetic_name}"}:
                return item
        raise HappyclawError(ErrorCode.CONNECTOR_NOT_FOUND, f"instance {instance_id!r} not found")

    repo = server.services.repos.connector_repo
    inst = repo.get(instance_id)
    if inst is None:
        raise HappyclawError(ErrorCode.CONNECTOR_NOT_FOUND, f"instance {instance_id!r} not found")
    _assert_can_manage_connector(inst, user)
    if is_custom_mcp_kind(inst.kind):
        raise HappyclawError(
            ErrorCode.CONNECTOR_KIND_UNSUPPORTED,
            "use PATCH /connectors/custom-mcp/servers/{name} for custom MCP servers",
        )
    if (
        body.status is None
        and body.default_open is None
        and body.display_name is None
        and body.description is None
        and body.credentials is None
        and body.shared is None
        and body.visibility is None
    ):
        raise HappyclawError(
            ErrorCode.CONNECTOR_INVALID_CREDENTIALS,
            "status or default_open is required",
        )
    if body.display_name is not None:
        display_name = body.display_name.strip()
        if not display_name:
            raise HappyclawError(ErrorCode.CONNECTOR_INVALID_CREDENTIALS, "display_name is required")
        svc = _connector_service(server)
        if repo.name_exists(
            inst.user_id, display_name, exclude_instance_id=instance_id
        ) or _custom_name_exists(svc, inst.user_id, display_name):
            _raise_name_taken(display_name)
        repo.update_metadata(instance_id, display_name=display_name)
    if body.visibility is not None or body.shared is not None:
        shared, visibility, group_ids = _shared_and_visibility(
            visibility=body.visibility,
            group_ids=body.group_ids,
            shared=body.shared,
            default_shared=bool(inst.shared),
        )
        _validate_connector_visibility(server, visibility=visibility, group_ids=group_ids)
        repo.update_metadata(instance_id, shared=shared)
        _apply_connector_visibility(server, instance_id, visibility=visibility, group_ids=group_ids)
    if body.credentials is not None:
        svc = _connector_service(server)
        merged = _merge_credentials(svc.decrypt(instance_id), body.credentials, kind=inst.kind)
        try:
            prepared = await _prepare_credentials(inst.kind, merged, server.services.settings_repo)
        except ValueError as exc:
            raise HappyclawError(
                ErrorCode.CONNECTOR_INVALID_CREDENTIALS,
                str(exc),
                details={"reason": str(exc)},
            ) from exc
        svc.encrypt_and_store(instance_id=instance_id, payload=prepared)
    if body.status is not None:
        status = body.status.strip()
        if status not in ("active", "disabled"):
            raise HappyclawError(
                ErrorCode.CONNECTOR_INVALID_CREDENTIALS, "status must be active or disabled"
            )
        repo.update_status(instance_id, status)
    if body.default_open is not None or body.description is not None:
        config = dict(ConnectorRepo.parse_config_json(inst))
        if body.default_open is not None:
            if body.default_open:
                config["default_open"] = True
            else:
                config.pop("default_open", None)
        if body.description is not None:
            description = body.description.strip()
            if not description:
                raise HappyclawError(
                    ErrorCode.CONNECTOR_INVALID_CREDENTIALS,
                    "description is required",
                )
            config["description"] = description
        repo.update_config_json(
            instance_id, json.dumps(config, ensure_ascii=False) if config else None
        )
    inst = repo.get(instance_id)
    assert inst is not None
    refreshed = repo.get(instance_id)
    assert refreshed is not None
    _schedule_connector_reload(
        server,
        refreshed.user_id,
        all_users=refreshed.shared
        or body.shared is True
        or body.shared is False
        or body.visibility is not None,
        mail_instance_id=instance_id if refreshed.kind == "agently-cli" else None,
    )
    return _instance_to_dict(refreshed, access=GroupAccess(server.services.repos))


@router.delete("/connector-instances/{instance_id}", status_code=204, summary="Delete connector")
async def delete_instance(
    instance_id: str,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> None:
    """Disconnect and delete stored credentials for a connector instance."""
    custom_target = _resolve_custom_target(instance_id, user=user, server=server)
    if custom_target is not None:
        custom_user_id, synthetic_name = custom_target
        svc = _connector_service(server)
        servers = dict(svc.get_custom_servers(custom_user_id))
        if synthetic_name not in servers:
            raise HappyclawError(ErrorCode.CONNECTOR_NOT_FOUND, f"instance {instance_id!r} not found")
        del servers[synthetic_name]
        try:
            svc.put_custom_servers(custom_user_id, servers)
        except ValueError as exc:
            raise HappyclawError(ErrorCode.CONNECTOR_INVALID_CREDENTIALS, str(exc)) from exc
        server.services.audit_repo.write(
            actor=user.username,
            action="connector.custom_mcp.delete_server",
            target=synthetic_name,
            payload=CUSTOM_MCP_KIND,
        )
        _schedule_connector_reload(server, custom_user_id, all_users=True)
        return

    repo = server.services.repos.connector_repo
    inst = repo.get(instance_id)
    if inst is None:
        raise HappyclawError(ErrorCode.CONNECTOR_NOT_FOUND, f"instance {instance_id!r} not found")
    _assert_can_manage_connector(inst, user)
    user_id = inst.user_id
    cli_creds: dict[str, Any] | None = None
    if (
        inst.kind in ("feishu-cli", "wecom-cli", "agently-cli", "dingtalk-cli")
        and inst.has_credentials
    ):
        try:
            cli_creds = _connector_service(server).decrypt(instance_id)
        except Exception:
            cli_creds = {"instance_id": instance_id}
        else:
            cli_creds = {**cli_creds, "instance_id": instance_id}
    # Device-login CLIs: cancel a pending login and revoke the grant before deleting.
    if inst.kind in ("agently-cli", "dingtalk-cli"):
        result = await _connector_service(server).agently_auth_for_instance(
            instance_id, inst.user_id, "disconnect", locale=resolve_request_locale(request)
        )
        if result["status"] == "error":
            raise HappyclawError.localized(
                ErrorCode.CONNECTOR_INVALID_CREDENTIALS,
                locale=resolve_request_locale(request),
                details={"reason": result["error"]},
            )
    if inst.kind == "qcc":
        try:
            await _connector_service(server).disconnect_qcc(instance_id)
        except ValueError as exc:
            raise HappyclawError(ErrorCode.CONNECTOR_INVALID_CREDENTIALS, str(exc)) from exc
    elif inst.kind not in ("agently-cli", "dingtalk-cli"):
        repo.delete(instance_id)
        GroupAccess(server.services.repos).clear(RESOURCE_CONNECTOR, instance_id)
    if cli_creds is not None:
        cleanup_creds_cli_dirs(inst.kind, cli_creds)
    _schedule_connector_reload(
        server,
        user_id,
        all_users=inst.shared,
        mail_instance_id=instance_id if inst.kind == "agently-cli" else None,
    )
    server.services.audit_repo.write(
        actor=user.username,
        action="connector.instance.delete",
        target=instance_id,
    )


@router.post("/connector-instances/{instance_id}/test", summary="Test connector")
async def test_instance(
    instance_id: str,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Probe the connector with stored credentials and return success or error details."""
    custom_target = _resolve_custom_target(instance_id, user=user, server=server)
    if custom_target is not None:
        custom_user_id, synthetic_name = custom_target
        svc = _connector_service(server)
        saved = svc.get_custom_servers(custom_user_id)
        raw = saved.get(synthetic_name)
        if not isinstance(raw, dict):
            raise HappyclawError(ErrorCode.CONNECTOR_NOT_FOUND, f"instance {instance_id!r} not found")
        return await probe_custom_mcp_server(dict(raw))

    repo = server.services.repos.connector_repo
    inst = repo.get(instance_id)
    if inst is None:
        raise HappyclawError(ErrorCode.CONNECTOR_NOT_FOUND, f"instance {instance_id!r} not found")
    _assert_can_manage_connector(inst, user)

    entry = get_catalog_entry(inst.kind)
    if entry is None:
        raise HappyclawError(ErrorCode.CONNECTOR_KIND_UNSUPPORTED, inst.kind)

    svc = _connector_service(server)
    creds = await svc.ensure_fresh_credentials(instance_id, inst.kind)
    if not creds:
        raise HappyclawError(ErrorCode.CONNECTOR_INVALID_CREDENTIALS, "missing credentials")
    if inst.kind in {"agently-cli", "ragflow"}:
        creds["_locale"] = resolve_request_locale(request)

    try:
        return await probe_connector(
            entry,
            creds,
            instance_id=instance_id,
            config=server.services.config,
        )
    except Exception as exc:
        logger.exception("connector test failed for %s", instance_id)
        return {"ok": False, "error": str(exc)}


@router.post("/connector-instances/{instance_id}/refresh", summary="Refresh OAuth tokens")
async def refresh_instance(
    instance_id: str,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Refresh expiring OAuth tokens for a connector instance."""
    repo = server.services.repos.connector_repo
    inst = repo.get(instance_id)
    if inst is None:
        raise HappyclawError(ErrorCode.CONNECTOR_NOT_FOUND, f"instance {instance_id!r} not found")
    if inst.user_id != user.id:
        raise HappyclawError(ErrorCode.FORBIDDEN, "not your connector instance")
    svc = _connector_service(server)
    creds = await svc.ensure_fresh_credentials(instance_id, inst.kind)
    return {"ok": True, "expires_at": creds.get("expires_at")}
