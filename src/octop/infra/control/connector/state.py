"""手机端连接器：配对请求、设备令牌与消息推送。

方向与 ``device_link`` 相反：这里是 HappyClaw 监听，手机端主动拨号进来。

- 手机 ``POST /api/connector/pair/request`` 发起请求（不需要令牌）；
- HappyClaw 侧在待批准列表 / 桌面通知里看到这条请求，带上 reviewToken 同意或拒绝；
- 手机用 pollToken 轮询结果，通过后拿到长期设备令牌，再用它连 ``/api/connector/ws``；
- 连接建立后，HappyClaw 主动推送的消息直接下发，手机回包以 ``reply`` 帧上行。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import WebSocket

from octop.infra.utils.paths import PathLayout

logger = logging.getLogger(__name__)

REQUEST_TTL_SECONDS = 300
MAX_PENDING = 20
MAX_REPLIES = 200
# 同一台设备重复发起时，20 秒内视为「请求还在路上」，直接拒绝；
# 超过后允许覆盖旧请求，避免手机丢了响应就卡到过期。
REQUEST_DUPLICATE_GRACE_SECONDS = 20

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_EXPIRED = "expired"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class PairRequest:
    id: str
    code: str
    poll_token: str
    review_token: str
    device_id: str
    device_name: str
    platform: str
    app_version: str
    created_at: float
    expires_at: float
    status: str = STATUS_PENDING
    reason: str | None = None
    device_token: str | None = None
    user_id: int | None = None

    @property
    def expired(self) -> bool:
        return time.time() > self.expires_at

    def public(self, *, include_token: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "requestId": self.id,
            "code": self.code,
            "status": self.status,
            "deviceId": self.device_id,
            "deviceName": self.device_name,
            "platform": self.platform,
            "appVersion": self.app_version,
            "createdAtMs": int(self.created_at * 1000),
            "expiresAtMs": int(self.expires_at * 1000),
        }
        if self.reason:
            payload["reason"] = self.reason
        if include_token and self.status == STATUS_APPROVED and self.device_token:
            payload["token"] = self.device_token
            payload["userId"] = self.user_id
        return payload


@dataclass(slots=True)
class PairedDevice:
    id: str
    name: str
    platform: str
    app_version: str
    token_hash: str
    created_at: float
    last_seen_at: float
    user_id: int | None = None

    def public(self) -> dict[str, Any]:
        return {
            "deviceId": self.id,
            "name": self.name,
            "platform": self.platform,
            "appVersion": self.app_version,
            "createdAtMs": int(self.created_at * 1000),
            "lastSeenAtMs": int(self.last_seen_at * 1000),
            "userId": self.user_id,
        }

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "platform": self.platform,
            "appVersion": self.app_version,
            "tokenHash": self.token_hash,
            "createdAt": self.created_at,
            "lastSeenAt": self.last_seen_at,
            "userId": self.user_id,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> PairedDevice:
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or "手机"),
            platform=str(data.get("platform") or ""),
            app_version=str(data.get("appVersion") or ""),
            token_hash=str(data.get("tokenHash") or ""),
            created_at=float(data.get("createdAt") or 0),
            last_seen_at=float(data.get("lastSeenAt") or 0),
            user_id=data.get("userId") if isinstance(data.get("userId"), int) else None,
        )


class ConnectorStore:
    """配对状态与设备令牌；设备清单落盘，待批准请求只留在内存。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._devices: dict[str, PairedDevice] = {}
        self._requests: dict[str, PairRequest] = {}
        self._load()

    # ---------------- 设备 ----------------

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("connector device store unreadable: %s", self._path)
            return
        for item in raw.get("devices", []) if isinstance(raw, dict) else []:
            if isinstance(item, dict):
                device = PairedDevice.from_json(item)
                if device.id and device.token_hash:
                    self._devices[device.id] = device

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"devices": [d.to_json() for d in self._devices.values()]}
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def list_devices(self) -> list[PairedDevice]:
        with self._lock:
            return sorted(self._devices.values(), key=lambda d: d.created_at, reverse=True)

    def revoke(self, device_id: str) -> bool:
        with self._lock:
            if self._devices.pop(device_id, None) is None:
                return False
            self._save()
            return True

    def authorize(self, token: str) -> PairedDevice | None:
        if not token:
            return None
        digest = _hash(token)
        with self._lock:
            for device in self._devices.values():
                if secrets.compare_digest(device.token_hash, digest):
                    device.last_seen_at = time.time()
                    self._save()
                    return device
        return None

    def touch(self, device_id: str) -> None:
        with self._lock:
            device = self._devices.get(device_id)
            if device is None:
                return
            device.last_seen_at = time.time()
            self._save()

    # ---------------- 配对 ----------------

    def create_request(
        self,
        *,
        device_id: str,
        device_name: str,
        platform: str,
        app_version: str,
    ) -> PairRequest:
        with self._lock:
            self._expire_requests()
            now = time.time()
            pending = [r for r in self._requests.values() if r.status == STATUS_PENDING]
            if len(pending) >= MAX_PENDING:
                raise ValueError("待批准的配对请求过多，请先在 HappyClaw 处理已有请求")
            for existing in pending:
                if existing.device_id == device_id:
                    if now - existing.created_at < REQUEST_DUPLICATE_GRACE_SECONDS:
                        raise ValueError("这台设备已有待批准的配对请求，请等待批准或稍后重试")
                    # 手机重发了请求：让旧请求失效，新请求继续走审批
                    existing.status = STATUS_EXPIRED
                    existing.reason = "已被同一设备的新请求替代"
            request = PairRequest(
                id=secrets.token_hex(8),
                code=f"{secrets.randbelow(900000) + 100000}",
                poll_token=secrets.token_urlsafe(24),
                review_token=secrets.token_urlsafe(24),
                device_id=device_id,
                device_name=device_name,
                platform=platform,
                app_version=app_version,
                created_at=now,
                expires_at=now + REQUEST_TTL_SECONDS,
            )
            self._requests[request.id] = request
            return request

    def get_request(self, request_id: str) -> PairRequest | None:
        with self._lock:
            request = self._requests.get(request_id)
            if request is None:
                return None
            if request.status == STATUS_PENDING and request.expired:
                request.status = STATUS_EXPIRED
            return request

    def list_pending(self) -> list[PairRequest]:
        with self._lock:
            self._expire_requests()
            return [
                r
                for r in sorted(self._requests.values(), key=lambda r: r.created_at, reverse=True)
                if r.status == STATUS_PENDING
            ]

    def _expire_requests(self) -> None:
        now = time.time()
        for request in self._requests.values():
            if request.status == STATUS_PENDING and now > request.expires_at:
                request.status = STATUS_EXPIRED
        # 已完成且过期的请求保留 10 分钟供手机查询结果，之后清掉避免无限增长
        stale = [
            rid
            for rid, request in self._requests.items()
            if request.status != STATUS_PENDING and now - request.expires_at > 600
        ]
        for rid in stale:
            self._requests.pop(rid, None)

    def approve(self, request_id: str, review_token: str, *, user_id: int | None = None) -> PairRequest:
        with self._lock:
            request = self._requests.get(request_id)
            if request is None:
                raise KeyError("配对请求不存在")
            if not secrets.compare_digest(request.review_token, review_token):
                raise PermissionError("配对请求凭据无效")
            if request.status == STATUS_PENDING and request.expired:
                request.status = STATUS_EXPIRED
            if request.status != STATUS_PENDING:
                raise ValueError(f"配对请求已结束（{request.status}）")
            token = secrets.token_urlsafe(32)
            now = time.time()
            self._devices[request.device_id] = PairedDevice(
                id=request.device_id,
                name=request.device_name,
                platform=request.platform,
                app_version=request.app_version,
                token_hash=_hash(token),
                created_at=now,
                last_seen_at=now,
                user_id=user_id,
            )
            self._save()
            request.status = STATUS_APPROVED
            request.device_token = token
            request.user_id = user_id
            return request

    def reject(self, request_id: str, review_token: str, *, reason: str | None = None) -> PairRequest:
        with self._lock:
            request = self._requests.get(request_id)
            if request is None:
                raise KeyError("配对请求不存在")
            if not secrets.compare_digest(request.review_token, review_token):
                raise PermissionError("配对请求凭据无效")
            if request.status == STATUS_PENDING and request.expired:
                request.status = STATUS_EXPIRED
            if request.status != STATUS_PENDING:
                raise ValueError(f"配对请求已结束（{request.status}）")
            request.status = STATUS_REJECTED
            request.reason = (reason or "已拒绝").strip() or "已拒绝"
            return request

    def consume_token(self, request: PairRequest) -> None:
        """手机已经取走令牌，不再重复下发。"""
        with self._lock:
            request.device_token = None

    def cancel_request(self, request_id: str, poll_token: str) -> bool:
        """手机端主动取消：让待批准请求立即失效，方便马上重新发起。"""
        with self._lock:
            request = self._requests.get(request_id)
            if request is None or not secrets.compare_digest(request.poll_token, poll_token):
                return False
            if request.status == STATUS_PENDING:
                request.status = STATUS_EXPIRED
                request.reason = "手机端已取消"
                return True
            return request.status in (STATUS_REJECTED, STATUS_EXPIRED)

    def device_for(self, device_id: str) -> PairedDevice | None:
        with self._lock:
            return self._devices.get(device_id)


