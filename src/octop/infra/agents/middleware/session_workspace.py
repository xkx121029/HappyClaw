"""Remember the first files a conversation creates while it has no workspace.

Spec §3.2 (hybrid C). Reads stay untouched — the expert home is where skills and
notes legitimately live. A *new* file write, however, means the conversation has
started producing user data; the manager moves those files into
``sessions/<thread_id>`` after the turn and binds the thread there.

Collection is intentionally passive: the middleware never blocks a tool and
never creates a directory.
"""

from __future__ import annotations

import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from octop.infra.agents.middleware.thread_artifacts import current_thread_id
from octop.infra.projects.session import thread_needs_workspace

_WRITE_TOOL = "write_file"


class _ThreadLookup(Protocol):
    def get(self, thread_id: str) -> Any | None: ...


def _base_tool_name(name: str) -> str:
    return (name or "").strip().rsplit("/", 1)[-1]


def _target_path(args: Any, workspace_dir: Path, root_dir: Path | None = None) -> Path | None:
    if not isinstance(args, dict):
        return None
    raw = args.get("file_path") or args.get("path")
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip().replace("\\", "/")
    candidate = Path(text).expanduser()
    if candidate.is_absolute() and candidate.drive:
        return candidate
    if text.startswith("/") and root_dir is not None:
        # The harness words tool paths relative to the backend root, so on
        # Windows a write arrives as "/agents/<id>/note.md" instead of a drive
        # path. Map it with the same helper the backend uses so both agree.
        from octop_harness.backends.local_shell import (  # noqa: PLC0415
            map_virtual_abs_path,
        )

        return Path(map_virtual_abs_path(text, root_dir, workspace_dir=workspace_dir))
    return workspace_dir / text.lstrip("/")


class SessionWorkspaceMiddleware(AgentMiddleware[Any, Any]):
    """Collect newly created files for threads that still have no workspace."""

    def __init__(
        self,
        *,
        thread_repo: _ThreadLookup,
        workspace_dir: Path,
        root_dir: Path | None = None,
    ) -> None:
        super().__init__()
        self._threads = thread_repo
        self._workspace_dir = workspace_dir.expanduser()
        self._root_dir = root_dir.expanduser() if root_dir is not None else None
        self._pending: dict[str, list[Path]] = {}
        self._lock = threading.Lock()

    def take(self, thread_id: str) -> list[Path]:
        with self._lock:
            return self._pending.pop(thread_id, [])

    def _pending_thread(self, thread_id: str) -> bool:
        if not thread_id or "~" in thread_id:
            return False
        try:
            thread = self._threads.get(thread_id)
        except Exception:  # pragma: no cover - legacy schemas
            return False
        return thread_needs_workspace(thread)

    def _note(self, thread_id: str, path: Path) -> None:
        with self._lock:
            bucket = self._pending.setdefault(thread_id, [])
            if path not in bucket:
                bucket.append(path)

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        thread_id, target, existed = self._inspect(request)
        result = handler(request)
        self._record(thread_id, target, existed, result)
        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        thread_id, target, existed = self._inspect(request)
        result = await handler(request)
        self._record(thread_id, target, existed, result)
        return result

    def _inspect(self, request: ToolCallRequest) -> tuple[str, Path | None, bool]:
        call = request.tool_call
        if _base_tool_name(str(call.get("name") or "")) != _WRITE_TOOL:
            return "", None, True
        thread_id = current_thread_id()
        if not self._pending_thread(thread_id):
            return "", None, True
        target = _target_path(call.get("args"), self._workspace_dir, self._root_dir)
        if target is None:
            return "", None, True
        try:
            existed = target.exists()
        except OSError:  # pragma: no cover - unreadable path
            return "", None, True
        return thread_id, target, existed

    def _record(
        self,
        thread_id: str,
        target: Path | None,
        existed: bool,
        result: ToolMessage | Command[Any],
    ) -> None:
        if not thread_id or target is None or existed:
            return
        if not isinstance(result, ToolMessage) or getattr(result, "status", None) == "error":
            return
        self._note(thread_id, target)


__all__ = ["SessionWorkspaceMiddleware"]
