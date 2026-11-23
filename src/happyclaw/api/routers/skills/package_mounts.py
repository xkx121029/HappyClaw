"""Skill-package mounts on an agent plus package/workspace copies."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from happyclaw.api.common.agent import require_agent_owner_row
from happyclaw.api.deps import current_user, get_server, require_permission
from happyclaw.api.routers.skills.common import (
    _ctx,
    _guard_package_only_skill_write,
    _skill_package_store,
)
from happyclaw.api.routers.skills.crud import _persist_disabled, _skill_disable_keys
from happyclaw.infra.agents.manager import (
    skill_package_ids_list,
)
from happyclaw.infra.agents.manager import (
    skills_disabled_set as _disabled_set,
)
from happyclaw.infra.errors import ErrorCode, HappyclawError
from happyclaw.infra.skills.skill_package_store import normalize_copy_policy
from happyclaw.infra.skills.skill_packages import SkillPackageError, validate_skill_slug
from happyclaw.infra.skills.skill_transfer import (
    SkillTransferConflict,
    SkillTransferNotFound,
    copy_package_skills_to_workspace,
    copy_workspace_skill_to_package,
)
from happyclaw.infra.utils.locale import Locale, resolve_request_locale

router = APIRouter()

class SkillPackageMountBody(BaseModel):
    package_ids: list[str]


class CopyPackageSkillsBody(BaseModel):
    skill_slugs: list[str]
    overwrite: bool = False


class CopyWorkspaceSkillBody(BaseModel):
    source_agent_id: str
    slug: str
    overwrite: bool = True


class PushSkillToPackageBody(BaseModel):
    package_id: str
    overwrite: bool = False


@router.get(
    "/agents/{agent_id}/skill-packages",
    summary="List global skill packages mounted on an agent",
)
async def list_skill_package_mounts(
    agent_id: str,
    request: Request,
    as_user: int | None = None,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    require_agent_owner_row(agent_id, user=user, as_user=as_user, server=server)
    assert server.app_runtime is not None
    package_ids = skill_package_ids_list(server.app_runtime.agent_registry.get_config(agent_id))
    assert server.services is not None
    store = _skill_package_store(server)
    locale = resolve_request_locale(request)
    packages: list[dict[str, Any]] = []
    for package_id in package_ids:
        package = store.repo.get(package_id)
        if package is None:
            continue
        packages.append(
            {
                "id": package.id,
                "name": package.name,
                "description": package.description,
                "skills": store.list_skill_summaries(package_id, locale=locale),
            }
        )
    return {"package_ids": package_ids, "packages": packages}


@router.put(
    "/agents/{agent_id}/skill-packages",
    summary="Replace global skill packages mounted on an agent",
)
async def replace_skill_package_mounts(
    agent_id: str,
    body: SkillPackageMountBody,
    request: Request,
    as_user: int | None = None,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, list[str]]:
    require_agent_owner_row(agent_id, user=user, as_user=as_user, server=server)
    assert server.app_runtime is not None
    package_ids = skill_package_ids_list({"skill_package_ids": body.package_ids})
    store = _skill_package_store(server)
    locale = resolve_request_locale(request)
    for package_id in package_ids:
        package_row = store.repo.get(package_id)
        if package_row is None:
            raise HappyclawError.localized(ErrorCode.SKILL_PACKAGE_NOT_FOUND, locale)
        store.assert_can_view(package_row, user)
    await server.app_runtime.agent_registry.persist_skill_package_ids(agent_id, package_ids)
    return {"package_ids": package_ids}


def _assert_skill_package_group(server: Any, user: Any, row: Any, locale: str) -> None:
    """Groups narrow a shared package. They do not open a private one."""
    services = getattr(server, "services", None)
    repos = getattr(services, "repos", None) if services is not None else None
    if repos is None:
        return
    from happyclaw.infra.users.groups import RESOURCE_SKILL_PACKAGE, GroupAccess

    if GroupAccess(repos).allows(
        user_id=user.id,
        is_admin=bool(getattr(user, "is_admin", False)),
        resource_type=RESOURCE_SKILL_PACKAGE,
        resource_key=row.id,
        is_owner=str(user.id) == str(row.created_by),
    ):
        return
    raise HappyclawError.localized(ErrorCode.SKILL_PACKAGE_NOT_FOUND, locale)


def _skill_transfer_error(exc: SkillPackageError, *, locale: Locale) -> HappyclawError:
    if isinstance(exc, SkillTransferConflict):
        return HappyclawError.localized(
            ErrorCode.SKILL_ALREADY_EXISTS,
            locale,
            name=exc.slug,
        )
    if isinstance(exc, SkillTransferNotFound):
        return HappyclawError(ErrorCode.NOT_FOUND, str(exc))
    return HappyclawError(ErrorCode.SLASH_BAD_ARGS, str(exc))


@router.post(
    "/agents/{agent_id}/skill-packages/{package_id}/copy",
    summary="Copy package skills into an agent workspace",
)
async def copy_skill_package_to_workspace(
    agent_id: str,
    package_id: str,
    body: CopyPackageSkillsBody,
    request: Request,
    as_user: int | None = None,
    user: Any = Depends(require_permission("skill_packages")),
    server: Any = Depends(get_server),
) -> dict[str, list[str]]:
    ctx = await _ctx(agent_id, user=user, as_user=as_user, server=server)
    store = _skill_package_store(server)
    package_row = store.repo.get(package_id)
    if package_row is None:
        raise HappyclawError.localized(
            ErrorCode.SKILL_PACKAGE_NOT_FOUND,
            resolve_request_locale(request),
        )
    store.assert_can_copy(package_row, user)
    _assert_skill_package_group(server, user, package_row, resolve_request_locale(request))
    try:
        requested_slugs = list(
            dict.fromkeys(validate_skill_slug(slug) for slug in body.skill_slugs)
        )
        copied_identity_keys = set(requested_slugs)
        for slug in requested_slugs:
            copied_identity_keys.update(await _skill_disable_keys(ctx, slug))
        copied = await copy_package_skills_to_workspace(
            store=store,
            package_id=package_id,
            slugs=requested_slugs,
            workspace=ctx.workspace,
            overwrite=body.overwrite,
            copy_policy=normalize_copy_policy(package_row.copy_policy),
        )
    except SkillPackageError as exc:
        raise _skill_transfer_error(
            exc,
            locale=resolve_request_locale(request),
        ) from exc

    for slug in copied:
        copied_identity_keys.update(await _skill_disable_keys(ctx, slug))
    disabled = _disabled_set(ctx.config)
    if disabled.intersection(copied_identity_keys):
        disabled.difference_update(copied_identity_keys)
        await _persist_disabled(server, agent_id, disabled)
    if server.services is not None:
        server.services.audit_repo.write(
            actor=user.username,
            action="skill_package.copied",
            target=package_id,
            payload=",".join(copied)[:200],
        )
    return {"copied": copied}


@router.post(
    "/agents/{agent_id}/skills/{name}/push-to-package",
    summary="Copy a workspace skill into a global skill package",
)
async def push_workspace_skill_to_package(
    agent_id: str,
    name: str,
    body: PushSkillToPackageBody,
    request: Request,
    as_user: int | None = None,
    user: Any = Depends(require_permission("skill_packages")),
    server: Any = Depends(get_server),
) -> dict[str, str]:
    ctx = await _ctx(agent_id, user=user, as_user=as_user, server=server)
    store = _skill_package_store(server)
    row = store.repo.get(body.package_id)
    if row is None:
        raise HappyclawError.localized(
            ErrorCode.SKILL_PACKAGE_NOT_FOUND,
            resolve_request_locale(request),
        )
    store.assert_can_mutate(row, user)
    await _guard_package_only_skill_write(ctx.workspace, ctx.config, server, name, user)
    try:
        slug = await copy_workspace_skill_to_package(
            workspace=ctx.workspace,
            store=store,
            package_id=body.package_id,
            slug=name,
            overwrite=body.overwrite,
        )
    except SkillPackageError as exc:
        raise _skill_transfer_error(
            exc,
            locale=resolve_request_locale(request),
        ) from exc

    assert server.app_runtime is not None
    await server.app_runtime.agent_registry.refresh_agents_for_package(body.package_id)
    return {"package_id": body.package_id, "slug": slug}
