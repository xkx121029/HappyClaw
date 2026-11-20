"""链路协议自测（不依赖真机、不依赖设备侧 JVM）。

覆盖：
- 协议单一来源：vendored ``protocol.json`` 校验和固定，改协议必须显式改这里；
- 配对证明跨语言黄金向量（与设备侧 Kotlin 用例同一输入、同一期望值）；
- 帧编解码与非法帧；
- 配对握手 → hello → 命令执行 → 结果回流；
- 同一 command_id 只执行一次（幂等回放）；
- 客户端超时语义（UNKNOWN_OUTCOME，不自动重发）；
- 断线后自动重连，且不重放断线前的命令；
- 在飞命令遇到 TCP 断开：UNKNOWN_OUTCOME，不自动重发；
- 重连后复用同一 command_id：设备幂等回放；
- 心跳丢失 → 离线 → 恢复在线；
- 配对坏路径（错码 / 窗口一次性 / 尝试超限）与指纹不匹配；
- 设备侧 TIMEOUT 在重放时仍然稳定；
- token 轮换落盘并在重连时使用新 token。
"""

from __future__ import annotations

import asyncio
import json
import ssl
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from octop.infra.control.device_link import protocol as P
from octop.infra.control.device_link import wire
from octop.infra.control.device_link.client import (
    CLOSED_BY_DEVICE,
    CLOSED_BY_SERVER,
    DeviceLinkClient,
    DeviceLinkError,
)
from octop.infra.control.device_link.manager import DeviceLinkManager

# 设备仓库 protocol/spec/protocol.json 的校验和；两端同步的唯一硬约束
EXPECTED_SPEC_SHA256 = "57e02fd1c4347cecb18b4af0e67344c1e741cb692893fa096b5766e9a8ca6312"
PAIRING_CODE = "12345678"


def _make_cert(tmp: Path) -> tuple[Path, Path, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "HappyClaw Fake Device")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    key_path = tmp / "key.pem"
    cert_path = tmp / "cert.pem"
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    fingerprint = wire.sha256_hex(cert.public_bytes(serialization.Encoding.DER))
    return cert_path, key_path, fingerprint


