"""手机端连接器 HTTP / WebSocket 接口。

路由挂载在 ``/api`` 下，因此对外路径形如 ``/api/connector/...``。
配对请求与 WS 在全局 access token 之外单独鉴权：前者只创建待批准请求，
后者必须持有批准后下发的设备令牌。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from html import escape
from typing import Any

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from octop.api.deps import get_server, require_permission
from octop.infra.control.connector.state import (
    STATUS_APPROVED,
    connector_hub,
    connector_store,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class PairRequestBody(BaseModel):
    deviceId: str = Field(min_length=4, max_length=128)
    deviceName: str = Field(min_length=1, max_length=128)
    platform: str = Field(default="android", max_length=64)
    appVersion: str = Field(default="", max_length=64)


class ReviewBody(BaseModel):
    token: str = Field(min_length=8)
    reason: str | None = Field(default=None, max_length=200)


class PollBody(BaseModel):
    pollToken: str = Field(min_length=8)


class PushMessageBody(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    agentId: str | None = None
    agentName: str | None = None
    threadId: str | None = None


def _dashboard_hub(server: Any) -> Any:
    runtime = getattr(server, "app_runtime", None)
    gateway = getattr(runtime, "gateway", None)
    return getattr(gateway, "ws_hub", None)


async def _notify_dashboard(server: Any, frame: dict[str, Any]) -> None:
    hub = _dashboard_hub(server)
    if hub is None:
        return
    try:
        await hub.broadcast(frame)
    except Exception:  # noqa: BLE001
        logger.warning("connector: dashboard notify failed", exc_info=True)


@router.post("/connector/pair/request", summary="Phone requests pairing")
async def request_pairing(
    body: PairRequestBody,
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    store = connector_store()
    try:
        request = store.create_request(
            device_id=body.deviceId,
            device_name=body.deviceName,
            platform=body.platform,
            app_version=body.appVersion,
        )
    except ValueError as exc:
        return {"ok": False, "code": "PAIR_REJECTED_LOCAL", "message": str(exc)}
    review_url = f"/api/connector/pair/{request.id}/review?token={request.review_token}"
    await _notify_dashboard(
        server,
        {
            "type": "connector_pair_request",
            "requestId": request.id,
            "code": request.code,
            "deviceName": request.device_name,
            "platform": request.platform,
            "appVersion": request.app_version,
            "reviewUrl": review_url,
            "expiresAtMs": int(request.expires_at * 1000),
        },
    )
    return {
        "ok": True,
        "requestId": request.id,
        "pollToken": request.poll_token,
        "code": request.code,
        "expiresAtMs": int(request.expires_at * 1000),
        "pollIntervalMs": 1500,
    }


@router.get("/connector/pair/request/{request_id}", summary="Phone polls pairing status")
async def poll_pairing(request_id: str, pollToken: str = Query("")) -> dict[str, Any]:
    store = connector_store()
    request = store.get_request(request_id)
    if request is None:
        return {
            "ok": False,
            "code": "PAIR_NOT_FOUND",
            "message": "配对请求不存在或已清理，请重新发起",
        }
    if not request.poll_token or pollToken != request.poll_token:
        return {"ok": False, "code": "PAIR_INVALID_TOKEN", "message": "配对请求凭据无效"}
    include_token = request.status == STATUS_APPROVED and request.device_token is not None
    payload = request.public(include_token=include_token)
    if include_token:
        store.consume_token(request)
    return {"ok": True, **payload}


@router.get("/connector/pair/pending", summary="List pending phone pairing requests")
async def pending_pairings(
    _user: Any = Depends(require_permission("mobile")),
) -> dict[str, Any]:
    requests = connector_store().list_pending()
    return {
        "ok": True,
        "requests": [
            {**r.public(), "reviewUrl": f"/api/connector/pair/{r.id}/review?token={r.review_token}"}
            for r in requests
        ],
    }


@router.post("/connector/pair/{request_id}/approve", summary="Approve phone pairing")
async def approve_pairing(
    request_id: str,
    body: ReviewBody,
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    store = connector_store()
    try:
        request = store.approve(request_id, body.token)
    except KeyError as exc:
        return {"ok": False, "code": "PAIR_NOT_FOUND", "message": str(exc).strip("'")}
    except PermissionError as exc:
        return {"ok": False, "code": "PAIR_INVALID_TOKEN", "message": str(exc)}
    except ValueError as exc:
        return {"ok": False, "code": "PAIR_NOT_PENDING", "message": str(exc)}
    await _notify_dashboard(
        server,
        {
            "type": "connector_pair_resolved",
            "requestId": request.id,
            "status": request.status,
            "deviceName": request.device_name,
        },
    )
    return {"ok": True, "status": request.status, "deviceId": request.device_id}


@router.post("/connector/pair/{request_id}/reject", summary="Reject phone pairing")
async def reject_pairing(
    request_id: str,
    body: ReviewBody,
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    store = connector_store()
    try:
        request = store.reject(request_id, body.token, reason=body.reason)
    except KeyError as exc:
        return {"ok": False, "code": "PAIR_NOT_FOUND", "message": str(exc).strip("'")}
    except PermissionError as exc:
        return {"ok": False, "code": "PAIR_INVALID_TOKEN", "message": str(exc)}
    except ValueError as exc:
        return {"ok": False, "code": "PAIR_NOT_PENDING", "message": str(exc)}
    await _notify_dashboard(
        server,
        {
            "type": "connector_pair_resolved",
            "requestId": request.id,
            "status": request.status,
            "deviceName": request.device_name,
            "reason": request.reason,
        },
    )
    return {"ok": True, "status": request.status, "reason": request.reason}


@router.post("/connector/pair/{request_id}/cancel", summary="Phone cancels a pairing request")
async def cancel_pairing(request_id: str, body: PollBody) -> dict[str, Any]:
    ok = connector_store().cancel_request(request_id, body.pollToken)
    return {"ok": ok, "requestId": request_id}


@router.get(
    "/connector/pair/{request_id}/review",
    response_class=HTMLResponse,
    summary="Pairing review page",
)
async def review_page(request_id: str, token: str = Query("")) -> HTMLResponse:
    store = connector_store()
    request = store.get_request(request_id)
    if request is None or token != request.review_token:
        return HTMLResponse("<h1>配对请求不存在或链接无效</h1>", status_code=404)
    status_text = {
        "pending": "等待处理",
        "approved": "已同意",
        "rejected": "已拒绝",
        "expired": "已过期",
    }.get(request.status, request.status)
    disabled = "disabled" if request.status != "pending" else ""
    return HTMLResponse(
        f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>手机上配对请求 · HappyClaw</title>
<style>
body{{font-family:-apple-system,system-ui,sans-serif;background:#0f1115;color:#e8eaed;margin:0;padding:32px}}
.card{{max-width:520px;margin:0 auto;background:#171a21;border:1px solid #262b36;border-radius:16px;padding:24px}}
h1{{font-size:20px;margin:0 0 4px}} .muted{{color:#9aa3b2;font-size:13px}}
.row{{display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid #262b36}}
.row:last-of-type{{border-bottom:none}} .code{{font-family:ui-monospace,monospace;font-size:28px;letter-spacing:6px}}
button{{border:0;border-radius:12px;padding:12px 20px;font-size:15px;cursor:pointer}}
.ok{{background:#2f7cf6;color:#fff}} .no{{background:#2a2f3a;color:#e8eaed}}
#msg{{margin-top:14px;font-size:14px}} .row:last-child{{gap:10px}}
</style></head><body><div class="card">
<h1>手机请求配对</h1><p class="muted">核对设备信息后再决定；同意后手机即可收发 HappyClaw 消息。</p>
<div class="row"><span>设备</span><b>{escape(request.device_name)}</b></div>
<div class="row"><span>平台 / 版本</span><b>{escape(request.platform)} {escape(request.app_version)}</b></div>
<div class="row"><span>配对码</span><b class="code">{escape(request.code)}</b></div>
<div class="row"><span>状态</span><b>{status_text}</b></div>
<div class="row" style="justify-content:flex-end">
<button class="no" {disabled} onclick="act('reject')">拒绝</button>
<button class="ok" {disabled} onclick="act('approve')">同意配对</button>
</div>
<div id="msg" class="muted"></div>
</div>
<script>
async function act(kind) {{
  const res = await fetch('/api/connector/pair/{request_id}/' + kind, {{
    method: 'POST', headers: {{'content-type': 'application/json'}},
    body: JSON.stringify({{token: {json.dumps(token)}}}),
  }});
  const data = await res.json();
  document.getElementById('msg').textContent = data.ok
    ? (kind === 'approve' ? '已同意，手机端会自动连上。' : '已拒绝，手机端会收到回执。')
    : (data.message || '操作失败');
  if (data.ok) setTimeout(() => location.reload(), 800);
}}
</script></body></html>"""
    )


