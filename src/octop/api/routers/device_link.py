"""设备链路（HappyClaw ↔ 手机 App）HTTP / SSE 接口。

App 主动连过来的跨局域网 TLS 长连接，服务端地址由用户配置，不做同网段自动发现。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from octop.api.deps import require_permission
from octop.infra.control.device_link.client import DeviceLinkError
from octop.infra.control.device_link.manager import get_device_link_manager
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.identity import User

router = APIRouter()


class PairBody(BaseModel):
    host: str = Field(description="设备所在局域网地址（可配置，不假设同网段）")
    port: int = Field(gt=0, le=65535, description="设备链路端口")
    code: str = Field(min_length=6, max_length=12, description="设备上显示的配对码")
    client_name: str = Field(default="HappyClaw", max_length=64)


class ConnectBody(BaseModel):
    host: str | None = None
    port: int | None = Field(default=None, gt=0, le=65535)


class CommandBody(BaseModel):
    name: str
    params: dict[str, Any] = Field(default_factory=dict)
    command_id: str | None = Field(
        default=None,
        description="幂等键；重试必须复用同一个值，设备侧只会执行一次",
    )
    timeout_ms: int | None = Field(default=None, ge=100, le=120_000)


@router.get("/device-link/status", summary="Device link status")
async def device_link_status(
    _user: User = Depends(require_permission("mobile")),
) -> dict[str, Any]:
    return await get_device_link_manager().status()


@router.get("/device-link/commands", summary="Device link command catalog")
async def device_link_commands(
    _user: User = Depends(require_permission("mobile")),
) -> dict[str, Any]:
    manager = get_device_link_manager()
    return {"commands": manager.catalog()}


@router.post("/device-link/pair", summary="Pair with a device using the on-screen code")
async def device_link_pair(
    body: PairBody,
    _user: User = Depends(require_permission("mobile")),
) -> dict[str, Any]:
    manager = get_device_link_manager()
    try:
        return await manager.pair(body.host, body.port, body.code.strip(), body.client_name)
    except DeviceLinkError as exc:
        raise OctopError(
            ErrorCode.DEVICE_LINK_PAIR_FAILED,
            exc.message,
            details={"reason": exc.message},
        ) from exc
    except OSError as exc:
        raise OctopError(
            ErrorCode.DEVICE_LINK_UNREACHABLE,
            f"cannot connect to device: {exc}",
            details={"reason": str(exc)},
        ) from exc


@router.post("/device-link/connect", summary="Connect using stored credentials")
async def device_link_connect(
    body: ConnectBody | None = None,
    _user: User = Depends(require_permission("mobile")),
) -> dict[str, Any]:
    manager = get_device_link_manager()
    host = body.host if body else None
    port = body.port if body else None
    try:
        return await manager.connect(host, port)
    except DeviceLinkError as exc:
        raise OctopError(
            ErrorCode.DEVICE_LINK_UNREACHABLE,
            exc.message,
            details={"reason": exc.message},
        ) from exc


@router.post("/device-link/disconnect", summary="Disconnect the device link")
async def device_link_disconnect(
    _user: User = Depends(require_permission("mobile")),
) -> dict[str, Any]:
    return await get_device_link_manager().disconnect()


@router.post("/device-link/command", summary="Run one device capability command")
async def device_link_command(
    body: CommandBody,
    _user: User = Depends(require_permission("mobile")),
) -> dict[str, Any]:
    manager = get_device_link_manager()
    result = await manager.run_command(body.name, body.params, body.command_id, body.timeout_ms)
    return result


@router.get("/device-link/today", summary="Today aggregate snapshot and config")
async def device_link_today(
    _user: User = Depends(require_permission("mobile")),
) -> dict[str, Any]:
    from octop.infra.control.device_link.today.collector import (  # noqa: PLC0415
        get_today_collector,
    )

    collector = get_today_collector()
    if collector is None:
        raise OctopError(ErrorCode.DEVICE_LINK_UNREACHABLE, "today collector is not running")
    return collector.snapshot()


@router.put("/device-link/today", summary="Update Today collection config (incl. notification consent)")
async def device_link_today_update(
    body: dict[str, Any],
    _user: User = Depends(require_permission("mobile")),
) -> dict[str, Any]:
    from octop.infra.control.device_link.today.collector import (  # noqa: PLC0415
        get_today_collector,
    )

    collector = get_today_collector()
    if collector is None:
        raise OctopError(ErrorCode.DEVICE_LINK_UNREACHABLE, "today collector is not running")
    return {"config": collector.update_config(body)}


@router.get("/device-link/screenshot/{filename}", summary="Fetch a saved screenshot")
async def device_link_screenshot(
    filename: str,
    _user: User = Depends(require_permission("mobile")),
) -> FileResponse:
    path = get_device_link_manager().screenshot_path(filename)
    if path is None:
        raise OctopError(ErrorCode.DEVICE_LINK_SCREENSHOT_NOT_FOUND, "screenshot not found")
    return FileResponse(path, media_type="image/png")


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/device-link/events", summary="Device link live event stream (SSE)")
async def device_link_events(
    _user: User = Depends(require_permission("mobile")),
) -> StreamingResponse:
    manager = get_device_link_manager()
    queue = manager.subscribe()

    async def stream() -> AsyncIterator[str]:
        try:
            status = await manager.status()
            yield _sse("status", status)
            for event in manager.recent_events()[-20:]:
                yield _sse("device", event)
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # 保活注释：代理/浏览器会在长时间静默后断开 SSE
                    yield ": keepalive\n\n"
                    continue
                yield _sse("device", event)
        finally:
            manager.unsubscribe(queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