class FakeDevice:
    """最小假设备：实现协议里客户端用到的全部消息类型。"""

    def __init__(self, cert_path: Path, key_path: Path, fingerprint: str) -> None:
        self.cert_path = cert_path
        self.key_path = key_path
        self.fingerprint = fingerprint
        self.executions: Counter[str] = Counter()
        self.results: dict[str, dict[str, Any]] = {}
        self.tokens: set[str] = set()
        self.writers: list[asyncio.StreamWriter] = []
        self.events: list[tuple[str, dict[str, Any]]] = []
        self._server: asyncio.AbstractServer | None = None
        self.port = 0
        # ---- 故障注入开关（默认全关，正常路径用例的行为不受影响）----
        self.silent_pong = False  # 收到 ping 也不回 pong（模拟心跳对端消失）
        self.hold_commands = False  # 收到 cmd 只计数、不回结果（模拟命令在飞时挂起）
        self.withhold_results = False  # 正常执行并写幂等缓存，但不回 result（模拟回包丢失）
        self.rotate_on_hello = False  # 第一次 hello 下发 rotatedToken
        self.rotated_tokens: list[str] = []
        self.seen_tokens: list[str] = []  # 每次 hello 收到的 token（含无效 token）
        # ---- 配对窗口：开窗、限次、成功或超限即关窗 ----
        self.pairing_open = True
        self.pairing_attempts_left = P.PAIRING_MAX_ATTEMPTS

    async def start(self, port: int = 0) -> None:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=str(self.cert_path), keyfile=str(self.key_path))
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", port, ssl=ctx)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        for writer in list(self.writers):
            writer.close()
        self.writers.clear()
        if self._server is not None:
            server, self._server = self._server, None
            server.close()
            await server.wait_closed()

    def drop_all(self) -> None:
        for writer in list(self.writers):
            writer.close()
        self.writers.clear()

    async def wait_connected(self, timeout: float = 5.0) -> None:
        await _wait_until(lambda: bool(self.writers), timeout, "设备侧没有连接")

    def _emit(self, writer: asyncio.StreamWriter, kind: str, data: dict[str, Any]) -> None:
        self.events.append((kind, data))
        payload = wire.envelope(
            P.T_EVENT, f"e{len(self.events)}", {"kind": kind, "seq": len(self.events), "at": _now(), "data": data}
        )
        writer.write(_frame(payload))

    async def _pair_error(
        self, writer: asyncio.StreamWriter, request_id: str, reason: str, message: str, attempts_left: int
    ) -> None:
        await wire.write_frame(
            writer,
            wire.envelope(
                P.T_PAIR_ERROR,
                request_id,
                {"reason": reason, "message": message, "attemptsLeft": attempts_left},
            ),
        )

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.writers.append(writer)
        nonce = b"\x01" * 16
        authed = False
        try:
            await wire.write_frame(
                writer,
                wire.envelope(
                    P.T_SERVER_HELLO,
                    "h1",
                    {
                        "apiVersion": P.VERSION,
                        "deviceName": "Fake Device",
                        "versionName": "0.0.0-test",
                        "versionCode": 0,
                        "fingerprint": self.fingerprint,
                        "nonce": wire.b64(nonce),
                        "pairingAvailable": self.pairing_open,
                        "serverTime": _now(),
                    },
                ),
            )
            while True:
                frame = await wire.read_frame(reader)
                if frame is None:
                    return
                kind = frame["type"]
                body = frame["body"]
                if kind == P.T_PAIR_REQUEST:
                    if not self.pairing_open:
                        # 窗口未开 / 已成功一次 / 尝试次数用尽，一律拒绝
                        await self._pair_error(
                            writer, frame["id"], "PAIRING_DISABLED", "配对窗口未开启", 0
                        )
                        continue
                    proof = wire.unb64(wire.body_str(body, "proof") or "")
                    client_nonce = wire.unb64(wire.body_str(body, "clientNonce") or "")
                    name = wire.body_str(body, "clientName") or "client"
                    expected = wire.pairing_proof(PAIRING_CODE, nonce, self.fingerprint, client_nonce, name)
                    if proof != expected:
                        self.pairing_attempts_left -= 1
                        if self.pairing_attempts_left <= 0:
                            self.pairing_attempts_left = 0
                            self.pairing_open = False
                            await self._pair_error(
                                writer, frame["id"], "TOO_MANY_ATTEMPTS", "配对尝试次数已用尽", 0
                            )
                        else:
                            await self._pair_error(
                                writer,
                                frame["id"],
                                "CODE_INVALID",
                                "配对码不正确",
                                self.pairing_attempts_left,
                            )
                        continue
                    self.pairing_open = False  # 配对码一次性：成功即关窗
                    token = wire.b64(b"t" * 32)
                    self.tokens.add(token)
                    authed = True
                    await wire.write_frame(
                        writer,
                        wire.envelope(
                            P.T_PAIR_OK,
                            frame["id"],
                            {
                                "clientId": "c_fake",
                                "token": token,
                                "deviceName": "Fake Device",
                                "fingerprint": self.fingerprint,
                                "serverTime": _now(),
                            },
                        ),
                    )
                    self._emit(writer, P.EV_CLIENT_CONNECTED, {"clientId": "c_fake", "mode": "paired"})
                elif kind == P.T_HELLO:
                    token = wire.body_str(body, "token") or ""
                    self.seen_tokens.append(token)
                    if token not in self.tokens:
                        await wire.write_frame(
                            writer,
                            wire.envelope(
                                P.T_HELLO_ERROR,
                                frame["id"],
                                {"reason": "TOKEN_INVALID", "message": "token 无效"},
                            ),
                        )
                        continue
                    authed = True
                    hello_body: dict[str, Any] = {
                        "serverTime": _now(),
                        "rotateAfterMs": P.TOKEN_ROTATION_MS,
                    }
                    if self.rotate_on_hello and not self.rotated_tokens:
                        rotated = wire.b64(b"r" * 32)
                        self.tokens.add(rotated)
                        self.rotated_tokens.append(rotated)
                        hello_body["rotatedToken"] = rotated
                    await wire.write_frame(
                        writer, wire.envelope(P.T_HELLO_OK, frame["id"], hello_body)
                    )
                    self._emit(writer, P.EV_CLIENT_CONNECTED, {"clientId": "c_fake", "mode": "session"})
                elif kind == P.T_PING:
                    if self.silent_pong:
                        # 静默丢 pong：客户端应自行判定心跳超时并断连重连
                        continue
                    await wire.write_frame(
                        writer, wire.envelope(P.T_PONG, frame["id"], {"serverTime": _now()})
                    )
                elif kind == P.T_CMD:
                    if not authed:
                        await wire.write_frame(
                            writer,
                            wire.envelope(
                                P.T_RESULT,
                                frame["id"],
                                _error_body("NOT_AUTHENTICATED", "请先 hello"),
                            ),
                        )
                        continue
                    asyncio.create_task(self._run_command(writer, frame))
        except (ConnectionError, asyncio.IncompleteReadError, ssl.SSLError):
            return
        finally:
            if writer in self.writers:
                self.writers.remove(writer)
            writer.close()

    async def _run_command(self, writer: asyncio.StreamWriter, frame: dict[str, Any]) -> None:
        cid = frame["id"]
        body = frame["body"]
        name = wire.body_str(body, "name") or ""
        params = wire.body_obj(body, "params") or {}
        self._emit(writer, P.EV_ACTION_STARTED, {"commandId": cid, "name": name})
        started = _now()
        if self.hold_commands:
            # 命令已被设备接收（执行次数 +1），但故意挂起不回包
            self.executions[cid] += 1
            return
        if cid in self.results:
            payload = dict(self.results[cid])
            payload["replayed"] = True
        else:
            self.executions[cid] += 1
            if params.get("_silent"):
                # 模拟「设备收到了但永远不回包」：验证客户端等待结果超时的语义
                return
            timeout_ms = int(body.get("timeoutMs") or P.COMMAND_TIMEOUT_MS)
            try:
                payload = await asyncio.wait_for(self._execute(name, params), timeout=timeout_ms / 1000)
            except asyncio.TimeoutError:
                # 设备侧超时也要回执，并带上 TIMEOUT；客户端据此知道「设备没执行完」
                payload = _error_body("TIMEOUT", f"命令 {name} 超过 {timeout_ms}ms 未完成")
            self.results[cid] = payload
            payload = dict(payload)
            payload["replayed"] = False
        payload["durationMs"] = _now() - started
        if self.withhold_results:
            # 结果已进幂等缓存，但故意不回流：客户端只能判定「结果未知」
            return
        try:
            await wire.write_frame(writer, wire.envelope(P.T_RESULT, cid, payload))
            self._emit(
                writer,
                P.EV_ACTION_FINISHED,
                {"commandId": cid, "name": name, "ok": payload.get("ok"), "durationMs": payload["durationMs"]},
            )
        except (ConnectionError, ssl.SSLError):
            pass

    async def _execute(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        if name == "ui.swipe":
            duration = int(params.get("durationMs") or 0)
            if duration > 0:
                await asyncio.sleep(duration / 1000)
        if name == "screen.screenshot":
            return {
                "ok": True,
                "result": {
                    "format": "png",
                    "sizeBytes": 4,
                    "base64": wire.b64(b"\x89PNG"),
                },
            }
        if name == "screen.tree":
            return {"ok": True, "result": {"elements": [{"viewId": "fake"}]}}
        return {"ok": True, "result": {"success": True, "reason": "fake"}}


def _frame(payload: dict[str, Any]) -> bytes:
    data = wire.encode(payload)
    return len(data).to_bytes(4, "big") + data


def _error_body(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message, "retryable": False}}


