"""把本机 adb 能力暴露为 Agent 工具。

工具清单（与用户需求一一对应）：

- 只读：``adb_devices``（列设备）、``adb_screenshot``（截屏落盘）
- 有副作用：``adb_shell`` / ``adb_install`` / ``adb_uninstall`` / ``adb_tap`` /
  ``adb_swipe`` / ``adb_input_text`` / ``adb_keyevent``（逐次审批）

所有结果都是 JSON，且一定带 ``exit_code`` / ``stdout`` / ``stderr`` /
``timed_out`` / ``duration_ms``；任何失败都有 ``code`` 与中文 ``message``，
不会出现「点了没反应」的静默失败。
"""

from __future__ import annotations

import json
import shlex
import struct
from pathlib import Path
from typing import Annotated, Any

from langchain_core.tools import StructuredTool
from langgraph.config import get_config
from pydantic import Field

from octop.infra.control.adb.runner import (
    DEFAULT_TIMEOUT_MS,
    AdbNotFound,
    AdbResult,
    AdbRunner,
    DeviceInfo,
    parse_devices,
)
from octop.infra.utils.paths import PathLayout
from octop.infra.utils.ulid import new_short_id

ADB_DEVICES = "adb_devices"
ADB_SHELL = "adb_shell"
ADB_INSTALL = "adb_install"
ADB_UNINSTALL = "adb_uninstall"
ADB_SCREENSHOT = "adb_screenshot"
ADB_TAP = "adb_tap"
ADB_SWIPE = "adb_swipe"
ADB_INPUT_TEXT = "adb_input_text"
ADB_KEYEVENT = "adb_keyevent"

ADB_READONLY_TOOLS: frozenset[str] = frozenset({ADB_DEVICES, ADB_SCREENSHOT})
ADB_SIDE_EFFECT_TOOLS: frozenset[str] = frozenset(
    {ADB_SHELL, ADB_INSTALL, ADB_UNINSTALL, ADB_TAP, ADB_SWIPE, ADB_INPUT_TEXT, ADB_KEYEVENT}
)
ADB_TOOL_NAMES: frozenset[str] = ADB_READONLY_TOOLS | ADB_SIDE_EFFECT_TOOLS

_DEVICES_TIMEOUT_MS = 10_000
_INSTALL_TIMEOUT_MS = 180_000
_SCREENSHOT_TIMEOUT_MS = 30_000


# ----------------------------------------------------------------------
# 结果整形
# ----------------------------------------------------------------------


def _dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _error(tool: str, code: str, message: str, *, hint: str | None = None) -> str:
    payload: dict[str, Any] = {
        "ok": False,
        "tool": tool,
        "code": code,
        "message": message,
    }
    if hint:
        payload["hint"] = hint
    return _dumps(payload)


def _failed(tool: str, result: AdbResult, *, hint: str | None = None) -> str:
    payload = result.payload(tool=tool)
    payload["ok"] = False
    payload["code"] = "ADB_TIMEOUT" if result.timed_out else "ADB_FAILED"
    if result.timed_out:
        message = f"adb 命令超时（{result.duration_ms}ms），已终止进程"
    else:
        detail = (result.stderr or result.stdout).strip().splitlines()
        tail = detail[-1] if detail else ""
        message = f"adb 退出码 {result.exit_code}" + (f"：{tail}" if tail else "")
    payload["message"] = message
    if hint:
        payload["hint"] = hint
    return _dumps(payload)


def _ok(tool: str, result: AdbResult, **extra: Any) -> str:
    payload = result.payload(tool=tool)
    payload.update(extra)
    return _dumps(payload)


def _parse_png_size(data: bytes) -> tuple[int | None, int | None]:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None, None
    width, height = struct.unpack(">II", data[16:24])
    return int(width), int(height)


# ----------------------------------------------------------------------
# 设备解析与目标选择
# ----------------------------------------------------------------------


def _device_hint(devices: list[DeviceInfo]) -> str:
    if not devices:
        return (
            "未发现设备：请确认手机已开启 USB 调试并授权（或模拟器已启动），"
            "然后在主机执行 adb devices 检查。"
        )
    waiting = [d for d in devices if not d.ready]
    if waiting:
        states = "、".join(f"{d.serial}({d.state})" for d in waiting)
        return f"设备尚未就绪：{states}。unauthorized 需要在手机上点允许调试；offline 可重新插拔或 adb kill-server。"
    return ""


