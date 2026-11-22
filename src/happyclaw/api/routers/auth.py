"""Single-user profile endpoints.

There is no login: the dashboard is served from this machine and every request
is the local owner. These paths stay mounted (dashboard builds still probe
``/auth/me``), but nothing reads or validates a token.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Response, UploadFile
from pydantic import BaseModel, Field

from happyclaw.api.deps import current_user, get_server
from happyclaw.infra.errors import ErrorCode, OctopError
from happyclaw.infra.utils.locale import normalize_locale

logger = logging.getLogger(__name__)

router = APIRouter()

LOCAL_ROLE = "local"


def _user_json(user: Any, *, locale: str | None = None) -> dict[str, Any]:
    """Minimal single-user profile: no RBAC permissions, no SSO fields."""
    return {
        "id": user.id,
        "username": user.username,
        "role": LOCAL_ROLE,
        "display_name": user.display_name,
        "locale": normalize_locale(locale or user.locale),
        "is_local_owner": True,
    }


def me_payload(user: Any, server: Any) -> dict[str, Any]:
    """Profile JSON for ``/auth/me`` and other single-user surfaces."""
    payload = _user_json(user, locale=user.locale)
    row = server.services.user_repo.get(user.id) if server.services is not None else None
    if row is not None:
        from happyclaw.infra.users.profile_avatar import profile_avatar_url

        payload["avatar_icon"] = row.avatar_icon
        payload["avatar_url"] = profile_avatar_url(
            server.services.avatars("user"),
            str(user.id),
            f"/api/users/{user.id}/avatar",
        )
    else:
        payload["avatar_icon"] = None
        payload["avatar_url"] = None
    return payload


class LoginBody(BaseModel):
    username: str = ""
    password: str = ""
    captcha_token: str | None = Field(default=None, max_length=4096)


class CaptchaPublicResponse(BaseModel):
    provider: str
    site_key: str | None = None


class ChangePasswordBody(BaseModel):
    old_password: str = ""
    new_password: str = ""


@router.get(
    "/captcha",
    summary="Public login captcha config",
    response_model=CaptchaPublicResponse,
    response_model_exclude_none=True,
)
async def get_captcha() -> CaptchaPublicResponse:
    """Captcha is part of the removed login flow."""
    return CaptchaPublicResponse(provider="none")


@router.post("/login", summary="Sign in")
async def login(server: Any = Depends(get_server)) -> dict[str, Any]:
    """Return the local owner with a placeholder token.

    Single-user builds have no credential check; the token is never validated
    and exists only so older clients that expect ``access_token`` keep working.
    """
    user = current_owner(server)
    return {
        "access_token": "local-owner",
        "token_type": "Bearer",
        "expires_in": 0,
        "user": me_payload(user, server),
    }


@router.post("/logout", status_code=204, summary="Sign out")
async def logout() -> Response:
    """No session to revoke in single-user mode."""
    return Response(status_code=204)


@router.get("/me", summary="Current user profile")
async def me(
    user: Any = Depends(current_user), server: Any = Depends(get_server)
) -> dict[str, Any]:
    """Return the local owner's minimal profile."""
    return me_payload(user, server)


@router.post("/change-password", status_code=400, summary="Change password")
async def change_password(body: ChangePasswordBody) -> Response:  # noqa: ARG001
    """Passwords are not part of the single-user model."""
    raise OctopError(
        ErrorCode.SINGLE_USER_UNSUPPORTED,
        "single-user mode has no password",
    )


class UpdateMeBody(BaseModel):
    display_name: str | None = None
    locale: str | None = None
    avatar_icon: str | None = Field(default=None, max_length=32)


@router.patch("/me", summary="Update profile")
async def update_me(
    body: UpdateMeBody,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Update the local owner's display name, locale or avatar icon."""
    provided = body.model_dump(exclude_unset=True)
    repo = server.services.user_repo
    if "display_name" in provided:
        repo.set_display_name(user.id, body.display_name)
    if "locale" in provided:
        repo.set_locale(user.id, body.locale)
    if "avatar_icon" in provided:
        from happyclaw.infra.users.profile_avatar import clean_avatar_icon, delete_profile_avatar

        repo.set_avatar_icon(user.id, clean_avatar_icon(body.avatar_icon))
        delete_profile_avatar(server.services.avatars("user"), str(user.id))
    user.display_name = body.display_name if "display_name" in provided else user.display_name
    if "locale" in provided and body.locale:
        user.locale = normalize_locale(body.locale)
    return me_payload(user, server)


@router.post("/me/avatar", status_code=201, summary="Upload the current user's portrait")
async def upload_my_avatar(
    file: UploadFile = File(...),  # noqa: B008
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, str | None]:
    from happyclaw.infra.users.profile_avatar import profile_avatar_url, write_profile_avatar

    write_profile_avatar(
        server.services.avatars("user"),
        str(user.id),
        await file.read(),
    )
    return {
        "avatar_url": profile_avatar_url(
            server.services.avatars("user"),
            str(user.id),
            f"/api/users/{user.id}/avatar",
        )
    }


@router.delete("/me/avatar", status_code=204, summary="Remove the current user's portrait")
async def delete_my_avatar(
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Response:
    from happyclaw.infra.users.profile_avatar import delete_profile_avatar

    delete_profile_avatar(server.services.avatars("user"), str(user.id))
    return Response(status_code=204)


def current_owner(server: Any) -> Any:
    return server.services.owner.owner()