def _now() -> int:
    return int(time.time() * 1000)


async def _wait_until(predicate: Callable[[], bool], timeout: float, message: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.05)
    raise AssertionError(message)


@pytest.fixture()
async def device(tmp_path: Path) -> Any:
    cert_path, key_path, fingerprint = _make_cert(tmp_path)
    fake = FakeDevice(cert_path, key_path, fingerprint)
    await fake.start()
    try:
        yield fake
    finally:
        await fake.stop()


def test_spec_is_single_source() -> None:
    assert P.SPEC_SHA256 == EXPECTED_SPEC_SHA256, "protocol.json 变了：请同步设备侧并更新校验和"
    assert P.VERSION == 1
    for name in (
        "screen.screenshot",
        "ui.click",
        "ui.swipe",
        "ui.typeText",
        "screen.tree",
        "app.list",
        "notification.status",
        "notification.list",
        "calendar.list",
        "alarm.list",
        "today.sync",
    ):
        assert name in P.COMMANDS
    assert "UNKNOWN_OUTCOME" in P.ERROR_CODES


def test_pairing_proof_matches_kotlin_golden_vector() -> None:
    proof = wire.pairing_proof(
        "12345678",
        bytes(range(16)),
        "4f9a1c2b3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8",
        bytes(0xA0 + i for i in range(16)),
        "HappyClaw CLI",
    )
    assert proof.hex() == "70c7f7fd0dc8f38c0f29aedcf132deebc46d817930e24f762b792901d2fb02de"