async def _resolve_target(
    runner: AdbRunner, serial: str | None, tool: str
) -> tuple[DeviceInfo | None, str | None]:
    """选定目标设备；返回 (设备, 错误 JSON)。"""
    if not runner.binary:
        return None, _error(
            tool,
            "ADB_NOT_FOUND",
            "主机上找不到 adb，无法执行设备命令。",
            hint="安装 Android platform-tools 并加入 PATH，或设置 OCTOP_ADB_PATH 指向 adb。",
        )
    listed = await runner.run(["devices", "-l"], timeout_ms=_DEVICES_TIMEOUT_MS)
    if not listed.ok:
        return None, _failed(tool, listed)
    devices = parse_devices(listed.stdout)
    if serial:
        for device in devices:
            if device.serial != serial:
                continue
            if not device.ready:
                return None, _error(
                    tool,
                    "DEVICE_NOT_READY",
                    f"设备 {serial} 当前状态为 {device.state}，不能执行命令。",
                    hint=_device_hint(devices),
                )
            return device, None
        known = "、".join(d.serial for d in devices) or "无"
        return None, _error(
            tool,
            "DEVICE_NOT_FOUND",
            f"找不到设备 {serial}。当前已连接：{known}。",
            hint="先调用 adb_devices 确认 serial。",
        )
    ready = [d for d in devices if d.ready]
    if len(ready) == 1:
        return ready[0], None
    if not ready:
        return None, _error(
            tool,
            "NO_DEVICE",
            "没有可用的设备。",
            hint=_device_hint(devices),
        )
    serials = "、".join(d.serial for d in ready)
    return None, _error(
        tool,
        "DEVICE_REQUIRED",
        f"当前有多台设备（{serials}），必须用 serial 指定目标设备。",
        hint="先调用 adb_devices 查看列表，再把 serial 传给本次命令。",
    )


def _check_access(user_repo: Any) -> str | None:
    """与设备链路一致：需要 mobile 权限，且必须有用户上下文。"""
    from octop.infra.users.permissions import user_has_permission  # noqa: PLC0415

    ctx = get_config().get("configurable") or {}
    user_raw = ctx.get("user")
    if user_raw is None:
        return "当前对话缺少用户身份，无法校验 mobile 权限"
    if ctx.get("user_is_admin"):
        return None
    if user_repo is None:
        return "缺少用户仓储，无法校验 mobile 权限"
    try:
        row = user_repo.get(int(user_raw))
    except (TypeError, ValueError):
        return "当前对话的用户身份无效"
    if row is None or not user_has_permission(row, "mobile"):
        return "需要 mobile 权限才能通过 adb 操作手机"
    return None


# ----------------------------------------------------------------------
# 审批文案
# ----------------------------------------------------------------------


def _args_of(tool_call: Any) -> dict[str, Any]:
    raw = tool_call.get("args") if isinstance(tool_call, dict) else None
    return raw if isinstance(raw, dict) else {}


def _preview(text: str, limit: int = 60) -> str:
    clean = " ".join(text.split())
    return clean if len(clean) <= limit else clean[:limit] + "…"


def describe_adb_action(tool_call: Any, state: Any = None, runtime: Any = None) -> str:
    name = str(tool_call.get("name") or "") if isinstance(tool_call, dict) else ""
    args = _args_of(tool_call)
    target = args.get("serial") or "当前唯一设备"
    if name == ADB_SHELL:
        return f"即将在设备 {target} 上执行 shell 命令「{_preview(str(args.get('command') or ''))}」，可能修改系统或应用状态。"
    if name == ADB_INSTALL:
        return f"即将向设备 {target} 安装 APK：{args.get('path')}（会覆盖同包名的已安装版本）。"
    if name == ADB_UNINSTALL:
        keep = "，保留应用数据" if args.get("keep_data") else ""
        return f"即将从设备 {target} 卸载应用 {args.get('package')}（不可撤销{keep}）。"
    if name == ADB_TAP:
        return f"即将在设备 {target} 上点击坐标 ({args.get('x')}, {args.get('y')})。"
    if name == ADB_SWIPE:
        return (
            f"即将在设备 {target} 上从 ({args.get('x1')}, {args.get('y1')}) 滑到 "
            f"({args.get('x2')}, {args.get('y2')})。"
        )
    if name == ADB_INPUT_TEXT:
        return f"即将向设备 {target} 的焦点输入框输入「{_preview(str(args.get('text') or ''))}」。"
    if name == ADB_KEYEVENT:
        return f"即将向设备 {target} 发送按键 {args.get('key')}。"
    return f"即将在手机上执行有副作用的 adb 动作：{name}。"


