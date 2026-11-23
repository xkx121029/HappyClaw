"""SkillHub search and rankings for the package picker."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from happyclaw.api.deps import require_permission
from happyclaw.infra.users.identity import User

router = APIRouter()

@router.get("/hub/search", summary="Search SkillHub for installing into packages")
async def package_hub_search(
    q: str = "",
    limit: int = 50,
    _user: User = Depends(require_permission("skill_packages")),
) -> list[dict[str, Any]]:
    from fastapi import HTTPException  # noqa: PLC0415

    from happyclaw.infra.skills.skillhub_market import (  # noqa: PLC0415
        SkillHubMarketError,
        search_skillhub,
    )

    query = q.strip() or "a"
    effective_limit = max(1, min(limit, 100))
    try:
        return await search_skillhub(query, limit=effective_limit)
    except SkillHubMarketError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/hub/rankings", summary="SkillHub rankings for installing into packages")
async def package_hub_rankings(
    type: str = "all",
    _user: User = Depends(require_permission("skill_packages")),
) -> dict[str, Any]:
    from fastapi import HTTPException  # noqa: PLC0415

    from happyclaw.infra.skills.skillhub_market import (  # noqa: PLC0415
        SkillHubMarketError,
        SkillHubMarketTimeout,
        fetch_skillhub_rankings,
    )

    ranking_types = {"all", "hot", "featured", "newest", "recommended", "trending", "paid"}
    rtype = type if type in ranking_types else "all"
    try:
        return await fetch_skillhub_rankings(rtype)
    except SkillHubMarketTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except SkillHubMarketError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
