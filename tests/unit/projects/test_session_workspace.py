"""Spec §3.2: a conversation without a workspace, and converting it to a project."""

from __future__ import annotations

import json
from pathlib import Path

from octop.config import OctopConfig
from octop.infra.agents.middleware.session_workspace import _target_path
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import build_shared_services
from octop.infra.projects.session import (
    bind_session_workspace,
    convert_thread_to_project,
    is_movable_workspace_file,
    thread_needs_workspace,
)
from octop.infra.utils.paths import PathLayout
from octop.infra.utils.ulid import new_ulid


def _seed(tmp_path: Path):
    db = SqlitePool(tmp_path / "octop.db")
    run_migrations(db)
    services = build_shared_services(db=db, paths=PathLayout(tmp_path), config=OctopConfig())
    user_id = services.repos.user_repo.create(
        username="owner", password_hash="x", role="admin"
    )
    agent_id = new_ulid()
    services.repos.agent_repo.create(
        agent_id=agent_id,
        user_id=user_id,
        name="Ops",
        config_json=json.dumps({"workspace_dir": str(tmp_path / "agents" / agent_id)}),
    )
    workspace = tmp_path / "agents" / agent_id
    workspace.mkdir(parents=True, exist_ok=True)
    thread_id = new_ulid()
    services.thread_repo.insert(
        thread_id=thread_id,
        agent_id=agent_id,
        user_id=user_id,
        channel_type="dashboard",
        session_key=f"sk-{thread_id}",
    )
    return services, user_id, agent_id, thread_id, workspace


def test_harness_root_relative_path_maps_into_workspace(tmp_path: Path) -> None:
    """Harness tools word paths against the backend root, not the host drive."""
    root = tmp_path / "home"
    workspace = root / "agents" / "main"
    workspace.mkdir(parents=True)

    assert _target_path({"file_path": "/agents/main/note.md"}, workspace, root) == (
        workspace / "note.md"
    ).resolve()
    assert _target_path({"file_path": "notes.md"}, workspace) == workspace / "notes.md"


def test_thread_without_workspace_is_pending(tmp_path: Path) -> None:
    services, _, _, thread_id, _ = _seed(tmp_path)
    assert thread_needs_workspace(services.thread_repo.get(thread_id)) is True

    services.thread_repo.set_workspace(
        thread_id, project_id=None, workspace_kind="session", workspace_dir="/tmp/x"
    )
    assert thread_needs_workspace(services.thread_repo.get(thread_id)) is False


def test_first_write_moves_file_and_binds_session(tmp_path: Path) -> None:
    services, _, _, thread_id, workspace = _seed(tmp_path)
    written = workspace / "reports" / "week.md"
    written.parent.mkdir(parents=True)
    written.write_text("done", encoding="utf-8")
    services.thread_repo.append_artifacts(thread_id, [str(written)])

    session_dir = bind_session_workspace(
        thread_repo=services.thread_repo,
        paths=services.paths,
        thread_id=thread_id,
        workspace_dir=workspace,
        written=[written],
    )

    assert session_dir == services.paths.session_root(thread_id)
    assert not written.exists()
    moved = session_dir / "reports" / "week.md"  # type: ignore[operator]
    assert moved.read_text(encoding="utf-8") == "done"
    thread = services.thread_repo.get(thread_id)
    assert thread is not None
    assert thread.workspace_kind == "session"
    assert thread.workspace_dir == str(session_dir)
    assert thread.project_id is None
    assert [a.path for a in thread.artifacts] == [str(moved)]


def test_no_new_file_means_no_directory(tmp_path: Path) -> None:
    services, _, _, thread_id, workspace = _seed(tmp_path)

    session_dir = bind_session_workspace(
        thread_repo=services.thread_repo,
        paths=services.paths,
        thread_id=thread_id,
        workspace_dir=workspace,
        written=[],
    )

    assert session_dir is None
    assert not services.paths.sessions_dir.exists()
    assert services.thread_repo.get(thread_id).workspace_kind is None  # type: ignore[union-attr]


def test_system_files_are_not_moved(tmp_path: Path) -> None:
    services, _, _, _, workspace = _seed(tmp_path)
    assert is_movable_workspace_file(workspace / "SOUL.md", workspace) is False
    assert is_movable_workspace_file(workspace / ".octop" / "x.db", workspace) is False
    assert is_movable_workspace_file(workspace / "inbound" / "a.png", workspace) is False
    assert is_movable_workspace_file(workspace / "notes.md", workspace) is True
    assert is_movable_workspace_file(tmp_path / "outside.md", workspace) is False


def test_convert_keeps_session_dir_and_history(tmp_path: Path) -> None:
    services, user_id, _, thread_id, workspace = _seed(tmp_path)
    (workspace / "notes.md").write_text("keep", encoding="utf-8")
    bind_session_workspace(
        thread_repo=services.thread_repo,
        paths=services.paths,
        thread_id=thread_id,
        workspace_dir=workspace,
        written=[workspace / "notes.md"],
    )

    project = convert_thread_to_project(
        thread_repo=services.thread_repo,
        project_repo=services.project_repo,
        paths=services.paths,
        thread_id=thread_id,
        user_id=user_id,
    )

    session_dir = services.paths.session_root(thread_id)
    assert project.root_dir == str(session_dir)  # type: ignore[attr-defined]
    assert (session_dir / "notes.md").read_text(encoding="utf-8") == "keep"
    thread = services.thread_repo.get(thread_id)
    assert thread is not None
    assert thread.project_id == project.project_id  # type: ignore[attr-defined]
    assert thread.workspace_kind == "project"

    again = convert_thread_to_project(
        thread_repo=services.thread_repo,
        project_repo=services.project_repo,
        paths=services.paths,
        thread_id=thread_id,
        user_id=user_id,
    )
    assert again.project_id == project.project_id  # type: ignore[attr-defined]
