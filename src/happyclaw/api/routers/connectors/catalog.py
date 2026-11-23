"""Read-only connector catalog endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from happyclaw.api.deps import current_user, get_server
from happyclaw.infra.connectors.catalog import catalog_entry_to_dict, list_catalog
from happyclaw.infra.connectors.oauth import oauth_ready_for_kind
from happyclaw.infra.connectors.probe import detect_local_weknora
from happyclaw.infra.utils.locale import resolve_request_locale

router = APIRouter()

@router.get("/connectors/catalog", summary="Connector catalog")
async def get_catalog(
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> list[dict[str, Any]]:
    """List supported connector kinds and whether OAuth is configured for each."""
    del user
    settings = server.services.settings_repo
    return [
        catalog_entry_to_dict(
            e,
            oauth_ready=oauth_ready_for_kind(e.kind, settings),
            locale=resolve_request_locale(request),
        )
        for e in list_catalog()
    ]


@router.get("/connectors/weknora/detect-local", summary="Detect local WeKnora")
async def detect_weknora_on_octop_host(
    user: Any = Depends(current_user),
) -> dict[str, Any]:
    """Check WeKnora's fixed default loopback health endpoint (no persistence)."""
    del user
    return await detect_local_weknora()
