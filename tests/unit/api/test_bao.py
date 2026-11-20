"""Unit tests for the Bao overview and dispatch endpoints."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from octop.api.routers import bao
from octop.infra.errors import ErrorCode, OctopError


def _agent(agent_id: str, name: str, *, state: str = "stopped", error: str | None = None):
    return SimpleNamespace(
        agent_id=agent_id,
        name=name,
        last_state=state,
        last_error=error,
        default_model="openai/gpt-4o",
        config_json="{}",
    )


def _thread(thread_id: str, agent_id: str, title: str, last_active: int):
    return SimpleNamespace(
        thread_id=thread_id,
        agent_id=agent_id,
        user_id=7,
        title=title,
        last_active=last_active,
        created_at=1,
        contributed=False,
        session_key=f"dashboard|{agent_id}|7",
        conversation_mode="craft",
    )


def _server(*, active: set[str] | None = None, pending: set[str] | None = None):
    server = MagicMock()
    server.paths.agents_dir = Path("E:/octop/agents")
    gateway = server.app_runtime.gateway
    gateway.ws_hub.is_turn_active.side_effect = lambda tid: tid in (active or set())
    gateway.processor.hitl_coordinator.store.pending_thread_ids.side_effect = (
        lambda **kwargs: (pending or set())
        if kwargs.get("any_user")
        else (pending or set())
    )
    server.services.thread_message_repo.threads_with_messages.return_value = {
        "t1",
        "t2",
    }
    server.services.thread_message_repo.projection_status.return_value = "ready"
    server.app_runtime.gateway.channel_manager.enqueue = MagicMock()
    return server


def _user():
    return SimpleNamespace(id=7, is_admin=True, locale="zh")


async def test_overview_groups_default_and_explicit_projects(monkeypatch):
    server = _server(active={"t2"}, pending={"t1"})
    monkeypatch.setattr(bao, "host_path_text", lambda path: str(path))
    rows = [
        _agent("a1", "A1", state="running"),
        _agent("a2", "A2", state="stopped", error="model missing"),
    ]
    thread_registry = server.app_runtime.gateway.thread_registry
    thread_registry.list_visible_threads.side_effect = lambda agent_id, **_: (
        [_thread("t1", "a1", "会话一", 100)]
        if agent_id == "a1"
        else [_thread("t2", "a2", "会话二", 200)]
    )
    monkeypatch.setattr(bao, "_visible_agent_rows", lambda server, user: rows)
    monkeypatch.setattr(
        bao,
        "_agent_workspace",
        lambda server, row: (
            "E:/octop/agents/a1" if row.agent_id == "a1" else "E:/work/alpha"
        ),
    )

    payload = await bao.get_overview(session_limit=20, user=_user(), server=server)

    assert payload["totals"] == {
        "projects": 2,
        "agents": 2,
        "running_agents": 1,
        "active_turns": 1,
        "awaiting_user": 1,
        "failed_agents": 1,
    }
    default_project = payload["projects"][0]
    assert default_project["key"] == "default"
    assert default_project["is_default"] is True
    assert default_project["sessions"][0]["thread_id"] == "t1"
    assert default_project["sessions"][0]["awaiting_user"] is True
    alpha = payload["projects"][1]
    assert alpha["key"] == bao.project_identity("E:/work/alpha", "E:/octop/agents")[0]
    assert alpha["name"] == "alpha"
    assert alpha["sessions"][0]["turn_active"] is True
    assert alpha["failed_agents"] == 1


async def test_overview_empty_state(monkeypatch):
    server = _server()
    monkeypatch.setattr(bao, "_visible_agent_rows", lambda server, user: [])

    payload = await bao.get_overview(session_limit=20, user=_user(), server=server)

    assert payload["projects"] == []
    assert payload["totals"]["projects"] == 0


async def test_dispatch_enqueues_with_thread_session_key(monkeypatch):
    server = _server()
    monkeypatch.setattr(bao, "host_path_text", lambda path: str(path))
    row = _agent("a1", "A1")
    thread = _thread("t1", "a1", "会话一", 100)
    server.app_runtime.gateway.thread_registry.get_thread.return_value = thread
    monkeypatch.setattr(bao, "require_agent_row", lambda *args, **kwargs: row)
    monkeypatch.setattr(bao, "_agent_workspace", lambda server, row: "E:/work/alpha")
    captured: dict = {}

    async def fake_prepare(server, *, agent_id, user, turn):
        captured["agent_id"] = agent_id
        captured["turn"] = turn
        return SimpleNamespace(thread_id=turn.thread_id, session_key=turn.session_key)

    monkeypatch.setattr(bao, "prepare_dashboard_turn", fake_prepare)
    monkeypatch.setattr(
        bao,
        "build_dashboard_inbound",
        lambda **kwargs: {"inbound": kwargs},
    )

    result = await bao.dispatch_task(
        bao.BaoDispatchBody(agent_id="a1", thread_id="t1", text="  帮我跑一下  "),
        user=_user(),
        server=server,
    )

    assert result["dispatched"] is True
    assert result["project_key"] == bao.project_identity("E:/work/alpha", "E:/octop/agents")[0]
    assert captured["turn"].text == "帮我跑一下"
    assert captured["turn"].session_key == thread.session_key
    assert captured["turn"].conversation_mode == "craft"
    inbound = server.app_runtime.gateway.channel_manager.enqueue.call_args.args
    assert inbound[0] == "octop-dashboard"
    assert inbound[1]["inbound"]["prepared"].thread_id == "t1"


async def test_dispatch_creates_conversation_when_thread_id_omitted(monkeypatch):
    server = _server()
    row = _agent("a1", "A1")
    created_thread = _thread("t-new", "a1", None, 0)
    thread_registry = server.app_runtime.gateway.thread_registry
    thread_registry.create_thread.return_value = "t-new"
    thread_registry.get_thread.return_value = created_thread
    monkeypatch.setattr(bao, "require_agent_row", lambda *args, **kwargs: row)
    monkeypatch.setattr(bao, "_agent_workspace", lambda server, row: "E:/work/alpha")
    monkeypatch.setattr(bao, "host_path_text", lambda path: str(path))
    captured: dict = {}

    async def fake_prepare(server, *, agent_id, user, turn):
        captured["turn"] = turn
        return SimpleNamespace(thread_id=turn.thread_id, session_key=turn.session_key)

    monkeypatch.setattr(bao, "prepare_dashboard_turn", fake_prepare)
    monkeypatch.setattr(bao, "build_dashboard_inbound", lambda **kwargs: {"inbound": kwargs})

    result = await bao.dispatch_task(
        bao.BaoDispatchBody(agent_id="a1", text="新建会话跑一下"),
        user=_user(),
        server=server,
    )

    assert result["created"] is True
    assert result["thread_id"] == "t-new"
    create_kwargs = thread_registry.create_thread.call_args.kwargs
    assert create_kwargs["agent_id"] == "a1"
    assert create_kwargs["user_id"] == 7
    assert create_kwargs["session_key"] == bao.ThreadRegistry.dashboard_key(
        agent_id="a1", user_id=7
    )
    assert captured["turn"].thread_id == "t-new"
    assert captured["turn"].session_key == created_thread.session_key
    server.app_runtime.gateway.channel_manager.enqueue.assert_called_once()


def _setup_overview(monkeypatch, server, *, alpha_sessions=True, no_sessions=False):
    monkeypatch.setattr(bao, "host_path_text", lambda path: str(path))
    rows = [
        _agent("a1", "小通", state="running"),
        _agent("a2", "小写", state="running"),
    ]
    thread_registry = server.app_runtime.gateway.thread_registry
    alpha = bao.project_identity("E:/work/alpha", "E:/octop/agents")[0]

    def list_threads(agent_id, **_):
        if no_sessions:
            return []
        if agent_id == "a1":
            return [_thread("t1", "a1", "会话一", 100)]
        if alpha_sessions:
            return [_thread("t2", "a2", "会话二", 200)]
        return []

    thread_registry.list_visible_threads.side_effect = list_threads
    monkeypatch.setattr(bao, "_visible_agent_rows", lambda server, user: rows)
    monkeypatch.setattr(
        bao,
        "_agent_workspace",
        lambda server, row: (
            "E:/octop/agents/a1" if row.agent_id == "a1" else "E:/work/alpha"
        ),
    )
    return alpha


async def test_route_matches_session_title(monkeypatch):
    server = _server()
    _setup_overview(monkeypatch, server)

    decision = await bao.route_task(
        bao.BaoRouteBody(text="请跟进 会话二 的进度"), user=_user(), server=server
    )

    assert decision["decided"] is True
    assert decision["thread"]["thread_id"] == "t2"
    assert decision["agent"]["agent_id"] == "a2"
    assert decision["project"]["name"] == "alpha"
    assert decision["reason"]["code"] == "session_title"
    assert decision["create_thread"] is False
    server.app_runtime.gateway.channel_manager.enqueue.assert_not_called()


async def test_route_deterministic_decision_skips_model(monkeypatch):
    server = _server()
    _setup_overview(monkeypatch, server)

    async def must_not_run(*args, **kwargs):
        raise AssertionError("model fallback must not run for a deterministic match")

    monkeypatch.setattr(bao, "_model_route", must_not_run)

    decision = await bao.route_task(
        bao.BaoRouteBody(text="请跟进 会话二 的进度"), user=_user(), server=server
    )

    assert decision["decided"] is True
    assert decision["reason"]["code"] == "session_title"
    assert "model_attempt" not in decision


async def test_route_stays_inside_project_scope(monkeypatch):
    server = _server(active={"t2"})
    alpha = _setup_overview(monkeypatch, server)

    decision = await bao.route_task(
        bao.BaoRouteBody(text="继续推进", scope="project", project_key=alpha),
        user=_user(),
        server=server,
    )

    assert decision["project"]["key"] == alpha
    assert decision["thread"]["thread_id"] == "t2"
    assert decision["reason"]["code"] == "scope_active_session"
    assert decision["thread"]["turn_active"] is True


async def test_route_names_expert_and_creates_thread(monkeypatch):
    server = _server()
    alpha = _setup_overview(monkeypatch, server, alpha_sessions=False)

    decision = await bao.route_task(
        bao.BaoRouteBody(
            text="让 小写 处理一下", scope="project", project_key=alpha
        ),
        user=_user(),
        server=server,
    )

    assert decision["agent"]["agent_id"] == "a2"
    assert decision["thread"] is None
    assert decision["create_thread"] is True
    assert decision["reason"]["code"] == "agent_name_new_thread"


async def test_route_global_without_sessions_asks_for_target(monkeypatch):
    server = _server()
    _setup_overview(monkeypatch, server, alpha_sessions=False, no_sessions=True)

    async def unsure(server, *, text, projects):
        return None, {"tried": True, "code": "model_unsure", "detail": "no clear target"}

    monkeypatch.setattr(bao, "_model_route", unsure)

    decision = await bao.route_task(
        bao.BaoRouteBody(text="帮我做点事"), user=_user(), server=server
    )

    assert decision["decided"] is False
    assert decision["needs_target"] is True
    assert decision["reason"]["code"] == "ambiguous_project"
    assert decision["model_attempt"]["code"] == "model_unsure"
    assert {item["name"] for item in decision["candidates"]["projects"]} == {
        "",
        "alpha",
    }
    server.app_runtime.gateway.channel_manager.enqueue.assert_not_called()


async def test_route_model_fallback_decides(monkeypatch):
    server = _server()
    alpha = _setup_overview(monkeypatch, server, alpha_sessions=False, no_sessions=True)
    model_decision = {
        "decided": True,
        "needs_target": False,
        "reason": {
            "code": "model_route",
            "params": {"model": "small", "confidence": 0.82, "note": "alpha 更相关"},
        },
        "project": {"key": alpha, "name": "alpha", "is_default": False},
        "agent": {"agent_id": "a2", "name": "小写", "state": "running"},
        "thread": None,
        "create_thread": True,
    }

    async def fallback(server, *, text, projects):
        return model_decision, {
            "tried": True,
            "code": "model_route",
            "detail": "a1 -> a2",
        }

    monkeypatch.setattr(bao, "_model_route", fallback)

    decision = await bao.route_task(
        bao.BaoRouteBody(text="把那个东西同步一下"), user=_user(), server=server
    )

    assert decision["decided"] is True
    assert decision["reason"]["code"] == "model_route"
    assert decision["agent"]["agent_id"] == "a2"
    assert decision["model_attempt"]["code"] == "model_route"


async def test_model_route_validates_and_builds_decision(monkeypatch):
    server = _server()
    runtime_agent = SimpleNamespace(
        config=SimpleNamespace(pick_default_model_ref=lambda: "small-model"),
        model_factory=SimpleNamespace(get=lambda ref: object()),
    )
    server.app_runtime.agent_registry.get_agent.return_value = runtime_agent
    projects = [
        {
            "key": "ws:a",
            "name": "alpha",
            "is_default": False,
            "agents": [
                {
                    "agent_id": "a1",
                    "name": "小写",
                    "state": "running",
                    "model_ready": True,
                }
            ],
            "sessions": [
                {
                    "agent_id": "a1",
                    "agent_name": "小写",
                    "thread_id": "t1",
                    "title": "会话一",
                    "last_active": 100,
                    "turn_active": False,
                    "awaiting_user": False,
                }
            ],
        }
    ]

    async def fake_invoke(llm, messages, timeout):
        return (
            '```json\n{"agent_id":"a1","thread_id":"t1","create_thread":false,'
            '"confidence":0.88,"reason":"提到了会话一"}\n```'
        )

    monkeypatch.setattr(bao, "ainvoke_text", fake_invoke)

    decision, attempt = await bao._model_route(
        server, text="继续推进会话一", projects=projects
    )

    assert decision is not None
    assert decision["reason"]["code"] == "model_route"
    assert decision["thread"]["thread_id"] == "t1"
    assert decision["reason"]["params"]["confidence"] == 0.88
    assert attempt["code"] == "model_route"


async def test_model_route_rejects_low_confidence_or_unknown_agent(monkeypatch):
    server = _server()
    server.app_runtime.agent_registry.get_agent.return_value = SimpleNamespace(
        config=SimpleNamespace(pick_default_model_ref=lambda: "small-model"),
        model_factory=SimpleNamespace(get=lambda ref: object()),
    )
    projects = [
        {
            "key": "ws:a",
            "name": "alpha",
            "is_default": False,
            "agents": [
                {
                    "agent_id": "a1",
                    "name": "小写",
                    "state": "running",
                    "model_ready": True,
                }
            ],
            "sessions": [],
        }
    ]

    async def low_confidence(*args, **kwargs):
        return '{"agent_id":"a1","create_thread":true,"confidence":0.2,"reason":"猜的"}'

    monkeypatch.setattr(bao, "ainvoke_text", low_confidence)
    decision, attempt = await bao._model_route(server, text="随便", projects=projects)
    assert decision is None
    assert attempt["code"] == "model_unsure"

    async def unknown_agent(*args, **kwargs):
        return '{"agent_id":"ghost","create_thread":true,"confidence":0.99,"reason":"x"}'

    monkeypatch.setattr(bao, "ainvoke_text", unknown_agent)
    decision, attempt = await bao._model_route(server, text="随便", projects=projects)
    assert decision is None
    assert attempt["code"] == "model_unsure"



def _fake_task(task_id: str = "task-1", status: str = "running"):
    return SimpleNamespace(
        id=task_id,
        status=status,
        to_dict=lambda: {"id": task_id, "status": status},
    )


async def test_dispatch_persists_task_before_enqueue(monkeypatch):
    server = _server()
    monkeypatch.setattr(bao, "host_path_text", lambda path: str(path))
    row = _agent("a1", "A1")
    thread = _thread("t1", "a1", "会话一", 100)
    server.app_runtime.gateway.thread_registry.get_thread.return_value = thread
    monkeypatch.setattr(bao, "require_agent_row", lambda *args, **kwargs: row)
    monkeypatch.setattr(bao, "_agent_workspace", lambda server, row: "E:/work/alpha")
    task = _fake_task()
    server.services.bao_task_repo.create.return_value = task

    async def fake_prepare(server, *, agent_id, user, turn):
        return SimpleNamespace(thread_id=turn.thread_id, session_key=turn.session_key)

    monkeypatch.setattr(bao, "prepare_dashboard_turn", fake_prepare)
    monkeypatch.setattr(bao, "build_dashboard_inbound", lambda **kwargs: {"inbound": kwargs})

    result = await bao.dispatch_task(
        bao.BaoDispatchBody(
            agent_id="a1",
            thread_id="t1",
            text="帮我跑一下",
            route_reason={"code": "session_title", "params": {"title": "会话一"}},
            source="bao",
        ),
        user=_user(),
        server=server,
    )

    assert result["task_id"] == "task-1"
    assert result["task"]["status"] == "running"
    create_kwargs = server.services.bao_task_repo.create.call_args.kwargs
    assert create_kwargs["thread_id"] == "t1"
    assert create_kwargs["source"] == "bao"
    assert create_kwargs["route_reason"]["code"] == "session_title"
    assert create_kwargs["task_text"] == "帮我跑一下"
    server.services.bao_task_repo.create.assert_called_once()
    server.app_runtime.gateway.channel_manager.enqueue.assert_called_once()


async def test_list_tasks_reconciles_and_acknowledges(monkeypatch):
    server = _server()
    server.app_runtime.gateway.ws_hub.active_thread_ids = frozenset({"t2"})
    server.services.bao_task_repo.list_for_user.return_value = [
        _fake_task("done-1", "done"),
        _fake_task("run-1", "running"),
    ]

    payload = await bao.list_tasks(limit=20, user=_user(), server=server)

    assert [task["id"] for task in payload["tasks"]] == ["done-1", "run-1"]
    assert payload["retention"]["max_per_user"] == 200
    server.services.bao_task_repo.reconcile_interrupted.assert_called_once()
    ack_args = server.services.bao_task_repo.acknowledge.call_args.args
    assert ack_args[0] == 7
    assert ack_args[1] == ["done-1"]


async def test_import_tasks_is_delegated():
    server = _server()
    server.services.bao_task_repo.import_legacy.return_value = (2, 1)

    payload = await bao.import_tasks(
        bao.BaoTaskImportBody(tasks=[{"id": "a"}, {"id": "b"}, {"id": "c"}]),
        user=_user(),
        server=server,
    )

    assert payload["imported"] == 2
    assert payload["skipped"] == 1
    server.services.bao_task_repo.import_legacy.assert_called_once()



async def test_route_empty_workspace(monkeypatch):
    server = _server()
    monkeypatch.setattr(bao, "_visible_agent_rows", lambda server, user: [])

    decision = await bao.route_task(
        bao.BaoRouteBody(text="继续"), user=_user(), server=server
    )

    assert decision["needs_target"] is True
    assert decision["reason"]["code"] == "no_project"


async def test_dispatch_rejects_busy_thread(monkeypatch):
    server = _server(active={"t1"})
    row = _agent("a1", "A1")
    server.app_runtime.gateway.thread_registry.get_thread.return_value = _thread(
        "t1", "a1", "会话一", 100
    )
    monkeypatch.setattr(bao, "require_agent_row", lambda *args, **kwargs: row)

    with pytest.raises(OctopError) as excinfo:
        await bao.dispatch_task(
            bao.BaoDispatchBody(agent_id="a1", thread_id="t1", text="跑一下"),
            user=_user(),
            server=server,
        )

    assert excinfo.value.code == ErrorCode.THREAD_TURN_ACTIVE
    server.app_runtime.gateway.channel_manager.enqueue.assert_not_called()


async def test_dispatch_rejects_pending_approval(monkeypatch):
    server = _server(pending={"t1"})
    row = _agent("a1", "A1")
    server.app_runtime.gateway.thread_registry.get_thread.return_value = _thread(
        "t1", "a1", "会话一", 100
    )
    monkeypatch.setattr(bao, "require_agent_row", lambda *args, **kwargs: row)

    with pytest.raises(OctopError) as excinfo:
        await bao.dispatch_task(
            bao.BaoDispatchBody(agent_id="a1", thread_id="t1", text="跑一下"),
            user=_user(),
            server=server,
        )

    assert excinfo.value.code == ErrorCode.THREAD_TURN_ACTIVE
    assert "approval" in str(excinfo.value)


def _team_setup(monkeypatch, server):
    """Team ``team1`` owns member ``a2``; both are visible in the panel."""
    team = _agent("team1", "军团")
    team.kind = "team"
    member = _agent("a2", "小写")
    member.kind = "expert"
    rows = [_agent("a1", "小通"), member, team]
    monkeypatch.setattr(bao, "host_path_text", lambda path: str(path))
    monkeypatch.setattr(bao, "host_text", lambda path: str(path), raising=False)
    monkeypatch.setattr(
        bao,
        "_agent_workspace",
        lambda server, row: "E:/work/alpha" if row.agent_id in ("a1", "a2") else "",
    )
    monkeypatch.setattr(bao, "_visible_agent_rows", lambda inner_server, user: rows)
    server.app_runtime.gateway.thread_registry.list_visible_threads.return_value = []
    server.app_runtime.agent_registry.teams.visible_member_ids.side_effect = (
        lambda team_id: ["a2"] if team_id == "team1" else []
    )
    return rows


async def test_overview_marks_team_members_not_directly_dispatchable(monkeypatch):
    server = _server()
    _team_setup(monkeypatch, server)

    payload = await bao.get_overview(session_limit=20, user=_user(), server=server)

    agents = {
        agent["agent_id"]: agent
        for project in payload["projects"]
        for agent in project["agents"]
    }
    assert agents["a2"]["direct_dispatchable"] is False
    assert agents["a2"]["direct_dispatch_hint"] == "team_member"
    assert agents["a2"]["team_name"] == "军团"
    assert agents["a1"]["direct_dispatchable"] is True


async def test_route_blocks_team_member_with_reason(monkeypatch):
    server = _server()
    _team_setup(monkeypatch, server)

    decision = await bao.route_task(
        bao.BaoRouteBody(text="让 小写 处理一下"), user=_user(), server=server
    )

    assert decision["decided"] is False
    assert decision["needs_target"] is True
    assert decision["direct_dispatchable"] is False
    assert decision["blocked"] == "team_member"
    assert decision["thread"] is None
    assert decision["create_thread"] is False
    assert decision["reason"]["code"] == "team_member"
    assert decision["reason"]["params"]["team"] == "军团"
    server.app_runtime.gateway.channel_manager.enqueue.assert_not_called()


async def test_dispatch_rejects_team_member_before_409(monkeypatch):
    server = _server()
    _team_setup(monkeypatch, server)
    monkeypatch.setattr(bao, "require_agent_row", lambda *args, **kwargs: _agent("a2", "小写"))

    with pytest.raises(OctopError) as excinfo:
        await bao.dispatch_task(
            bao.BaoDispatchBody(agent_id="a2", text="跑一下"),
            user=_user(),
            server=server,
        )

    assert excinfo.value.code == ErrorCode.TEAM_MEMBER_NOT_DIRECT
    assert excinfo.value.status == 400
    assert excinfo.value.details["team_name"] == "军团"
    server.app_runtime.gateway.channel_manager.enqueue.assert_not_called()


class _FakeMessages:
    def __init__(self):
        self.rows = []

    def append(self, *, user_id, role, text, intent="", refs=None, task_id=None):
        captured = dict(refs or {})
        index = len(self.rows)
        row = SimpleNamespace(
            id=f"m{index + 1}",
            role=role,
            text=text,
            intent=intent,
            refs=lambda captured=captured: captured,
            task_id=task_id,
            to_dict=lambda: {
                "id": f"m{index + 1}",
                "role": role,
                "text": text,
                "intent": intent,
                "refs": captured,
                "task_id": task_id,
            },
        )
        self.rows.append(row)
        return row

    def list_for_user(self, user_id, limit=100):
        return self.rows[-limit:]


class _FakeTasks:
    def __init__(self):
        self.rows: dict[str, dict] = {}

    def add(self, task_id: str, **overrides):
        row = {
            "id": task_id,
            "agent_id": "a1",
            "agent_name": "小写",
            "thread_id": "t1",
            "task_text": "跑一下健康检查",
            "status": "running",
            "result_text": None,
            "error_text": None,
            "followup_count": 0,
            **overrides,
        }
        self.rows[task_id] = row
        return row

    def get(self, task_id):
        row = self.rows.get(task_id)
        return SimpleNamespace(to_dict=lambda: dict(row)) if row else None

    def list_for_user(self, user_id, limit=50):
        rows = list(reversed(list(self.rows.values())))[:limit]
        return [SimpleNamespace(to_dict=lambda row=row: dict(row)) for row in rows]

    def acknowledge(self, user_id, task_ids):
        return len(task_ids)


def _chat_server(monkeypatch, tasks: _FakeTasks, messages: _FakeMessages):
    server = _server()
    server.services.bao_message_repo = messages
    server.services.bao_task_repo = tasks
    server.services.user_repo.get.return_value = SimpleNamespace(preferences_json="{}")
    monkeypatch.setattr(
        bao,
        "_overview_payload",
        lambda inner_server, user, limit: {
            "projects": [
                {"key": "default", "name": "", "is_default": True},
                {"key": "ws:a", "name": "alpha", "is_default": False},
            ],
            "totals": {"agents": 3},
        },
    )
    return server


async def test_chat_five_turns_remember_references(monkeypatch):
    tasks = _FakeTasks()
    messages = _FakeMessages()
    server = _chat_server(monkeypatch, tasks, messages)
    calls: list[dict] = []

    async def fake_route(body, *, user, server):
        return {
            "decided": True,
            "needs_target": False,
            "agent": {"agent_id": "a1", "name": "小写"},
            "thread": {"thread_id": "t1"},
            "reason": {"code": "agent_name", "params": {"agent": "小写"}},
        }

    async def fake_dispatch(inner_server, user, *, agent_id, thread_id, text, **kwargs):
        calls.append({"agent_id": agent_id, "thread_id": thread_id, "text": text})
        task = tasks.add(
            f"task-{len(calls)}",
            agent_id=agent_id,
            thread_id=thread_id,
            task_text=text,
        )
        return {
            "dispatched": True,
            "agent_id": agent_id,
            "agent_name": "小写",
            "thread_id": thread_id,
            "task_id": task["id"],
            "task": dict(task),
        }

    monkeypatch.setattr(bao, "route_task", fake_route)
    monkeypatch.setattr(bao, "_dispatch_core", fake_dispatch)

    first = await bao.chat(
        bao.BaoChatBody(text="看看现在有哪些项目"), user=_user(), server=server
    )
    assert first["intent"] == "overview"
    assert "2 个项目" in first["reply_text"]

    second = await bao.chat(
        bao.BaoChatBody(text="让小写跑一下健康检查"), user=_user(), server=server
    )
    assert second["intent"] == "new_task"
    assert calls[0]["agent_id"] == "a1"
    assert second["task"]["id"] == "task-1"

    third = await bao.chat(bao.BaoChatBody(text="再等等"), user=_user(), server=server)
    assert third["intent"] == "wait"
    assert len(calls) == 1

    tasks.rows["task-1"]["status"] = "done"
    tasks.rows["task-1"]["result_text"] = "健康检查通过，全部 200"
    fourth = await bao.chat(
        bao.BaoChatBody(text="刚才那个怎么样了"), user=_user(), server=server
    )
    assert fourth["intent"] == "status"
    assert "已完成" in fourth["reply_text"]
    assert "健康检查通过" in fourth["reply_text"]

    fifth = await bao.chat(
        bao.BaoChatBody(text="把那个也一起做了"), user=_user(), server=server
    )
    assert fifth["intent"] == "also"
    assert len(calls) == 2
    assert calls[1]["text"] == "让小写跑一下健康检查"
    assert calls[1]["thread_id"] == "t1"

    sixth = await bao.chat(
        bao.BaoChatBody(text="刚才那个完成了吗"), user=_user(), server=server
    )
    assert sixth["intent"] == "status"
    assert tasks.rows["task-1"]["task_text"] in sixth["reply_text"]
    assert len(messages.rows) == 12


async def test_chat_asks_for_target_then_dispatches_it(monkeypatch):
    tasks = _FakeTasks()
    messages = _FakeMessages()
    server = _chat_server(monkeypatch, tasks, messages)
    monkeypatch.setattr(
        bao,
        "_visible_agent_rows",
        lambda inner_server, user: [_agent("a1", "小写")],
    )
    calls: list[str] = []

    async def unsure_route(body, *, user, server):
        return {
            "decided": False,
            "needs_target": True,
            "reason": {"code": "ambiguous_project", "params": {}},
            "candidates": {"agents": [{"agent_id": "a1", "name": "小写"}]},
        }

    async def fake_dispatch(inner_server, user, *, agent_id, thread_id, text, **kwargs):
        calls.append(text)
        task = tasks.add("task-9", task_text=text, agent_id=agent_id)
        return {
            "agent_id": agent_id,
            "agent_name": "小写",
            "thread_id": "t1",
            "task": dict(task),
        }

    monkeypatch.setattr(bao, "route_task", unsure_route)
    monkeypatch.setattr(bao, "_dispatch_core", fake_dispatch)

    clarify = await bao.chat(
        bao.BaoChatBody(text="把发布流程跑一遍"), user=_user(), server=server
    )
    assert clarify["reply_code"] == "clarify"
    assert clarify["needs_target"] is True
    assert clarify["candidates"]["agents"][0]["name"] == "小写"

    resolved = await bao.chat(
        bao.BaoChatBody(text="派给小写"), user=_user(), server=server
    )
    assert resolved["intent"] == "target"
    assert resolved["reply_code"] == "dispatch"
    assert calls == ["把发布流程跑一遍"]


async def test_chat_explains_team_member_instead_of_dispatching(monkeypatch):
    tasks = _FakeTasks()
    messages = _FakeMessages()
    server = _chat_server(monkeypatch, tasks, messages)

    async def blocked_route(body, *, user, server):
        return {
            "decided": False,
            "needs_target": True,
            "reason": {
                "code": "team_member",
                "params": {"agent": "小写", "team": "军团"},
            },
        }

    monkeypatch.setattr(bao, "route_task", blocked_route)

    result = await bao.chat(
        bao.BaoChatBody(text="让小写处理一下"), user=_user(), server=server
    )

    assert result["reply_code"] == "team_member"
    assert "不能直接派活" in result["reply_text"]
    assert "军团" in result["reply_text"]
    assert "dispatch" not in result