def test_frame_roundtrip_and_rejects_bad_frames() -> None:
    raw = _frame(wire.envelope("ping", "1", {"clientTime": 1}))
    assert wire.parse(raw[4:])["type"] == "ping"

    with pytest.raises(wire.ProtocolError):
        wire.parse(b"not-json")
    with pytest.raises(wire.ProtocolError):
        wire.parse(b'{"version": 99, "type": "ping"}')
    with pytest.raises(wire.ProtocolError):
        wire.parse(b'{"version": 1}')


async def test_pair_hello_and_command(device: FakeDevice, tmp_path: Path) -> None:
    client = DeviceLinkClient(credentials_path=tmp_path / "credentials.json")
    creds = await client.pair(PAIRING_CODE, "HappyClaw Test", "127.0.0.1", device.port)
    assert creds.client_id == "c_fake"
    assert creds.device_fingerprint == device.fingerprint

    await client.start()
    try:
        await _wait_until(lambda: client.online, 5.0, "客户端没有进入在线状态")
        reply = await client.execute("screen.tree", {})
        assert reply["ok"] is True
        assert reply["result"]["elements"][0]["viewId"] == "fake"
    finally:
        await client.stop()


async def test_same_command_id_executes_once(device: FakeDevice, tmp_path: Path) -> None:
    client = DeviceLinkClient(credentials_path=tmp_path / "credentials.json")
    await client.pair(PAIRING_CODE, "HappyClaw Test", "127.0.0.1", device.port)
    await client.start()
    try:
        await _wait_until(lambda: client.online, 5.0, "客户端没有进入在线状态")
        cid = str(uuid.uuid4())
        first = await client.execute("ui.click", {"x": 10, "y": 20}, command_id=cid)
        second = await client.execute("ui.click", {"x": 10, "y": 20}, command_id=cid)
        assert first["ok"] and second["ok"]
        assert first["replayed"] is False
        assert second["replayed"] is True
        assert device.executions[cid] == 1, "同一个 command_id 被设备重复执行"
    finally:
        await client.stop()


async def test_device_timeout_is_reported_and_not_resent(device: FakeDevice, tmp_path: Path) -> None:
    client = DeviceLinkClient(credentials_path=tmp_path / "credentials.json")
    await client.pair(PAIRING_CODE, "HappyClaw Test", "127.0.0.1", device.port)
    await client.start()
    try:
        await _wait_until(lambda: client.online, 5.0, "客户端没有进入在线状态")
        cid = str(uuid.uuid4())
        reply = await client.execute(
            "ui.swipe",
            {"x1": 0, "y1": 0, "x2": 1, "y2": 1, "durationMs": 2000},
            command_id=cid,
            timeout_ms=200,
        )
        assert reply["ok"] is False
        assert (reply["error"] or {}).get("code") == "TIMEOUT"
        # 客户端不会因为超时自动补发
        assert device.executions[cid] == 1
    finally:
        await client.stop()


