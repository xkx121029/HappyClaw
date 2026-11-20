"""链路管理层：进程级单例，负责状态、命令历史、事件分发与截图落盘。

界面需要的三样东西都在这里产出，而不是只在日志里：
- 连接状态（含最近一次心跳、当前正在执行的动作）→ ``status()``
- 每次命令的结果（成功/失败、耗时、产出物路径）→ ``recent_commands()``
- 设备主动推的事件流 → ``subscribe()`` 队列，由 API 层转 SSE
"""

from __future__ import annotations

import asyncio
import binascii
import json
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from octop.infra.utils.paths import PathLayout

from . import protocol as P
from .client import (
    CLOSED_BY_SERVER,
    REASON_SERVER_DISCONNECT,
    Credentials,
    DeviceLinkClient,
    DeviceLinkError,
)
from .wire import unb64

_COMMAND_HISTORY = 50
_EVENT_HISTORY = 200


class DeviceLinkManager:
    def __init__(self, root: Path | None = None) -> None:
        self._root = (root or PathLayout.from_env().root) / "device-link"
        self._settings_path = self._root / "settings.json"
        self._credentials_path = self._root / "credentials.json"
        self._shots_dir = self._root / "screenshots"
        self._lock = threading.Lock()
        self._client: DeviceLinkClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

        self._commands: deque[dict[str, Any]] = deque(maxlen=_COMMAND_HISTORY)
        self._events: deque[dict[str, Any]] = deque(maxlen=_EVENT_HISTORY)
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._event_seq = 0

    # ------------------------------------------------------------------
    # 配置
    # ------------------------------------------------------------------

    def settings(self) -> dict[str, Any]:
        try:
            raw = json.loads(self._settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        return {
            "host": str(raw.get("host") or ""),
            "port": int(raw.get("port") or 0),
        }

    def _save_settings(self, host: str, port: int) -> None:
        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        self._settings_path.write_text(
            json.dumps({"host": host, "port": port}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _ensure_client(self) -> DeviceLinkClient:
        with self._lock:
            if self._client is not None:
                return self._client
            cfg = self.settings()
            client = DeviceLinkClient(
                credentials_path=self._credentials_path,
                host=cfg["host"],
                port=cfg["port"],
                on_event=self._handle_event,
            )
            self._client = client
            return client

    # ------------------------------------------------------------------
    # 操作
    # ------------------------------------------------------------------

    async def pair(self, host: str, port: int, code: str, client_name: str) -> dict[str, Any]:
        client = self._ensure_client()
        creds = await client.pair(code, client_name, host=host, port=port)
        client.set_endpoint(host, port)
        self._save_settings(host, port)
        self._push_event(
            "link.paired",
            {"clientId": creds.client_id, "deviceName": creds.device_name, "host": host, "port": port},
        )
        await client.start()
        return {"ok": True, "device_name": creds.device_name, "client_id": creds.client_id}

    async def connect(self, host: str | None = None, port: int | None = None) -> dict[str, Any]:
        client = self._ensure_client()
        if not client.has_credentials():
            raise DeviceLinkError(P.LOCAL_OFFLINE, "尚未配对，请先用设备上显示的配对码完成配对")
        cfg = self.settings()
        new_host = (host or cfg["host"]).strip()
        new_port = int(port or cfg["port"])
        if not new_host or new_port <= 0:
            raise DeviceLinkError(P.LOCAL_OFFLINE, "未配置设备地址（host/port）")
        client.set_endpoint(new_host, new_port)
        self._save_settings(new_host, new_port)
        if not client.online:
            await client.start()
        return {"ok": True, "host": new_host, "port": new_port}

    async def disconnect(self, reason: str = REASON_SERVER_DISCONNECT) -> dict[str, Any]:
        """本端主动断开。原因由调用方指定（下线设备 / token 轮换 / 超时踢线等）。"""
        client = self._ensure_client()
        await client.stop(reason)
        self._push_event("link.disconnected", {"reason": reason, "closedBy": CLOSED_BY_SERVER})
        return {"ok": True, "closed_by": CLOSED_BY_SERVER, "reason": reason}

    def is_online(self) -> bool:
        """同步查询链路是否在线；供工具可用性判定与中间件过滤使用，不发网络请求。"""
        try:
            return self._ensure_client().online
        except Exception:  # noqa: BLE001
            return False

    def is_paired(self) -> bool:
        """是否已持有设备凭据（配对完成）。未配对时不应向 agent 暴露任何设备工具。"""
        try:
            return Credentials.load(self._credentials_path) is not None
        except Exception:  # noqa: BLE001
            return False

    async def status(self) -> dict[str, Any]:
        client = self._ensure_client()
        cfg = self.settings()
        data = client.snapshot()
        if not data["host"]:
            data["host"] = cfg["host"]
            data["port"] = cfg["port"]
        data["credentials_path"] = str(self._credentials_path)
        data["recent_commands"] = list(self._commands)[-10:]
        return data

    async def run_command(
        self,
        name: str,
        params: dict[str, Any] | None = None,
        command_id: str | None = None,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        client = self._ensure_client()
        started = int(time.time() * 1000)
        record: dict[str, Any] = {
            "command_id": command_id or "",
            "name": name,
            "ok": False,
            "duration_ms": 0,
            "started_at": started,
            "error": None,
            "replayed": False,
            "artifact": None,
            "result": None,
        }
        try:
            outcome = await client.execute(name, params, command_id, timeout_ms)
        except DeviceLinkError as exc:
            record["command_id"] = command_id or record["command_id"]
            record["duration_ms"] = int(time.time() * 1000) - started
            record["error"] = exc.as_dict()
            self._remember(record)
            return {"ok": False, "command_id": record["command_id"], "error": exc.as_dict()}

        record["command_id"] = outcome["command_id"]
        record["ok"] = outcome["ok"]
        record["duration_ms"] = outcome["duration_ms"]
        record["replayed"] = outcome["replayed"]
        record["error"] = outcome["error"]
        result = outcome["result"] if isinstance(outcome["result"], dict) else None
        if name == "screen.screenshot" and outcome["ok"] and result:
            record["artifact"] = self._save_screenshot(record["command_id"], result)
            result = {k: v for k, v in result.items() if k != "base64"}
        record["result"] = result
        self._remember(record)
        return {
            "ok": record["ok"],
            "command_id": record["command_id"],
            "result": record["result"],
            "error": record["error"],
            "replayed": record["replayed"],
            "duration_ms": record["duration_ms"],
            "artifact": record["artifact"],
        }

    def recent_commands(self) -> list[dict[str, Any]]:
        return list(self._commands)

    def recent_events(self) -> list[dict[str, Any]]:
        return list(self._events)

    def catalog(self) -> list[dict[str, Any]]:
        return [
            {"name": c["name"], "summary": c.get("summary", ""), "params": c.get("params", {})}
            for c in P.SPEC["commands"]
        ]

    def screenshot_path(self, filename: str) -> Path | None:
        name = Path(filename).name
        if not name or not name.endswith(".png"):
            return None
        path = self._shots_dir / name
        return path if path.is_file() else None

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def _handle_event(self, kind: str, data: dict[str, Any], at: int) -> None:
        self._push_event(kind, data, at)

    def _push_event(self, kind: str, data: dict[str, Any], at: int | None = None) -> None:
        self._event_seq += 1
        event = {
            "seq": self._event_seq,
            "kind": kind,
            "at": int(at or time.time() * 1000),
            "data": data,
        }
        self._events.append(event)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # 订阅端太慢就丢最旧的一条，实时性优先于完整性
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except Exception:  # noqa: BLE001
                    pass

    def _remember(self, record: dict[str, Any]) -> None:
        self._commands.append(record)
        self._push_event(
            "command.finished" if record["ok"] else "command.failed",
            {
                "commandId": record["command_id"],
                "name": record["name"],
                "ok": record["ok"],
                "durationMs": record["duration_ms"],
                "replayed": record["replayed"],
                "error": record["error"],
                "artifact": record["artifact"],
            },
        )

    def _save_screenshot(self, command_id: str, result: dict[str, Any]) -> str | None:
        raw = result.get("base64")
        if not isinstance(raw, str) or not raw:
            return None
        try:
            # 设备用标准 base64（带填充），假设备用 url-safe 无填充；两种都接
            data = unb64(raw)
        except (ValueError, binascii.Error):
            return None
        self._shots_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{int(time.time() * 1000)}-{(command_id or 'shot')[:8]}.png"
        path = self._shots_dir / filename
        path.write_bytes(data)
        return str(path)

    async def close(self) -> None:
        client = self._client
        if client is not None:
            await client.stop()

    def credential_summary(self) -> dict[str, Any] | None:
        creds = Credentials.load(self._credentials_path)
        if creds is None:
            return None
        return {
            "client_id": creds.client_id,
            "device_name": creds.device_name,
            "device_fingerprint": creds.device_fingerprint,
        }


_manager: DeviceLinkManager | None = None
_manager_lock = threading.Lock()


def get_device_link_manager() -> DeviceLinkManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = DeviceLinkManager()
        return _manager
