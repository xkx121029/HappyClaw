"""Resolve the working directory for a conversation.

Order (see specs/workspace-ownership-restructure/spec.md §2.4):

1. ``thread.workspace_dir`` snapshot, when set. This wins over the project
   root because a merged upgrade points it at ``projects/default/legacy/<id>``
   where the checkpoints actually live.
2. ``thread.project_id`` → the project's ``root_dir`` (or its default path).
3. ``workspace_kind == "session"`` → ``{OCTOP_HOME}/sessions/<thread_id>``.
4. None: the conversation has no workspace yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from octop.infra.utils.paths import PathLayout

SESSION_KIND = "session"
PROJECT_KIND = "project"
LEGACY_KIND = "legacy"
NONE_KIND = "none"


class _ThreadLike(Protocol):
    thread_id: str
    project_id: str | None
    workspace_kind: str | None
    workspace_dir: str | None


class _ProjectLookup(Protocol):
    def get(self, project_id: str) -> object | None: ...


@dataclass(frozen=True)
class ResolvedWorkspace:
    path: Path | None
    kind: str
    project_id: str | None = None

    @property
    def exists(self) -> bool:
        return self.path is not None and self.path.is_dir()


def resolve_thread_workspace(
    *,
    thread: _ThreadLike,
    project_repo: _ProjectLookup,
    paths: PathLayout,
) -> ResolvedWorkspace:
    snapshot = (thread.workspace_dir or "").strip()
    kind = (thread.workspace_kind or "").strip()

    if thread.project_id:
        project = project_repo.get(thread.project_id)
        root = getattr(project, "root_dir", None) if project is not None else None
        if snapshot:
            return ResolvedWorkspace(Path(snapshot), kind or PROJECT_KIND, thread.project_id)
        path = Path(root) if root else paths.project_root(thread.project_id)
        return ResolvedWorkspace(path, kind or PROJECT_KIND, thread.project_id)

    if snapshot:
        return ResolvedWorkspace(Path(snapshot), kind or LEGACY_KIND, None)
    if kind == SESSION_KIND:
        return ResolvedWorkspace(paths.session_root(thread.thread_id), SESSION_KIND, None)
    return ResolvedWorkspace(None, NONE_KIND, None)
