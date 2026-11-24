"""Knowledge-base CRUD, portraits and the default-open list."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Request, UploadFile, status

from happyclaw.api.deps import current_user, get_server, require_permission
from happyclaw.api.routers.knowledge_bases.common import (
    _base_payload,
    _group_access,
    _is_admin,
    _kb_avatar_api_path,
    _kb_avatars,
    _knowledge_service,
    _map_knowledge_error,
    _require_usable,
)
from happyclaw.api.routers.knowledge_bases.schemas import CreateBaseBody, UpdateBaseBody
from happyclaw.infra.knowledge.service import MAX_DOCS_PER_KB
from happyclaw.infra.server import HappyclawServer
from happyclaw.infra.users.groups import RESOURCE_KNOWLEDGE_BASE
from happyclaw.infra.users.identity import User
from happyclaw.infra.utils.locale import resolve_request_locale

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", summary="List visible knowledge bases")
async def list_bases(
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(current_user),
) -> list[dict[str, Any]]:
    return [
        _base_payload(server, base)
        for base in _knowledge_service(server).list_visible_bases(
            actor_user_id=user.id, is_admin=_is_admin(user)
        )
    ]


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a knowledge base")
async def create_base(
    body: CreateBaseBody,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("knowledge_bases")),
) -> dict[str, Any]:
    locale = resolve_request_locale(request)
    try:
        _require_usable(server, request)
        access = _group_access(server)
        if body.visibility is not None and access is not None:
            access.validate_visibility(body.visibility, body.group_ids)
        base = _knowledge_service(server).create_base(
            owner_user_id=user.id,
            name=body.name.strip(),
            description=body.description.strip(),
            default_open=body.default_open,
            shared=(
                False
                if body.visibility == "owner"
                else True
                if body.visibility in {"all", "groups"}
                else body.shared
            ),
            icon_name=body.icon_name.strip(),
            icon_url=body.icon_url.strip(),
            max_documents=body.max_documents if body.max_documents is not None else MAX_DOCS_PER_KB,
        )
        if body.visibility is not None and access is not None:
            access.set_visibility(
                RESOURCE_KNOWLEDGE_BASE,
                base.id,
                body.visibility,
                body.group_ids,
            )
        return _base_payload(server, base)
    except Exception as exc:
        raise _map_knowledge_error(exc, locale=locale, server=server) from exc


@router.get("/default-open", summary="List current user's default-open knowledge-base IDs")
async def default_open_bases(
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(current_user),
) -> dict[str, list[str]]:
    bases = _knowledge_service(server).list_visible_bases(
        actor_user_id=user.id, is_admin=_is_admin(user)
    )
    return {
        "knowledge_base_ids": [
            base.id
            for base in bases
            if base.default_open and int(base.owner_user_id) == int(user.id)
        ]
    }


@router.get("/{kb_id}", summary="Get a visible knowledge base")
async def get_base(
    kb_id: str,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    try:
        return _base_payload(
            server,
            _knowledge_service(server).get_readable_base(
                kb_id, actor_user_id=user.id, is_admin=_is_admin(user)
            ),
        )
    except Exception as exc:
        raise _map_knowledge_error(
            exc, locale=resolve_request_locale(request), server=server
        ) from exc


@router.patch("/{kb_id}", summary="Update knowledge-base settings")
async def update_base(
    kb_id: str,
    body: UpdateBaseBody,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("knowledge_bases")),
) -> dict[str, Any]:
    try:
        access = _group_access(server)
        if body.visibility is not None and access is not None:
            access.validate_visibility(body.visibility, body.group_ids)
        shared = body.shared
        if body.visibility == "owner":
            shared = False
        elif body.visibility in {"all", "groups"}:
            shared = True
        updated = _knowledge_service(server).update_base(
            kb_id,
            actor_user_id=user.id,
            name=body.name.strip() if body.name is not None else None,
            description=body.description.strip() if body.description is not None else None,
            default_open=body.default_open,
            shared=shared,
            icon_name=body.icon_name.strip() if body.icon_name is not None else None,
            icon_url=body.icon_url.strip() if body.icon_url is not None else None,
            max_documents=body.max_documents,
            is_admin=_is_admin(user),
        )
        if body.visibility is not None and access is not None:
            access.set_visibility(
                RESOURCE_KNOWLEDGE_BASE,
                kb_id,
                body.visibility,
                body.group_ids,
            )
        return _base_payload(server, updated)
    except Exception as exc:
        raise _map_knowledge_error(
            exc, locale=resolve_request_locale(request), server=server
        ) from exc


@router.delete(
    "/{kb_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a knowledge base"
)
async def delete_base(
    kb_id: str,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("knowledge_bases")),
) -> None:
    try:
        _knowledge_service(server).delete_base(
            kb_id, actor_user_id=user.id, is_admin=_is_admin(user)
        )
        from happyclaw.infra.users.profile_avatar import delete_profile_avatar  # noqa: PLC0415

        delete_profile_avatar(_kb_avatars(server), kb_id)
    except Exception as exc:
        raise _map_knowledge_error(
            exc, locale=resolve_request_locale(request), server=server
        ) from exc


@router.post("/{kb_id}/avatar", status_code=201, summary="Upload a knowledge-base portrait")
async def upload_kb_avatar(
    kb_id: str,
    request: Request,
    file: UploadFile = File(...),  # noqa: B008
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("knowledge_bases")),
) -> dict[str, str]:
    from happyclaw.infra.users.profile_avatar import (  # noqa: PLC0415
        profile_avatar_url,
        write_profile_avatar,
    )

    try:
        _knowledge_service(server).require_owner(
            kb_id, actor_user_id=user.id, is_admin=_is_admin(user)
        )
        write_profile_avatar(
            _kb_avatars(server),
            kb_id,
            await file.read(),
        )
        icon_url = _kb_avatar_api_path(kb_id)
        updated = _knowledge_service(server).update_base(
            kb_id,
            actor_user_id=user.id,
            icon_url=icon_url,
            is_admin=_is_admin(user),
        )
        display = (
            profile_avatar_url(
                _kb_avatars(server),
                kb_id,
                icon_url,
            )
            or icon_url
        )
        return {"icon_url": display or updated.icon_url}
    except Exception as exc:
        raise _map_knowledge_error(
            exc, locale=resolve_request_locale(request), server=server
        ) from exc


@router.get("/{kb_id}/avatar", summary="Read a knowledge-base portrait")
async def get_kb_avatar(
    kb_id: str,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(current_user),
) -> Any:
    from happyclaw.infra.users.profile_avatar import avatar_response  # noqa: PLC0415

    try:
        _knowledge_service(server).get_readable_base(
            kb_id, actor_user_id=user.id, is_admin=_is_admin(user)
        )
        return avatar_response(_kb_avatars(server), kb_id)
    except Exception as exc:
        raise _map_knowledge_error(
            exc, locale=resolve_request_locale(request), server=server
        ) from exc


@router.delete(
    "/{kb_id}/avatar",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a knowledge-base portrait",
)
async def delete_kb_avatar(
    kb_id: str,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("knowledge_bases")),
) -> None:
    from happyclaw.infra.users.profile_avatar import delete_profile_avatar  # noqa: PLC0415

    try:
        _knowledge_service(server).require_owner(
            kb_id, actor_user_id=user.id, is_admin=_is_admin(user)
        )
        delete_profile_avatar(_kb_avatars(server), kb_id)
        _knowledge_service(server).update_base(
            kb_id,
            actor_user_id=user.id,
            icon_url="",
            is_admin=_is_admin(user),
        )
    except Exception as exc:
        raise _map_knowledge_error(
            exc, locale=resolve_request_locale(request), server=server
        ) from exc