def adb_interrupt_on() -> dict[str, Any]:
    entry = {"allowed_decisions": ["approve", "reject"], "description": describe_adb_action}
    return {name: dict(entry) for name in sorted(ADB_SIDE_EFFECT_TOOLS)}


# ----------------------------------------------------------------------
# 参数整形
# ----------------------------------------------------------------------


def _encode_input_text(text: str) -> str:
    """``input text`` 不认识空格，按官方约定用 %s 代替，再按远端 shell 规则转义。"""
    if "\n" in text or "\r" in text:
        raise ValueError("input text 不支持换行；请拆成多次调用")
    return shlex.quote(text.replace(" ", "%s"))


def _screenshot_dir() -> Path:
    path = PathLayout.from_env().root / "adb" / "screenshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ----------------------------------------------------------------------
# 工具构建
# ----------------------------------------------------------------------


def build_adb_tools(
    runner: AdbRunner | None = None, *, user_repo: Any = None
) -> list[StructuredTool]:
    """构建 adb 工具集合。调用方负责在主机没有 adb 时不要挂载。"""
    adb = runner or AdbRunner()

    async def adb_devices() -> str:
        denied = _check_access(user_repo)
        if denied:
            return _error(ADB_DEVICES, "DENIED", denied)
        if not adb.binary:
            return _error(
                ADB_DEVICES,
                "ADB_NOT_FOUND",
                "主机上找不到 adb。",
                hint="安装 Android platform-tools 并加入 PATH，或设置 OCTOP_ADB_PATH。",
            )
        result = await adb.run(["devices", "-l"], timeout_ms=_DEVICES_TIMEOUT_MS)
        if not result.ok:
            return _failed(ADB_DEVICES, result)
        devices = [d.payload() for d in parse_devices(result.stdout)]
        return _ok(
            ADB_DEVICES,
            result,
            adb=adb.binary,
            count=len(devices),
            devices=devices,
            hint=_device_hint(parse_devices(result.stdout)) or None,
        )

    async def adb_shell(
        command: Annotated[str, Field(description="在设备上执行的 shell 命令，例如 `dumpsys battery`")],
        serial: Annotated[str | None, Field(description="目标设备 serial；只有一台时可省略")] = None,
        timeout_ms: Annotated[
            int, Field(description="超时毫秒，默认 20000，最大 300000", ge=1000, le=300_000)
        ] = DEFAULT_TIMEOUT_MS,
    ) -> str:
        denied = _check_access(user_repo)
        if denied:
            return _error(ADB_SHELL, "DENIED", denied)
        if not command.strip():
            return _error(ADB_SHELL, "INVALID_ARGS", "command 不能为空")
        device, error = await _resolve_target(adb, serial, ADB_SHELL)
        if error:
            return error
        assert device is not None
        result = await adb.run(
            ["shell", command], serial=device.serial, timeout_ms=timeout_ms
        )
        if not result.ok:
            return _failed(ADB_SHELL, result)
        return _ok(ADB_SHELL, result)

    async def adb_install(
        path: Annotated[str, Field(description="主机上 APK 的绝对路径")],
        serial: Annotated[str | None, Field(description="目标设备 serial；只有一台时可省略")] = None,
        reinstall: Annotated[bool, Field(description="覆盖已安装的同包名应用（-r）")] = True,
        allow_downgrade: Annotated[bool, Field(description="允许版本降级（-d）")] = False,
    ) -> str:
        denied = _check_access(user_repo)
        if denied:
            return _error(ADB_INSTALL, "DENIED", denied)
        apk = Path(path).expanduser()
        if not apk.is_file():
            return _error(
                ADB_INSTALL,
                "INVALID_ARGS",
                f"APK 不存在：{path}",
                hint="传主机上的绝对路径；先确认构建产物位置。",
            )
        device, error = await _resolve_target(adb, serial, ADB_INSTALL)
        if error:
            return error
        assert device is not None
        args = ["install"]
        if reinstall:
            args.append("-r")
        if allow_downgrade:
            args.append("-d")
        args.append(str(apk))
        result = await adb.run(args, serial=device.serial, timeout_ms=_INSTALL_TIMEOUT_MS)
        if not result.ok:
            return _failed(ADB_INSTALL, result)
        summary = (result.stdout or result.stderr).strip().splitlines()
        return _ok(
            ADB_INSTALL,
            result,
            apk=str(apk),
            summary=summary[-1] if summary else "Success",
        )

    async def adb_uninstall(
        package: Annotated[str, Field(description="要卸载的应用包名，例如 `com.happyclaw.device`")],
        serial: Annotated[str | None, Field(description="目标设备 serial；只有一台时可省略")] = None,
        keep_data: Annotated[bool, Field(description="保留应用数据与缓存（-k）")] = False,
    ) -> str:
        denied = _check_access(user_repo)
        if denied:
            return _error(ADB_UNINSTALL, "DENIED", denied)
        pkg = package.strip()
        if not pkg or any(ch.isspace() for ch in pkg) or pkg.startswith("-"):
            return _error(ADB_UNINSTALL, "INVALID_ARGS", f"非法包名：{package!r}")
        device, error = await _resolve_target(adb, serial, ADB_UNINSTALL)
        if error:
            return error
        assert device is not None
        args = ["uninstall"]
        if keep_data:
            args.append("-k")
        args.append(pkg)
        result = await adb.run(args, serial=device.serial, timeout_ms=_INSTALL_TIMEOUT_MS)
        # 包不存在时 adb 也会返回 0，stdout 为 Failure [DELETE_FAILED_INTERNAL_ERROR]，
        # 只看退出码会把「没卸载」当成成功。
        summary = (result.stdout or result.stderr).strip().splitlines()
        last = summary[-1] if summary else ""
        if not result.ok or "Failure" in last:
            payload = result.payload(tool=ADB_UNINSTALL)
            payload.update(
                ok=False,
                code="ADB_FAILED",
                message=f"卸载 {pkg} 失败：" + (last or f"退出码 {result.exit_code}"),
                package=pkg,
            )
            return _dumps(payload)
        return _ok(ADB_UNINSTALL, result, package=pkg, summary=last or "Success")

    async def adb_screenshot(
        serial: Annotated[str | None, Field(description="目标设备 serial；只有一台时可省略")] = None,
    ) -> str:
        denied = _check_access(user_repo)
        if denied:
            return _error(ADB_SCREENSHOT, "DENIED", denied)
        device, error = await _resolve_target(adb, serial, ADB_SCREENSHOT)
        if error:
            return error
        assert device is not None
        data, result = await adb.run_bytes(
            ["exec-out", "screencap", "-p"],
            serial=device.serial,
            timeout_ms=_SCREENSHOT_TIMEOUT_MS,
        )
        if not result.ok or not data.startswith(b"\x89PNG"):
            hint = "若设备锁屏，先解锁；部分 ROM 需要先 adb shell input keyevent 224 唤醒。"
            return _failed(ADB_SCREENSHOT, result, hint=hint)
        target = _screenshot_dir() / f"{new_short_id(16)}.png"
        target.write_bytes(data)
        width, height = _parse_png_size(data)
        return _ok(
            ADB_SCREENSHOT,
            result,
            path=str(target),
            width=width,
            height=height,
            bytes=len(data),
        )

    async def adb_tap(
        x: Annotated[int, Field(description="横坐标（设备像素）", ge=0)],
        y: Annotated[int, Field(description="纵坐标（设备像素）", ge=0)],
        serial: Annotated[str | None, Field(description="目标设备 serial；只有一台时可省略")] = None,
    ) -> str:
        denied = _check_access(user_repo)
        if denied:
            return _error(ADB_TAP, "DENIED", denied)
        device, error = await _resolve_target(adb, serial, ADB_TAP)
        if error:
            return error
        assert device is not None
        result = await adb.run(
            ["shell", "input", "tap", str(x), str(y)], serial=device.serial
        )
        if not result.ok:
            return _failed(ADB_TAP, result)
        return _ok(ADB_TAP, result, x=x, y=y)

    async def adb_swipe(
        x1: Annotated[int, Field(description="起点横坐标", ge=0)],
        y1: Annotated[int, Field(description="起点纵坐标", ge=0)],
        x2: Annotated[int, Field(description="终点横坐标", ge=0)],
        y2: Annotated[int, Field(description="终点纵坐标", ge=0)],
        duration_ms: Annotated[int, Field(description="滑动耗时毫秒", ge=50, le=10_000)] = 300,
        serial: Annotated[str | None, Field(description="目标设备 serial；只有一台时可省略")] = None,
    ) -> str:
        denied = _check_access(user_repo)
        if denied:
            return _error(ADB_SWIPE, "DENIED", denied)
        device, error = await _resolve_target(adb, serial, ADB_SWIPE)
        if error:
            return error
        assert device is not None
        result = await adb.run(
            ["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)],
            serial=device.serial,
        )
        if not result.ok:
            return _failed(ADB_SWIPE, result)
        return _ok(ADB_SWIPE, result)

    async def adb_input_text(
        text: Annotated[str, Field(description="要输入的文本（不支持换行）")],
        serial: Annotated[str | None, Field(description="目标设备 serial；只有一台时可省略")] = None,
    ) -> str:
        denied = _check_access(user_repo)
        if denied:
            return _error(ADB_INPUT_TEXT, "DENIED", denied)
        if not text:
            return _error(ADB_INPUT_TEXT, "INVALID_ARGS", "text 不能为空")
        try:
            encoded = _encode_input_text(text)
        except ValueError as exc:
            return _error(ADB_INPUT_TEXT, "INVALID_ARGS", str(exc))
        device, error = await _resolve_target(adb, serial, ADB_INPUT_TEXT)
        if error:
            return error
        assert device is not None
        result = await adb.run(
            ["shell", "input", "text", encoded], serial=device.serial
        )
        if not result.ok:
            return _failed(ADB_INPUT_TEXT, result)
        return _ok(ADB_INPUT_TEXT, result, text=text)

    async def adb_keyevent(
        key: Annotated[str, Field(description="按键名或数字，如 KEYCODE_HOME / BACK / 4")],
        serial: Annotated[str | None, Field(description="目标设备 serial；只有一台时可省略")] = None,
    ) -> str:
        denied = _check_access(user_repo)
        if denied:
            return _error(ADB_KEYEVENT, "DENIED", denied)
        if not (key.isdigit() or key.replace("_", "").isalnum()):
            return _error(ADB_KEYEVENT, "INVALID_ARGS", f"非法按键：{key}")
        device, error = await _resolve_target(adb, serial, ADB_KEYEVENT)
        if error:
            return error
        assert device is not None
        result = await adb.run(
            ["shell", "input", "keyevent", key], serial=device.serial
        )
        if not result.ok:
            return _failed(ADB_KEYEVENT, result)
        return _ok(ADB_KEYEVENT, result, key=key)

    return [
        StructuredTool.from_function(
            coroutine=adb_devices,
            name=ADB_DEVICES,
            description=(
                "列出主机上通过 adb 连接的设备（serial/状态/model），multidevice 时后续命令必须传 serial。只读。"
            ),
        ),
        StructuredTool.from_function(
            coroutine=adb_shell,
            name=ADB_SHELL,
            description=(
                "在目标设备上执行 adb shell 命令，返回退出码、stdout、stderr 与耗时；超时会明确标记。有副作用，需审批。"
            ),
        ),
        StructuredTool.from_function(
            coroutine=adb_install,
            name=ADB_INSTALL,
            description="把主机上的 APK 安装到目标设备（默认 -r 覆盖安装），返回 adb 输出与退出码。有副作用，需审批。",
        ),
        StructuredTool.from_function(
            coroutine=adb_uninstall,
            name=ADB_UNINSTALL,
            description="卸载目标设备上的应用（按包名，默认连同数据一起删除）；失败时明确返回原因。有副作用，需审批。",
        ),
        StructuredTool.from_function(
            coroutine=adb_screenshot,
            name=ADB_SCREENSHOT,
            description="通过 adb 截取目标设备屏幕，PNG 落盘并返回绝对路径、宽高与字节数。只读。",
        ),
        StructuredTool.from_function(
            coroutine=adb_tap,
            name=ADB_TAP,
            description="在目标设备上点击指定坐标（设备像素）。有副作用，需审批。",
        ),
        StructuredTool.from_function(
            coroutine=adb_swipe,
            name=ADB_SWIPE,
            description="在目标设备上滑动（起点/终点/耗时）。有副作用，需审批。",
        ),
        StructuredTool.from_function(
            coroutine=adb_input_text,
            name=ADB_INPUT_TEXT,
            description="向目标设备当前焦点输入框输入文本（空格自动转义，不支持换行）。有副作用，需审批。",
        ),
        StructuredTool.from_function(
            coroutine=adb_keyevent,
            name=ADB_KEYEVENT,
            description="向目标设备发送按键事件（KEYCODE_HOME/BACK/4 等）。有副作用，需审批。",
        ),
    ]


__all__ = [
    "ADB_DEVICES",
    "ADB_INPUT_TEXT",
    "ADB_INSTALL",
    "ADB_KEYEVENT",
    "ADB_READONLY_TOOLS",
    "ADB_SCREENSHOT",
    "ADB_SHELL",
    "ADB_SIDE_EFFECT_TOOLS",
    "ADB_SWIPE",
    "ADB_TAP",
    "ADB_TOOL_NAMES",
    "AdbNotFound",
    "adb_interrupt_on",
    "build_adb_tools",
    "describe_adb_action",
]
