"""Workspace resolution and pooled-runtime limits for project conversations."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from octop.config import OctopConfig
from octop.infra.agents.manager import AgentManager
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import build_shared_services
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.utils.paths import PathLayout
from octop.infra.utils.ulid import new_ulid


def _setup(tmp_path: Path):
    db = SqlitePool(tmp_path / "octop.db")
    run_migrations(db)
    services = build_shared_services(
        db=db, paths=PathLayout(tmp_path), config=OctopConfig()
    )
    user_id = services.repos.user_repo.create(
        username="owner", password_hash="x", role="admin"
    )
    agent_id = new_ulid()
    services.repos.agent_repo.create(
        agent_id=agent_id, user_id=user_id, name="Ops"
    )
    manager = AgentManager(
        repos=services.repos,
        paths=PathLayout(tmp_path),
        config=OctopConfig(),
    )
    return services, manager, user_id, agent_id


def test_thread_workspace_uses_project_root(tmp_path: Path) -> None:
    services, manager, user_id, agent_id = _setup(tmp_path)
    root = tmp_path / "projects" / "prj_one"
    root.mkdir(parents=True)
    services.project_repo.create(
        project_id="prj_one", user_id=user_id, name="One", root_dir=str(root)
    )
    thread_id = new_ulid()
    services.thread_repo.insert(
        thread_id=thread_id,
        agent_id=agent_id,
        user_id=user_id,
        channel_type="dashboard",
        session_key=f"sk-{thread_id}",
        project_id="prj_one",
        workspace_kind="project",
        workspace_dir=str(root),
    )

    assert manager.thread_workspace_path(agent_id, thread_id) == root
    assert manager.pooled_agent_id(agent_id, root).startswith(f"{agent_id}~")


def test_thread_workspace_session_kind(tmp_path: Path) -> None:
    services, manager, user_id, agent_id = _setup(tmp_path)
    session_dir = tmp_path / "sessions" / "thr_x"
    session_dir.mkdir(parents=True)
    thread_id = new_ulid()
    services.thread_repo.insert(
        thread_id=thread_id,
        agent_id=agent_id,
        user_id=user_id,
        channel_type="dashboard",
        session_key=f"sk-{thread_id}",
        workspace_kind="session",
        workspace_dir=str(session_dir),
    )

    assert manager.thread_workspace_path(agent_id, thread_id) == session_dir


def test_thread_workspace_legacy_is_none(tmp_path: Path) -> None:
    services, manager, user_id, agent_id = _setup(tmp_path)
    thread_id = new_ulid()
    services.thread_repo.insert(
        thread_id=thread_id,
        agent_id=agent_id,
        user_id=user_id,
        channel_type="dashboard",
        session_key=f"sk-{thread_id}",
    )
    assert manager.thread_workspace_path(agent_id, thread_id) is None


@pytest.mark.asyncio
async def test_pool_limit_raises_busy(tmp_path: Path) -> None:
    _, manager, _, _ = _setup(tmp_path)
    manager._config = OctopConfig(
        project_runtime_max_instances=1,
        project_runtime_per_agent=1,
        project_runtime_queue_timeout_s=0.01,
    )
    manager._pool_last_used["other~1"] = time.monotonic()

    with pytest.raises(OctopError) as caught:
        await manager._acquire_pool_slot("any")
    assert caught.value.code == ErrorCode.AGENT_BUSY


@pytest.mark.asyncio
async def test_pool_slot_available_under_limit(tmp_path: Path) -> None:
    _, manager, _, _ = _setup(tmp_path)
    manager._config = OctopConfig(
        project_runtime_max_instances=2,
        project_runtime_per_agent=1,
        project_runtime_queue_timeout_s=0.01,
    )
    await manager._acquire_pool_slot("any")
