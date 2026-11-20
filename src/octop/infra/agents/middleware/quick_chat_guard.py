"""快速对话（quick chat）的工具闸门。

快速对话不启用工作区：既不建会话目录，也不应该读写文件。这里在每次模型
调用前把文件/Shell 类工具从 ``request.tools`` 中移除，并在工具调用处兜底
拒绝，防止模型凭旧上下文强行调用。

判定失败（任何异常）一律放行，不得因为线程状态读取错误而阻断正常对话。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from octop.infra.agents.middleware.thread_artifacts import current_thread_id
from octop.infra.projects.session import QUICK_KIND

logger = logging.getLogger(__name__)

# Everything that reads or writes the filesystem, runs commands, or surfaces a
# file in the chat UI. Quick chats keep conversation-only tools.
QUICK_CHAT_HIDDEN_TOOLS = frozenset(
    {
        "ls",
        "read_file",
        "write_file",
        "edit_file",
        "delete",
        "move_file",
        "append_file",
        "glob",
        "grep",
        "execute",
        "bash",
        "read_env_file",
        "write_env_file",
        "present_file",
        "send_file_to_user",
    }
)

QUICK_CHAT_TOOL_ERROR = "快速对话不使用工作区，文件相关工具不可用。"


class _ThreadLookup(Protocol):
    def get(self, thread_id: str) -> Any | None: ...


def _tool_name(tool: Any) -> str:
    if isinstance(tool, dict):
        name = tool.get("name")
        if isinstance(name, str):
            return name
        fn = tool.get("function")
        if isinstance(fn, dict) and isinstance(fn.get("name"), str):
            return str(fn["name"])
        return ""
    return str(getattr(tool, "name", "") or "")


def _base_tool_name(name: str) -> str:
    return (name or "").strip().rsplit("/", 1)[-1]


class QuickChatGuardMiddleware(AgentMiddleware[Any, Any]):
    """Hide workspace tools while the current thread is a quick chat."""

    def __init__(self, *, thread_repo: _ThreadLookup) -> None:
        super().__init__()
        self._threads = thread_repo

    def _is_quick(self) -> bool:
        thread_id = current_thread_id()
        if not thread_id or "~" in thread_id:
            return False
        try:
            thread = self._threads.get(thread_id)
        except Exception:  # noqa: BLE001 - legacy schemas must not break chat
            logger.warning("quick chat guard lookup failed; passing through", exc_info=True)
            return False
        return (getattr(thread, "workspace_kind", None) or "") == QUICK_KIND

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        return handler(self._gate(request))

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        return await handler(self._gate(request))

    def _gate(self, request: ModelRequest[Any]) -> ModelRequest[Any]:
        try:
            if not self._is_quick():
                return request
            tools = request.tools or []
            kept = [
                tool
                for tool in tools
                if _base_tool_name(_tool_name(tool)) not in QUICK_CHAT_HIDDEN_TOOLS
            ]
            if len(kept) == len(tools):
                return request
            return request.override(tools=kept)
        except Exception:  # noqa: BLE001
            logger.warning("quick chat tool gate failed; passing request through", exc_info=True)
            return request

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        blocked = self._blocked_result(request)
        if blocked is not None:
            return blocked
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        blocked = self._blocked_result(request)
        if blocked is not None:
            return blocked
        return await handler(request)

    def _blocked_result(self, request: ToolCallRequest) -> ToolMessage | None:
        call = request.tool_call
        name = _base_tool_name(str(call.get("name") or ""))
        if name not in QUICK_CHAT_HIDDEN_TOOLS or not self._is_quick():
            return None
        return ToolMessage(
            content=QUICK_CHAT_TOOL_ERROR,
            tool_call_id=str(call.get("id") or ""),
            status="error",
        )


__all__ = [
    "QUICK_CHAT_HIDDEN_TOOLS",
    "QUICK_CHAT_TOOL_ERROR",
    "QuickChatGuardMiddleware",
]
