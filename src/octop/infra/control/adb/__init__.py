"""本地 adb 通道：让 Agent 直接通过 adb 操作连接在主机上的手机。

与 ``device_link``（经手机 App 的 WebSocket 链路）并列，两者互不依赖：
本通道直接调用主机上的 ``adb`` 可执行文件，适合模拟器 / USB 调试场景。
"""

from __future__ import annotations

from .runner import (
    AdbNotFound,
    AdbResult,
    AdbRunner,
    DeviceInfo,
    adb_available,
    adb_binary,
    parse_devices,
)
from .tools import (
    ADB_READONLY_TOOLS,
    ADB_SIDE_EFFECT_TOOLS,
    ADB_TOOL_NAMES,
    adb_interrupt_on,
    build_adb_tools,
    describe_adb_action,
)

__all__ = [
    "ADB_READONLY_TOOLS",
    "ADB_SIDE_EFFECT_TOOLS",
    "ADB_TOOL_NAMES",
    "AdbNotFound",
    "AdbResult",
    "AdbRunner",
    "DeviceInfo",
    "adb_available",
    "adb_binary",
    "adb_interrupt_on",
    "build_adb_tools",
    "describe_adb_action",
    "parse_devices",
]
