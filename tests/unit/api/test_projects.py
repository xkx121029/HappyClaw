"""Unit tests for the project management endpoints."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from octop.api.routers import projects
from octop.infra.errors import ErrorCode, OctopError


def _project(
    project_id: str = "p1",
    *,
    name: str = "Alpha",
    root_dir: str | None = "E:/work/alpha",
    is_default: bool = False,
):
    return SimpleNamespace(
        project_id=project_id,
        user_id=7,
        name=name,
        root_dir=root_dir,
        is_default=is_default,
        origin="manual",
        created_at=100,
        updated_at=200,
    )


def _thread(thread_id: str, title: str | None):
    return SimpleNamespace(
        thread_id=thread_id,
        agent_id="a1",
        title=title,
        channel_type="dashboard",
        last_active=300,
        created_at=100,
        pinned=False,
        project_id="p1",
        workspace_kind="project",
        workspace_dir="E:/work/alpha",
    )


def _server(project_row=None):
    server = MagicMock()
    server.services.project_repo.get.return_value = project_row
    return server


def _user():
    return SimpleNamespace(id=7, is_admin=True, locale="zh")


async def test_list_projects_returns_payloads():
    server = _server()
    server.services.project_repo.list_for_user.return_value = [
        _project("p0", name="默认项目", root_dir=None, is_default=True),
        _project("p1"),
    ]

    payload = await projects.list_projects(user=_user(), server=server)

    assert [row["project_id"] for row in payload] == ["p0", "p1"]
    assert payload[0]["is_default"] is True
    assert payload[0]["root_dir"] is None
    server.services.project_repo.list_for_user.assert_called_once_with(7)


async def test_create_project_generates_id_and_stores_root():
    server = _server()
    server.services.project_repo.find_by_root_dir.return_value = None
    server.services.project_repo.create.return_value = _project("p9")

    payload = await projects.create_project(
        projects.CreateProjectBody(name="  Alpha  ", root_dir="E:/work/alpha"),
        user=_user(),
        server=server,
    )

    assert payload["project_id"] == "p9"
    args, kwargs = server.services.project_repo.create.call_args
    assert kwargs["name"] == "Alpha"
    assert kwargs["root_dir"] == "E:/work/alpha"
    assert kwargs["user_id"] == 7
    assert kwargs["project_id"]


async def test_create_project_blank_root_dir_treated_as_none():
    server = _server()
    server.services.project_repo.create.return_value = _project("p9", root_dir=None)

    await projects.create_project(
        projects.CreateProjectBody(name="Alpha", root_dir="   "),
        user=_user(),
        server=server,
    )

    assert server.services.project_repo.create.call_args.kwargs["root_dir"] is None


async def test_create_project_rejects_relative_root_dir():
    with pytest.raises(OctopError) as exc:
        projects._clean_root_dir("relative/path")
    assert exc.value.code == ErrorCode.SLASH_BAD_ARGS


async def test_create_project_rejects_duplicate_root_dir():
    server = _server()
    server.services.project_repo.find_by_root_dir.return_value = _project("p1")

    with pytest.raises(OctopError) as exc:
        await projects.create_project(
            projects.CreateProjectBody(name="Beta", root_dir="E:/work/alpha"),
            user=_user(),
            server=server,
        )
    assert exc.value.code == ErrorCode.SLASH_BAD_ARGS
    assert exc.value.details == {"project_id": "p1"}
    server.services.project_repo.create.assert_not_called()


async def test_rename_project_updates_and_returns_fresh_row():
    server = _server(_project("p1"))
    server.services.project_repo.get.side_effect = None
    server.services.project_repo.get.return_value = _project("p1", name="Renamed")

    payload = await projects.rename_project(
        "p1",
        projects.RenameProjectBody(name="  Renamed "),
        user=_user(),
        server=server,
    )

    assert payload["name"] == "Renamed"
    server.services.project_repo.update.assert_called_once_with("p1", name="Renamed")


async def test_rename_project_missing_raises_not_found():
    server = _server(None)
    with pytest.raises(OctopError) as exc:
        await projects.rename_project(
            "missing",
            projects.RenameProjectBody(name="X"),
            user=_user(),
            server=server,
        )
    assert exc.value.code == ErrorCode.NOT_FOUND


async def test_delete_project_protects_default():
    server = _server(_project("p0", is_default=True))
    with pytest.raises(OctopError) as exc:
        await projects.delete_project("p0", user=_user(), server=server)
    assert exc.value.code == ErrorCode.PROJECT_DEFAULT_UNDELETABLE
    server.services.project_repo.delete.assert_not_called()


async def test_delete_project_unbinds_threads_then_deletes():
    server = _server(_project("p1"))
    server.services.thread_repo.unbind_project.return_value = 3

    payload = await projects.delete_project("p1", user=_user(), server=server)

    assert payload == {"ok": True, "threads_unbound": 3}
    server.services.thread_repo.unbind_project.assert_called_once_with("p1")
    server.services.project_repo.delete.assert_called_once_with("p1")


async def test_delete_project_missing_raises_not_found():
    server = _server(None)
    with pytest.raises(OctopError) as exc:
        await projects.delete_project("missing", user=_user(), server=server)
    assert exc.value.code == ErrorCode.NOT_FOUND


async def test_list_project_threads_falls_back_to_untitled():
    server = _server(_project("p1"))
    server.services.thread_repo.list_by_project.return_value = [
        _thread("t1", "有标题"),
        _thread("t2", "   "),
    ]

    payload = await projects.list_project_threads(
        "p1",
        request=SimpleNamespace(headers={}),
        limit=50,
        user=_user(),
        server=server,
    )

    assert [row["thread_id"] for row in payload] == ["t1", "t2"]
    assert payload[0]["title"] == "有标题"
    assert payload[1]["title"]  # localized untitled placeholder, non-empty
    server.services.thread_repo.list_by_project.assert_called_once_with(
        project_id="p1", limit=50
    )
