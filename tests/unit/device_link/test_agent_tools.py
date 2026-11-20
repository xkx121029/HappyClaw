"""设备链路 Agent 工具单测（不依赖真机与网络）。

覆盖：
- 6 个工具与协议命令一一对应；
- 截图落到具体路径并解析宽高；元素树/应用列表给摘要并截断；
- 失败透传错误码与耗时；离线拒绝执行；
- 副作用工具的一次性审批配置与中文描述（坐标/输入框）；
- 离线中间件把工具从模型可见列表中剔除。
"""

from __future__ import annotations

import asyncio
import json
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from octop.infra.control.device_link import agent_tools as A
from octop.infra.agents.middleware import device_link_gate as G


class _FakeManager:
    def __init__(self, *, online: bool = True) -> None:
        self.online = online
        self.calls: list[tuple[str, dict, str | None]] = []
        self.reply: dict = {}
        self.replies: dict[str, dict] = {}

    def is_online(self) -> bool:
        return self.online

    async def run_command(self, name, params=None, command_id=None, timeout_ms=None):
        self.calls.append((name, params or {}, command_id))
        return self.replies.get(name, self.reply)


def _config() -> SimpleNamespace:
    # Legacy ADB capability is off; device-link access must not depend on it.
    return SimpleNamespace(capabilities=SimpleNamespace(mobile=SimpleNamespace(enabled=False)))


def _patch(monkeypatch, manager: _FakeManager) -> None:
    monkeypatch.setattr(
        "octop.infra.control.device_link.manager.get_device_link_manager", lambda: manager
    )
    monkeypatch.setattr(
        A, "get_config", lambda: {"configurable": {"user": "1", "user_is_admin": True}}
    )


def _tools() -> dict[str, object]:
    return {tool.name: tool for tool in A.build_device_link_tools(_config(), user_repo=None)}


def _png(path: Path, width: int = 1080, height: int = 2400) -> None:
    head = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0d" + b"IHDR" + struct.pack(">II", width, height)
    path.write_bytes(head + b"\x00" * 8)


def _ok(name: str, result: dict, *, artifact: str | None = None, duration: int = 120) -> dict:
    return {
        "ok": True,
        "command_id": "cmd-1",
        "result": result,
        "error": None,
        "replayed": False,
        "duration_ms": duration,
        "artifact": artifact,
    }


def _run(coro):
    return asyncio.run(coro)


def test_tool_set_matches_side_effect_split() -> None:
    assert A.DEVICE_LINK_READONLY_TOOLS == {
        "phone_screenshot",
        "phone_ui_tree",
        "phone_list_apps",
        "phone_notifications",
        "phone_time_context",
    }
    assert A.DEVICE_LINK_SIDE_EFFECT_TOOLS == {"phone_tap", "phone_swipe", "phone_type_text"}
    assert set(_tools()) == A.DEVICE_LINK_TOOL_NAMES


def test_screenshot_returns_path_and_dimensions(monkeypatch, tmp_path: Path) -> None:
    shot = tmp_path / "shot.png"
    _png(shot)
    manager = _FakeManager()
    manager.reply = _ok(
        "screen.screenshot",
        {"format": "png", "sizeBytes": 32},
        artifact=str(shot),
        duration=187,
    )
    _patch(monkeypatch, manager)

    payload = json.loads(_run(_tools()["phone_screenshot"].ainvoke({})))

    assert payload["ok"] is True
    assert payload["artifact"] == str(shot)
    assert payload["width"] == 1080 and payload["height"] == 2400
    assert payload["duration_ms"] == 187
    assert manager.calls[0][0] == "screen.screenshot"
    assert manager.calls[0][2]  # 每次调用都带新的 command_id