async def test_stalled_device_leads_to_unknown_outcome(device: FakeDevice, tmp_path: Path) -> None:
    client = DeviceLinkClient(credentials_path=tmp_path / "credentials.json")
    await client.pair(PAIRING_CODE, "HappyClaw Test", "127.0.0.1", device.port)
    await client.start()
    try:
        await _wait_until(lambda: client.online, 5.0, "客户端没有进入在线状态")
        cid = str(uuid.uuid4())
        with pytest.raises(DeviceLinkError) as excinfo:
            await client.execute("ui.click", {"x": 1, "y": 2, "_silent": True}, command_id=cid, timeout_ms=100)
        assert excinfo.value.code == "UNKNOWN_OUTCOME"
        assert excinfo.value.retryable is True
        assert device.executions[cid] == 1, "命令被重复下发"
    finally:
        await client.stop()


async def test_reconnect_after_disconnect_and_no_replay(device: FakeDevice, tmp_path: Path) -> None:
    client = DeviceLinkClient(credentials_path=tmp_path / "credentials.json")
    await client.pair(PAIRING_CODE, "HappyClaw Test", "127.0.0.1", device.port)
    await client.start()
    try:
        await _wait_until(lambda: client.online, 5.0, "客户端没有进入在线状态")
        device.drop_all()
        await _wait_until(lambda: not client.online, 5.0, "断线后状态没有变化")
        await _wait_until(lambda: client.online, 15.0, "客户端没有自动重连")
        reply = await client.execute("ui.click", {"x": 1, "y": 2})
        assert reply["ok"] is True
        assert not any(cid == reply["command_id"] for cid in device.executions if device.executions[cid] > 1)
    finally:
        await client.stop()


async def test_manager_records_history_and_screenshot_artifact(device: FakeDevice, tmp_path: Path) -> None:
    manager = DeviceLinkManager(root=tmp_path)
    await manager.pair("127.0.0.1", device.port, PAIRING_CODE, "HappyClaw Test")
    try:
        await _wait_until(lambda: manager._client is not None and manager._client.online, 5.0, "管理器未上线")
        shot = await manager.run_command("screen.screenshot", {})
        assert shot["ok"] is True
        artifact = Path(str(shot["artifact"]))
        assert artifact.is_file() and artifact.read_bytes().startswith(b"\x89PNG")
        assert "base64" not in (shot["result"] or {})

        status = await manager.status()
        assert status["status"] == "online"
        assert status["recent_commands"][-1]["name"] == "screen.screenshot"
        kinds = [event["kind"] for event in manager.recent_events()]
        assert "command.finished" in kinds
    finally:
        await manager.close()


async def test_断连发起方决定_reason_方向(device: FakeDevice, tmp_path: Path) -> None:
    """本端主动断开写「服务端」，设备掉线写「设备侧」，两个方向不能共用一句。"""
    manager = DeviceLinkManager(root=tmp_path)
    await manager.pair("127.0.0.1", device.port, PAIRING_CODE, "HappyClaw Test")
    try:
        await _wait_until(
            lambda: manager._client is not None and manager._client.online, 5.0, "管理器未上线"
        )

        # 设备侧断连（App 退出 / 切后台 / 网络断）：归因设备
        device.drop_all()
        await _wait_until(
            lambda: (manager._client.state.closed_by or "") == CLOSED_BY_DEVICE,
            5.0,
            "设备侧断连没有归因到设备",
        )
        device_status = await manager.status()
        assert device_status["closed_by"] == CLOSED_BY_DEVICE
        assert "设备" in (device_status["reason"] or "")

        # 自动重连后由本端发起断连：必须写服务端，不能沿用设备文案
        await _wait_until(lambda: manager._client.online, 15.0, "客户端没有自动重连")
        await manager.disconnect()
        status = await manager.status()
        assert status["status"] == "idle"
        assert status["closed_by"] == CLOSED_BY_SERVER
        assert "服务端" in (status["reason"] or "")
        assert "设备关闭了连接" not in (status["reason"] or "")
        assert status["reason"] != device_status["reason"], "两个方向的文案不能共用一句"
    finally:
        await manager.close()


