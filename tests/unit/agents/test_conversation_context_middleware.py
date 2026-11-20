"""Unit tests for the per-turn conversation context block."""

from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from langchain.agents.middleware import ModelRequest
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.config import var_child_runnable_config

from octop.infra.agents.middleware.conversation_context import (
    ConversationContextMiddleware,
)


@contextmanager
def _configurable(**kwargs: object):
    token = var_child_runnable_config.set({"configurable": kwargs})
    try:
        yield
    finally:
        var_child_runnable_config.reset(token)


class _ThreadRepo:
    def __init__(self, thread: object | None = None, rows: list[object] | None = None) -> None:
        self.thread = thread
        self.rows = rows or []

    def get(self, thread_id: str) -> object | None:
        return self.thread

    def list_by_agent(self, *, agent_id: str, limit: int = 50) -> list[object]:
        return self.rows


class _ProjectRepo:
    def __init__(self, project: object | None = None) -> None:
        self.project = project

    def get(self, project_id: str) -> object | None:
        return self.project


class _Paths:
    def __init__(self, root: Path) -> None:
        self.root = root

    def project_root(self, project_id: str) -> Path:
        return self.root / "projects" / project_id

    def session_root(self, thread_id: str) -> Path:
        return self.root / "sessions" / thread_id


class _Cron:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def list_by_agent(self, agent_id: str) -> list[object]:
        return self.rows


def _middleware(
    *,
    workspace: Path,
    thread: object | None = None,
    rows: list[object] | None = None,
    project: object | None = None,
    cron: _Cron | None = None,
    ttl: float = 90.0,
) -> ConversationContextMiddleware:
    return ConversationContextMiddleware(
        thread_repo=_ThreadRepo(thread, rows),
        project_repo=_ProjectRepo(project),
        paths=_Paths(workspace),
        agent_id="55AK5S",
        agent_name="HappyClaw",
        workspace_dir=workspace,
        default_timezone="Asia/Shanghai",
        cron_manager=cron,
        ttl_seconds=ttl,
    )


def _request(system: str | None = "base") -> ModelRequest:
    return ModelRequest(
        model=MagicMock(),
        messages=[HumanMessage(content="hi")],
        system_message=SystemMessage(content=system) if system else None,
    )


def test_project_scope_and_recent_files_are_rendered(tmp_path: Path) -> None:
    workspace = tmp_path / "Octop"
    workspace.mkdir()
    (workspace / "agent_tools.py").write_text("x", encoding="utf-8")
    (workspace / "AGENTS.md").write_text("skip me", encoding="utf-8")
    thread = SimpleNamespace(project_id="prj_1", workspace_kind="project", workspace_dir=None)
    project = SimpleNamespace(project_id="prj_1", name="Octop", root_dir=str(workspace))
    mw = _middleware(workspace=workspace, thread=thread, project=project)

    with _configurable(thread_id="thr_1", locale="zh", timezone="Asia/Shanghai"):
        text = mw._block()

    assert "<conversation-context>" in text
    assert "expert: HappyClaw" in text
    assert "scope: project Octop" in text
    assert f"workspace: {workspace}" in text
    assert "agent_tools.py" in text
    assert "AGENTS.md" not in text
    assert "(Asia/Shanghai)" in text
    assert "<conversation-context-rules>" in text
    assert "不要只说「我记得你的项目」" in text


def test_recent_conversations_and_scheduled_jobs_are_rendered(tmp_path: Path) -> None:
    other = SimpleNamespace(
        thread_id="thr_2",
        title="侧栏文件预览修复",
        last_active=1760000000,
    )
    cron = _Cron(
        [
            SimpleNamespace(
                cron_id="cron_1",
                name="早报",
                trigger="0 9 * * *",
                enabled=1,
                next_run_at=1760050000,
            )
        ]
    )
    mw = _middleware(
        workspace=tmp_path,
        rows=[other],
        cron=cron,
    )

    with _configurable(thread_id="thr_1", locale="en"):
        text = mw._block()

    assert "recent conversations:" in text
    assert "「侧栏文件预览修复」" in text
    assert "scheduled:" in text
    assert "早报 — 0 9 * * *" in text
    assert "conversation-context-rules>" in text
    assert "I remember your project" in text


def test_session_thread_uses_session_root(tmp_path: Path) -> None:
    thread = SimpleNamespace(project_id=None, workspace_kind="session", workspace_dir=None)
    mw = _middleware(workspace=tmp_path, thread=thread)

    with _configurable(thread_id="thr_9", locale="en"):
        text = mw._block()

    assert "scope: temporary session workspace (no project)" in text
    assert f"workspace: {tmp_path / 'sessions' / 'thr_9'}" in text


def test_quick_chat_thread_has_no_workspace_or_recent_files(tmp_path: Path) -> None:
    (tmp_path / "notes.md").write_text("x", encoding="utf-8")
    thread = SimpleNamespace(project_id=None, workspace_kind="quick", workspace_dir=None)
    mw = _middleware(workspace=tmp_path, thread=thread)

    with _configurable(thread_id="thr_quick", locale="en"):
        text = mw._block()

    assert "scope: quick chat (no workspace)" in text
    assert "workspace:" not in text
    assert "recent files:" not in text
    assert "notes.md" not in text


def test_block_is_cached_within_ttl(tmp_path: Path) -> None:
    mw = _middleware(workspace=tmp_path, ttl=90.0)
    calls = {"n": 0}
    original = mw._render

    def counting(thread_id: str) -> str:
        calls["n"] += 1
        return original(thread_id)

    mw._render = counting  # type: ignore[method-assign]

    with _configurable(thread_id="thr_1", locale="en"):
        first = mw._block()
        second = mw._block()

    assert first == second
    assert calls["n"] == 1


def test_ttl_expiry_rebuilds_block(tmp_path: Path) -> None:
    mw = _middleware(workspace=tmp_path, ttl=0.0)
    calls = {"n": 0}
    original = mw._render

    def counting(thread_id: str) -> str:
        calls["n"] += 1
        return original(thread_id)

    mw._render = counting  # type: ignore[method-assign]

    with _configurable(thread_id="thr_1", locale="en"):
        mw._block()
        time.sleep(0.001)
        mw._block()

    assert calls["n"] == 2


def test_wrap_model_call_appends_block_without_mutating_request(tmp_path: Path) -> None:
    mw = _middleware(workspace=tmp_path)
    request = _request("base")
    captured: list[ModelRequest] = []

    def handler(req: ModelRequest) -> object:
        captured.append(req)
        return object()

    with _configurable(thread_id="thr_1", locale="en"):
        mw.wrap_model_call(request, handler)

    forwarded = captured[0]
    assert forwarded is not request
    assert forwarded.system_message is not None
    assert forwarded.system_message.text.startswith("base\n\n<conversation-context>")
    assert request.system_message is not None
    assert request.system_message.text == "base"


def test_wrap_model_call_works_without_existing_system_message(tmp_path: Path) -> None:
    mw = _middleware(workspace=tmp_path)
    captured: list[ModelRequest] = []

    def handler(req: ModelRequest) -> object:
        captured.append(req)
        return object()

    with _configurable(thread_id="thr_1", locale="en"):
        mw.wrap_model_call(_request(None), handler)

    assert captured[0].system_message is not None
    assert captured[0].system_message.text.startswith("<conversation-context>")
