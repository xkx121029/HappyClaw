"""Unit tests for the quick-chat tool guard (no workspace, no file tools)."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

from langchain.agents.middleware import ModelRequest
from langchain_core.messages import HumanMessage
from langgraph.config import var_child_runnable_config

from octop.infra.agents.middleware.quick_chat_guard import (
    QUICK_CHAT_HIDDEN_TOOLS,
    QUICK_CHAT_TOOL_ERROR,
    QuickChatGuardMiddleware,
)


@contextmanager
def _configurable(**kwargs: object):
    token = var_child_runnable_config.set({"configurable": kwargs})
    try:
        yield
    finally:
        var_child_runnable_config.reset(token)


class _ThreadRepo:
    def __init__(self, thread: object | None = None, *, raises: bool = False) -> None:
        self.thread = thread
        self.raises = raises

    def get(self, thread_id: str) -> object | None:
        if self.raises:
            raise RuntimeError("thread store unavailable")
        return self.thread


def _quick_thread() -> SimpleNamespace:
    return SimpleNamespace(workspace_kind="quick")


def _normal_thread() -> SimpleNamespace:
    return SimpleNamespace(workspace_kind=None)


def _request(tools: list[object]) -> ModelRequest:
    return ModelRequest(
        model=MagicMock(),
        messages=[HumanMessage(content="hi")],
        tools=tools,  # type: ignore[arg-type]
    )


def _names(request: ModelRequest) -> list[str]:
    names: list[str] = []
    for tool in request.tools or []:
        if isinstance(tool, dict):
            names.append(str(tool.get("name") or ""))
        else:
            names.append(str(getattr(tool, "name", "")))
    return names


def test_quick_thread_hides_file_and_shell_tools() -> None:
    middleware = QuickChatGuardMiddleware(thread_repo=_ThreadRepo(_quick_thread()))
    tools = [
        {"name": "read_file"},
        SimpleNamespace(name="write_file"),
        SimpleNamespace(name="delete"),
        SimpleNamespace(name="execute"),
        SimpleNamespace(name="present_file"),
        SimpleNamespace(name="current_time"),
        SimpleNamespace(name="web_search"),
    ]

    with _configurable(thread_id="thr_quick"):
        gated = middleware._gate(_request(tools))

    assert _names(gated) == ["current_time", "web_search"]
    assert "read_file" in QUICK_CHAT_HIDDEN_TOOLS


def test_normal_thread_keeps_every_tool() -> None:
    middleware = QuickChatGuardMiddleware(thread_repo=_ThreadRepo(_normal_thread()))
    tools = [SimpleNamespace(name="read_file"), SimpleNamespace(name="write_file")]

    with _configurable(thread_id="thr_normal"):
        request = _request(tools)
        gated = middleware._gate(request)

    assert gated is request


def test_quick_thread_blocks_direct_file_tool_calls() -> None:
    middleware = QuickChatGuardMiddleware(thread_repo=_ThreadRepo(_quick_thread()))
    tool_call = {"name": "write_file", "args": {"path": "x.txt"}, "id": "call_1"}

    with _configurable(thread_id="thr_quick"):
        blocked = middleware._blocked_result(
            SimpleNamespace(tool_call=tool_call)  # type: ignore[arg-type]
        )

    assert blocked is not None
    assert blocked.status == "error"
    assert blocked.tool_call_id == "call_1"
    assert str(blocked.content) == QUICK_CHAT_TOOL_ERROR


def test_normal_thread_allows_direct_file_tool_calls() -> None:
    middleware = QuickChatGuardMiddleware(thread_repo=_ThreadRepo(_normal_thread()))
    tool_call = {"name": "write_file", "args": {}, "id": "call_2"}

    with _configurable(thread_id="thr_normal"):
        blocked = middleware._blocked_result(
            SimpleNamespace(tool_call=tool_call)  # type: ignore[arg-type]
        )

    assert blocked is None


def test_lookup_failure_passes_tools_through() -> None:
    middleware = QuickChatGuardMiddleware(thread_repo=_ThreadRepo(raises=True))
    tools = [SimpleNamespace(name="read_file"), SimpleNamespace(name="current_time")]

    with _configurable(thread_id="thr_broken"):
        request = _request(tools)
        gated = middleware._gate(request)

    assert gated is request


def test_missing_thread_id_passes_tools_through() -> None:
    middleware = QuickChatGuardMiddleware(thread_repo=_ThreadRepo(_quick_thread()))
    tools = [SimpleNamespace(name="read_file")]

    with _configurable():
        request = _request(tools)
        gated = middleware._gate(request)

    assert gated is request
