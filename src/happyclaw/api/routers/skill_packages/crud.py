"""Skill-package CRUD, portraits and create-from-SkillHub."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, File, Request, UploadFile, status
from fastapi.responses import Response

from happyclaw.api.deps import get_server, require_permission
from happyclaw.api.routers.skill_packages.common import (
    CreateSkillPackageBody,
    FromSkillHubBody,
    UpdateSkillPackageBody,
    _creator_fields,
    _icon_url,
    _is_package_avatar_url,
    _map_skillhub_error,
    _package_access,
    _package_avatar_api_path,
    _package_avatars,
    _package_or_404,
    _package_owner,
    _package_payload_with_creator,
    _package_visible_or_404,
    _required,
    _row_public_dict,
    _store,
    _visible_packages,
)
from happyclaw.infra.agents.experts.skillhub_market import SkillHubMarketError
from happyclaw.infra.server import HappyclawServer
from happyclaw.infra.skills.skill_package_from_skillhub import create_package_from_skillhub
from happyclaw.infra.skills.skill_package_store import (
    is_skill_package_name_conflict,
    raise_skill_package_name_taken,
)
from happyclaw.infra.skills.skillhub_market import SkillHubMarketError as SkillHubDownloadError
from happyclaw.infra.users.groups import RESOURCE_SKILL_PACKAGE
from happyclaw.infra.users.identity import User
from happyclaw.infra.utils.locale import resolve_request_locale

router = APIRouter()


@router.get("", summary="List global skill packages")
async def list_skill_packages(
    writable_only: bool = False,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("skill_packages")),
) -> list[dict[str, Any]]:
    store = _store(server)
    access = _package_access(server)
    rows = access.filter_rows(
        _visible_packages(store, user),
        user_id=user.id,
        is_admin=user.is_admin,
        resource_type=RESOURCE_SKILL_PACKAGE,
        key_of=lambda row: row.id,
        is_owner=lambda row: _package_owner(user, row),
    )
    return [
        {
            **_row_public_dict(server, row),
            **_creator_fields(server, row.created_by),
            **access.visibility(RESOURCE_SKILL_PACKAGE, row.id, shared=bool(row.shared)),
            "can_write": store.can_mutate(row, user),
            "can_copy": store.can_copy(row, user),
            "can_download": store.can_download(row, user),
        }
        for row in rows
        if not writable_only or store.can_mutate(row, user)
    ]


@router.post("", summary="Create a global skill package")
async def create_skill_package(
    body: CreateSkillPackageBody,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("skill_packages")),
) -> dict[str, Any]:
    store = _store(server)
    name = _required(body.name, "name")
    if body.visibility is not None:
        _package_access(server).validate_visibility(body.visibility, body.group_ids)
    try:
        shared = bool(body.shared)
        if body.visibility == "owner":
            shared = False
        elif body.visibility in {"all", "groups"}:
            shared = True
        row = store.create(
            name=name,
            description=body.description.strip(),
            created_by=str(user.id),
            icon_name=body.icon_name.strip(),
            icon_url=_icon_url(body.icon_url),
            shared=shared,
            copy_policy=body.copy_policy,
            allow_download=bool(body.allow_download),
        )
    except Exception as exc:
        if is_skill_package_name_conflict(exc):
            raise_skill_package_name_taken(name)
        raise
    if body.visibility is not None:
        _package_access(server).set_visibility(
            RESOURCE_SKILL_PACKAGE,
            row.id,
            body.visibility,
            body.group_ids,
        )
    return {
        **_package_payload_with_creator(server, store, row),
        **_package_access(server).visibility(
            RESOURCE_SKILL_PACKAGE, row.id, shared=bool(row.shared)
        ),
    }


@router.post(
    "/from-skillhub",
    status_code=status.HTTP_201_CREATED,
    summary="Create a skill package from a SkillHub skillset",
)
async def create_from_skillhub(
    body: FromSkillHubBody,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("skill_packages")),
) -> dict[str, Any]:
    store = _store(server)
    try:
        result = await asyncio.to_thread(
            create_package_from_skillhub,
            store,
            slug=_required(body.slug, "slug"),
            created_by=str(user.id),
            name=body.name.strip() if body.name is not None else None,
            description=body.description.strip() if body.description is not None else None,
            icon_name=body.icon_name.strip() if body.icon_name is not None else None,
            icon_url=_icon_url(body.icon_url) if body.icon_url is not None else None,
            shared=bool(body.shared),
        )
    except (SkillHubMarketError, SkillHubDownloadError) as exc:
        raise _map_skillhub_error(exc) from exc
    payload = _package_payload_with_creator(server, store, result.row)
    if result.skipped_slugs:
        payload["skipped_skills"] = list(result.skipped_slugs)
    return payload


@router.get("/{package_id}", summary="Get a global skill package and its skills")
async def get_skill_package(
    package_id: str,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("skill_packages")),
) -> dict[str, Any]:
    store = _store(server)
    locale = resolve_request_locale(request)
    row = _package_visible_or_404(store, package_id, user, server, locale=locale)
    return {
        **_package_payload_with_creator(
            server,
            store,
            row,
            locale=locale,
        ),
        **_package_access(server).visibility(
            RESOURCE_SKILL_PACKAGE, row.id, shared=bool(row.shared)
        ),
        "can_write": store.can_mutate(row, user),
        "can_copy": store.can_copy(row, user),
        "can_download": store.can_download(row, user),
    }


@router.patch("/{package_id}", summary="Update global skill package metadata")
async def update_skill_package(
    package_id: str,
    body: UpdateSkillPackageBody,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("skill_packages")),
) -> dict[str, Any]:
    store = _store(server)
    locale = resolve_request_locale(request)
    row = _package_or_404(store, package_id, locale=locale)
    store.assert_can_mutate(row, user)
    name = _required(body.name, "name") if body.name is not None else None
    description = body.description.strip() if body.description is not None else None
    icon_name = body.icon_name.strip() if body.icon_name is not None else None
    icon_url = (
        _icon_url(body.icon_url, package_id=package_id) if body.icon_url is not None else None
    )
    if body.visibility is not None:
        _package_access(server).validate_visibility(body.visibility, body.group_ids)
    shared_value = None if body.shared is None else int(body.shared)
    if body.visibility == "owner":
        shared_value = 0
    elif body.visibility in {"all", "groups"}:
        shared_value = 1
    try:
        store.repo.update(
            package_id,
            name=name,
            description=description,
            icon_name=icon_name,
            icon_url=icon_url,
            copy_policy=body.copy_policy,
            allow_download=None if body.allow_download is None else int(body.allow_download),
            shared=shared_value,
        )
    except Exception as exc:
        if name is not None and is_skill_package_name_conflict(exc):
            raise_skill_package_name_taken(name)
        raise
    if icon_url is not None and not _is_package_avatar_url(icon_url, package_id):
        from happyclaw.infra.users.profile_avatar import delete_profile_avatar  # noqa: PLC0415

        delete_profile_avatar(_package_avatars(server), package_id)
    if body.visibility is not None:
        _package_access(server).set_visibility(
            RESOURCE_SKILL_PACKAGE,
            package_id,
            body.visibility,
            body.group_ids,
        )
    updated = _package_or_404(store, package_id, locale=locale)
    return {
        **_package_payload_with_creator(
            server,
            store,
            updated,
            locale=locale,
        ),
        **_package_access(server).visibility(
            RESOURCE_SKILL_PACKAGE, package_id, shared=bool(updated.shared)
        ),
    }


@router.delete(
    "/{package_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a global skill package"
)
async def delete_skill_package(
    package_id: str,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("skill_packages")),
) -> None:
    store = _store(server)
    row = _package_or_404(store, package_id, locale=resolve_request_locale(request))
    store.assert_can_mutate(row, user)
    store.delete_package(package_id)
    from happyclaw.infra.users.profile_avatar import delete_profile_avatar  # noqa: PLC0415

    delete_profile_avatar(_package_avatars(server), package_id)
    _package_access(server).clear(RESOURCE_SKILL_PACKAGE, package_id)
    if server.app_runtime is not None:
        await server.app_runtime.agent_registry.strip_skill_package_id(package_id)


@router.post(
    "/{package_id}/avatar",
    status_code=201,
    summary="Upload a skill-package portrait",
)
async def upload_skill_package_avatar(
    package_id: str,
    request: Request,
    file: UploadFile = File(...),  # noqa: B008
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("skill_packages")),
) -> dict[str, str]:
    from happyclaw.infra.users.profile_avatar import (  # noqa: PLC0415
        profile_avatar_url,
        write_profile_avatar,
    )

    store = _store(server)
    locale = resolve_request_locale(request)
    row = _package_or_404(store, package_id, locale=locale)
    store.assert_can_mutate(row, user)
    write_profile_avatar(
        _package_avatars(server),
        package_id,
        await file.read(),
    )
    icon_url = _package_avatar_api_path(package_id)
    store.repo.update(package_id, icon_url=icon_url)
    display = profile_avatar_url(_package_avatars(server), package_id, icon_url) or icon_url
    return {"icon_url": display}


@router.get("/{package_id}/avatar", summary="Read a skill-package portrait")
async def get_skill_package_avatar(
    package_id: str,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("skill_packages")),
) -> Response:
    from happyclaw.infra.users.profile_avatar import avatar_response  # noqa: PLC0415

    store = _store(server)
    locale = resolve_request_locale(request)
    _package_visible_or_404(store, package_id, user, server, locale=locale)
    return avatar_response(_package_avatars(server), package_id)


@router.delete(
    "/{package_id}/avatar",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a skill-package portrait",
)
async def delete_skill_package_avatar(
    package_id: str,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("skill_packages")),
) -> None:
    from happyclaw.infra.users.profile_avatar import delete_profile_avatar  # noqa: PLC0415

    store = _store(server)
    locale = resolve_request_locale(request)
    row = _package_or_404(store, package_id, locale=locale)
    store.assert_can_mutate(row, user)
    delete_profile_avatar(_package_avatars(server), package_id)
    store.repo.update(package_id, icon_url="")
