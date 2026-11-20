"""Resolve agent ``workspace_dir`` for API handlers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast


def resolve_agent_workspace_dir(
    server: Any, agent_id: str, thread_id: str | None = None
) -> Path:
    """Prefer the conversation's project directory, then the agent workspace.

    ``thread_id`` lets file/terminal/history handlers follow a conversation into
    its project or session directory; without it the expert's base workspace is
    used, which is also the pre-migration behavior.
    """
    runtime = getattr(server, "app_runtime", None)
    registry = getattr(runtime, "agent_registry", None) if runtime is not None else None
    if thread_id and registry is not None and hasattr(registry, "thread_workspace_path"):
        resolved = registry.thread_workspace_path(agent_id, thread_id)
        if resolved is not None:
            return cast(Path, resolved)
    if registry is not None and hasattr(registry, "resolve_workspace_dir"):
        return cast(Path, registry.resolve_workspace_dir(agent_id))
    paths = getattr(server, "paths", None) or server.services.paths
    return cast(Path, paths.ensure_agent_workspace(agent_id))


__all__ = ["resolve_agent_workspace_dir"]