@router.get("/connector/devices", summary="List paired phones")
async def list_devices(
    _user: Any = Depends(require_permission("mobile")),
) -> dict[str, Any]:
    return {"ok": True, "devices": [d.public() for d in connector_store().list_devices()]}


@router.delete("/connector/devices/{device_id}", summary="Revoke a paired phone")
async def revoke_device(
    device_id: str,
    _user: Any = Depends(require_permission("mobile")),
) -> dict[str, Any]:
    store = connector_store()
    ok = store.revoke(device_id)
    hub = connector_hub()
    if ok:
        await hub.send_to(device_id, {"type": "revoked", "message": "这台手机已被移出配对列表"})
    return {"ok": ok, "deviceId": device_id}


@router.post("/connector/messages", summary="Push a message to paired phones")
async def push_message(
    body: PushMessageBody,
    _user: Any = Depends(require_permission("mobile")),
) -> dict[str, Any]:
    hub = connector_hub()
    delivered = await hub.push_message(
        {
            "text": body.text,
            "agentId": body.agentId,
            "agentName": body.agentName,
            "threadId": body.threadId,
        }
    )
    return {"ok": True, "delivered": delivered, "online": hub.online_count()}


@router.get("/connector/replies", summary="Recent replies from phones")
async def list_replies(
    limit: int = Query(50, ge=1, le=200),
    _user: Any = Depends(require_permission("mobile")),
) -> dict[str, Any]:
    return {"ok": True, "replies": connector_hub().recent_replies(limit)}


