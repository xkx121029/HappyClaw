"""adb Agent 工具单测。

覆盖用户要求的关键点：
- 工具集合与只读/副作用分组；
- 多设备必须指定 serial，未授权/离线设备给出明确原因；
- 退出码、stderr、超时都透传到结果里，不静默失败；
- 截屏落盘并解析宽高；input text 空格转义。
"""

from __future__ import annotations

import asyncio
import json
import struct
from pathlib import Path

import pytest

from octop.infra.control.adb import runner as R
from octop.infra.control.adb import tools as T

PNG_HEAD = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0d" + b"IHDR"


class _FakeExec:
    """按 argv 片段返回预设结果，并记录调用。"""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.devices = "List of devices attached\nemulator-5554          device product:sdk model:sdk\n"
        self.responses: dict[str, tuple[int, bytes, bytes, bool]] = {}

    async def __call__(
        self, argv: list[str], timeout_s: float
    ) -> tuple[int | None, bytes, bytes, bool, int]:
        self.calls.append(argv)
        joined = " ".join(argv)
        for key, value in self.responses.items():
            if key in joined:
                code, out, err, timed_out = value
                return code, out, err, timed_out, 12
        if "devices" in argv:
            return 0, self.devices.encode(), b"", False, 8
        return 0, b"", b"", False, 5


@pytest.fixture()
def fake(monkeypatch: pytest.MonkeyPatch) -> _FakeExec:
    fake = _FakeExec()
    monkeypatch.setattr(R, "_exec", fake)
    monkeypatch.setattr(
        T, "get_config", lambda: {"configurable": {"user": "1", "user_is_admin": True}}
    )
    monkeypatch.setattr(T, "_screenshot_dir", lambda: Path(_shot_dir()))
    return fake


_SHOT_DIR = {"path": Path(".")}


def _shot_dir() -> Path:
    return _SHOT_DIR["path"]


def _tools() -> dict[str, object]:
    return {tool.name: tool for tool in T.build_adb_tools(R.AdbRunner(binary="adb"))}


def _run(coro):  # noqa: ANN001
    return asyncio.run(coro)


def _png(width: int = 1080, height: int = 2400) -> bytes:
    return PNG_HEAD + struct.pack(">II", width, height) + b"\x00" * 8


def test_tool_names_split() -> None:
    assert T.ADB_READONLY_TOOLS == {"adb_devices", "adb_screenshot"}
    assert T.ADB_SIDE_EFFECT_TOOLS == {
        "adb_shell",
        "adb_install",
        "adb_uninstall",
        "adb_tap",
        "adb_swipe",
        "adb_input_text",
        "adb_keyevent",
    }
    assert set(_tools()) == T.ADB_TOOL_NAMES


def test_parse_devices_reads_props() -> None:
    devices = R.parse_devices(
        "List of devices attached\n"
        "emulator-5554          device product:sdk model:Pixel transport_id:1\n"
        "R58M12345              unauthorized\n"
    )
    assert [d.serial for d in devices] == ["emulator-5554", "R58M12345"]
    assert devices[0].ready is True
    assert devices[0].model == "Pixel"
    assert devices[1].ready is False


def test_devices_tool_reports_list(fake: _FakeExec) -> None:
    payload = json.loads(_run(_tools()["adb_devices"].ainvoke({})))
    assert payload["ok"] is True
    assert payload["count"] == 1
    assert payload["devices"][0]["serial"] == "emulator-5554"
    assert payload["adb"] == "adb"


def test_multiple_devices_require_serial(monkeypatch: pytest.MonkeyPatch, fake: _FakeExec) -> None:
    fake.devices = (
        "List of devices attached\n"
        "emulator-5554 device product:sdk\n"
        "R58M12345 device product:sea\n"
    )
    payload = json.loads(_run(_tools()["adb_shell"].ainvoke({"command": "echo hi"})))
    assert payload["ok"] is False
    assert payload["code"] == "DEVICE_REQUIRED"
    assert "emulator-5554" in payload["message"]


