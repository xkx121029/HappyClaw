"""TodayCollector 单测（假设备、假网关，不依赖真机与网络）。"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from octop.infra.control.device_link.today import collector as C

NOW_MS = int(time.time() * 1000)


class _FakeManager:
    def __init__(self, replies: dict[str, dict] | None = None, *, online: bool = True) -> None:
        self.online = online
        self.replies = replies or {}
        self.calls: list[tuple[str, dict]] = []

    def is_online(self) -> bool:
        return self.online

    def subscribe(self):
        return asyncio.Queue()

    def unsubscribe(self, queue) -> None:  # noqa: ANN001
        return None

    async def run_command(self, name, params=None, command_id=None, timeout_ms=None):
        self.calls.append((name, params or {}))
        return self.replies.get(name, {"ok": True, "result": {}})


class _FakeGateway:
    def __init__(self) -> None:
        self.pushed: list[tuple[str, str, str]] = []

    async def push_text_from_session(self, agent_id, session_key, text) -> None:
        self.pushed.append((agent_id, session_key, text))


class _FakeBridge:
    def __init__(self) -> None:
        self.atoms: list[dict] = []

    def handle(self, payload: dict) -> dict:
        self.atoms.append(payload["params"])
        return {"jsonrpc": "2.0", "id": payload.get("id"), "result": {"ok": True}}


def _ok(result: dict) -> dict:
    return {"ok": True, "result": result}


def _replies(*, events: list[dict] | None = None, notes: list[dict] | None = None,
             granted: bool = True) -> dict[str, dict]:
    return {
        "notification.status": _ok({"granted": granted}),
        "notification.list": _ok({"granted": granted, "notifications": notes or []}),
        "calendar.list": _ok({"granted": True, "events": events or []}),
        "alarm.list": _ok({"nextAlarm": "", "hasAlarm": False}),
        "today.sync": _ok({"applied": 1}),
    }


def _collector(tmp_path: Path, manager: _FakeManager, gateway: _FakeGateway,
               *, config: dict | None = None) -> C.TodayCollector:
    path = tmp_path / "today.json"
    if config is not None:
        path.write_text(json.dumps(config), encoding="utf-8")
    return C.TodayCollector(
        manager=manager,
        server=SimpleNamespace(),
        gateway=gateway,
        agent_repo=SimpleNamespace(list_all=lambda: [SimpleNamespace(id="a1")]),
        session_repo=SimpleNamespace(
            list_by_agent=lambda agent_id, limit=10: [
                SimpleNamespace(session_key="web:1", channel_id="web")
            ]
        ),
        thread_repo=SimpleNamespace(latest_user_activity=lambda agent_id: None),
        timezone="UTC",
        config_path=path,
    )


def _config(**overrides) -> dict:
    cfg = {
        "activeHours": {"start": "00:00", "end": "23:59"},
        "minPushGapMinutes": 60,
        "maxPushesPerDay": 6,
        "notificationConsent": False,
        "notificationStorage": "none",
    }
    cfg.update(overrides)
    return cfg


def _note(text: str = "快递到了") -> dict:
    return {
        "package": "com.demo",
        "appLabel": "Demo",
        "title": "张三",
        "text": text,
        "postedAt": NOW_MS,
        "category": "msg",
        "key": f"k-{text}",
    }


def test_notifications_not_collected_without_consent(tmp_path: Path) -> None:
    manager = _FakeManager(_replies(notes=[_note()]))
    gateway = _FakeGateway()
    collector = _collector(tmp_path, manager, gateway, config=_config())

    asyncio.run(collector.run_once())

    names = [name for name, _ in manager.calls]
    assert "notification.status" not in names
    assert "notification.list" not in names
    assert all(not item.source.startswith("notification:") for item in collector.store.items())


def test_notifications_are_ephemeral_when_storage_none(tmp_path: Path) -> None:
    manager = _FakeManager(_replies(notes=[_note("快递到了")]))
    gateway = _FakeGateway()
    collector = _collector(
        tmp_path,
        manager,
        gateway,
        config=_config(notificationConsent=True, notificationStorage="none"),
    )

    asyncio.run(collector.run_once())

    names = [name for name, _ in manager.calls]
    assert "notification.list" in names
    assert all(not item.source.startswith("notification:") for item in collector.store.items())
    raw = (tmp_path / "today.json").read_text(encoding="utf-8")
    assert "快递到了" not in raw


def test_notifications_persist_and_remember_only_when_storage_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = _FakeBridge()
    monkeypatch.setattr(
        "octop.infra.agents.memory.client._open_memory_for_agent",
        lambda server, agent_id: (None, bridge),
    )
    manager = _FakeManager(_replies(notes=[_note("评审改到 15:00")]))
    collector = _collector(
        tmp_path,
        manager,
        _FakeGateway(),
        config=_config(notificationConsent=True, notificationStorage="memory"),
    )

    asyncio.run(collector.run_once())
    stored = collector.store.items()
    assert any(item.source.startswith("notification:") for item in stored)
    assert len(bridge.atoms) == 1
    assert "评审改到 15:00" in bridge.atoms[0]["assertion"]

    # 第二轮同样的通知不应重复写记忆
    asyncio.run(collector.run_once())
    assert len(bridge.atoms) == 1


def test_proactive_push_is_rate_limited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "octop.infra.agents.memory.client._open_memory_for_agent",
        lambda server, agent_id: (None, _FakeBridge()),
    )
    gateway = _FakeGateway()
    manager = _FakeManager(_replies(notes=[_note("快递到了")]))
    collector = _collector(
        tmp_path,
        manager,
        gateway,
        config=_config(notificationConsent=True, notificationStorage="memory"),
    )

    async def two_rounds() -> None:
        await collector.run_once()
        await collector.run_once()

    asyncio.run(two_rounds())

    assert len(gateway.pushed) == 1
    agent_id, session_key, text = gateway.pushed[0]
    assert agent_id == "a1" and session_key == "web:1"
    assert text.startswith("今天")
    assert "张三" in text
    # 主动提醒来自整合结果，不是通知原文照搬
    assert "快递到了" not in text


def test_push_prefers_agent_with_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """id 最小的 agent 可能没有会话，主动提醒要挑真的有会话的那个。"""
    monkeypatch.setattr(
        "octop.infra.agents.memory.client._open_memory_for_agent",
        lambda server, agent_id: (None, _FakeBridge()),
    )
    gateway = _FakeGateway()
    manager = _FakeManager(_replies(notes=[_note("帮我确认一下")]))

    def sessions(agent_id: str, limit: int = 10):  # noqa: ANN202
        if agent_id == "a0":
            return []
        return [SimpleNamespace(session_key="web:9", channel_id="web")]

    collector = C.TodayCollector(
        manager=manager,
        server=SimpleNamespace(),
        gateway=gateway,
        agent_repo=SimpleNamespace(
            list_all=lambda: [
                SimpleNamespace(id=1, agent_id="a0"),
                SimpleNamespace(id=2, agent_id="a2"),
            ]
        ),
        session_repo=SimpleNamespace(list_by_agent=sessions),
        thread_repo=SimpleNamespace(latest_user_activity=lambda agent_id: None),
        timezone="UTC",
        config_path=tmp_path / "today.json",
    )
    (tmp_path / "today.json").write_text(
        json.dumps(_config(notificationConsent=True, notificationStorage="digest")),
        encoding="utf-8",
    )

    asyncio.run(collector.run_once())

    assert gateway.pushed
    assert gateway.pushed[0][0] == "a2"
    assert gateway.pushed[0][1] == "web:9"


def test_capture_note_becomes_todo_and_syncs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = _FakeBridge()
    monkeypatch.setattr(
        "octop.infra.agents.memory.client._open_memory_for_agent",
        lambda server, agent_id: (None, bridge),
    )
    manager = _FakeManager(_replies())
    collector = _collector(tmp_path, manager, _FakeGateway(), config=_config())

    asyncio.run(collector.handle_capture({"text": "买牛奶", "capturedAt": NOW_MS}))

    stored = collector.store.items()
    assert any(item.kind == "todo" and item.title == "买牛奶" for item in stored)
    assert any("买牛奶" in atom["assertion"] for atom in bridge.atoms)
    sync_calls = [params for name, params in manager.calls if name == "today.sync"]
    assert sync_calls
    assert any(todo["text"] == "买牛奶" for todo in sync_calls[-1]["todos"])


def test_ungranted_notifications_skip_list(tmp_path: Path) -> None:
    manager = _FakeManager(_replies(granted=False))
    collector = _collector(
        tmp_path,
        manager,
        _FakeGateway(),
        config=_config(notificationConsent=True, notificationStorage="memory"),
    )

    asyncio.run(collector.run_once())

    names = [name for name, _ in manager.calls]
    assert "notification.status" in names
    assert "notification.list" not in names
    assert collector.store.permissions().get("notification") is False

