"""SkillHub search, rankings and install into an agent workspace."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from happyclaw.api.common.agent import require_agent_owner_row
from happyclaw.api.deps import current_user, get_server, require_permission
from happyclaw.api.routers.skills.common import _ctx, _guard_package_only_skill_write
from happyclaw.api.routers.skills.transfer import _AgentWorkspaceInstallTarget
from happyclaw.infra.skills.skill_packages import (
    SkillPackageError,
    SkillPackageTooLarge,
    validate_skill_slug,
)

router = APIRouter()


class LocalizedSkillCopy(BaseModel):
    zh: str | None = None
    en: str | None = None


class HubInstallBody(BaseModel):
    skill_name: str
    enable: bool = True
    display_name: str | None = None
    icon_url: str | None = None
    label: LocalizedSkillCopy | None = None
    summary: LocalizedSkillCopy | None = None


_RANKING_TYPES = {"all", "hot", "featured", "newest", "recommended", "trending", "paid"}


async def _hub_search(*, q: str, limit: int) -> list[dict[str, Any]]:
    from fastapi import HTTPException  # noqa: PLC0415

    query = q.strip() or "a"
    effective_limit = max(1, min(limit, 100))
    from happyclaw.infra.skills.skillhub_market import (  # noqa: PLC0415
        SkillHubMarketError,
        search_skillhub,
        skill_market_failure_status,
    )

    try:
        return await search_skillhub(query, limit=effective_limit)
    except SkillHubMarketError as exc:
        raise HTTPException(
            status_code=skill_market_failure_status(exc),
            detail=str(exc),
        ) from exc


async def _hub_rankings(ranking_type: str) -> dict[str, Any]:
    from fastapi import HTTPException  # noqa: PLC0415

    rtype = ranking_type if ranking_type in _RANKING_TYPES else "all"
    from happyclaw.infra.skills.skillhub_market import (  # noqa: PLC0415
        SkillHubMarketError,
        SkillHubMarketTimeout,
        fetch_skillhub_rankings,
    )

    try:
        return await fetch_skillhub_rankings(rtype)
    except SkillHubMarketTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except SkillHubMarketError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/skills/hub/search", summary="Search SkillHub without an agent")
async def hub_search_skills_global(
    q: str = "",
    limit: int = 50,
    _user: Any = Depends(current_user),
) -> list[dict[str, Any]]:
    """Browse SkillHub while composing a new expert (no agent exists yet)."""
    return await _hub_search(q=q, limit=limit)


@router.get("/skills/hub/rankings", summary="SkillHub rankings without an agent")
async def hub_rankings_global(
    type: str = "all",
    _user: Any = Depends(current_user),
) -> dict[str, Any]:
    """Browse SkillHub rankings while composing a new expert."""
    return await _hub_rankings(type)


@router.get("/agents/{agent_id}/skills/hub/search")
async def hub_search_skills(
    agent_id: str,
    q: str = "",
    limit: int = 50,
    as_user: int | None = None,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> list[dict[str, Any]]:
    """Search the skill market over HTTP.

    The agent_id param is accepted for auth/routing symmetry with
    the install endpoint but is not used for the search itself.
    """
    require_agent_owner_row(agent_id, user=user, as_user=as_user, server=server)
    return await _hub_search(q=q, limit=limit)


@router.get("/agents/{agent_id}/skills/hub/rankings")
async def hub_rankings(
    agent_id: str,
    type: str = "all",
    as_user: int | None = None,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Fetch Tencent SkillHub rankings directly over HTTP.

    Returns the same payload shape previously produced by
    ``skillhub skill rankings`` (typically ``section``, ``skills``, ``total``).
    ``type`` selects a section (all / hot / recommended / trending / newest /
    featured / paid). The host is ``SKILL_MARKET_ORIGIN``, else
    https://api.skillhub.cn. The agent_id is accepted for auth/routing
    symmetry with search/install; rankings are global.
    """
    require_agent_owner_row(agent_id, user=user, as_user=as_user, server=server)
    return await _hub_rankings(type)


@router.post("/agents/{agent_id}/skills/hub/install", status_code=201)
async def hub_install_skill(
    agent_id: str,
    body: HubInstallBody,
    as_user: int | None = None,
    user: Any = Depends(require_permission("skills")),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Install a SkillHub skill into the specified agent's workspace.

    The package is downloaded and validated over HTTP.
    """
    from fastapi import HTTPException  # noqa: PLC0415

    from happyclaw.infra.skills.install import (  # noqa: PLC0415
        SkillAlreadyExistsError,
        install_skill_from_skillhub,
        valid_skillhub_icon_url,
    )
    from happyclaw.infra.skills.skillhub_market import (  # noqa: PLC0415
        SkillHubMarketError,
        SkillHubPackageError,
        SkillHubPackageTooLarge,
        download_skillhub_package,
        skill_market_failure_status,
    )

    try:
        skill_name = validate_skill_slug(body.skill_name)
    except SkillPackageError:
        raise HTTPException(
            status_code=400,
            detail="skill_name is required and must not contain path separators or start with .",
        ) from None
    display_name = (body.display_name or "").strip()
    icon_url = (body.icon_url or "").strip()
    label = (
        {key: value.strip() for key, value in body.label.model_dump().items() if value}
        if body.label
        else {}
    )
    summary = (
        {key: value.strip() for key, value in body.summary.model_dump().items() if value}
        if body.summary
        else {}
    )
    if len(display_name) > 200:
        raise HTTPException(status_code=400, detail="display_name is too long")
    if any(len(value) > 200 for value in label.values()):
        raise HTTPException(status_code=400, detail="localized skill label is too long")
    if any(len(value) > 1024 for value in summary.values()):
        raise HTTPException(status_code=400, detail="localized skill summary is too long")
    if len(icon_url) > 2048 or (icon_url and not valid_skillhub_icon_url(icon_url)):
        raise HTTPException(status_code=400, detail="icon_url must be an HTTP(S) URL")

    ctx = await _ctx(agent_id, user=user, as_user=as_user, server=server)
    target = _AgentWorkspaceInstallTarget(
        workspace=ctx.workspace,
        config=ctx.config,
        server=server,
        agent_id=agent_id,
    )
    transport = "http"
    try:
        files = await download_skillhub_package(skill_name)
    except SkillHubPackageTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except SkillHubPackageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except SkillHubMarketError as exc:
        raise HTTPException(
            status_code=skill_market_failure_status(exc),
            detail=str(exc),
        ) from exc

    await _guard_package_only_skill_write(ctx.workspace, ctx.config, server, skill_name, user)
    try:
        await install_skill_from_skillhub(
            target,
            skill_name=skill_name,
            files=files,
            display_name=display_name,
            icon_url=icon_url,
            label=label,
            summary=summary,
            overwrite=True,
            enable=body.enable,
        )
    except SkillAlreadyExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"skill '{exc.slug}' already exists",
        ) from exc
    except SkillPackageTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except SkillPackageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "installed": True,
        "name": skill_name,
        "enabled": body.enable,
        "transport": transport,
    }
