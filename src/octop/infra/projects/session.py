"""Conversations without a workspace, and turning one into a project.

Spec §3.2 (hybrid C): merely opening a conversation must not create a
directory. The first *new* file written in such a conversation binds the
thread to ``{OCTOP_HOME}/sessions/<thread_id>`` and moves that turn's freshly
created files there, so later turns run inside the conversation directory while
the expert's private home stays clean (and safe to publish).
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from octop.infra.utils.paths import PathLayout
from octop.infra.utils.thread_artifact import ThreadArtifact
from octop.infra.utils.ulid import new_ulid

logger = logging.getLogger(__name__)

SESSION_KIND = "session"
PROJECT_KIND = "project"
# Quick chat: a lightweight conversation with no workspace at all. The non-empty
# kind makes ``thread_needs_workspace()`` false, so no ``sessions/<id>`` folder
# is ever created and the file/shell tools are hidden by the guard middleware.
QUICK_KIND = "quick"

_SYSTEM_NAMES = frozenset(
    {"AGENTS.md", "SOUL.md", "IDENTITY.md", "MEMORY.md", "USER.md"}
)
_SYSTEM_DIRS = (".octop", "_builtin_skills", "inbound", "outbound")


class _ThreadLike(Protocol):
    thread_id: str
    project_id: str | None
    workspace_kind: str | None
    workspace_dir: str | None
    artifacts: tuple[ThreadArtifact, ...]


class _ThreadStore(Protocol):
    def get(self, thread_id: str) -> _ThreadLike | None: ...
    def set_workspace(
        self,
        thread_id: str,
        *,
        project_id: str | None,
        workspace_kind: str | None,
        workspace_dir: str | None,
    ) -> None: ...
    def set_artifacts(self, thread_id: str, artifacts: Sequence[ThreadArtifact]) -> None: ...


class _ProjectStore(Protocol):
    def create(
        self,
        *,
        project_id: str,
        user_id: int,
        name: str,
        root_dir: str | None = None,
        is_default: bool = False,
        origin: str = "manual",
    ) -> object: ...
    def find_by_root_dir(self, user_id: int, root_dir: str) -> object | None: ...
    def get(self, project_id: str) -> object | None: ...


def thread_needs_workspace(thread: _ThreadLike | None) -> bool:
    """True when this conversation has neither a project nor a directory."""
    if thread is None:
        return False
    return not (
        (thread.project_id or "").strip()
        or (thread.workspace_kind or "").strip()
        or (thread.workspace_dir or "").strip()
    )


def is_movable_workspace_file(path: Path, workspace_dir: Path) -> bool:
    """A user file the model created in the expert home during this turn."""
    try:
        rel = path.resolve().relative_to(workspace_dir.resolve())
    except (OSError, ValueError):
        return False
    if not rel.parts:
        return False
    if rel.parts[0] in _SYSTEM_DIRS:
        return False
    return rel.name not in _SYSTEM_NAMES


def bind_session_workspace(
    *,
    thread_repo: _ThreadStore,
    paths: PathLayout,
    thread_id: str,
    workspace_dir: Path,
    written: Sequence[Path],
) -> Path | None:
    """Move this turn's new files into ``sessions/<thread_id>`` and bind it.

    The thread row is only touched when at least one file actually moved, so a
    failed or empty turn leaves no trace.
    """
    thread = thread_repo.get(thread_id)
    if not thread_needs_workspace(thread):
        return None
    session_dir = paths.session_root(thread_id)
    moved: list[tuple[str, str]] = []
    for source in written:
        path = Path(source)
        if not path.is_file() or not is_movable_workspace_file(path, workspace_dir):
            continue
        try:
            rel = path.resolve().relative_to(workspace_dir.resolve())
        except (OSError, ValueError):
            continue
        target = session_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target))
        moved.append((str(path), str(target)))
    if not moved:
        return None

    thread_repo.set_workspace(
        thread_id,
        project_id=None,
        workspace_kind=SESSION_KIND,
        workspace_dir=str(session_dir),
    )
    _remap_artifacts(thread_repo, thread_id, moved)
    logger.info("Thread %s: session workspace enabled at %s", thread_id, session_dir)
    return session_dir


def _remap_artifacts(
    thread_repo: _ThreadStore,
    thread_id: str,
    moved: Sequence[tuple[str, str]],
) -> None:
    thread = thread_repo.get(thread_id)
    if thread is None or not thread.artifacts:
        return
    lookup = {source: target for source, target in moved}
    updated: list[ThreadArtifact] = []
    seen: set[str] = set()
    for entry in thread.artifacts:
        path = lookup.get(entry.path, entry.path)
        item = ThreadArtifact(path=path, agent_id=entry.agent_id)
        if item.dedupe_key() in seen:
            continue
        seen.add(item.dedupe_key())
        updated.append(item)
    if updated != list(thread.artifacts):
        thread_repo.set_artifacts(thread_id, updated)


def project_name_for(root: Path) -> str:
    return root.name or "project"


def convert_thread_to_project(
    *,
    thread_repo: _ThreadStore,
    project_repo: _ProjectStore,
    paths: PathLayout,
    thread_id: str,
    user_id: int,
    root_dir: str | Path | None = None,
    name: str | None = None,
) -> object:
    """Turn one conversation into the first thread of a project (in place).

    No message, artifact, or file moves: the conversation's directory becomes
    the project root and the thread keeps its id.
    """
    thread = thread_repo.get(thread_id)
    if thread is None:
        raise ValueError(f"thread not found: {thread_id}")
    if thread.project_id:
        existing = project_repo.get(thread.project_id)
        if existing is not None:
            return existing

    project_id = f"prj_{new_ulid()}"
    raw_root = str(root_dir).strip() if root_dir else ""
    if not raw_root:
        raw_root = (thread.workspace_dir or "").strip()
    if raw_root:
        root = Path(raw_root).expanduser()
    elif (thread.workspace_kind or "") == SESSION_KIND:
        root = paths.session_root(thread_id)
    else:
        root = paths.project_root(project_id)
    root.mkdir(parents=True, exist_ok=True)

    existing = project_repo.find_by_root_dir(user_id, str(root))
    if existing is not None:
        project = existing
    else:
        project = project_repo.create(
            project_id=project_id,
            user_id=user_id,
            name=(name or "").strip() or project_name_for(root),
            root_dir=str(root),
            origin="converted",
        )
    project_id = str(getattr(project, "project_id", "") or "")
    thread_repo.set_workspace(
        thread_id,
        project_id=project_id,
        workspace_kind=PROJECT_KIND,
        workspace_dir=None,
    )
    logger.info("Thread %s converted to project %s at %s", thread_id, project_id, root)
    return project
