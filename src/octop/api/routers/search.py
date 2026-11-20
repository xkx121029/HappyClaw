"""Search-provider connectivity API (Settings → Advanced → Search)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from octop.api.deps import get_server, require_permission
from octop.infra.utils.search_probe import probe_search_provider

router = APIRouter(prefix="/search", tags=["search"])


class TestSearchRequest(BaseModel):
    env_vars: dict[str, str] = Field(
        ...,
        description="Provider env vars to use for this probe (not persisted).",
    )


class TestSearchResponse(BaseModel):
    success: bool
    provider_id: str
    response_time_ms: int
    result_count: int | None = None
    message: str | None = None
    error: str | None = None
    error_type: str | None = Field(
        None,
        description=(
            "auth_error | insufficient_balance | rate_limit | timeout | "
            "network_error | invalid_config | unknown"
        ),
    )


@router.get(
    "/happy/status",
    summary="HappySearch embedded tool status",
    description=(
        "Read-only snapshot: whether the tool is enabled, its engine/timeout/"
        "concurrency config, and the last run (query, latency, engines that "
        "succeeded/returned empty/failed, fallback usage)."
    ),
)
async def happysearch_status(
    _: Any = Depends(require_permission("search")),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    from octop.infra.search.happy_tool import happysearch_status as snapshot  # noqa: PLC0415
    from octop.infra.search.source import load_source  # noqa: PLC0415

    state = load_source(server.services.settings_repo)
    return snapshot(enabled=state.effective in ("happysearch", "both"))


@router.get(
    "/status",
    summary="Free search source and runtime status",
    description=(
        "Aggregated read-only snapshot: effective/persisted/env search source, "
        "model-visible tool names, configured commercial providers, HappySearch "
        "engine health, native searchfree health, and the last query."
    ),
)
async def search_status(
    _: Any = Depends(require_permission("search")),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    from octop.infra.search.happy_tool import happysearch_status  # noqa: PLC0415
    from octop.infra.search.native_tool import searchfree_status  # noqa: PLC0415
    from octop.infra.search.source import (  # noqa: PLC0415
        commercial_providers,
        load_source,
        visible_tool_names,
    )

    state = load_source(server.services.settings_repo)
    happy = happysearch_status(enabled=state.effective in ("happysearch", "both"))
    native = searchfree_status()

    if state.effective == "searchfree":
        last_raw = native["runtime"].get("last")
        used_source = "searchfree"
    else:
        last_raw = happy["runtime"].get("last")
        used_source = (last_raw or {}).get("source") or state.effective

    last = None
    if last_raw:
        last = {
            "used_source": used_source,
            "query": last_raw.get("query"),
            "elapsed_ms": last_raw.get("elapsed_ms"),
            "fallback": bool(last_raw.get("fallback")),
            "fallback_count": (
                happy["runtime"].get("fallbacks", 0)
                if state.effective != "searchfree"
                else 0
            ),
            "status": last_raw.get("status"),
            "degraded": bool(last_raw.get("degraded")),
            "at": last_raw.get("finished_at") or last_raw.get("started_at"),
        }

    return {
        "source": {
            "effective": state.effective,
            "stored": state.stored,
            "env": state.env,
            "origin": state.origin,
        },
        "tools_visible": visible_tool_names(state, agent_cfg={}),
        "commercial_providers": commercial_providers(),
        "happysearch": happy,
        "searchfree": native,
        "last": last,
    }


@router.post(
    "/{provider_id}/test",
    response_model=TestSearchResponse,
    summary="Test search provider API key",
    description=(
        "Run a one-shot query against a web-search provider using the supplied "
        "env vars (TAVILY_API_KEY, BRAVE_API_KEY, DEEPSEEK_API_KEY, "
        "GOOGLE_API_KEY + GOOGLE_CSE_ID, MOONSHOT_API_KEY, or "
        "TENCENTCLOUD_WSA_APIKEY). Credentials are not written to ~/.octop/env."
    ),
)
async def test_search_provider(
    provider_id: str,
    body: TestSearchRequest,
    _: Any = Depends(require_permission("search")),
) -> TestSearchResponse:
    result = await probe_search_provider(provider_id, body.env_vars)
    return TestSearchResponse(**result)