def test_unauthorized_device_explains(fake: _FakeExec) -> None:
    fake.devices = "List of devices attached\nR58M12345 unauthorized\n"
    payload = json.loads(
        _run(_tools()["adb_shell"].ainvoke({"command": "echo hi", "serial": "R58M12345"}))
    )
    assert payload["ok"] is False
    assert payload["code"] == "DEVICE_NOT_READY"
    assert "unauthorized" in payload["message"]


def test_shell_failure_keeps_exit_code_and_stderr(fake: _FakeExec) -> None:
    fake.responses["shell"] = (1, b"", b"error: closed\n", False)
    payload = json.loads(_run(_tools()["adb_shell"].ainvoke({"command": "bad-cmd"})))
    assert payload["ok"] is False
    assert payload["code"] == "ADB_FAILED"
    assert payload["exit_code"] == 1
    assert payload["stderr"].strip() == "error: closed"
    assert "退出码 1" in payload["message"]


def test_shell_timeout_is_marked(fake: _FakeExec) -> None:
    fake.responses["shell"] = (137, b"", b"", True)
    payload = json.loads(
        _run(_tools()["adb_shell"].ainvoke({"command": "sleep 999", "timeout_ms": 1000}))
    )
    assert payload["ok"] is False
    assert payload["timed_out"] is True
    assert payload["code"] == "ADB_TIMEOUT"


def test_shell_targets_serial(fake: _FakeExec) -> None:
    _run(_tools()["adb_shell"].ainvoke({"command": "echo hi", "serial": "emulator-5554"}))
    assert any("-s" in call and "emulator-5554" in call for call in fake.calls)


def test_input_text_escapes_spaces(fake: _FakeExec) -> None:
    _run(_tools()["adb_input_text"].ainvoke({"text": "hello world"}))
    shell_calls = [call for call in fake.calls if "input" in call]
    assert shell_calls and "%s" in shell_calls[-1][-1]
    assert "hello%sworld" in shell_calls[-1][-1]


def test_screenshot_saves_png(tmp_path: Path, fake: _FakeExec) -> None:
    _SHOT_DIR["path"] = tmp_path
    fake.responses["exec-out"] = (0, _png(1080, 2400), b"", False)
    payload = json.loads(_run(_tools()["adb_screenshot"].ainvoke({})))
    assert payload["ok"] is True
    assert payload["width"] == 1080 and payload["height"] == 2400
    saved = Path(payload["path"])
    assert saved.is_file() and saved.stat().st_size == len(_png(1080, 2400))


def test_install_rejects_missing_apk(fake: _FakeExec) -> None:
    payload = json.loads(_run(_tools()["adb_install"].ainvoke({"path": "E:/nope/app.apk"})))
    assert payload["ok"] is False
    assert payload["code"] == "INVALID_ARGS"


def test_uninstall_success_and_failure(fake: _FakeExec) -> None:
    fake.responses["uninstall"] = (0, b"Success\n", b"", False)
    payload = json.loads(
        _run(_tools()["adb_uninstall"].ainvoke({"package": "com.demo.app"}))
    )
    assert payload["ok"] is True
    assert payload["package"] == "com.demo.app"

    # 包不存在时 adb 退出码仍是 0，必须按 stdout 判定失败
    fake.responses["uninstall"] = (0, b"Failure [DELETE_FAILED_INTERNAL_ERROR]\n", b"", False)
    payload = json.loads(
        _run(_tools()["adb_uninstall"].ainvoke({"package": "com.demo.missing"}))
    )
    assert payload["ok"] is False
    assert payload["code"] == "ADB_FAILED"
    assert "DELETE_FAILED_INTERNAL_ERROR" in payload["message"]


def test_uninstall_rejects_bad_package(fake: _FakeExec) -> None:
    payload = json.loads(_run(_tools()["adb_uninstall"].ainvoke({"package": "--all"})))
    assert payload["ok"] is False
    assert payload["code"] == "INVALID_ARGS"


def test_interrupt_only_covers_side_effects() -> None:
    assert set(T.adb_interrupt_on()) == T.ADB_SIDE_EFFECT_TOOLS
    description = T.describe_adb_action(
        {"name": "adb_shell", "args": {"command": "pm clear com.demo"}}
    )
    assert "pm clear com.demo" in description
