"""Device credential endpoints for the desktop shell.

Single-user mode does not issue or validate session tokens. These endpoints
stay for shell compatibility: registering a device is a no-op and requesting a
token returns the local placeholder token.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from happyclaw.api.deps import current_user, get_server

logger = logging.getLogger(__name__)

router = APIRouter()

LOCAL_TOKEN = "local-owner"


class RegisterBody(BaseModel):
    device_token: str = Field(min_length=1, max_length=4096)
    label: str | None = Field(default=None, max_length=128)


class DeviceTokenBody(BaseModel):
    device_token: str = Field(min_length=1, max_length=4096)


@router.post("/device/register", summary="Register this device's session credential")
async def register_device(
    body: RegisterBody,  # noqa: ARG001
    request: Request,  # noqa: ARG001
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),  # noqa: ARG001
) -> dict[str, Any]:
    """Nothing to bind: the machine itself is the identity."""
    return {"ok": True, "username": user.username}


@router.post("/device/token", summary="Exchange the device credential for an access token")
async def device_token(
    body: DeviceTokenBody,  # noqa: ARG001
    request: Request,  # noqa: ARG001
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Return the local placeholder token; no credential is checked."""
    from happyclaw.api.routers.auth import me_payload  # noqa: PLC0415

    return {
        "access_token": LOCAL_TOKEN,
        "token_type": "Bearer",
        "expires_in": 0,
        "user": me_payload(user, server),
    }


@router.post("/device/revoke", status_code=204, summary="Revoke this install's device credential")
async def revoke_device(request: Request) -> Response:  # noqa: ARG001
    return Response(status_code=204)