# ----------------------------------------------------------------------
# 坏路径：断线 / 幂等回放 / 心跳
# ----------------------------------------------------------------------


async def test_在飞命令遇到断线必须报未知结果且不重发(
    device: FakeDevice, tmp_path: Path
) -> None:
    """设备收到命令后 TCP 断开：只能以 UNKNOWN_OUTCOME 失败，且不会自动补发。"""
    client = DeviceLinkClient(credentials_path=tmp_path / "credentials.json")
    await client.pair(PAIRING_CODE, "HappyClaw Test", "127.0.0.1", device.port)
    device.hold_commands = True  # 设备只收命令、挂起不回包
    await client.start()
    try:
        await _wait_until(lambda: client.online, 5.0, "客户端没有进入在线状态")
        cid = str(uuid.uuid4())
        task = asyncio.create_task(client.execute("ui.click", {"x": 1, "y": 2}, command_id=cid))
        await _wait_until(lambda: device.executions[cid] == 1, 5.0, "设备没有收到在飞命令")
        device.drop_all()  # 命令还没回结果就断开

        with pytest.raises(DeviceLinkError) as excinfo:
            await asyncio.wait_for(task, timeout=3.0)
        assert excinfo.value.code == "UNKNOWN_OUTCOME"
        assert excinfo.value.retryable is True
        assert device.executions[cid] == 1, "断线后命令被自动重发"
    finally:
        await client.stop()


async def test_断线重连后复用同一命令_id_走幂等回放(
    device: FakeDevice, tmp_path: Path
) -> None:
    """设备执行完并缓存结果、但回包丢失：重连后同 id 重试只能拿到 replayed 回放。"""
    client = DeviceLinkClient(credentials_path=tmp_path / "credentials.json")
    await client.pair(PAIRING_CODE, "HappyClaw Test", "127.0.0.1", device.port)
    device.withhold_results = True  # 结果留在设备缓存里，但不回包
    await client.start()
    try:
        await _wait_until(lambda: client.online, 5.0, "客户端没有进入在线状态")
        cid = str(uuid.uuid4())
        task = asyncio.create_task(client.execute("ui.click", {"x": 3, "y": 4}, command_id=cid))
        await _wait_until(
            lambda: cid in device.results and device.executions[cid] == 1,
            5.0,
            "设备没有完成命令并缓存结果",
        )
        device.withhold_results = False
        device.drop_all()

        with pytest.raises(DeviceLinkError) as excinfo:
            await asyncio.wait_for(task, timeout=3.0)
        assert excinfo.value.code == "UNKNOWN_OUTCOME"
        assert excinfo.value.retryable is True

        await _wait_until(lambda: client.online, 15.0, "客户端没有自动重连")
        replay = await client.execute("ui.click", {"x": 3, "y": 4}, command_id=cid)
        assert replay["ok"] is True
        assert replay["replayed"] is True, "重试没有命中设备侧幂等缓存"
        assert device.executions[cid] == 1, "复用同一 command_id 仍被重复执行"
    finally:
        await client.stop()


