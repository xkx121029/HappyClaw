"""线上报文：4 字节大端长度 + UTF-8 JSON 信封。

信封形状 ``{version,type,id,ts,body}`` 与设备侧 ``Wire.envelope`` 完全一致；
配对的 HMAC 证明也必须逐字节一致，否则两端永远对不上。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import struct
from typing import Any, Final

from . import protocol as P

_HEADER: Final[struct.Struct] = struct.Struct(">I")


class ProtocolError(Exception):
    """帧或信封不合规。设备侧遇到同类问题会直接断连，不尝试跳过。"""


def b64(data: bytes) -> str:
    """URL-safe base64，无填充——与 Java ``Base64.getUrlEncoder().withoutPadding()`` 对齐。"""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def unb64(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hmac_sha256(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def pairing_proof(
    code: str,
    server_nonce: bytes,
    fingerprint_hex: str,
    client_nonce: bytes,
    client_name: str,
) -> bytes:
    """与设备侧 ``PairingProof.compute`` 同构。

    key  = SHA256("happyclaw-pair-v1" + code + serverNonce)
    data = serverNonce + fingerprintHex(ASCII) + clientNonce + clientName(UTF-8)
    指纹进 HMAC 数据是关键：中间人转发时出示的证书指纹不同，设备端校验必然失败。
    """
    key = sha256(P.PAIRING_CONTEXT.encode("utf-8") + code.encode("utf-8") + server_nonce)
    data = (
        server_nonce
        + fingerprint_hex.encode("ascii")
        + client_nonce
        + client_name.encode("utf-8")
    )
    return hmac_sha256(key, data)


def envelope(type_: str, id_: str, body: dict[str, Any], ts: int | None = None) -> dict[str, Any]:
    import time

    return {
        "version": P.VERSION,
        "type": type_,
        "id": id_,
        "ts": int(ts if ts is not None else time.time() * 1000),
        "body": body,
    }


def encode(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def parse(payload: bytes) -> dict[str, Any]:
    try:
        obj = json.loads(payload.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - 任何解析失败都按坏帧处理
        raise ProtocolError(f"帧载荷不是合法 JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise ProtocolError("帧载荷不是 JSON 对象")
    version = obj.get("version", P.VERSION)
    if version != P.VERSION:
        raise ProtocolError(f"不支持的协议版本 {version}")
    if not isinstance(obj.get("type"), str):
        raise ProtocolError("缺少 type")
    if not isinstance(obj.get("body", {}), dict):
        raise ProtocolError("body 不是对象")
    obj.setdefault("id", "")
    obj.setdefault("body", {})
    obj.setdefault("ts", 0)
    return obj


async def write_frame(writer: asyncio.StreamWriter, obj: dict[str, Any]) -> None:
    payload = encode(obj)
    if len(payload) > P.MAX_FRAME_BYTES:
        raise ProtocolError(f"帧过大: {len(payload)}")
    writer.write(_HEADER.pack(len(payload)) + payload)
    await writer.drain()


async def read_frame(reader: asyncio.StreamReader) -> dict[str, Any] | None:
    """读一帧；对端正常关闭（EOF）返回 None。"""
    try:
        header = await reader.readexactly(4)
    except asyncio.IncompleteReadError as exc:
        if not exc.partial:
            return None
        raise ProtocolError("连接在帧头中途断开") from exc
    (length,) = _HEADER.unpack(header)
    if length <= 0 or length > P.MAX_FRAME_BYTES:
        raise ProtocolError(f"非法帧长度 {length}")
    try:
        payload = await reader.readexactly(length)
    except asyncio.IncompleteReadError as exc:
        raise ProtocolError(f"连接在帧中途断开（已读 {len(exc.partial)}/{length}）") from exc
    return parse(payload)


def body_str(body: dict[str, Any], key: str) -> str | None:
    value = body.get(key)
    if isinstance(value, str):
        return value
    return None


def body_obj(body: dict[str, Any], key: str) -> dict[str, Any] | None:
    value = body.get(key)
    return value if isinstance(value, dict) else None