@router.websocket("/connector/ws")
async def connector_ws(
    websocket: WebSocket,
    token: str = Query(""),
) -> None:
    store = connector_store()
    device = await asyncio.to_thread(store.authorize, token)
    if device is None:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    # WebSocket 作用域拿不到 Request，依赖注入会 500；直接从 app.state 取服务器实例
    server = getattr(websocket.app.state, "octop_server", None)
    hub = connector_hub()
    await hub.register(device.id, websocket)
    await websocket.send_json(
        {
            "type": "hello",
            "deviceId": device.id,
            "deviceName": device.name,
            "serverTimeMs": int(time.time() * 1000),
            "history": hub.history(),
        }
    )
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                frame = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "帧不是合法 JSON"})
                continue
            if not isinstance(frame, dict):
                continue
            kind = str(frame.get("type") or "")
            logger.debug("connector ws frame: %s device=%s", kind, device.id)
            if kind == "ping":
                await websocket.send_json({"type": "pong", "serverTimeMs": int(time.time() * 1000)})
            elif kind == "reply":
                text = str(frame.get("text") or "").strip()
                if not text:
                    await websocket.send_json({"type": "error", "message": "回复内容为空"})
                    continue
                entry = {
                    "id": f"r{int(time.time() * 1000)}",
                    "deviceId": device.id,
                    "deviceName": device.name,
                    "text": text[:8000],
                    "receivedAtMs": int(time.time() * 1000),
                }
                hub.add_reply(entry)
                await websocket.send_json({"type": "ack", "id": entry["id"]})
                await _notify_dashboard(
                    server,
                    {
                        "type": "connector_reply",
                        "deviceId": device.id,
                        "deviceName": device.name,
                        "text": entry["text"],
                        "receivedAtMs": entry["receivedAtMs"],
                    },
                )
            else:
                await websocket.send_json({"type": "error", "message": f"未知帧类型：{kind}"})
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        logger.warning("connector ws closed unexpectedly", exc_info=True)
    finally:
        await hub.unregister(device.id, websocket)
        store.touch(device.id)


__all__ = ["router"]
