"""ZIP export, agent-to-agent copy and install-from-URL import."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from happyclaw.api.common.agent import require_agent_owner_row
from happyclaw.api.common.content_disposition import content_disposition
from happyclaw.api.deps import get_server, require_permission
from happyclaw.api.routers.skills.common import (
    _ctx,
    _guard_package_only_skill_write,
    _resolve_skill,
    _summary_dict,
)
from happyclaw.api.routers.skills.crud import (
    ImportSkillBody,
    _persist_disabled,
    _skill_disable_keys,
    _write_skill_files,
)
from happyclaw.api.routers.skills.package_mounts import (
    CopyWorkspaceSkillBody,
    _skill_transfer_error,
)
from happyclaw.infra.agents.manager import skills_disabled_set as _disabled_set
from happyclaw.infra.errors import ErrorCode, HappyclawError
from happyclaw.infra.skills.skill_archive import build_skill_zip, build_skills_zip
from happyclaw.infra.skills.skill_packages import SkillPackageError, validate_skill_slug
from happyclaw.infra.skills.skill_transfer import (
    copy_workspace_skill_to_workspace,
    read_workspace_skill_files,
)
from happyclaw.infra.utils.frontmatter import parse_frontmatter
from happyclaw.infra.utils.locale import resolve_request_locale

router = APIRouter()


@router.get(
    "/agents/{agent_id}/skills/{name}/export",
    summary="Download a workspace skill as a ZIP",
    description=(
        "Pack one self-built workspace skill (SKILL.md and sibling files) into a ZIP "
        "whose top-level folder is the skill slug. Built-in skills are not included. "
        "The archive matches the dashboard ZIP importer, so it can be imported onto "
        "another agent or into a skill package."
    ),
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}}},
)
async def export_skill_zip(
    agent_id: str,
    name: str,
    request: Request,
    as_user: int | None = None,
    user: Any = Depends(require_permission("skills")),
    server: Any = Depends(get_server),
) -> Response:
    ctx = await _ctx(agent_id, user=user, as_user=as_user, server=server)
    locale = resolve_request_locale(request)
    try:
        files = await read_workspace_skill_files(ctx.workspace, name)
        safe_slug = validate_skill_slug(name)
        payload = await asyncio.to_thread(build_skill_zip, safe_slug, files)
    except SkillPackageError as exc:
        raise _skill_transfer_error(exc, locale=locale) from exc
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": content_disposition(f"{safe_slug}.zip")},
    )


class ExportSkillsBody(BaseModel):
    slugs: list[str] = Field(min_length=1)


@router.post(
    "/agents/{agent_id}/skills/export",
    summary="Download workspace skills as one ZIP",
    description=(
        "Pack the selected workspace skills into one ZIP. Each skill is a top-level "
        "folder containing SKILL.md, which is the layout the dashboard ZIP importer "
        "already accepts."
    ),
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}}},
)
async def export_skills_zip(
    agent_id: str,
    body: ExportSkillsBody,
    request: Request,
    as_user: int | None = None,
    user: Any = Depends(require_permission("skills")),
    server: Any = Depends(get_server),
) -> Response:
    ctx = await _ctx(agent_id, user=user, as_user=as_user, server=server)
    locale = resolve_request_locale(request)
    slugs = list(dict.fromkeys(body.slugs))
    try:
        packed: list[tuple[str, list[tuple[str, bytes]]]] = []
        for slug in slugs:
            files = await read_workspace_skill_files(ctx.workspace, slug)
            packed.append((validate_skill_slug(slug), files))
        payload = await asyncio.to_thread(build_skills_zip, packed)
    except SkillPackageError as exc:
        raise _skill_transfer_error(exc, locale=locale) from exc
    filename = f"{packed[0][0]}.zip" if len(packed) == 1 else "skills.zip"
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": content_disposition(filename)},
    )


# --- write endpoints --------------------------------------------------------


class _AgentWorkspaceInstallTarget:
    """Install skills into an agent workspace (``skills/<slug>/``)."""

    def __init__(
        self,
        *,
        workspace: Any,
        config: dict[str, Any],
        server: Any,
        agent_id: str,
    ) -> None:
        self._workspace = workspace
        self._config = config
        self._server = server
        self._agent_id = agent_id

    async def skill_exists(self, slug: str) -> bool:
        return await _resolve_skill(self._workspace, slug) is not None

    async def write_files(self, slug: str, files: list[tuple[str, bytes]]) -> None:
        skill_root = f"skills/{slug}"
        with contextlib.suppress(Exception):
            await self._workspace.adelete(skill_root)
        await _write_skill_files(self._workspace, skill_root, files)

    async def after_install(self, slug: str, *, enable: bool | None = None) -> None:
        if not enable:
            return
        disabled = _disabled_set(self._config)
        disabled.discard(slug)
        await _persist_disabled(self._server, self._agent_id, disabled)


@router.post(
    "/agents/{agent_id}/skills/copy",
    status_code=201,
    summary="Copy a workspace skill from another agent",
)
async def copy_skill_from_agent(
    agent_id: str,
    body: CopyWorkspaceSkillBody,
    request: Request,
    as_user: int | None = None,
    user: Any = Depends(require_permission("skills")),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    dest = await _ctx(agent_id, user=user, as_user=as_user, server=server)
    require_agent_owner_row(body.source_agent_id, user=user, as_user=as_user, server=server)
    assert server.app_runtime is not None
    source = server.app_runtime.agent_registry.workspace_for_agent(body.source_agent_id)
    if source is None:
        raise HappyclawError(ErrorCode.NOT_FOUND, "source workspace not found")
    locale = resolve_request_locale(request)
    try:
        slug = validate_skill_slug(body.slug)
        copied_identity_keys = set(await _skill_disable_keys(dest, slug))
        copied = await copy_workspace_skill_to_workspace(
            source=source,
            destination=dest.workspace,
            slug=slug,
            overwrite=body.overwrite,
        )
    except SkillPackageError as exc:
        raise _skill_transfer_error(exc, locale=locale) from exc
    copied_identity_keys.update(await _skill_disable_keys(dest, copied))
    disabled = _disabled_set(dest.config)
    if disabled.intersection(copied_identity_keys):
        disabled.difference_update(copied_identity_keys)
        await _persist_disabled(server, agent_id, disabled)
    return {"slug": copied, "copied": True}


@router.post("/agents/{agent_id}/skills/import", status_code=201)
async def import_skill_from_url(
    agent_id: str,
    body: ImportSkillBody,
    request: Request,
    as_user: int | None = None,
    user: Any = Depends(require_permission("skills")),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Import a skill bundle from a supported external URL into the agent workspace."""
    from urllib.error import HTTPError, URLError

    from happyclaw.infra.skills.install import (  # noqa: PLC0415
        SkillAlreadyExistsError,
        commit_skill_install,
        resolve_url_import,
    )
    from happyclaw.infra.skills.skills_hub import is_supported_skill_url  # noqa: PLC0415

    locale = resolve_request_locale(request)
    bundle_url = body.bundle_url.strip()
    if not bundle_url:
        raise HappyclawError(ErrorCode.SLASH_BAD_ARGS, "bundle_url is required")
    if not is_supported_skill_url(bundle_url):
        raise HappyclawError.localized(ErrorCode.SKILL_IMPORT_UNSUPPORTED_URL, locale)

    ctx = await _ctx(agent_id, user=user, as_user=as_user, server=server)
    target = _AgentWorkspaceInstallTarget(
        workspace=ctx.workspace,
        config=ctx.config,
        server=server,
        agent_id=agent_id,
    )

    try:
        package = await asyncio.to_thread(
            resolve_url_import,
            bundle_url=bundle_url,
            version=body.version,
        )
        await _guard_package_only_skill_write(ctx.workspace, ctx.config, server, package.slug, user)
        await commit_skill_install(
            target,
            package,
            overwrite=body.overwrite,
            enable=body.enable,
        )
    except SkillAlreadyExistsError as exc:
        raise HappyclawError.localized(
            ErrorCode.SKILL_ALREADY_EXISTS,
            locale,
            name=exc.slug,
        ) from exc
    except SkillPackageError as exc:
        raise HappyclawError.localized(
            ErrorCode.SKILL_IMPORT_FAILED,
            locale,
            reason=str(exc),
        ) from exc
    except ValueError as exc:
        raise HappyclawError.localized(
            ErrorCode.SKILL_IMPORT_FAILED,
            locale,
            reason=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HappyclawError.localized(
            ErrorCode.SKILL_IMPORT_FAILED,
            locale,
            reason=str(exc),
        ) from exc
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise HappyclawError.localized(
            ErrorCode.SKILL_IMPORT_FAILED,
            locale,
            reason=str(exc),
        ) from exc

    skill_md = next(
        (content for path, content in package.files if path == "SKILL.md"),
        b"",
    )
    meta, _body = parse_frontmatter(skill_md.decode("utf-8"))
    return _summary_dict(
        package.slug,
        meta,
        enabled=body.enable,
        kind="workspace",
    )
