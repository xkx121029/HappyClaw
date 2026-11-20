"""adb 命令执行器：解析目标设备、限时执行、原样保留退出码与 stderr。

设计原则（对应「不要静默失败」）：
- 每条命令都返回退出码、stdout、stderr、耗时与是否超时；
- 输出超长时截断但明确标注总长度；
- 失败信息分两类：``ADB_NOT_FOUND``（主机没有 adb）与 ``ADB_FAILED``（adb 执行失败）。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_OUTPUT_CHARS = 20_000
DEFAULT_TIMEOUT_MS = 20_000
MAX_TIMEOUT_MS = 300_000


class AdbNotFound(RuntimeError):
    """主机上找不到 adb 可执行文件。"""


@dataclass(slots=True)
class DeviceInfo:
    serial: str
    state: str
    props: dict[str, str] = field(default_factory=dict)

    @property
    def model(self) -> str | None:
        return self.props.get("model")

    @property
    def device(self) -> str | None:
        return self.props.get("device")

    @property
    def product(self) -> str | None:
        return self.props.get("product")

    @property
    def transport_id(self) -> str | None:
        return self.props.get("transport_id")

    @property
    def ready(self) -> bool:
        return self.state == "device"

    def payload(self) -> dict[str, Any]:
        return {
            "serial": self.serial,
            "state": self.state,
            "ready": self.ready,
            "model": self.model,
            "device": self.device,
            "product": self.product,
            "transport_id": self.transport_id,
        }


@dataclass(slots=True)
class AdbResult:
    ok: bool
    argv: list[str]
    serial: str | None
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    truncated: bool = False

    @property
    def command(self) -> str:
        return " ".join(_quote(arg) for arg in self.argv)

    def payload(self, *, tool: str | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {
            "ok": self.ok,
            "command": self.command,
            "serial": self.serial,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
            "duration_ms": self.duration_ms,
            "truncated": self.truncated,
        }
        if tool:
            out["tool"] = tool
        return out


def _quote(arg: str) -> str:
    return f"'{arg}'" if (" " in arg or "\t" in arg) else arg


def _truncate(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text, False
    keep = MAX_OUTPUT_CHARS // 2
    head = text[:keep]
    tail = text[-keep:]
    marker = f"\n…（输出已截断，共 {len(text)} 字符）…\n"
    return head + marker + tail, True


def adb_binary() -> str | None:
    """按 环境变量 → PATH → 常见 SDK 安装目录 的顺序定位 adb。"""
    explicit = os.environ.get("OCTOP_ADB_PATH", "").strip()
    if explicit and Path(explicit).is_file():
        return explicit
    found = shutil.which("adb")
    if found:
        return found
    exe = "adb.exe" if os.name == "nt" else "adb"
    candidates: list[Path] = []
    for env in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        base = os.environ.get(env, "").strip()
        if base:
            candidates.append(Path(base) / "platform-tools" / exe)
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        candidates.append(Path(local) / "Android" / "Sdk" / "platform-tools" / exe)
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def adb_available() -> bool:
    return adb_binary() is not None


def parse_devices(output: str) -> list[DeviceInfo]:
    """解析 ``adb devices -l`` 的输出。"""
    devices: list[DeviceInfo] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line or line.startswith("List of devices") or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        props: dict[str, str] = {}
        for token in parts[2:]:
            if ":" in token:
                key, value = token.split(":", 1)
                props[key.strip()] = value.strip()
        devices.append(DeviceInfo(serial=parts[0], state=parts[1], props=props))
    return devices


async def _exec(argv: list[str], timeout_s: float) -> tuple[int | None, bytes, bytes, bool, int]:
    """执行命令，返回 (exit_code, stdout, stderr, timed_out, duration_ms)。"""
    started = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        timed_out = False
    except TimeoutError:
        proc.kill()
        out, err = await proc.communicate()
        timed_out = True
    duration_ms = int((time.monotonic() - started) * 1000)
    return proc.returncode, out, err, timed_out, duration_ms


class AdbRunner:
    """带目标设备与超时控制的 adb 执行器。"""

    def __init__(self, binary: str | None = None) -> None:
        self._binary = binary if binary is not None else adb_binary()

    @property
    def binary(self) -> str | None:
        return self._binary

    def require_binary(self) -> str:
        if not self._binary:
            raise AdbNotFound(
                "主机上找不到 adb。请安装 Android platform-tools 并加入 PATH，"
                "或设置环境变量 OCTOP_ADB_PATH 指向 adb 可执行文件。"
            )
        return self._binary

    async def run(
        self,
        args: list[str],
        *,
        serial: str | None = None,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> AdbResult:
        argv = self._argv(args, serial=serial)
        timeout_s = _timeout_seconds(timeout_ms)
        try:
            code, out, err, timed_out, duration_ms = await _exec(argv, timeout_s)
        except FileNotFoundError as exc:  # adb 在解析后被卸载/移动
            raise AdbNotFound(f"adb 可执行文件不可用：{exc}") from exc
        stdout, t1 = _truncate(_decode(out))
        stderr, t2 = _truncate(_decode(err))
        return AdbResult(
            ok=(not timed_out) and code == 0,
            argv=argv,
            serial=serial,
            exit_code=code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            timed_out=timed_out,
            truncated=t1 or t2,
        )

    async def run_bytes(
        self,
        args: list[str],
        *,
        serial: str | None = None,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> tuple[bytes, AdbResult]:
        """执行并保留原始字节（截图等二进制输出）。"""
        argv = self._argv(args, serial=serial)
        timeout_s = _timeout_seconds(timeout_ms)
        try:
            code, out, err, timed_out, duration_ms = await _exec(argv, timeout_s)
        except FileNotFoundError as exc:
            raise AdbNotFound(f"adb 可执行文件不可用：{exc}") from exc
        result = AdbResult(
            ok=(not timed_out) and code == 0,
            argv=argv,
            serial=serial,
            exit_code=code,
            stdout="" if out.startswith(b"\x89PNG") else _decode(out)[:MAX_OUTPUT_CHARS],
            stderr=_decode(err)[:MAX_OUTPUT_CHARS],
            duration_ms=duration_ms,
            timed_out=timed_out,
        )
        return out, result

    def _argv(self, args: list[str], *, serial: str | None) -> list[str]:
        binary = self.require_binary()
        argv = [binary]
        if serial:
            argv.extend(["-s", serial])
        argv.extend(args)
        return argv


def _timeout_seconds(timeout_ms: int) -> float:
    bounded = max(1_000, min(int(timeout_ms or DEFAULT_TIMEOUT_MS), MAX_TIMEOUT_MS))
    return bounded / 1000.0


def _decode(data: bytes) -> str:
    # adb 在 Windows 上可能输出 GBK（如部分中文错误信息），逐级回退避免乱码
    for encoding in ("utf-8", "gbk"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")