def test_ui_tree_returns_capped_summary(monkeypatch) -> None:
    elements = [
        {"text": f"item-{i}", "viewId": f"id/{i}", "bounds": "[0,0][10,10]", "clickable": i % 2}
        for i in range(60)
    ]
    manager = _FakeManager()
    manager.reply = _ok(
        "screen.tree",
        {"packageName": "com.android.settings", "screenWidth": 1080, "screenHeight": 2400,
         "elements": elements},
        duration=142,
    )
    _patch(monkeypatch, manager)

    payload = json.loads(_run(_tools()["phone_ui_tree"].ainvoke({})))

    summary = payload["summary"]
    assert summary["package"] == "com.android.settings"
    assert summary["screen"] == "1080x2400"
    assert summary["node_count"] == 60
    assert len(summary["elements"]) == 40
    assert summary["truncated"] is True
    assert payload["duration_ms"] == 142


def test_app_list_is_capped(monkeypatch) -> None:
    manager = _FakeManager()
    manager.reply = _ok(
        "app.list",
        {
            "apps": [
                {"package": f"p{i}", "label": f"L{i}", "isSystem": i % 2 == 0, "launchable": True}
                for i in range(250)
            ]
        },
    )
    _patch(monkeypatch, manager)

    payload = json.loads(_run(_tools()["phone_list_apps"].ainvoke({})))

    assert payload["ok"] is True
    assert payload["count"] == 250
    assert len(payload["apps"]) == 200
    assert payload["truncated"] is True
    assert payload["apps"][0]["isSystem"] is True
    assert payload["apps"][1]["isSystem"] is False


def test_notifications_without_permission_explain_instead_of_error(monkeypatch) -> None:
    manager = _FakeManager()
    manager.reply = _ok("notification.status", {"granted": False, "packages": []})
    _patch(monkeypatch, manager)

    payload = json.loads(_run(_tools()["phone_notifications"].ainvoke({})))

    assert payload["ok"] is True
    assert payload["granted"] is False
    assert payload["settingsAction"] == "notification-listener"
    assert "通知使用权" in payload["hint"]
    assert [call[0] for call in manager.calls] == ["notification.status"]


def test_notifications_are_redacted_and_filtered(monkeypatch) -> None:
    manager = _FakeManager()
    manager.replies = {
        "notification.status": _ok("notification.status", {"granted": True, "packages": ["com.demo"]}),
        "notification.list": _ok(
            "notification.list",
            {
                "granted": True,
                "notifications": [
                    {
                        "package": "com.demo",
                        "appLabel": "Demo",
                        "title": "张三",
                        "text": "评审改到 15:00",
                        "postedAt": 1794739000000,
                        "category": "msg",
                        "key": "k1",
                    },
                    {
                        "package": "com.android.mms",
                        "appLabel": "短信",
                        "title": "验证码",
                        "text": "验证码 123456",
                        "postedAt": 1794739000000,
                    },
                ],
                "count": 2,
            },
        ),
    }
    _patch(monkeypatch, manager)

    payload = json.loads(
        _run(_tools()["phone_notifications"].ainvoke({"allow_packages": ["com.demo"]}))
    )

    assert payload["granted"] is True
    assert payload["count"] == 1
    assert payload["items"][0]["text"] == "评审改到 15:00"
    assert payload["items"][0]["key"] == "k1"
    sent = manager.calls[1][1]
    assert sent["allowPackages"] == "com.demo"


def test_time_context_includes_reminder_policy_and_duplicates(monkeypatch) -> None:
    manager = _FakeManager()
    manager.replies = {
        "calendar.list": _ok(
            "calendar.list",
            {
                "granted": True,
                "events": [
                    {"title": "评审会", "startAt": 1794739000000, "endAt": 1794740000000},
                ],
            },
        ),
        "alarm.list": _ok("alarm.list", {"nextAlarm": "明天 08:00 闹钟", "hasAlarm": True}),
    }
    _patch(monkeypatch, manager)
    cron = SimpleNamespace(list_all=lambda include_disabled=False: [
        SimpleNamespace(id="cron1", name="评审会", next_run_at=1794739000, enabled=1)
    ])

    tools = {t.name: t for t in A.build_device_link_tools(_config(), user_repo=None, cron_manager=cron)}
    payload = json.loads(_run(tools["phone_time_context"].ainvoke({})))

    assert payload["ok"] is True
    assert payload["calendar"]["items"][0]["title"] == "评审会"
    assert payload["alarm"]["nextAlarm"] == "明天 08:00 闹钟"
    assert payload["cronjobs"][0]["id"] == "cron1"
    assert payload["duplicates"] == ["评审会"]
    assert "HappyClaw 侧创建一次" in payload["reminder_policy"]


