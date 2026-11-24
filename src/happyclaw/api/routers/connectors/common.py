"""Shared connector helpers: instance serialisation, visibility and credentials."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlparse

from happyclaw.infra.connectors.builder import (
    normalize_weiyun_mcp_token,
    validate_create_credentials,
)
from happyclaw.infra.connectors.catalog import get_catalog_entry
from happyclaw.infra.connectors.custom_mcp import (
    CUSTOM_MCP_KIND,
    is_custom_mcp_kind,
    parse_synthetic_instance_id,
)
from happyclaw.infra.connectors.default_open import read_default_open
from happyclaw.infra.connectors.oauth import exchange_pasted_auth_code
from happyclaw.infra.connectors.service import ConnectorService
from happyclaw.infra.db.repos.connectors import ConnectorRepo
from happyclaw.infra.errors import ErrorCode, HappyclawError
from happyclaw.infra.users.groups import CONNECTOR_FEATURE_KEY, RESOURCE_CONNECTOR, GroupAccess

logger = logging.getLogger(__name__)


def _connector_service(server: Any) -> ConnectorService:
    return ConnectorService(
        repo=server.services.repos.connector_repo,
        secret_repo=server.services.secret_repo,
        settings_repo=server.services.settings_repo,
        config=server.services.config,
    )


def _instance_to_dict(inst: Any, *, access: GroupAccess | None = None) -> dict[str, Any]:
    config = ConnectorRepo.parse_config_json(inst) if hasattr(inst, "config_json") else {}
    shared = bool(inst.shared)
    payload: dict[str, Any] = {
        "instance_id": inst.instance_id,
        "kind": inst.kind,
        "display_name": inst.display_name,
        "description": config.get("description"),
        "status": inst.status,
        "mcp_server_name": inst.mcp_server_name,
        "has_credentials": inst.has_credentials,
        "default_open": read_default_open(config),
        "shared": shared,
        "owner_user_id": inst.user_id,
        "created_at": inst.created_at,
        "updated_at": inst.updated_at,
    }
    if access is not None:
        payload.update(access.visibility(RESOURCE_CONNECTOR, inst.instance_id, shared=shared))
    return payload


def _shared_and_visibility(
    *,
    visibility: str | None,
    group_ids: list[str] | None,
    shared: bool | None,
    default_shared: bool = False,
) -> tuple[bool, str, list[str] | None]:
    """Map visibility/shared fields into ``(shared, visibility, group_ids)``."""
    if visibility is not None:
        if visibility == "owner":
            return False, "owner", []
        if visibility == "all":
            return True, "all", []
        return True, "groups", group_ids
    flag = default_shared if shared is None else bool(shared)
    return flag, ("all" if flag else "owner"), []


def _apply_connector_visibility(
    server: Any,
    instance_id: str,
    *,
    visibility: str,
    group_ids: list[str] | None,
) -> None:
    access = GroupAccess(server.services.repos)
    # Drop the legacy feature-wide grant if present.
    access.clear(RESOURCE_CONNECTOR, CONNECTOR_FEATURE_KEY)
    access.set_visibility(RESOURCE_CONNECTOR, instance_id, visibility, group_ids)


def _validate_connector_visibility(
    server: Any,
    *,
    visibility: str | None,
    group_ids: list[str] | None,
) -> None:
    """Raise before any ``shared`` write when visibility args are invalid."""
    if visibility is None:
        return
    GroupAccess(server.services.repos).validate_visibility(visibility, group_ids)


async def _prepare_credentials(
    kind: str,
    credentials: dict[str, Any],
    settings_repo: Any,
) -> dict[str, Any]:
    entry = get_catalog_entry(kind)
    if entry is None:
        raise ValueError(f"unknown connector kind: {kind}")
    cred_payload = dict(credentials)
    if entry.auth_kind == "auth_code" and cred_payload.get("code"):
        code = str(cred_payload.pop("code")).strip()
        extra = {
            k: cred_payload.pop(k) for k in ("bkn", "knowledge_base_id") if cred_payload.get(k)
        }
        exchanged = await exchange_pasted_auth_code(
            kind=kind,
            code=code,
            settings_repo=settings_repo,
            extra=extra or None,
        )
        cred_payload.update(exchanged)
    elif entry.kind == "tencent-weiyun" and entry.auth_kind == "personal_token":
        raw = str(cred_payload.get("token") or cred_payload.get("access_token") or "").strip()
        token = normalize_weiyun_mcp_token(raw)
        if not token:
            raise ValueError("token is required")
        cred_payload = {"token": token}
    return validate_create_credentials(kind, cred_payload)


def _merge_credentials(
    old: dict[str, Any],
    new: dict[str, Any],
    *,
    kind: str | None = None,
) -> dict[str, Any]:
    # QCC: switching auth mode must replace the other mode's secrets, not layer them.
    if kind == "qcc":
        new_api_key = str(new.get("api_key") or "").strip()
        new_access = str(new.get("access_token") or new.get("token") or "").strip()
        oauth_in_new = bool(new.get("oauth_client_id") or new.get("refresh_token") or new_access)
        if new_api_key and not oauth_in_new:
            out: dict[str, Any] = {"api_key": new_api_key}
            if old.get("internal_token"):
                out["internal_token"] = old["internal_token"]
            return out
        if oauth_in_new:
            merged_oauth = dict(old)
            for key, value in new.items():
                if value is None:
                    continue
                if isinstance(value, str) and not value.strip():
                    continue
                merged_oauth[key] = value
            merged_oauth.pop("api_key", None)
            return merged_oauth
    merged = dict(old)
    for key, value in new.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        merged[key] = value
    return merged


def _credentials_preview(kind: str, creds: dict[str, Any]) -> dict[str, Any]:
    entry = get_catalog_entry(kind)
    if entry is None or not creds:
        return {}
    preview: dict[str, Any] = {}
    if entry.auth_kind == "personal_token":
        if entry.kind == "tencent-weiyun":
            if str(creds.get("token") or "").strip():
                preview["token_configured"] = True
        elif str(creds.get("token") or creds.get("access_token") or "").strip():
            preview["token_configured"] = True
    elif entry.auth_kind == "oauth2":
        if (
            kind == "qcc"
            and str(creds.get("api_key") or "").strip()
            and not (creds.get("oauth_client_id") or creds.get("refresh_token"))
        ):
            preview["api_key_configured"] = True
        elif str(creds.get("access_token") or "").strip():
            preview["oauth_configured"] = True
        if creds.get("expires_at") is not None:
            preview["expires_at"] = creds.get("expires_at")
    elif entry.auth_kind == "auth_code":
        if str(creds.get("access_token") or creds.get("cookie") or "").strip():
            preview["auth_configured"] = True
        if creds.get("bkn"):
            preview["bkn"] = str(creds["bkn"])
        if creds.get("knowledge_base_id"):
            preview["knowledge_base_id"] = str(creds["knowledge_base_id"])
    elif entry.auth_kind == "api_key":
        if str(creds.get("api_key") or "").strip():
            preview["api_key_configured"] = True
        # Legacy tencent-news instances stored the key as ``cookie``.
        if kind == "tencent-news" and str(creds.get("cookie") or "").strip():
            preview["api_key_configured"] = True
        if kind == "tencent-ima" and creds.get("client_id"):
            preview["client_id"] = str(creds["client_id"])
        if kind == "feishu-cli" and creds.get("app_id"):
            preview["app_id"] = str(creds["app_id"])
            if str(creds.get("app_secret") or "").strip():
                preview["app_secret_configured"] = True
            default_as = str(creds.get("default_as") or "bot").strip().lower()
            preview["default_as"] = "user" if default_as == "user" else "bot"
            if default_as == "user":
                preview["user_auth_configured"] = True
            if creds.get("cli_config_key"):
                preview["cli_config_key"] = str(creds["cli_config_key"])
        if kind == "wecom-cli" and creds.get("bot_id"):
            preview["bot_id"] = str(creds["bot_id"])
            if str(creds.get("bot_secret") or "").strip():
                preview["bot_secret_configured"] = True
        if kind == "tencent-lexiang":
            company_from = creds.get("company_from") or creds.get("client_id")
            if company_from:
                preview["client_id"] = str(company_from)
    elif entry.auth_kind == "imap_app_password":
        if creds.get("email"):
            preview["email"] = str(creds["email"])
        if creds.get("mail_provider"):
            preview["mail_provider"] = str(creds["mail_provider"])
        if creds.get("imap_host"):
            preview["imap_host"] = str(creds["imap_host"])
        if creds.get("smtp_host"):
            preview["smtp_host"] = str(creds["smtp_host"])
        if str(creds.get("password") or "").strip():
            preview["password_configured"] = True
    elif entry.auth_kind == "api_credentials":
        if creds.get("app_id"):
            preview["app_id"] = str(creds["app_id"])
        if creds.get("sdk_id"):
            preview["sdk_id"] = str(creds["sdk_id"])
        if str(creds.get("secret_key") or "").strip():
            preview["secret_key_configured"] = True
    elif entry.auth_kind == "custom_fields":
        for field in entry.credential_fields:
            value = creds.get(field.key)
            if field.secret:
                if str(value or "").strip():
                    preview[f"{field.key}_configured"] = True
            elif value not in (None, "", []):
                preview[field.key] = value
    return preview


def _schedule_connector_reload(
    server: Any,
    user_id: int,
    *,
    all_users: bool = False,
    mail_instance_id: str | None = None,
) -> None:
    assert server.app_runtime is not None

    async def _run() -> None:
        try:
            if mail_instance_id:
                await server.app_runtime.cron_manager.sync_mail_watch(mail_instance_id)
            if all_users:
                await server.app_runtime.agent_registry.reload_all()
            else:
                await server.app_runtime.agent_registry.reload_connectors_for_user(user_id)
        except Exception:
            logger.exception("background connector reload failed for user %s", user_id)

    asyncio.create_task(_run())


def _can_manage_connector(inst: Any, user: Any) -> bool:
    """Only the owning user may view credentials or change the instance.

    Sharing lets other users (including admins) select the connector. It does
    not grant edit, delete, enable, or credential access.
    """
    return bool(inst.user_id == user.id)


def _assert_can_manage_connector(inst: Any, user: Any) -> None:
    if not _can_manage_connector(inst, user):
        raise HappyclawError(ErrorCode.FORBIDDEN, "not your connector instance")


def _raise_name_taken(name: str) -> None:
    raise HappyclawError(
        ErrorCode.CONNECTOR_NAME_TAKEN,
        f"connector name {name!r} is already in use",
    )


def _custom_name_exists(svc: ConnectorService, user_id: int, name: str) -> bool:
    return any(
        item["display_name"] == name
        for item in svc.list_instances_for_api(user_id)
        if item["kind"] == CUSTOM_MCP_KIND and int(item.get("owner_user_id") or user_id) == user_id
    )


def _resolve_custom_target(
    instance_id: str,
    *,
    user: Any,
    server: Any,
) -> tuple[int, str] | None:
    raw = parse_synthetic_instance_id(instance_id)
    if raw is None:
        return None
    parent_id, separator, server_name = raw.partition(":")
    if separator:
        parent = server.services.repos.connector_repo.get(parent_id)
        if parent is not None and is_custom_mcp_kind(parent.kind):
            _assert_can_manage_connector(parent, user)
            return parent.user_id, server_name
    return user.id, raw


def _is_public_http_uri(uri: str) -> bool:
    parsed = urlparse(uri)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "http" and host not in {"localhost", "127.0.0.1", "::1"}


async def validate_chat_mcp_servers(
    server: Any,
    *,
    user_id: int,
    names: list[str] | None,
) -> list[str] | None:
    from happyclaw.api.common.validators import validate_chat_mcp_servers as _validate

    return await _validate(server, user_id=user_id, names=names)