async def test_心跳丢失后离线并在恢复后重新在线(
    device: FakeDevice, tmp_path: Path
) -> None:
    """设备静默丢 pong：客户端 2s 内离线；恢复回 pong 后退避重连成功。"""
    client = DeviceLinkClient(
        credentials_path=tmp_path / "credentials.json",
        ping_interval_ms=100,
        pong_timeout_ms=300,
    )
    await client.pair(PAIRING_CODE, "HappyClaw Test", "127.0.0.1", device.port)
    await client.start()
    try:
        await _wait_until(lambda: client.online, 5.0, "客户端没有进入在线状态")
        await _wait_until(
            lambda: client.state.last_heartbeat_at is not None, 3.0, "心跳时间没有初始化"
        )
        heartbeat_before = client.state.last_heartbeat_at or 0

        device.silent_pong = True
        # 100ms 发 ping + 300ms 等 pong，2s 上限足以证明是心跳判定的离线
        await _wait_until(lambda: not client.online, 2.0, "心跳丢失后 2s 内没有离线")
        assert client.state.reason, "离线原因不应为空"

        device.silent_pong = False
        await _wait_until(lambda: client.online, 10.0, "pong 恢复后没有重连成功")
        await _wait_until(
            lambda: (client.state.last_heartbeat_at or 0) > heartbeat_before,
            3.0,
            "恢复在线后心跳时间没有推进",
        )
        assert client.state.current_action is None
    finally:
        await client.stop()


# ----------------------------------------------------------------------
# 坏路径：配对与证书指纹
# ----------------------------------------------------------------------


async def test_配对码错误后仍可用正确码成功(device: FakeDevice, tmp_path: Path) -> None:
    """错误配对码：CODE_INVALID，尝试次数递减，剩余次数内正确码仍能配对。"""
    client = DeviceLinkClient(credentials_path=tmp_path / "credentials.json")
    with pytest.raises(DeviceLinkError) as excinfo:
        await client.pair("00000000", "HappyClaw Test", "127.0.0.1", device.port)
    assert excinfo.value.code == "CODE_INVALID"
    assert device.pairing_attempts_left == P.PAIRING_MAX_ATTEMPTS - 1, "设备端尝试次数没有递减"

    creds = await client.pair(PAIRING_CODE, "HappyClaw Test", "127.0.0.1", device.port)
    assert creds.client_id == "c_fake"
    assert device.pairing_open is False, "配对成功后窗口应一次性关闭"


async def test_配对窗口成功一次后立即关闭(device: FakeDevice, tmp_path: Path) -> None:
    """同一配对码重复使用：第一次成功后窗口关闭，第二次 PAIRING_DISABLED。"""
    client = DeviceLinkClient(credentials_path=tmp_path / "credentials.json")
    await client.pair(PAIRING_CODE, "HappyClaw Test", "127.0.0.1", device.port)
    with pytest.raises(DeviceLinkError) as excinfo:
        await client.pair(PAIRING_CODE, "HappyClaw Test", "127.0.0.1", device.port)
    assert excinfo.value.code == "PAIRING_DISABLED"


async def test_连续三次配对码错误后窗口关闭(device: FakeDevice, tmp_path: Path) -> None:
    """连续 3 次错码：第三次 TOO_MANY_ATTEMPTS，之后正确码也是 PAIRING_DISABLED。"""
    client = DeviceLinkClient(credentials_path=tmp_path / "credentials.json")
    for _ in range(2):
        with pytest.raises(DeviceLinkError) as excinfo:
            await client.pair("00000000", "HappyClaw Test", "127.0.0.1", device.port)
        assert excinfo.value.code == "CODE_INVALID"

    with pytest.raises(DeviceLinkError) as excinfo:
        await client.pair("00000000", "HappyClaw Test", "127.0.0.1", device.port)
    assert excinfo.value.code == "TOO_MANY_ATTEMPTS"
    assert device.pairing_attempts_left == 0
    assert device.pairing_open is False

    with pytest.raises(DeviceLinkError) as excinfo:
        await client.pair(PAIRING_CODE, "HappyClaw Test", "127.0.0.1", device.port)
    assert excinfo.value.code == "PAIRING_DISABLED"