def test_failure_passes_through_code_and_duration(monkeypatch) -> None:
    manager = _FakeManager()
    manager.reply = {
        "ok": False,
        "command_id": "cmd-9",
        "result": None,
        "error": {"code": "TIMEOUT", "message": "设备无响应", "retryable": True},
        "replayed": False,
        "duration_ms": 5001,
        "artifact": None,
    }
    _patch(monkeypatch, manager)

    payload = json.loads(_run(_tools()["phone_tap"].ainvoke({"x": 540, "y": 1200})))

    assert payload == {
        "ok": False,
        "tool": "phone_tap",
        "command": "ui.click",
        "code": "TIMEOUT",
        "message": "设备无响应",
        "retryable": True,
        "duration_ms": 5001,
        "command_id": "cmd-9",
    }


def test_offline_fails_closed_without_executing(monkeypatch) -> None:
    manager = _FakeManager(online=False)
    _patch(monkeypatch, manager)

    payload = json.loads(_run(_tools()["phone_screenshot"].ainvoke({})))

    assert payload["ok"] is False
    assert payload["code"] == "DEVICE_OFFLINE"
    assert payload["duration_ms"] == 0
    assert manager.calls == []


def test_side_effect_tools_require_one_time_approval() -> None:
    config = A.device_link_interrupt_on()
    assert set(config) == A.DEVICE_LINK_SIDE_EFFECT_TOOLS
    for entry in config.values():
        assert entry["allowed_decisions"] == ["approve", "reject"]


def test_approval_description_names_coordinates_and_target() -> None:
    tap = A.describe_device_action({"name": "phone_tap", "args": {"x": 540, "y": 1200}})
    assert "(540, 1200)" in tap and "点击" in tap

    swipe = A.describe_device_action(
        {"name": "phone_swipe", "args": {"x1": 1, "y1": 2, "x2": 3, "y2": 4, "duration_ms": 300}}
    )
    assert "(1, 2)" in swipe and "(3, 4)" in swipe

    typed = A.describe_device_action(
        {"name": "phone_type_text", "args": {"text": "hello happyclaw"}}
    )
    assert "当前焦点输入框" in typed and "hello happyclaw" in typed

    typed_at = A.describe_device_action(
        {"name": "phone_type_text", "args": {"text": "x", "x": 10, "y": 20}}
    )
    assert "(10, 20)" in typed_at


class _Req:
    def __init__(self, tools: list) -> None:
        self.tools = tools

    def override(self, **kwargs):
        return _Req(list(kwargs.get("tools", self.tools)))


def test_gate_hides_device_tools_when_offline(monkeypatch) -> None:
    monkeypatch.setattr(G, "get_device_link_manager", lambda: _FakeManager(online=False))
    tools = [SimpleNamespace(name="phone_tap"), SimpleNamespace(name="read_file")]
    gated = G.DeviceLinkToolGateMiddleware()._gate(_Req(tools))
    assert [t.name for t in gated.tools] == ["read_file"]


def test_gate_keeps_device_tools_when_online(monkeypatch) -> None:
    monkeypatch.setattr(G, "get_device_link_manager", lambda: _FakeManager(online=True))
    tools = [SimpleNamespace(name="phone_tap"), SimpleNamespace(name="read_file")]
    gated = G.DeviceLinkToolGateMiddleware()._gate(_Req(tools))
    assert [t.name for t in gated.tools] == ["phone_tap", "read_file"]
