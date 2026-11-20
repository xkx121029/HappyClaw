"""HTTP surface for the DSH compatibility adapter.

Mounted at ``/api/dsh-compat``. Every route is inert while the switch is off:
``/status`` reports ``enabled: false`` and control routes answer 503 with a
stable code instead of spawning anything.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from octop.api.deps import current_user
from octop.infra.dsh.compat.client_asset import resolve_client_file, slot_map
from octop.infra.dsh.compat.errors import DshCompatCode, DshCompatError
from octop.infra.dsh.compat.probe import run_inventory
from octop.infra.dsh.compat.registry import _market_root, get_registry
from octop.infra.dsh.compat.switch import compat_enabled

router = APIRouter(tags=["dsh-compat"])


class UiReportBody(BaseModel):
    plugin_id: str
    state: str = Field(default="unknown")
    error: str = ""


class ToolCallBody(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


def _error(exc: DshCompatError, status: int = 409) -> HTTPException:
    return HTTPException(status_code=status, detail=exc.to_dict())


def _require_enabled() -> None:
    if not compat_enabled():
        raise HTTPException(
            status_code=503,
            detail={
                "code": DshCompatCode.DISABLED.value,
                "message": "DSH compatibility adapter is disabled (set OCTOP_DSH_COMPAT=1)",
            },
        )


def _require_plugin(plugin_id: str):
    state = get_registry().state(plugin_id)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail={"code": DshCompatCode.ENTRY_SHAPE.value, "message": f"plugin {plugin_id} is not installed"},
        )
    return state


@router.get("/status")
async def status(_user: Any = Depends(current_user)) -> dict[str, Any]:
    return get_registry().status()


@router.post("/refresh")
async def refresh(_user: Any = Depends(current_user)) -> dict[str, Any]:
    _require_enabled()
    await asyncio.to_thread(get_registry().refresh, force=True)
    return get_registry().status()


@router.post("/{plugin_id}/start")
async def start(plugin_id: str, _user: Any = Depends(current_user)) -> dict[str, Any]:
    _require_enabled()
    _require_plugin(plugin_id)
    try:
        state = await asyncio.to_thread(get_registry().start, plugin_id)
    except DshCompatError as exc:
        raise _error(exc) from exc
    return state.to_dict()


@router.post("/{plugin_id}/stop")
async def stop(plugin_id: str, _user: Any = Depends(current_user)) -> dict[str, Any]:
    _require_enabled()
    _require_plugin(plugin_id)
    state = await asyncio.to_thread(get_registry().stop, plugin_id)
    return state.to_dict()


@router.post("/report")
async def report(body: UiReportBody, _user: Any = Depends(current_user)) -> dict[str, Any]:
    get_registry().report_ui(body.plugin_id, body.state, body.error)
    return {"ok": True}


@router.get("/slots")
async def slots(_user: Any = Depends(current_user)) -> dict[str, Any]:
    return {
        "host_slots": [
            "home.sidebar",
            "chat.messages.top",
            "conversation.view",
            "conversation.input.left",
            "conversation.input.overlay",
            "settings.section",
        ],
        "map": slot_map(),
    }


@router.get("/inventory")
async def inventory(_user: Any = Depends(current_user)) -> dict[str, Any]:
    report = await asyncio.to_thread(
        run_inventory,
        [_market_root()],
        dynamic=False,
    )
    return report


@router.post("/{plugin_id}/tools/{tool_name}")
async def call_tool(
    plugin_id: str,
    tool_name: str,
    body: ToolCallBody,
    _user: Any = Depends(current_user),
) -> dict[str, Any]:
    _require_enabled()
    _require_plugin(plugin_id)
    try:
        result = await asyncio.to_thread(
            get_registry().call_tool, plugin_id, tool_name, body.arguments
        )
    except DshCompatError as exc:
        raise _error(exc) from exc
    return result


@router.get("/ui/{native_id}/client.js")
async def client_js(native_id: str, _user: Any = Depends(current_user)):
    state = get_registry().state(f"dsh:{native_id}")
    if state is None:
        raise HTTPException(status_code=404, detail={"code": "ENTRY_SHAPE", "message": "unknown plugin"})
    if not state.allowed:
        raise HTTPException(
            status_code=403,
            detail={"code": DshCompatCode.NOT_ALLOWED.value, "message": "plugin is not in the allow list"},
        )
    rel = state.client.entry
    path = resolve_client_file(state.package_dir, rel) if rel else None
    if path is None:
        raise HTTPException(
            status_code=404,
            detail={"code": state.client.code, "message": "client entry is missing or not servable"},
        )
    return FileResponse(path, media_type="text/javascript; charset=utf-8")


@router.api_route("/route/{plugin_id}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy(plugin_id: str, path: str, request: Request, _user: Any = Depends(current_user)):
    _require_enabled()
    _require_plugin(plugin_id)
    raw = await request.body()
    headers = {key.lower(): value for key, value in request.headers.items()}
    try:
        result = await asyncio.to_thread(
            get_registry().dispatch_http,
            plugin_id,
            method=request.method,
            path=f"/{path}",
            headers=headers,
            body=raw.decode("utf-8", errors="replace"),
        )
    except DshCompatError as exc:
        raise _error(exc, status=502) from exc
    return JSONResponse(
        content=result.get("body", ""),
        status_code=int(result.get("status") or 200),
        headers=result.get("headers") or {},
    )


__all__ = ["router"]