class ConnectorHub:
    """在线连接表与消息收发。"""

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}
        self._replies: list[dict[str, Any]] = []
        self._messages: list[dict[str, Any]] = []

    def online_count(self) -> int:
        return len(self._connections)

    def history(self) -> list[dict[str, Any]]:
        """最近下发的消息，手机重连后补发，避免漏看。"""
        return list(self._messages)

    async def push_message(self, payload: dict[str, Any]) -> int:
        frame = {
            "type": "message",
            "id": secrets.token_hex(6),
            "sentAtMs": int(time.time() * 1000),
            **payload,
        }
        self._messages.append(frame)
        if len(self._messages) > 100:
            del self._messages[: len(self._messages) - 100]
        return await self.push_all(frame)

    async def register(self, device_id: str, ws: WebSocket) -> None:
        self._connections.setdefault(device_id, set()).add(ws)

    async def unregister(self, device_id: str, ws: WebSocket) -> None:
        conns = self._connections.get(device_id)
        if conns is None:
            return
        conns.discard(ws)
        if not conns:
            self._connections.pop(device_id, None)

    async def send_to(self, device_id: str, payload: dict[str, Any]) -> bool:
        delivered = False
        for ws in list(self._connections.get(device_id, ())):
            try:
                await ws.send_json(payload)
                delivered = True
            except Exception:  # noqa: BLE001
                await self.unregister(device_id, ws)
        return delivered

    async def push_all(self, payload: dict[str, Any]) -> int:
        count = 0
        for device_id in list(self._connections):
            if await self.send_to(device_id, payload):
                count += 1
        return count

    async def push_user(self, user_id: int | None, payload: dict[str, Any], store: ConnectorStore) -> int:
        count = 0
        for device in store.list_devices():
            if user_id is not None and device.user_id is not None and device.user_id != user_id:
                continue
            if await self.send_to(device.id, payload):
                count += 1
        return count

    def add_reply(self, entry: dict[str, Any]) -> None:
        self._replies.append(entry)
        if len(self._replies) > MAX_REPLIES:
            del self._replies[: len(self._replies) - MAX_REPLIES]

    def recent_replies(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(reversed(self._replies[-limit:]))


_store: ConnectorStore | None = None
_hub: ConnectorHub | None = None
_init_lock = threading.Lock()


def connector_store() -> ConnectorStore:
    global _store
    if _store is None:
        with _init_lock:
            if _store is None:
                root = PathLayout.from_env().root / "connector"
                _store = ConnectorStore(root / "devices.json")
    return _store


def connector_hub() -> ConnectorHub:
    global _hub
    if _hub is None:
        with _init_lock:
            if _hub is None:
                _hub = ConnectorHub()
    return _hub


def reset_connector_state() -> None:
    """测试用：清空单例状态。"""
    global _store, _hub
    with _init_lock:
        _store = None
        _hub = None
