"""设备链路协议常量。

唯一来源是同目录的 ``protocol.json``——它和设备仓库
``happyclaw-device/protocol/spec/protocol.json`` 是同一份文件，不允许各写一份。
任何一端改了协议而没同步本文件，``tests/test_device_link_protocol.py`` 里的
一致性用例会失败（校验和记录在 ``SPEC_SHA256``）。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

SPEC_PATH: Final[Path] = Path(__file__).with_name("protocol.json")
SPEC_BYTES: Final[bytes] = SPEC_PATH.read_bytes()
SPEC_SHA256: Final[str] = hashlib.sha256(SPEC_BYTES).hexdigest()
SPEC: Final[dict[str, Any]] = json.loads(SPEC_BYTES.decode("utf-8"))

VERSION: Final[int] = int(SPEC["version"])
DEFAULTS: Final[dict[str, Any]] = SPEC["defaults"]

MAX_FRAME_BYTES: Final[int] = int(DEFAULTS["maxFrameBytes"])
COMMAND_TIMEOUT_MS: Final[int] = int(DEFAULTS["commandTimeoutMs"])
PING_INTERVAL_MS: Final[int] = int(DEFAULTS["pingIntervalMs"])
PONG_TIMEOUT_MS: Final[int] = int(DEFAULTS["pongTimeoutMs"])
IDLE_TIMEOUT_MS: Final[int] = int(DEFAULTS["idleTimeoutMs"])
IDEMPOTENCY_TTL_MS: Final[int] = int(DEFAULTS["idempotencyTtlMs"])
TOKEN_ROTATION_MS: Final[int] = int(DEFAULTS["tokenRotationMs"])
TOKEN_OVERLAP_MS: Final[int] = int(DEFAULTS["tokenOverlapMs"])
PAIRING_TTL_MS: Final[int] = int(DEFAULTS["pairingTtlMs"])
PAIRING_MAX_ATTEMPTS: Final[int] = int(DEFAULTS["pairingMaxAttempts"])
RECONNECT_INITIAL_MS: Final[int] = int(DEFAULTS["reconnectInitialMs"])
RECONNECT_MAX_MS: Final[int] = int(DEFAULTS["reconnectMaxMs"])
RECONNECT_JITTER: Final[float] = float(DEFAULTS["reconnectJitter"])

# 配对证明的域分隔串：两端写死同一个值，改它等于让所有旧配对失效
PAIRING_CONTEXT: Final[str] = "happyclaw-pair-v1"

ERROR_CODES: Final[tuple[str, ...]] = tuple(SPEC["errorCodes"])
COMMANDS: Final[dict[str, dict[str, Any]]] = {c["name"]: c for c in SPEC["commands"]}
COMMAND_NAMES: Final[tuple[str, ...]] = tuple(COMMANDS)

# 消息类型
T_PAIR_REQUEST: Final[str] = "pair.request"
T_HELLO: Final[str] = "hello"
T_CMD: Final[str] = "cmd"
T_PING: Final[str] = "ping"
T_SERVER_HELLO: Final[str] = "server.hello"
T_PAIR_OK: Final[str] = "pair.ok"
T_PAIR_ERROR: Final[str] = "pair.error"
T_HELLO_OK: Final[str] = "hello.ok"
T_HELLO_ERROR: Final[str] = "hello.error"
T_RESULT: Final[str] = "result"
T_PONG: Final[str] = "pong"
T_EVENT: Final[str] = "event"
# 设备主动上行的「说一句就记下来」：不带 command_id，服务端只做记录与同步
T_CAPTURE: Final[str] = "today.capture"

# 事件 kind（设备侧 LinkServer.EventKind 的字面量）
EV_CLIENT_CONNECTED: Final[str] = "client.connected"
EV_CLIENT_DISCONNECTED: Final[str] = "client.disconnected"
EV_ACTION_STARTED: Final[str] = "action.started"
EV_ACTION_FINISHED: Final[str] = "action.finished"
EV_HEARTBEAT: Final[str] = "heartbeat"

# 客户端本地错误码：设备没回包、链路断了才有，不会出现在设备回执里
LOCAL_UNKNOWN_OUTCOME: Final[str] = "UNKNOWN_OUTCOME"
LOCAL_OFFLINE: Final[str] = "OFFLINE"
LOCAL_BAD_RESPONSE: Final[str] = "BAD_RESPONSE"


def command_spec(name: str) -> dict[str, Any]:
    """取一条命令的协议描述；未登记的命令返回空 dict（由设备侧拒绝）。"""
    return COMMANDS.get(name, {})