async def test_设备指纹变化时拒绝连接且不改写凭据(tmp_path: Path) -> None:
    """凭据钉的是设备 A 的指纹，同端口换成设备 B：必须拒绝，且凭据不被改写。"""
    dir_a = tmp_path / "dev-a"
    dir_a.mkdir()
    cert_a, key_a, fp_a = _make_cert(dir_a)
    device_a = FakeDevice(cert_a, key_a, fp_a)
    await device_a.start()
    port = device_a.port

    client = DeviceLinkClient(credentials_path=tmp_path / "credentials.json")
    device_b: FakeDevice | None = None
    try:
        await client.pair(PAIRING_CODE, "HappyClaw Test", "127.0.0.1", port)
        await device_a.stop()

        dir_b = tmp_path / "dev-b"
        dir_b.mkdir()
        cert_b, key_b, fp_b = _make_cert(dir_b)
        assert fp_b != fp_a, "两张自签证书的指纹不应相同"
        device_b = FakeDevice(cert_b, key_b, fp_b)
        await device_b.start(port=port)

        await client.start()
        await _wait_until(
            lambda: bool(client.state.reason)
            and ("指纹" in (client.state.reason or "") or "证书" in (client.state.reason or "")),
            5.0,
            "客户端没有因指纹/证书不匹配拒绝连接",
        )
        assert client.online is False, "换了证书后不应建立在线会话"

        saved = json.loads((tmp_path / "credentials.json").read_text(encoding="utf-8"))
        assert saved["deviceFingerprint"] == fp_a, "凭据里的设备指纹被静默改写"
    finally:
        await client.stop()
        if device_b is not None:
            await device_b.stop()
        await device_a.stop()


# ----------------------------------------------------------------------
# 坏路径：设备侧超时与 token 轮换
# ----------------------------------------------------------------------


async def test_设备侧超时在重放时仍然是超时(device: FakeDevice, tmp_path: Path) -> None:
    """设备回 TIMEOUT 后该 id 永远保持 TIMEOUT：重试只能拿到 replayed 的失败结果。"""
    client = DeviceLinkClient(credentials_path=tmp_path / "credentials.json")
    await client.pair(PAIRING_CODE, "HappyClaw Test", "127.0.0.1", device.port)
    await client.start()
    try:
        await _wait_until(lambda: client.online, 5.0, "客户端没有进入在线状态")
        cid = str(uuid.uuid4())
        params = {"x1": 0, "y1": 0, "x2": 1, "y2": 1, "durationMs": 2000}
        first = await client.execute("ui.swipe", params, command_id=cid, timeout_ms=200)
        assert first["ok"] is False
        assert (first["error"] or {}).get("code") == "TIMEOUT"
        assert first["replayed"] is False

        second = await client.execute("ui.swipe", params, command_id=cid, timeout_ms=200)
        assert second["ok"] is False, "设备侧超时不应在之后变成成功"
        assert (second["error"] or {}).get("code") == "TIMEOUT"
        assert second["replayed"] is True
        assert device.executions[cid] == 1, "TIMEOUT 后被重复执行"
    finally:
        await client.stop()


async def test_token_轮换后落盘并在重连时使用新_token(
    device: FakeDevice, tmp_path: Path
) -> None:
    """hello.ok 下发 rotatedToken：新 token 必须落盘，并在下一次重连时使用。"""
    client = DeviceLinkClient(credentials_path=tmp_path / "credentials.json")
    creds = await client.pair(PAIRING_CODE, "HappyClaw Test", "127.0.0.1", device.port)
    old_token = creds.token
    device.rotate_on_hello = True
    await client.start()
    try:
        await _wait_until(lambda: client.online, 5.0, "客户端没有进入在线状态")
        await _wait_until(lambda: bool(device.rotated_tokens), 3.0, "设备没有下发 rotatedToken")
        new_token = device.rotated_tokens[0]
        assert new_token != old_token

        saved = json.loads((tmp_path / "credentials.json").read_text(encoding="utf-8"))
        assert saved["token"] == new_token, "轮换后的 token 没有落盘"
        assert device.seen_tokens == [old_token], "首次 hello 应携带旧 token"

        device.drop_all()
        await _wait_until(lambda: len(device.seen_tokens) >= 2, 10.0, "重连后设备没有收到 hello")
        assert device.seen_tokens[-1] == new_token, "重连没有使用轮换后的新 token"
        assert device.seen_tokens.count(old_token) == 1, "轮换后旧 token 仍被使用"
    finally:
        await client.stop()

