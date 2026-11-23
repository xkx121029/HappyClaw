"""Skill list / detail / create / update / delete and enable-disable."""

from __future__ import annotations

import base64
import contextlib
from collections.abc import Sequence
from typing import Any, cast

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from happyclaw.api.deps import current_user, get_server, require_permission
from happyclaw.api.routers.skills.common import (
    _AgentCtx,
    _aoverwrite_text,
    _aread_text,
    _ctx,
    _guard_package_only_skill_write,
    _resolve_skill,
    _summary_dict,
)
from happyclaw.infra.agents.manager import skills_disabled_set as _disabled_set
from happyclaw.infra.errors import ErrorCode, HappyclawError
from happyclaw.infra.skills.skill_packages import (
    SkillPackageError,
    SkillPackageTooLarge,
    resolve_skill_package,
    validate_skill_slug,
)
from happyclaw.infra.utils.frontmatter import parse_frontmatter
from happyclaw.infra.utils.locale import resolve_request_locale

router = APIRouter()

@router.get("/agents/{agent_id}/skills")
async def list_skills(
    agent_id: str,
    request: Request,
    as_user: int | None = None,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> list[dict[str, Any]]:
    await _ctx(agent_id, user=user, as_user=as_user, server=server, owner_only=False)
    assert server.app_runtime is not None
    return cast(
        list[dict[str, Any]],
        await server.app_runtime.agent_registry.list_skill_summaries(
            agent_id,
            locale=resolve_request_locale(request),
        ),
    )


@router.get("/agents/{agent_id}/skills/{name}")
async def get_skill(
    agent_id: str,
    name: str,
    request: Request,
    as_user: int | None = None,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    ctx = await _ctx(
        agent_id,
        user=user,
        as_user=as_user,
        server=server,
        owner_only=False,
    )
    resolved = await _resolve_skill(ctx.workspace, name)
    if resolved is None:
        raise HappyclawError(ErrorCode.NOT_FOUND, f"skill {name!r} not found")
    manifest_path, kind, _body = resolved
    manifest = await _aread_text(ctx.workspace, manifest_path)
    assert manifest is not None
    meta, body = parse_frontmatter(manifest)
    disabled = _disabled_set(ctx.config)
    return {
        **_summary_dict(
            name,
            meta,
            enabled=name not in disabled,
            kind=kind,
            locale=resolve_request_locale(request),
        ),
        "frontmatter": meta,
        "body": body,
        "raw": manifest,
    }


class SkillFilePart(BaseModel):
    path: str
    content_base64: str


class CreateSkillBody(BaseModel):
    name: str
    content: str = ""
    files: list[SkillFilePart] | None = None
    overwrite: bool = False


class UpdateSkillBody(BaseModel):
    content: str = ""
    files: list[SkillFilePart] | None = None


class ImportSkillBody(BaseModel):
    bundle_url: str
    version: str = ""
    enable: bool = True
    overwrite: bool = False


async def _write_skill_files(
    workspace: Any,
    skill_root: str,
    files: Sequence[tuple[str, bytes]],
) -> None:
    """Write skill files into a workspace, creating empty directories first."""
    dirs = [path for path, _content in files if path.endswith("/")]
    payload = [(path, content) for path, content in files if not path.endswith("/")]
    for path in dirs:
        await workspace.amkdir(f"{skill_root}/{path}".rstrip("/"))
    if payload:
        await workspace.aupload_many(
            [(f"{skill_root}/{path}", content) for path, content in payload]
        )


def _files_from_skill_body(
    *,
    content: str,
    files: list[SkillFilePart] | None,
) -> list[tuple[str, bytes]]:
    if files:
        decoded: list[tuple[str, bytes]] = []
        for part in files:
            try:
                decoded.append((part.path, base64.b64decode(part.content_base64, validate=True)))
            except Exception as exc:
                raise HappyclawError(
                    ErrorCode.SLASH_BAD_ARGS,
                    f"invalid base64 content for {part.path!r}",
                ) from exc
        return decoded
    if not content:
        raise HappyclawError(ErrorCode.SLASH_BAD_ARGS, "content or files is required")
    return [("SKILL.md", content.encode("utf-8"))]


@router.post("/agents/{agent_id}/skills", status_code=201)
async def create_skill(
    agent_id: str,
    body: CreateSkillBody,
    as_user: int | None = None,
    user: Any = Depends(require_permission("skills")),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    ctx = await _ctx(agent_id, user=user, as_user=as_user, server=server)
    try:
        name = validate_skill_slug(body.name)
        package = resolve_skill_package(
            slug=name,
            files=_files_from_skill_body(content=body.content, files=body.files),
            source="manual",
        )
    except SkillPackageTooLarge as exc:
        raise HappyclawError(ErrorCode.SLASH_BAD_ARGS, str(exc)) from exc
    except SkillPackageError:
        raise HappyclawError(ErrorCode.NOT_FOUND, "invalid skill name") from None
    await _guard_package_only_skill_write(ctx.workspace, ctx.config, server, name, user)
    # Conflict check must use SKILL.md — ZIP payloads often list siblings first,
    # and soft-delete only marks the manifest (leaving sibling files behind).
    existing = await _aread_text(ctx.workspace, f"skills/{name}/SKILL.md")
    if existing is not None:
        meta, _ = parse_frontmatter(existing)
        if not meta.get("removed") and not body.overwrite:
            raise HappyclawError(ErrorCode.SKILL_ALREADY_EXISTS, f"skill {name!r} already exists")
    with contextlib.suppress(Exception):
        await ctx.workspace.adelete(f"skills/{name}")
    await _write_skill_files(ctx.workspace, f"skills/{name}", package.files)
    # Reinstall after disable/delete must clear skills_disabled (ZIP create
    # always installs as enabled, matching URL import with enable=True).
    disabled = _disabled_set(ctx.config)
    if name in disabled:
        disabled.discard(name)
        await _persist_disabled(server, agent_id, disabled)
    skill_md = next(
        (content for path, content in package.files if path == "SKILL.md"),
        body.content.encode("utf-8"),
    )
    meta, _body = parse_frontmatter(skill_md.decode("utf-8", errors="replace"))
    return _summary_dict(name, meta, enabled=True, kind="workspace")


@router.put("/agents/{agent_id}/skills/{name}")
async def update_skill(
    agent_id: str,
    name: str,
    body: UpdateSkillBody,
    as_user: int | None = None,
    user: Any = Depends(require_permission("skills")),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Overwrite an installed workspace skill via BackendWorkspace only.

    A ``content``-only body (the dashboard editor edits SKILL.md) rewrites just
    the manifest in place - sibling files and directories are preserved. A
    ``files`` payload replaces the whole skill directory, matching
    create-with-overwrite / re-import semantics.
    """
    ctx = await _ctx(agent_id, user=user, as_user=as_user, server=server)
    try:
        slug = validate_skill_slug(name)
        package = resolve_skill_package(
            slug=slug,
            files=_files_from_skill_body(content=body.content, files=body.files),
            source="manual",
        )
    except SkillPackageTooLarge as exc:
        raise HappyclawError(ErrorCode.SLASH_BAD_ARGS, str(exc)) from exc
    except SkillPackageError:
        raise HappyclawError(ErrorCode.NOT_FOUND, "invalid skill name") from None

    await _guard_package_only_skill_write(ctx.workspace, ctx.config, server, slug, user)
    existing = await _aread_text(ctx.workspace, f"skills/{slug}/SKILL.md")
    if existing is None:
        raise HappyclawError(ErrorCode.NOT_FOUND, f"skill {slug!r} not found")
    meta_existing, _ = parse_frontmatter(existing)
    if meta_existing.get("removed"):
        raise HappyclawError(ErrorCode.NOT_FOUND, f"skill {slug!r} not found")

    # ``content``-only updates (the dashboard editor edits SKILL.md) must keep
    # the skill's sibling files and directories (README.md, references/, ...)
    # intact - deleting the whole directory here wiped imported ZIP skills down
    # to a lone SKILL.md. A full ``files`` payload still replaces the directory
    # wholesale, matching create-with-overwrite / re-import semantics. The
    # truthiness check mirrors ``_files_from_skill_body`` so an empty ``files``
    # list falls back to the content path on both sides.
    if body.files:
        with contextlib.suppress(Exception):
            await ctx.workspace.adelete(f"skills/{slug}")
    await _write_skill_files(ctx.workspace, f"skills/{slug}", package.files)
    skill_md = next(
        (content for path, content in package.files if path == "SKILL.md"),
        body.content.encode("utf-8"),
    )
    meta, _body = parse_frontmatter(skill_md.decode("utf-8", errors="replace"))
    disabled = _disabled_set(ctx.config)
    return _summary_dict(
        slug,
        meta,
        enabled=slug not in disabled,
        kind="workspace",
    )


@router.delete("/agents/{agent_id}/skills/{name}", status_code=204)
async def delete_skill(
    agent_id: str,
    name: str,
    as_user: int | None = None,
    user: Any = Depends(require_permission("skills")),
    server: Any = Depends(get_server),
) -> None:
    """Soft-delete via marker — see module docstring for rationale."""
    ctx = await _ctx(agent_id, user=user, as_user=as_user, server=server)
    try:
        slug = validate_skill_slug(name)
    except SkillPackageError:
        raise HappyclawError(ErrorCode.NOT_FOUND, "invalid skill name") from None
    await _guard_package_only_skill_write(ctx.workspace, ctx.config, server, slug, user)
    resolved = await _resolve_skill(ctx.workspace, slug)
    if resolved is None:
        raise HappyclawError(ErrorCode.NOT_FOUND, f"skill {slug!r} not found")
    manifest_path, kind, _body = resolved
    if kind == "builtin":
        raise HappyclawError(ErrorCode.NOT_FOUND, f"builtin skill {name!r} cannot be deleted")
    target = manifest_path
    existing = await _aread_text(ctx.workspace, target)
    if existing is None:
        raise HappyclawError(ErrorCode.NOT_FOUND, f"skill {name!r} not found")
    err = await _aoverwrite_text(ctx.workspace, target, "---\nremoved: true\n---\n")
    if err:
        raise HappyclawError(ErrorCode.NOT_FOUND, f"cannot remove {target!r}: {err}")


# --- enable / disable -------------------------------------------------------


async def _persist_disabled(server: Any, agent_id: str, disabled: set[str]) -> None:
    """Write back ``skills_disabled`` and hot-sync the running harness agent."""
    assert server.app_runtime is not None
    await server.app_runtime.agent_registry.persist_skills_disabled(agent_id, disabled)


async def _skill_disable_keys(ctx: _AgentCtx, name: str) -> set[str]:
    """Return slug / display-name keys to toggle for enable/disable."""
    from happyclaw_harness.skills.catalog import skill_identity_keys

    slug = name.strip()
    keys = {slug} if slug else set()
    resolved = await _resolve_skill(ctx.workspace, slug)
    if resolved is None:
        return keys
    manifest_path, kind, _body = resolved
    manifest = await _aread_text(ctx.workspace, manifest_path)
    if manifest is None:
        return keys
    meta, _ = parse_frontmatter(manifest)
    summary = _summary_dict(slug, meta, enabled=False, kind=kind)
    keys |= skill_identity_keys(
        {
            "name": summary["name"],
            "slug": summary["slug"],
            "path": manifest_path,
        }
    )
    return keys


@router.post("/agents/{agent_id}/skills/{name}/enable", status_code=204)
async def enable_skill(
    agent_id: str,
    name: str,
    as_user: int | None = None,
    user: Any = Depends(require_permission("skills")),
    server: Any = Depends(get_server),
) -> None:
    ctx = await _ctx(agent_id, user=user, as_user=as_user, server=server)
    disabled = _disabled_set(ctx.config)
    keys = await _skill_disable_keys(ctx, name)
    if disabled & keys:
        disabled -= keys
        await _persist_disabled(server, agent_id, disabled)


@router.post("/agents/{agent_id}/skills/{name}/disable", status_code=204)
async def disable_skill(
    agent_id: str,
    name: str,
    as_user: int | None = None,
    user: Any = Depends(require_permission("skills")),
    server: Any = Depends(get_server),
) -> None:
    ctx = await _ctx(agent_id, user=user, as_user=as_user, server=server)
    disabled = _disabled_set(ctx.config)
    disabled |= await _skill_disable_keys(ctx, name)
    await _persist_disabled(server, agent_id, disabled)
