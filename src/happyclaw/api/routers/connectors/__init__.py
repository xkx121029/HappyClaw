"""Connector and agent-binding HTTP API.

Split by resource subdomain; the package keeps the old module's namespace
(``from happyclaw.api.routers.connectors import router`` still works):

  schemas      request bodies shared by the routes
  common       instance serialisation, visibility, credential helpers
  catalog      connector catalog and local WeKnora detection
  instances    connector-instance CRUD, probe and token refresh
  custom_mcp   user-defined MCP servers
  credentials  credential probing and auth-code exchange
  cli_auth     host CLI install status and device-code logins
  oauth        browser OAuth start / callback / pending polling"""

from __future__ import annotations

from fastapi import APIRouter

from happyclaw.api.routers.connectors.catalog import detect_weknora_on_octop_host, get_catalog
from happyclaw.api.routers.connectors.catalog import router as catalog_router
from happyclaw.api.routers.connectors.cli_auth import (
    FeishuUserAuthInstanceCompleteBody,
    agently_auth_logout,
    agently_auth_refresh,
    agently_auth_start,
    agently_auth_status,
    connector_cli_status,
    connector_install_cli,
    feishu_cli_user_auth_complete,
    feishu_cli_user_auth_complete_instance,
    feishu_cli_user_auth_start,
    feishu_cli_user_auth_start_instance,
)
from happyclaw.api.routers.connectors.cli_auth import router as cli_auth_router
from happyclaw.api.routers.connectors.common import (
    _apply_connector_visibility,
    _assert_can_manage_connector,
    _can_manage_connector,
    _connector_service,
    _credentials_preview,
    _custom_name_exists,
    _instance_to_dict,
    _is_public_http_uri,
    _merge_credentials,
    _prepare_credentials,
    _raise_name_taken,
    _resolve_custom_target,
    _schedule_connector_reload,
    _shared_and_visibility,
    _validate_connector_visibility,
    validate_chat_mcp_servers,
)
from happyclaw.api.routers.connectors.credentials import (
    auth_authorize_url,
    auth_exchange_code,
    auth_info,
    test_credentials,
)
from happyclaw.api.routers.connectors.credentials import router as credentials_router
from happyclaw.api.routers.connectors.custom_mcp import (
    get_custom_mcp,
    patch_custom_mcp_server,
    put_custom_mcp,
    test_custom_mcp,
)
from happyclaw.api.routers.connectors.custom_mcp import router as custom_mcp_router
from happyclaw.api.routers.connectors.instances import (
    create_instance,
    delete_instance,
    get_instance,
    list_instances,
    patch_instance,
    refresh_instance,
    test_instance,
)
from happyclaw.api.routers.connectors.instances import router as instances_router
from happyclaw.api.routers.connectors.oauth import (
    _begin_oauth_flow,
    _oauth_callback_html,
    _resolve_custom_mcp_oauth_target,
    oauth_callback,
    oauth_pending,
    oauth_start_legacy,
    oauth_start_unified,
)
from happyclaw.api.routers.connectors.oauth import router as oauth_router
from happyclaw.api.routers.connectors.schemas import (
    AgentlyAuthResponse,
    CreateInstanceBody,
    CustomMcpPutBody,
    CustomMcpServerPatchBody,
    CustomMcpTestBody,
    ExchangeAuthCodeBody,
    FeishuUserAuthCompleteBody,
    FeishuUserAuthStartBody,
    OAuthStartBody,
    OAuthStartLegacyBody,
    PatchInstanceBody,
    TestCredentialsBody,
)

router = APIRouter()
router.include_router(catalog_router)
router.include_router(instances_router)
router.include_router(custom_mcp_router)
router.include_router(credentials_router)
router.include_router(cli_auth_router)
router.include_router(oauth_router)

__all__ = [
    "router",
    "AgentlyAuthResponse",
    "CreateInstanceBody",
    "CustomMcpPutBody",
    "CustomMcpServerPatchBody",
    "CustomMcpTestBody",
    "ExchangeAuthCodeBody",
    "FeishuUserAuthCompleteBody",
    "FeishuUserAuthInstanceCompleteBody",
    "FeishuUserAuthStartBody",
    "OAuthStartBody",
    "OAuthStartLegacyBody",
    "PatchInstanceBody",
    "TestCredentialsBody",
    "_apply_connector_visibility",
    "_assert_can_manage_connector",
    "_begin_oauth_flow",
    "_can_manage_connector",
    "_connector_service",
    "_credentials_preview",
    "_custom_name_exists",
    "_instance_to_dict",
    "_is_public_http_uri",
    "_merge_credentials",
    "_oauth_callback_html",
    "_prepare_credentials",
    "_raise_name_taken",
    "_resolve_custom_mcp_oauth_target",
    "_resolve_custom_target",
    "_schedule_connector_reload",
    "_shared_and_visibility",
    "_validate_connector_visibility",
    "agently_auth_logout",
    "agently_auth_refresh",
    "agently_auth_start",
    "agently_auth_status",
    "auth_authorize_url",
    "auth_exchange_code",
    "auth_info",
    "connector_cli_status",
    "connector_install_cli",
    "create_instance",
    "delete_instance",
    "detect_weknora_on_octop_host",
    "feishu_cli_user_auth_complete",
    "feishu_cli_user_auth_complete_instance",
    "feishu_cli_user_auth_start",
    "feishu_cli_user_auth_start_instance",
    "get_catalog",
    "get_custom_mcp",
    "get_instance",
    "list_instances",
    "oauth_callback",
    "oauth_pending",
    "oauth_start_legacy",
    "oauth_start_unified",
    "patch_custom_mcp_server",
    "patch_instance",
    "put_custom_mcp",
    "refresh_instance",
    "test_credentials",
    "test_custom_mcp",
    "test_instance",
    "validate_chat_mcp_servers",
]
