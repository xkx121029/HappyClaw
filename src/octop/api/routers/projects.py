"""Project management REST APIs.

Projects own a group of conversations (see ``infra/db/repos/projects.py``).
Per the workspace-ownership spec this surface is list / create / rename /
delete (default project protected) / list threads in a project.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from octop.api.deps import current_user, get_server
from octop.i18n import tr
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.utils.locale import resolve_request_locale
from octop.infra.utils.ulid import new_ulid

router = APIRouter()

_NAME_MAX = 80
_ROOT_DIR_MAX = 1024


class CreateProjectBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    root_dir: str | None = Field(default=None, max_length=_ROOT_DIR_MAX)


class RenameProjectBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)


def _clean_name(raw: str) -> str:
    name = " ".join(raw.split())
    if not name:
        raise OctopError(ErrorCode.SLASH_BAD_ARGS, "project name must not be blank")
    if len(name) > _NAME_MAX:
        raise OctopError(
            ErrorCode.SLASH_BAD_ARGS,
            f"project name must be at most {_NAME_MAX} characters",
        )
    return name


def _clean_root_dir(raw: str | None) -> str | None:
    if raw is None:
        return None
    root = raw.strip()
    if not root:
        return None
    if not Path(root).is_absolute():
        raise OctopError(
            ErrorCode.SLASH_BAD_ARGS,
            "project root_dir must be an absolute path",
        )
    return root


def _require_project(server: Any, project_id: str) -> Any:
    row = server.services.project_repo.get(project_id)
    if row is None:
        raise OctopError(ErrorCode.NOT_FOUND, f"project {project_id!r} not found")
    return row


def _project_payload(row: Any) -> dict[str, Any]:
    return {
        "project_id": row.project_id,
        "name": row.name,
        "root_dir": row.root_dir,
        "is_default": bool(row.is_default),
        "origin": row.origin,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("/projects", summary="List projects")
async def list_projects(
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> list[dict[str, Any]]:
    """List the local owner's projects, default project first, newest first."""
    rows = server.services.project_repo.list_for_user(int(user.id))
    return [_project_payload(row) for row in rows]


@router.post("/projects", summary="Create a project")
async def create_project(
    body: CreateProjectBody,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Create a named project, optionally rooted at a user-chosen folder.

    ``root_dir`` is stored as an absolute path reference; user files are never
    moved into ``{OCTOP_HOME}``.
    """
    name = _clean_name(body.name)
    root_dir = _clean_root_dir(body.root_dir)
    repo = server.services.project_repo
    if root_dir is not None:
        existing = repo.find_by_root_dir(int(user.id), root_dir)
        if existing is not None:
            raise OctopError(
                ErrorCode.SLASH_BAD_ARGS,
                f"root_dir is already linked to project {existing.name!r}",
                details={"project_id": existing.project_id},
            )
    row = repo.create(project_id=new_ulid(), user_id=int(user.id), name=name, root_dir=root_dir)
    return _project_payload(row)


@router.patch("/projects/{project_id}", summary="Rename a project")
async def rename_project(
    project_id: str,
    body: RenameProjectBody,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Rename a project. Conversations keep their ``project_id`` binding."""
    _require_project(server, project_id)
    server.services.project_repo.update(project_id, name=_clean_name(body.name))
    return _project_payload(server.services.project_repo.get(project_id))


@router.delete("/projects/{project_id}", summary="Delete a project")
async def delete_project(
    project_id: str,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Delete a non-default project and unbind its conversations.

    Threads only lose the ``project_id`` grouping; their workspace snapshots
    stay, so files and history remain reachable. The default project cannot be
    deleted.
    """
    row = _require_project(server, project_id)
    if row.is_default:
        raise OctopError(
            ErrorCode.PROJECT_DEFAULT_UNDELETABLE,
            "the default project cannot be deleted",
            details={"project_id": row.project_id},
        )
    threads_unbound = server.services.thread_repo.unbind_project(project_id)
    server.services.project_repo.delete(project_id)
    return {"ok": True, "threads_unbound": threads_unbound}


@router.get("/projects/{project_id}/threads", summary="List threads in a project")
async def list_project_threads(
    project_id: str,
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> list[dict[str, Any]]:
    """List conversations bound to a project across agents, pinned first."""
    _require_project(server, project_id)
    rows = server.services.thread_repo.list_by_project(project_id=project_id, limit=limit)
    untitled = tr("threads.new_chat_title", resolve_request_locale(request))
    return [
        {
            "thread_id": row.thread_id,
            "agent_id": row.agent_id,
            "title": row.title if isinstance(row.title, str) and row.title.strip() else untitled,
            "channel_type": row.channel_type,
            "last_active": row.last_active,
            "created_at": row.created_at,
            "pinned": bool(row.pinned),
            "project_id": row.project_id,
            "workspace_kind": row.workspace_kind,
            "workspace_dir": row.workspace_dir,
        }
        for row in rows
    ]
