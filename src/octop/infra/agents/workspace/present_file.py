"""Built-in tool that opens a workspace file in the dashboard chat dock.

The dashboard watches for ``present_file`` tool results and opens the path in
its side panel (text / Markdown / HTML preview). Paths are always returned
workspace-relative so the panel reads through the *current* conversation
scope (project directory or ``sessions/<thread_id>``), never the expert home.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

from langchain_core.tools import StructuredTool
from pydantic import Field

if TYPE_CHECKING:
    from octop_harness.backends.workspace import BackendWorkspace

PRESENT_FILE_TOOL = "present_file"

_DESCRIPTION = (
    "Show a file from the current conversation workspace to the user in the "
    "chat side panel (file view, Markdown and HTML preview) so they can look "
    "at it without leaving the conversation. Call it right after creating a "
    "report, page or note the user should see, or when they ask to look at an "
    "existing file. The file must already exist inside the current workspace; "
    "this tool only presents it, it never creates or edits content."
)


def _workspace_relative_path(workspace: BackendWorkspace, raw: str) -> str:
    """Map an agent-supplied path onto a workspace-relative POSIX path."""
    resolved = Path(workspace.resolve_path(raw))
    try:
        return resolved.resolve().relative_to(workspace.workspace_dir.resolve()).as_posix()
    except ValueError:
        pass
    # Sandboxed backends resolve to a virtual ``/…`` key instead of a host path.
    if getattr(workspace.backend, "sandbox_fs", False) and resolved.is_absolute():
        return resolved.as_posix().lstrip("/")
    raise PermissionError(f"path {raw!r} is outside the current conversation workspace")


def build_present_file_tool(workspace: BackendWorkspace) -> StructuredTool:
    """Bind ``present_file`` to one agent workspace (base or pooled)."""

    def present_file(
        path: Annotated[
            str,
            Field(description="Workspace file to show, e.g. 'report.html' or 'notes/summary.md'."),
        ],
    ) -> str:
        def payload(status: str, **extra: Any) -> str:
            return json.dumps({"status": status, **extra}, ensure_ascii=False)

        raw = (path or "").strip()
        if not raw:
            return payload("error", error="path is required")
        try:
            relative = _workspace_relative_path(workspace, raw)
        except (PermissionError, OSError, ValueError) as exc:
            return payload("error", error=str(exc))
        if not relative or relative.endswith("/"):
            return payload("error", error=f"{raw} is not a file")
        if not workspace.exists(relative):
            return payload("error", error=f"{relative} does not exist in the current workspace")
        return payload("ok", path=relative)

    return StructuredTool.from_function(
        func=present_file,
        name=PRESENT_FILE_TOOL,
        description=_DESCRIPTION,
    )
