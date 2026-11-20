"""Bao follow-through: classify, nudge once, escalate, push with rate limits."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from octop.infra.bao.followup import BaoFollowupService, FOLLOWUP_PROMPT


def _task(**overrides: Any):
    values = {
        "id": "task-1",
        "user_id": 7,
        "agent_id": "a1",
        "agent_name": "小写",
        "thread_id": "t1",
        "task_text": "跑一下健康检查",
        "status": "done",
        "result_text": None,
        "error_text": None,
        "followup_count": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _TaskRepo:
    def __init__(self, task):
        self.task = task
        self.followups = 0
        self.evaluated: list[str] = []
        self.completed: list[dict[str, Any]] = []

    def latest_terminal_for_thread(self, thread_id, agent_id):
        if self.evaluated:
            return None
        return self.task

    def record_followup(self, task_id):
        self.followups += 1
        self.task.followup_count += 1
        self.task.status = "running"
        return self.task

    def mark_evaluated(self, task_id, eval_status):
        self.evaluated.append(eval_status)
        return 1

    def complete_running(self, **kwargs):
        self.completed.append(kwargs)
        return 1


class _Messages:
    def __init__(self):
        self.rows: list[dict[str, Any]] = []

    def append(self, **kwargs):
        self.rows.append(kwargs)
        return SimpleNamespace(id=f"m{len(self.rows)}")


class _Proactive:
    def __init__(self, claimed=True, reason=None):
        self.claimed = claimed
        self.reason = reason
        self.calls: list[dict[str, Any]] = []

    def claim(self, **kwargs):
        self.calls.append(kwargs)
        return self.claimed, self.reason


class _Users:
    def __init__(self, preferences='{"bao": {"proactive_muted": false}}'):
        self.preferences = preferences

    def get(self, user_id):
        return SimpleNamespace(
            id=user_id,
            username="u",
            role="user",
            preferences_json=self.preferences,
        )


class _Hub:
    def __init__(self):
        self.frames: list[tuple[int, dict[str, Any]]] = []
        self.active = False

    def is_turn_active(self, thread_id):
        return self.active

    async def push_to_user(self, user_id, frame):
        self.frames.append((user_id, frame))


def _service(task, *, proactive=None, users=None, messages=None):
    hub = _Hub()
    gateway = SimpleNamespace(ws_hub=hub)
    repo = _TaskRepo(task)
    service = BaoFollowupService(
        server=SimpleNamespace(services=SimpleNamespace()),
        gateway=gateway,
        task_repo=repo,
        message_repo=messages or _Messages(),
        proactive_repo=proactive or _Proactive(),
        user_repo=users or _Users(),
    )
    return service, repo, hub


def test_redispatch_enqueues_on_the_registered_dashboard_channel(monkeypatch) -> None:
    """A made-up channel id silently drops the nudge; use the real one."""
    import asyncio
    from unittest.mock import AsyncMock

    from octop.infra.gateway.ws.ws_channel import WS_CHANNEL_ID

    calls: list[str] = []

    class _Manager:
        def enqueue(self, channel_id, inbound):
            calls.append(channel_id)

    gateway = SimpleNamespace(
        channel_manager=_Manager(),
        thread_registry=SimpleNamespace(
            get_thread=lambda thread_id: SimpleNamespace(
                session_key="dashboard:7:a1", conversation_mode="craft"
            )
        ),
        ws_hub=None,
    )
    service = BaoFollowupService(
        server=SimpleNamespace(),
        gateway=gateway,
        task_repo=_TaskRepo(_task()),
        message_repo=_Messages(),
        proactive_repo=_Proactive(),
        user_repo=_Users(),
    )
    monkeypatch.setattr(
        "octop.api.routers.chat.turn.prepare_dashboard_turn",
        AsyncMock(return_value="prepared"),
    )
    monkeypatch.setattr(
        "octop.api.routers.chat.turn.build_dashboard_inbound",
        lambda **kwargs: kwargs,
    )

    asyncio.run(service._redispatch(_task()))

    assert calls == [WS_CHANNEL_ID]


@pytest.mark.parametrize(
    ("status", "result", "error", "expected"),
    [
        ("failed", None, "boom", ("failed", "failed")),
        ("awaiting", None, None, ("needs_decision", "needs_decision")),
        ("done", "", None, ("stuck", "done_stuck")),
        ("done", "短", None, ("stuck", "done_stuck")),
        ("done", "需要更多信息才能继续，请提供仓库地址", None, ("stuck", "done_stuck")),
        ("done", "你希望用哪个环境的配置来执行这次健康检查任务，能告诉我吗？", None, ("needs_decision", "needs_decision")),
        ("done", "健康检查全部通过，共 42 项，没有发现异常。", None, ("done", "done_ok")),
    ],
)
def test_classify(status, result, error, expected):
    assert BaoFollowupService._classify(status, result, error) == expected


async def test_stuck_task_gets_one_nudge_without_push(monkeypatch):
    task = _task(result_text="需要更多信息")
    service, repo, hub = _service(task)
    redispatched: list[str] = []

    async def fake_redispatch(inner_task):
        redispatched.append(inner_task.id)

    monkeypatch.setattr(service, "_redispatch", fake_redispatch)

    await service._evaluate(
        thread_id="t1",
        agent_id="a1",
        status="done",
        result_text=task.result_text,
        error_text=None,
    )

    assert redispatched == ["task-1"]
    assert repo.followups == 1
    assert repo.evaluated == []
    assert hub.frames == []
    assert service._message_repo.rows[0]["intent"] == "followup"


async def test_stuck_exhausted_escalates_to_decision_push():
    task = _task(result_text="需要更多信息", followup_count=2)
    proactive = _Proactive()
    service, repo, hub = _service(task, proactive=proactive)

    await service._evaluate(
        thread_id="t1",
        agent_id="a1",
        status="done",
        result_text=task.result_text,
        error_text=None,
    )

    assert repo.followups == 0
    assert repo.evaluated == ["stuck_escalated"]
    assert len(hub.frames) == 1
    assert "需要你决定" in hub.frames[0][1]["text"]
    assert "2 次" in hub.frames[0][1]["text"]
    assert proactive.calls[0]["kind"] == "needs_decision"


async def test_done_pushes_one_dashboard_frame():
    task = _task(result_text="健康检查全部通过，共 42 项，没有发现异常。")
    service, repo, hub = _service(task)

    await service._evaluate(
        thread_id="t1",
        agent_id="a1",
        status="done",
        result_text=task.result_text,
        error_text=None,
    )

    assert repo.evaluated == ["done_ok"]
    user_id, frame = hub.frames[0]
    assert user_id == 7
    assert frame["type"] == "dashboard_push"
    assert frame["agent_id"] == "a1"
    assert frame["thread_id"] == "t1"
    assert "任务完成" in frame["text"]


async def test_suppressed_push_does_not_reach_user():
    task = _task(result_text="健康检查全部通过，共 42 项，没有发现异常。")
    service, _, hub = _service(task, proactive=_Proactive(False, "rate_limited"))

    await service._evaluate(
        thread_id="t1",
        agent_id="a1",
        status="done",
        result_text=task.result_text,
        error_text=None,
    )

    assert hub.frames == []


async def test_muted_user_is_passed_to_proactive_claim():
    task = _task(result_text="健康检查全部通过，共 42 项，没有发现异常。")
    proactive = _Proactive(False, "muted")
    users = _Users('{"bao": {"proactive_muted": true}}')
    service, _, hub = _service(task, proactive=proactive, users=users)

    await service._evaluate(
        thread_id="t1",
        agent_id="a1",
        status="done",
        result_text=task.result_text,
        error_text=None,
    )

    assert proactive.calls[0]["muted"] is True
    assert hub.frames == []


async def test_failed_task_pushes_failure():
    task = _task(status="failed", error_text="worker crashed")
    service, repo, hub = _service(task)

    await service._evaluate(
        thread_id="t1",
        agent_id="a1",
        status="failed",
        result_text=None,
        error_text="worker crashed",
    )

    assert repo.evaluated == ["failed"]
    assert "任务失败" in hub.frames[0][1]["text"]


def test_followup_prompt_is_deterministic():
    assert "不要停在提问上" in FOLLOWUP_PROMPT
