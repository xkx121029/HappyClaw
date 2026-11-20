"""手机端连接器：配对状态机、路由与时序。

覆盖：
- 手机发起配对 → 轮询待批准 → 审批页同意/拒绝 → 设备令牌只下发一次；
- 拒绝带明确回执，过期请求不可再批准；
- 设备令牌鉴权 WebSocket，hello 补发历史消息，reply 回 ack 并通知 Dashboard；
- 配对/WS 路径在共享密钥开启时仍可访问，设备清单/推送仍需密钥。
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from octop.api.deps import current_user, get_server
from octop.api.middleware.access_token import _connector_public
from octop.infra.control.connector import state as S
from octop.infra.control.connector import router as R
from tests.support.http import ws_connect


class _FakeHub:
    def __init__(self) -> None:
        self.frames: list[dict] = []

    async def broadcast(self, frame: dict) -> int:
        self.frames.append(frame)
        return 1


def _fake_server() -> SimpleNamespace:
    gateway = SimpleNamespace(ws_hub=_FakeHub())
    return SimpleNamespace(
        app_runtime=SimpleNamespace(gateway=gateway),
        _started=True,
        services=None,
    )


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path))
    S.reset_connector_state()
    server = _fake_server()
    app = FastAPI()
    app.include_router(R.router, prefix="/api")
    # WebSocket 路由从 app.state 取 server，HTTP 路由仍走依赖注入
    app.state.octop_server = server
    app.dependency_overrides[get_server] = lambda: server
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id=1)
    yield app, server
    S.reset_connector_state()


@pytest.fixture
def client(app_env):
    app, server = app_env
    with TestClient(app) as http:
        yield http, server


def _start_pairing(client: TestClient, device_id: str = "dev-aaaa1111") -> dict:
    res = client.post(
        "/api/connector/pair/request",
        json={
            "deviceId": device_id,
            "deviceName": "Pixel 8",
            "platform": "android",
            "appVersion": "0.3.0",
        },
    )
    assert res.status_code == 200
    return res.json()


def test_pair_approve_issues_token_once(client):
    http, server = client
    started = _start_pairing(http)
    assert started["ok"] is True
    assert len(started["code"]) == 6 and started["code"].isdigit()
    assert started["expiresAtMs"] > int(time.time() * 1000)

    notified = server.app_runtime.gateway.ws_hub.frames[0]
    assert notified["type"] == "connector_pair_request"
    assert notified["deviceName"] == "Pixel 8"
    assert notified["reviewUrl"].startswith("/api/connector/pair/")

    request_id = started["requestId"]
    poll = lambda: http.get(  # noqa: E731
        f"/api/connector/pair/request/{request_id}",
        params={"pollToken": started["pollToken"]},
    ).json()
    assert poll()["status"] == "pending"

    pending = http.get("/api/connector/pair/pending").json()["requests"]
    assert [r["requestId"] for r in pending] == [request_id]

    review_url = pending[0]["reviewUrl"]
    page = http.get(review_url)
    assert page.status_code == 200 and "Pixel 8" in page.text

    review_token = review_url.split("token=", 1)[1]
    approved = http.post(
        f"/api/connector/pair/{request_id}/approve", json={"token": review_token}
    ).json()
    assert approved["ok"] is True and approved["status"] == "approved"

    first = poll()
    assert first["status"] == "approved"
    assert first["token"]
    # 令牌只下发一次，避免轮询链路被重放
    assert "token" not in poll()

    device = S.connector_store().authorize(first["token"])
    assert device is not None and device.id == "dev-aaaa1111"
    assert S.connector_store().authorize("wrong-token") is None


def test_reject_returns_reason_and_blocks_approval(client):
    http, _server = client
    started = _start_pairing(http, "dev-bbbb2222")
    pending = http.get("/api/connector/pair/pending").json()["requests"][0]
    token = pending["reviewUrl"].split("token=", 1)[1]
    request_id = started["requestId"]

    rejected = http.post(
        f"/api/connector/pair/{request_id}/reject",
        json={"token": token, "reason": "不是我的手机"},
    ).json()
    assert rejected["ok"] is True and rejected["status"] == "rejected"

    polled = http.get(
        f"/api/connector/pair/request/{request_id}",
        params={"pollToken": started["pollToken"]},
    ).json()
    assert polled["status"] == "rejected" and polled["reason"] == "不是我的手机"
    assert "token" not in polled

    again = http.post(
        f"/api/connector/pair/{request_id}/approve", json={"token": token}
    ).json()
    assert again["ok"] is False and again["code"] == "PAIR_NOT_PENDING"


def test_bad_review_token_and_unknown_request(client):
    http, _server = client
    started = _start_pairing(http, "dev-cccc3333")
    request_id = started["requestId"]

    denied = http.post(
        f"/api/connector/pair/{request_id}/approve", json={"token": "x" * 12}
    ).json()
    assert denied["ok"] is False and denied["code"] == "PAIR_INVALID_TOKEN"

    missing = http.get(
        "/api/connector/pair/request/nope", params={"pollToken": "whatever"}
    ).json()
    assert missing["ok"] is False and missing["code"] == "PAIR_NOT_FOUND"

    wrong_poll = http.get(
        f"/api/connector/pair/request/{request_id}", params={"pollToken": "bad"}
    ).json()
    assert wrong_poll["ok"] is False and wrong_poll["code"] == "PAIR_INVALID_TOKEN"


def test_expired_request_cannot_be_approved(client, monkeypatch):
    http, _server = client
    started = _start_pairing(http, "dev-dddd4444")
    store = S.connector_store()
    request = store.get_request(started["requestId"])
    assert request is not None
    request.expires_at = time.time() - 1

    polled = http.get(
        f"/api/connector/pair/request/{request.id}",
        params={"pollToken": started["pollToken"]},
    ).json()
    assert polled["status"] == "expired"

    pending = http.get("/api/connector/pair/pending").json()["requests"]
    assert pending == []


def test_duplicate_device_and_pending_cap(client, monkeypatch):
    http, _server = client
    started = _start_pairing(http, "dev-eeee5555")
    dup = _start_pairing(http, "dev-eeee5555")
    assert dup["ok"] is False and dup["code"] == "PAIR_REJECTED_LOCAL"

    # 手机丢了响应、20 秒后重发：允许覆盖旧请求，而不是卡到过期
    S.connector_store().get_request(started["requestId"]).created_at -= 21
    retried = _start_pairing(http, "dev-eeee5555")
    assert retried["ok"] is True and retried["requestId"] != started["requestId"]

    monkeypatch.setattr(S, "MAX_PENDING", 1)
    capped = _start_pairing(http, "dev-ffff6666")
    assert capped["ok"] is False
    assert "待批准的配对请求过多" in capped["message"]


def test_cancel_request_lets_phone_start_over(client):
    http, _server = client
    started = _start_pairing(http, "dev-hhhh8888")
    request_id = started["requestId"]

    cancelled = http.post(
        f"/api/connector/pair/{request_id}/cancel",
        json={"pollToken": started["pollToken"]},
    ).json()
    assert cancelled["ok"] is True

    polled = http.get(
        f"/api/connector/pair/request/{request_id}",
        params={"pollToken": started["pollToken"]},
    ).json()
    assert polled["status"] == "expired"
    assert http.get("/api/connector/pair/pending").json()["requests"] == []

    again = _start_pairing(http, "dev-hhhh8888")
    assert again["ok"] is True and again["requestId"] != request_id


def test_message_push_and_replies_surface(client):
    http, _server = client
    started = _start_pairing(http, "dev-gggg7777")
    pending = http.get("/api/connector/pair/pending").json()["requests"][0]
    http.post(
        f"/api/connector/pair/{started['requestId']}/approve",
        json={"token": pending["reviewUrl"].split("token=", 1)[1]},
    )

    pushed = http.post(
        "/api/connector/messages",
        json={"text": "早报已生成", "agentId": "a1", "agentName": "小八"},
    ).json()
    assert pushed["ok"] is True and pushed["delivered"] == 0 and pushed["online"] == 0
    assert http.get("/api/connector/replies").json()["replies"] == []

    devices = http.get("/api/connector/devices").json()["devices"]
    assert devices[0]["deviceId"] == "dev-gggg7777"
    revoked = http.delete("/api/connector/devices/dev-gggg7777").json()
    assert revoked["ok"] is True
    assert http.get("/api/connector/devices").json()["devices"] == []


async def test_websocket_history_ping_and_reply(app_env):
    app, server = app_env
    store = S.connector_store()
    request = store.create_request(
        device_id="dev-ws0001",
        device_name="WS Phone",
        platform="android",
        app_version="0.3.0",
    )
    store.approve(request.id, request.review_token)
    token = request.device_token
    assert token

    await S.connector_hub().push_message({"text": "离线时发出的消息", "agentId": "a1"})

    async with ws_connect(app, f"/api/connector/ws?token={token}") as ws:
        hello = await ws.receive_json()
        assert hello["type"] == "hello" and hello["deviceId"] == "dev-ws0001"
        assert hello["history"][-1]["text"] == "离线时发出的消息"

        await ws.send_json({"type": "ping"})
        pong = await ws.receive_json()
        assert pong["type"] == "pong" and pong["serverTimeMs"] > 0

        await ws.send_json({"type": "reply", "text": "收到，稍后处理"})
        ack = await ws.receive_json()
        assert ack["type"] == "ack"

        await ws.send_json({"type": "reply", "text": "   "})
        empty = await ws.receive_json()
        assert empty["type"] == "error"

        await ws.send_json({"type": "nope"})
        unknown = await ws.receive_json()
        assert unknown["type"] == "error" and "nope" in unknown["message"]

    replies = S.connector_hub().recent_replies()
    assert replies[0]["text"] == "收到，稍后处理"
    frames = server.app_runtime.gateway.ws_hub.frames
    assert any(f["type"] == "connector_reply" for f in frames)


async def test_websocket_rejects_bad_token(app_env):
    app, _server = app_env
    with pytest.raises(WebSocketDisconnect):
        async with ws_connect(app, "/api/connector/ws?token=not-a-device-token"):
            pass


async def test_websocket_uses_real_server_dependency(tmp_path, monkeypatch):
    """生产环境没有 dependency_overrides：WS 不能依赖注入 Request。"""
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path))
    S.reset_connector_state()
    app = FastAPI()
    app.include_router(R.router, prefix="/api")
    app.state.octop_server = _fake_server()

    store = S.connector_store()
    request = store.create_request(
        device_id="dev-real01",
        device_name="Real Phone",
        platform="android",
        app_version="0.3.0",
    )
    store.approve(request.id, request.review_token)
    token = request.device_token
    assert token

    async with ws_connect(app, f"/api/connector/ws?token={token}") as ws:
        hello = await ws.receive_json()
        assert hello["type"] == "hello" and hello["deviceId"] == "dev-real01"
    S.reset_connector_state()


def test_access_token_exemptions():
    assert _connector_public("/api/connector/pair/request")
    assert _connector_public("/api/connector/pair/request/abc")
    assert _connector_public("/api/connector/pair/abc/review")
    assert _connector_public("/api/connector/pair/abc/approve")
    assert _connector_public("/api/connector/pair/abc/reject")
    assert _connector_public("/api/connector/pair/abc/cancel")
    assert _connector_public("/api/connector/ws")
    # 已配对设备清单与消息推送仍要带共享密钥
    assert not _connector_public("/api/connector/pair/pending")
    assert not _connector_public("/api/connector/devices")
    assert not _connector_public("/api/connector/messages")
