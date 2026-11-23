"""Token usage router — query the usage_log ledger.

  GET /api/usage/summary             → caller's own roll-up
  GET /api/usage/summary?as_user=N   → admin scope; another user's roll-up
  GET /api/usage/summary?agent_id=X  → scope to one agent (must be visible)
  GET /api/usage/export.xlsx         → Excel detail for the same scope
  GET /api/admin/usage/summary       → global roll-up (admin only)
  GET /api/admin/usage/export.xlsx   → Excel detail (admin only)

Query params:
  window      = today | yesterday | last_7d | last_30d | all
                | day:YYYY-MM-DD | month:YYYY-MM
                | range:YYYY-MM-DD:YYYY-MM-DD   (default last_30d)
  granularity = total | by_day | by_agent | by_model | by_user  (default by_day)
"""

from __future__ import annotations

from io import BytesIO
from typing import Any, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from happyclaw.api.common.content_disposition import content_disposition
from happyclaw.api.deps import current_user, get_server
from happyclaw.infra.errors import ErrorCode, HappyclawError
from happyclaw.infra.usage.report import UsageReportService
from happyclaw.infra.utils.locale import resolve_request_locale

router = APIRouter()

_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def build_usage_service(server: Any) -> UsageReportService:
    """Construct a :class:`UsageReportService` bound to *server*'s runtime."""
    assert server.services is not None
    assert server.app_runtime is not None

    config = getattr(server, "config", None)
    tz = getattr(config, "default_timezone", None) if config is not None else None

    return UsageReportService(
        usage_repo=server.services.usage_repo,
        agent_repo=server.services.agent_repo,
        user_manager=server.user_manager,
        agent_exists=lambda aid: server.app_runtime.agent_registry.get_row(aid) is not None,
        timezone=str(tz or "UTC"),
    )


def get_usage_service(server: Any = Depends(get_server)) -> UsageReportService:
    return build_usage_service(server)


@router.get("/usage/summary")
async def user_summary(
    window: str = "last_30d",
    granularity: str = "by_day",
    agent_id: str | None = None,
    as_user: int | None = None,
    user: Any = Depends(current_user),
    service: UsageReportService = Depends(get_usage_service),
) -> dict[str, Any]:
    user_id = service.resolve_user_scope(
        user_id=int(user.id),
        is_admin=bool(getattr(user, "is_admin", False)),
        as_user=as_user,
    )
    service.assert_agent_exists(agent_id)
    return service.summary(
        user_id=user_id,
        agent_id=agent_id,
        window=window,
        granularity=granularity,
    )


@router.get(
    "/usage/export.xlsx",
    summary="Export usage_log detail as Excel",
    response_class=StreamingResponse,
)
async def user_export(
    request: Request,
    window: str = "last_30d",
    agent_id: str | None = None,
    as_user: int | None = None,
    user: Any = Depends(current_user),
    service: UsageReportService = Depends(get_usage_service),
) -> StreamingResponse:
    user_id = service.resolve_user_scope(
        user_id=int(user.id),
        is_admin=bool(getattr(user, "is_admin", False)),
        as_user=as_user,
    )
    service.assert_agent_exists(agent_id)
    locale = resolve_request_locale(request)
    payload, filename = service.export_xlsx(
        user_id=user_id,
        agent_id=agent_id,
        window=window,
        locale=locale,
    )
    return StreamingResponse(
        BytesIO(payload),
        media_type=_XLSX_MEDIA,
        headers={"Content-Disposition": content_disposition(filename)},
    )


# --- admin --------------------------------------------------------------

admin_router = APIRouter()


@admin_router.get("/usage/summary")
async def admin_summary(
    window: str = "last_30d",
    granularity: str = "by_day",
    user_id: int | None = None,
    agent_id: str | None = None,
    user: Any = Depends(current_user),
    service: UsageReportService = Depends(get_usage_service),
) -> dict[str, Any]:
    """Global usage roll-up. Optional ``user_id`` / ``agent_id`` narrow
    the scope; absent both fields mean *all rows*. Admin only."""
    if not getattr(user, "is_admin", False):
        raise HappyclawError(ErrorCode.FORBIDDEN, "admin required")
    return service.summary(
        user_id=user_id,
        agent_id=agent_id,
        window=window,
        granularity=granularity,
    )


@admin_router.get(
    "/usage/export.xlsx",
    summary="Export global usage_log detail as Excel",
    response_class=StreamingResponse,
)
async def admin_export(
    request: Request,
    window: str = "last_30d",
    user_id: int | None = None,
    agent_id: str | None = None,
    user: Any = Depends(current_user),
    service: UsageReportService = Depends(get_usage_service),
) -> StreamingResponse:
    if not getattr(user, "is_admin", False):
        raise HappyclawError(ErrorCode.FORBIDDEN, "admin required")
    locale = resolve_request_locale(request)
    payload, filename = service.export_xlsx(
        user_id=user_id,
        agent_id=agent_id,
        window=window,
        locale=locale,
    )
    return StreamingResponse(
        BytesIO(payload),
        media_type=_XLSX_MEDIA,
        headers={"Content-Disposition": content_disposition(filename)},
    )
