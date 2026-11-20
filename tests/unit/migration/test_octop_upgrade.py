"""Tests for the Octop -> HappyClaw projects upgrade and its mandatory choice."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from octop.config import OctopConfig
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import build_shared_services
from octop.infra.migration.octop_upgrade import (
    CHOICE_FILE,
    GROUP_CHANGES_FILE,
    CHOICE_DATA_FIRST,
    CHOICE_MERGE_DEFAULT,
    UpgradeChoiceRequired,
    apply_upgrade,
    rollback_upgrade,
    scan_install,
    verify_upgrade,
    write_plan_reports,
)
from octop.infra.utils.paths import PathLayout
from octop.infra.utils.ulid import new_ulid


def _services(tmp_path: Path):
    db = SqlitePool(tmp_path / "octop.db")
    run_migrations(db)
    return build_shared_services(db=db, paths=PathLayout(tmp_path), config=OctopConfig())


def _seed(
    tmp_path: Path,
    *,
    user_file: str | None = None,
    workspace: Path | None = None,
) -> tuple[object, int, str, str]:
    services = _services(tmp_path)
    user_id = services.repos.user_repo.create(
        username="owner", password_hash="x", role="admin"
    )
    agent_id = new_ulid()
    config = json.dumps({"workspace_dir": str(workspace)}) if workspace else None
    services.repos.agent_repo.create(
        agent_id=agent_id, user_id=user_id, name="Ops", config_json=config
    )
    workspace = workspace or (tmp_path / "agents" / agent_id)
    workspace.mkdir(parents=True, exist_ok=True)
    if user_file:
        (workspace / user_file).write_text("keep me", encoding="utf-8")
    thread_id = new_ulid()
    services.thread_repo.insert(
        thread_id=thread_id,
        agent_id=agent_id,
        user_id=user_id,
        channel_type="dashboard",
        session_key=f"sk-{thread_id}",
        title="first",
    )
    return services, user_id, agent_id, thread_id


def test_explicit_workspace_needs_no_choice(tmp_path: Path) -> None:
    external = tmp_path / "external-comic"
    services, _, _, thread_id = _seed(tmp_path, workspace=external)

    plan = scan_install(services=services, locale="zh")

    assert plan.requires_choice is False
    assert plan.thread_count == 1
    assert plan.group_changes[0].before == "external-comic"
    assert plan.group_changes[0].after_data_first == "external-comic"

    report = apply_upgrade(plan, services=services, choice=None, backup=False)
    assert report.ok
    thread = services.thread_repo.get(thread_id)
    assert thread is not None
    assert thread.project_id
    project = services.project_repo.get(thread.project_id)
    assert project is not None
    assert project.root_dir == str(external)
    assert verify_upgrade(plan, services=services) == []


def test_default_workspace_with_files_requires_explicit_choice(tmp_path: Path) -> None:
    services, _, agent_id, thread_id = _seed(tmp_path, user_file="notes.txt")

    plan = scan_install(services=services, locale="zh")
    assert plan.requires_choice is True
    change = plan.group_changes[0]
    assert change.before == "默认工作区"
    assert change.after_data_first == agent_id
    assert change.after_merge_default == "默认工作区"

    out = write_plan_reports(plan)
    markdown = (out / GROUP_CHANGES_FILE).read_text(encoding="utf-8")
    assert "数据优先后" in markdown
    assert "合并进默认项目后" in markdown

    with pytest.raises(UpgradeChoiceRequired):
        apply_upgrade(plan, services=services, choice=None, backup=False)
    assert services.thread_repo.get(thread_id).project_id is None  # type: ignore[union-attr]

    report = apply_upgrade(
        plan, services=services, choice=CHOICE_DATA_FIRST, backup=False
    )
    assert report.ok
    assert (tmp_path / "agents" / agent_id / "notes.txt").is_file()
    thread = services.thread_repo.get(thread_id)
    assert thread is not None
    assert thread.workspace_dir == str(tmp_path / "agents" / agent_id)
    choice = json.loads((out / CHOICE_FILE).read_text(encoding="utf-8"))
    assert choice["mode"] == CHOICE_DATA_FIRST


def test_merge_default_copies_and_rolls_back(tmp_path: Path) -> None:
    services, _, agent_id, thread_id = _seed(tmp_path, user_file="notes.txt")

    plan = scan_install(services=services, locale="zh")
    out = write_plan_reports(plan)
    report = apply_upgrade(
        plan, services=services, choice=CHOICE_MERGE_DEFAULT, backup=False
    )
    assert report.ok

    copied = tmp_path / "projects" / "default" / "legacy" / agent_id / "notes.txt"
    assert copied.is_file()
    thread = services.thread_repo.get(thread_id)
    assert thread is not None
    assert thread.workspace_dir == str(copied.parent)
    assert thread.project_id
    default = services.project_repo.get_default(services.owner.owner_id())
    assert default is not None and default.project_id == thread.project_id

    failures = rollback_upgrade(services=services, report_dir=out)
    assert failures == []
    assert not copied.is_file()
    assert services.thread_repo.get(thread_id).project_id is None  # type: ignore[union-attr]


def test_ensure_default_is_idempotent(tmp_path: Path) -> None:
    services = _services(tmp_path)
    user_id = services.repos.user_repo.create(
        username="owner", password_hash="x", role="admin"
    )
    first = services.project_repo.ensure_default(
        project_id="prj_one", user_id=user_id, name="默认工作区"
    )
    second = services.project_repo.ensure_default(
        project_id="prj_two", user_id=user_id, name="默认工作区"
    )
    assert first.project_id == second.project_id == "prj_one"
    assert len(services.project_repo.list_for_user(user_id)) == 1
