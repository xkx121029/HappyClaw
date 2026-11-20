"""HappyClaw 侧链路客户端（asyncio）。

约定（与 docs/PROTOCOL.md、设备侧 ``LinkClient`` 一致）：
- TLS 1.2+，自签名证书用「指纹固定」：首次配对时把设备证书指纹钉进本地凭据，
  之后每次连接都比对，指纹变了就拒绝（不静默接受新证书）；
- 配对：8 位短码 + HMAC 证明，一次性、限时、限次；
- 心跳：每 ``pingIntervalMs`` 发 ping，``pongTimeoutMs`` 内没有 pong 就认定断线并重连；
- 断线期间的命令**不补发**：在飞命令一律以 ``UNKNOWN_OUTCOME`` 失败，
  需要重试的调用方必须复用同一个 ``command_id``，由设备侧幂等缓存回放结果。
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import ssl
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import protocol as P
from . import wire

EventCallback = Callable[[str, dict[str, Any], int], None]

# 断连发起方。状态里必须能看出「谁断的」：本端主动断开不能写成设备断开，
# 反之亦然；否则 UI 上的 reason 会把方向说反。
CLOSED_BY_SERVER = "server"
CLOSED_BY_DEVICE = "device"
CLOSED_BY_HEARTBEAT = "heartbeat"
CLOSED_BY_NETWORK = "network"

REASON_SERVER_DISCONNECT = "服务端主动断开连接（本端发起）"
REASON_DEVICE_DISCONNECT = "设备侧断开连接（App 退出或切到后台）"
REASON_HEARTBEAT_TIMEOUT = "心跳超时（未收到 pong），本端主动断开并重连"


class DeviceLinkError(Exception):
    """带协议错误码的链路异常（code 取自 protocol.json 的 errorCodes）。"""

    def __init__(self, code: str, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


@dataclass
class Credentials:
    client_id: str
    token: str
    device_fingerprint: str
    device_name: str = "Android"

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Credentials:
        return cls(
            client_id=str(raw.get("clientId", "")),
            token=str(raw.get("token", "")),
            device_fingerprint=str(raw.get("deviceFingerprint", "")),
            device_name=str(raw.get("deviceName", "Android")),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "clientId": self.client_id,
            "token": self.token,
            "deviceFingerprint": self.device_fingerprint,
            "deviceName": self.device_name,
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: Path) -> Credentials | None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(raw, dict) or not raw.get("clientId") or not raw.get("token"):
            return None
        return cls.from_json(raw)


def backoff_delay_ms(attempt: int, rng: random.Random | None = None) -> int:
    """指数退避 + 抖动：500ms 起步，封顶 30s，抖动 ±20%。"""
    r = rng or random
    base = min(P.RECONNECT_INITIAL_MS * (2**attempt), P.RECONNECT_MAX_MS)
    factor = 1.0 + r.uniform(-P.RECONNECT_JITTER, P.RECONNECT_JITTER)
    return max(100, int(base * factor))


def _tls_context() -> ssl.SSLContext:
    # 证书链不可验证（自签名），真正的信任判断在 _pin_peer 里做指纹比对；
    # 因此这里必须关掉主机名校验，否则 IP 直连会被标准校验提前拒绝。
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


@dataclass
class LinkState:
    status: str = "idle"  # idle / connecting / online / offline / unpaired
    host: str = ""
    port: int = 0
    device_name: str | None = None
    device_fingerprint: str | None = None
    client_id: str | None = None
    connected_at: int | None = None
    last_heartbeat_at: int | None = None
    latency_ms: int | None = None
    current_action: str | None = None
    next_retry_at: int | None = None
    reason: str | None = None
    closed_by: str | None = None  # server / device / heartbeat / network
    reconnect_count: int = 0
    commands_total: int = 0
    commands_failed: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "host": self.host,
            "port": self.port,
            "device_name": self.device_name,
            "device_fingerprint": self.device_fingerprint,
            "client_id": self.client_id,
            "connected_at": self.connected_at,
            "last_heartbeat_at": self.last_heartbeat_at,
            "latency_ms": self.latency_ms,
            "current_action": self.current_action,
            "next_retry_at": self.next_retry_at,
            "reason": self.reason,
            "closed_by": self.closed_by,
            "reconnect_count": self.reconnect_count,
            "commands_total": self.commands_total,
            "commands_failed": self.commands_failed,
        }


@dataclass
class _Pending:
    future: asyncio.Future[dict[str, Any]]
    started_at: int


class DeviceLinkClient:
    def __init__(
        self,
        credentials_path: Path,
        host: str = "",
        port: int = 0,
        *,
        ping_interval_ms: int = P.PING_INTERVAL_MS,
        pong_timeout_ms: int = P.PONG_TIMEOUT_MS,
        connect_timeout_s: float = 8.0,
        on_event: EventCallback | None = None,
        clock: Callable[[], int] | None = None,
    ) -> None:
        self._credentials_path = credentials_path
        self._state = LinkState(host=host, port=port)
        self._ping_interval = ping_interval_ms / 1000
        self._pong_timeout = pong_timeout_ms / 1000
        self._connect_timeout = connect_timeout_s
        self._clock = clock or (lambda: int(time.time() * 1000))
        self._on_event = on_event

        self._credentials: Credentials | None = Credentials.load(credentials_path)
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._write_lock = asyncio.Lock()
        self._pending: dict[str, _Pending] = {}
        self._pong_event = asyncio.Event()
        self._pong_sent_at = 0
        self._supervisor: asyncio.Task[None] | None = None
        self._read_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._running = False
        self._generation = 0
        # 本端主动关闭时记下 (closed_by, reason)，供读循环与 supervisor 复用，
        # 避免把「我们自己关的」误判成设备关闭了连接
        self._local_close: tuple[str, str] | None = None

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------

    @property
    def state(self) -> LinkState:
        return self._state

    @property
    def online(self) -> bool:
        return self._state.status == "online"

    def set_endpoint(self, host: str, port: int) -> None:
        self._state.host = host
        self._state.port = port

    def has_credentials(self) -> bool:
        return self._credentials is not None

    def snapshot(self) -> dict[str, Any]:
        data = self._state.as_dict()
        data["paired"] = self._credentials is not None
        return data

    # ------------------------------------------------------------------
    # 配对（TOFU + 短码证明）
    # ------------------------------------------------------------------

    async def pair(self, code: str, client_name: str, host: str, port: int) -> Credentials:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(
                host, port, ssl=_tls_context(), server_hostname=None, limit=P.MAX_FRAME_BYTES
            ),
            timeout=self._connect_timeout,
        )
        try:
            observed = self._pin_peer(writer, expected=None)
            hello = await wire.read_frame(reader)
            if hello is None:
                raise DeviceLinkError(P.LOCAL_BAD_RESPONSE, "设备在 server.hello 前关闭了连接")
            if hello["type"] != P.T_SERVER_HELLO:
                raise DeviceLinkError(P.LOCAL_BAD_RESPONSE, f"期望 server.hello，收到 {hello['type']}")
            body = hello["body"]
            fingerprint = wire.body_str(body, "fingerprint") or ""
            if not fingerprint or not observed or fingerprint.lower() != observed.lower():
                raise DeviceLinkError(
                    P.LOCAL_BAD_RESPONSE,
                    "TLS 证书指纹与 server.hello 申报的不一致，疑似中间人",
                )
            nonce_b64 = wire.body_str(body, "nonce")
            if not nonce_b64:
                raise DeviceLinkError(P.LOCAL_BAD_RESPONSE, "server.hello 缺少 nonce")
            server_nonce = wire.unb64(nonce_b64)

            client_nonce = os.urandom(16)
            proof = wire.pairing_proof(code, server_nonce, fingerprint, client_nonce, client_name)
            request_id = str(uuid.uuid4())
            await wire.write_frame(
                writer,
                wire.envelope(
                    P.T_PAIR_REQUEST,
                    request_id,
                    {
                        "code": code,
                        "proof": wire.b64(proof),
                        "clientNonce": wire.b64(client_nonce),
                        "clientName": client_name,
                    },
                ),
            )
            reply = await wire.read_frame(reader)
            if reply is None:
                raise DeviceLinkError(P.LOCAL_BAD_RESPONSE, "设备在配对响应前关闭了连接")
            if reply["type"] == P.T_PAIR_ERROR:
                rbody = reply["body"]
                raise DeviceLinkError(
                    wire.body_str(rbody, "reason") or "INTERNAL",
                    wire.body_str(rbody, "message") or "配对失败",
                )
            if reply["type"] != P.T_PAIR_OK:
                raise DeviceLinkError(P.LOCAL_BAD_RESPONSE, f"配对响应类型异常 {reply['type']}")
            rbody = reply["body"]
            creds = Credentials(
                client_id=wire.body_str(rbody, "clientId") or "",
                token=wire.body_str(rbody, "token") or "",
                device_fingerprint=wire.body_str(rbody, "fingerprint") or fingerprint,
                device_name=wire.body_str(rbody, "deviceName") or "Android",
            )
            if not creds.client_id or not creds.token:
                raise DeviceLinkError(P.LOCAL_BAD_RESPONSE, "配对响应缺少 clientId/token")
            creds.save(self._credentials_path)
            self._credentials = creds
            self.set_endpoint(host, port)
            self._state.device_name = creds.device_name
            self._state.device_fingerprint = creds.device_fingerprint
            self._state.client_id = creds.client_id
            return creds
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001 - 关闭失败不影响配对结果
                pass

    def _pin_peer(self, writer: asyncio.StreamWriter, expected: str | None) -> str:
        ssl_obj = writer.get_extra_info("ssl_object")
        if ssl_obj is None:
            raise DeviceLinkError("UNAVAILABLE", "连接没有建立 TLS")
        der = ssl_obj.getpeercert(binary_form=True)
        if not der:
            raise DeviceLinkError("TOKEN_INVALID", "设备没有出示证书")
        observed = wire.sha256_hex(der)
        if expected and observed.lower() != expected.lower():
            raise DeviceLinkError(
                "TOKEN_INVALID",
                f"设备证书指纹变化（期望 {expected}，实际 {observed}），已拒绝连接",
            )
        return observed

    # ------------------------------------------------------------------
    # 连接生命周期
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._supervisor = asyncio.create_task(self._supervise(), name="device-link-supervisor")

    async def stop(self, reason: str = REASON_SERVER_DISCONNECT) -> None:
        """本端主动断开（后端下线设备、token 轮换、用户点断开等）。

        ``reason`` 由调用方给出具体原因；默认文案明确标注「服务端发起」，
        不能再落成「设备关闭了连接」。
        """
        had_link = self._running or self._writer is not None or self._supervisor is not None
        self._running = False
        if had_link and self._state.status != "unpaired":
            self._local_close = (CLOSED_BY_SERVER, reason)
        await self._close_connection(reason)
        task = self._supervisor
        self._supervisor = None
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if self._state.status not in {"unpaired"}:
            self._state.status = "idle"
        # supervisor 在读循环结束时可能刚写下「设备侧断开」，这里以本端发起方为准
        if had_link and self._state.status != "unpaired":
            self._state.closed_by = CLOSED_BY_SERVER
            self._state.reason = reason

    async def _supervise(self) -> None:
        attempt = 0
        while self._running:
            if self._credentials is None:
                self._state.status = "unpaired"
                self._state.reason = "尚未配对"
                return
            self._state.status = "connecting"
            self._state.reason = None
            self._state.next_retry_at = None
            try:
                await self._connect_once()
                attempt = 0
                self._state.status = "online"
                self._state.reconnect_count = 0
                self._state.connected_at = self._clock()
                self._state.reason = None
                self._state.closed_by = None
                await self._read_loop()
            except asyncio.CancelledError:
                raise
            except DeviceLinkError as exc:
                self._state.closed_by, self._state.reason = self._classify_close(exc.message)
            except (OSError, ssl.SSLError, asyncio.TimeoutError) as exc:
                self._state.closed_by, self._state.reason = self._classify_close(
                    f"{type(exc).__name__}: {exc}"
                )
            except Exception as exc:  # noqa: BLE001 - 任何异常都只结束当前连接
                self._state.closed_by, self._state.reason = self._classify_close(
                    f"{type(exc).__name__}: {exc}"
                )
            finally:
                await self._close_connection(self._state.reason or "连接结束")

            if not self._running:
                break
            delay_ms = backoff_delay_ms(attempt)
            attempt += 1
            self._state.status = "offline"
            self._state.next_retry_at = self._clock() + delay_ms
            self._state.reconnect_count += 1
            self._state.current_action = None
            try:
                await asyncio.sleep(delay_ms / 1000)
            except asyncio.CancelledError:
                raise
        if self._state.status not in {"unpaired"}:
            self._state.status = "idle"

    async def _connect_once(self) -> None:
        self._local_close = None  # 新一轮连接，清掉上一轮的主动关闭标记
        creds = self._credentials
        if creds is None:
            raise DeviceLinkError(P.LOCAL_OFFLINE, "尚未配对")
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(
                self._state.host,
                self._state.port,
                ssl=_tls_context(),
                server_hostname=None,
                limit=P.MAX_FRAME_BYTES,
            ),
            timeout=self._connect_timeout,
        )
        self._generation += 1
        self._reader = reader
        self._writer = writer
        self._pong_event.clear()
        try:
            self._pin_peer(writer, expected=creds.device_fingerprint)
            hello = await wire.read_frame(reader)
            if hello is None or hello["type"] != P.T_SERVER_HELLO:
                raise DeviceLinkError(P.LOCAL_BAD_RESPONSE, "未收到 server.hello")
            fingerprint = wire.body_str(hello["body"], "fingerprint") or ""
            if fingerprint.lower() != creds.device_fingerprint.lower():
                raise DeviceLinkError("TOKEN_INVALID", "设备指纹与配对时不一致，拒绝连接")

            await self._send(
                wire.envelope(
                    P.T_HELLO,
                    str(uuid.uuid4()),
                    {
                        "clientId": creds.client_id,
                        "token": creds.token,
                        "clientNonce": wire.b64(os.urandom(16)),
                    },
                )
            )
            reply = await wire.read_frame(reader)
            if reply is None:
                raise DeviceLinkError(P.LOCAL_BAD_RESPONSE, "hello 后连接被关闭")
            if reply["type"] == P.T_HELLO_ERROR:
                raise DeviceLinkError(
                    wire.body_str(reply["body"], "reason") or "TOKEN_INVALID",
                    wire.body_str(reply["body"], "message") or "鉴权失败",
                )
            if reply["type"] != P.T_HELLO_OK:
                raise DeviceLinkError(P.LOCAL_BAD_RESPONSE, f"hello 响应类型异常 {reply['type']}")

            rotated = wire.body_str(reply["body"], "rotatedToken")
            if rotated:
                self._credentials = Credentials(
                    client_id=creds.client_id,
                    token=rotated,
                    device_fingerprint=creds.device_fingerprint,
                    device_name=creds.device_name,
                )
                self._credentials.save(self._credentials_path)

            self._state.device_name = creds.device_name
            self._state.device_fingerprint = creds.device_fingerprint
            self._state.client_id = creds.client_id
            self._state.last_heartbeat_at = self._clock()
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(), name="device-link-heartbeat")
        except Exception:
            await self._close_connection("握手失败")
            raise

    def _classify_close(self, fallback_reason: str) -> tuple[str, str]:
        """确定断连发起方与文案，避免把方向写反。

        - 本端刚主动关过（``stop`` / 心跳超时）：以本端记录为准；
        - 已经连上后读循环结束（EOF / 连接重置）：设备侧断开；
        - 还没连上就失败：网络/握手问题，不能归因给设备。
        """
        if self._local_close is not None:
            return self._local_close
        if self._state.status == "online":
            return CLOSED_BY_DEVICE, REASON_DEVICE_DISCONNECT
        return CLOSED_BY_NETWORK, fallback_reason

    async def _close_connection(self, reason: str) -> None:
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        writer, self._writer = self._writer, None
        self._reader = None
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass
        self._fail_pending(reason)

    def _fail_pending(self, reason: str) -> None:
        """断线时在飞命令一律失败，绝不重放。"""
        if not self._pending:
            return
        pending, self._pending = self._pending, {}
        for command_id, item in pending.items():
            if not item.future.done():
                item.future.set_exception(
                    DeviceLinkError(
                        P.LOCAL_UNKNOWN_OUTCOME,
                        f"链路中断（{reason}），命令 {command_id} 是否已执行未知；"
                        "重试请复用同一个 command_id",
                        retryable=True,
                    )
                )

    # ------------------------------------------------------------------
    # 收发
    # ------------------------------------------------------------------

    async def _send(self, obj: dict[str, Any]) -> None:
        writer = self._writer
        if writer is None:
            raise DeviceLinkError(P.LOCAL_OFFLINE, "链路离线，无法发送")
        async with self._write_lock:
            await wire.write_frame(writer, obj)

    async def _read_loop(self) -> None:
        reader = self._reader
        if reader is None:
            return
        while self._running and self._reader is reader:
            frame = await wire.read_frame(reader)
            if frame is None:
                # 本端主动关闭时，EOF 是我们自己造成的，不能写成设备断开
                _, reason = self._classify_close(REASON_DEVICE_DISCONNECT)
                raise DeviceLinkError(P.LOCAL_OFFLINE, reason)
            kind = frame["type"]
            if kind == P.T_RESULT:
                item = self._pending.pop(frame.get("id", ""), None)
                if item is not None and not item.future.done():
                    item.future.set_result(frame["body"])
            elif kind == P.T_PONG:
                self._pong_event.set()
                now = self._clock()
                self._state.last_heartbeat_at = now
                self._state.latency_ms = max(0, now - self._pong_sent_at)
            elif kind == P.T_EVENT:
                self._handle_event(frame["body"])
            elif kind == P.T_CAPTURE:
                # 设备侧「说一句就记下来」：上行帧只有业务字段，没有 kind/data 包裹
                body = frame.get("body") if isinstance(frame.get("body"), dict) else {}
                at = body.get("capturedAt")
                self._handle_event(
                    {
                        "kind": P.T_CAPTURE,
                        "data": body,
                        "at": int(at) if isinstance(at, (int, float)) else self._clock(),
                    }
                )
            # 其他类型忽略：设备只会在协议扩展时发新类型，旧客户端不应因此断线

    def _handle_event(self, body: dict[str, Any]) -> None:
        kind = wire.body_str(body, "kind") or "unknown"
        data = wire.body_obj(body, "data") or {}
        at = body.get("at")
        if kind == P.EV_ACTION_STARTED:
            self._state.current_action = wire.body_str(data, "name")
        elif kind == P.EV_ACTION_FINISHED:
            self._state.current_action = None
        if self._on_event is not None:
            try:
                self._on_event(kind, data, int(at) if isinstance(at, (int, float)) else self._clock())
            except Exception:  # noqa: BLE001 - 订阅方异常不能影响链路
                pass

    async def _heartbeat_loop(self) -> None:
        try:
            while self._running and self._writer is not None:
                await asyncio.sleep(self._ping_interval)
                if self._writer is None:
                    return
                self._pong_event.clear()
                self._pong_sent_at = self._clock()
                await self._send(
                    wire.envelope(P.T_PING, str(uuid.uuid4()), {"clientTime": self._clock()})
                )
                try:
                    await asyncio.wait_for(self._pong_event.wait(), timeout=self._pong_timeout)
                except asyncio.TimeoutError:
                    # 心跳超时：本端主动断连，交给 supervisor 退避重连（不重放命令）
                    writer = self._writer
                    self._local_close = (CLOSED_BY_HEARTBEAT, REASON_HEARTBEAT_TIMEOUT)
                    self._state.reason = REASON_HEARTBEAT_TIMEOUT
                    self._state.closed_by = CLOSED_BY_HEARTBEAT
                    if writer is not None:
                        writer.close()
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 心跳线程异常等价于断线
            self._local_close = (CLOSED_BY_HEARTBEAT, f"心跳异常: {exc}")
            self._state.reason = f"心跳异常: {exc}"
            self._state.closed_by = CLOSED_BY_HEARTBEAT
            writer = self._writer
            if writer is not None:
                writer.close()

    # ------------------------------------------------------------------
    # 命令
    # ------------------------------------------------------------------

    async def execute(
        self,
        name: str,
        params: dict[str, Any] | None = None,
        command_id: str | None = None,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        """下发一条命令。

        返回 ``{ok, result?, error?, replayed, duration_ms, command_id}``；
        链路层失败（离线/断线/等结果超时）抛 :class:`DeviceLinkError`，
        其中 ``UNKNOWN_OUTCOME`` 表示设备可能已经执行——重试务必复用 command_id。
        """
        if not self.online or self._writer is None:
            raise DeviceLinkError(P.LOCAL_OFFLINE, "设备不在线，命令未下发")
        cid = command_id or str(uuid.uuid4())
        timeout = int(timeout_ms or P.COMMAND_TIMEOUT_MS)
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        if cid in self._pending:
            raise DeviceLinkError("BAD_REQUEST", f"command_id {cid} 已在执行中")
        self._pending[cid] = _Pending(future=future, started_at=self._clock())
        self._state.commands_total += 1
        started = self._clock()
        try:
            await self._send(
                wire.envelope(
                    P.T_CMD,
                    cid,
                    {"name": name, "params": params or {}, "timeoutMs": timeout},
                )
            )
        except Exception as exc:  # noqa: BLE001 - 发送阶段断开同样属于未知结果
            self._pending.pop(cid, None)
            raise DeviceLinkError(
                P.LOCAL_UNKNOWN_OUTCOME,
                f"发送阶段链路断开（{exc}），命令是否执行未知",
                retryable=True,
            ) from exc

        try:
            body = await asyncio.wait_for(future, timeout=(timeout / 1000) + 3.0)
        except asyncio.TimeoutError as exc:
            self._pending.pop(cid, None)
            raise DeviceLinkError(
                P.LOCAL_UNKNOWN_OUTCOME,
                "等待结果超时，设备可能已执行；重试请复用同一个 command_id",
                retryable=True,
            ) from exc

        ok = bool(body.get("ok"))
        error = body.get("error") if isinstance(body.get("error"), dict) else None
        if not ok:
            self._state.commands_failed += 1
        return {
            "ok": ok,
            "command_id": cid,
            "result": body.get("result"),
            "error": error,
            "replayed": bool(body.get("replayed")),
            "duration_ms": int(body.get("durationMs") or (self._clock() - started)),
        }
