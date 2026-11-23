"""Admin backup / restore API."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from happyclaw.api.common.content_disposition import content_disposition
from happyclaw.api.deps import get_server, require_permission
from happyclaw.infra.backup.auto import (
    AUTO_BACKUP_JOB_ID,
    hold_backup_lock,
    raise_if_backup_busy,
    run_auto_backup,
    update_server_backup_config,
)
from happyclaw.infra.backup.service import (
    AutoBackupSettings,
    BackupSelection,
    BackupService,
)
from happyclaw.infra.backup.store import normalize_backup_filename
from happyclaw.infra.config_service import LocalConfigService
from happyclaw.infra.db.repos.audit import ACTOR_ADMIN
from happyclaw.infra.errors import ErrorCode, HappyclawError

logger = logging.getLogger(__name__)

router = APIRouter()


class AutoBackupSettingsBody(BaseModel):
    auto_enabled: bool = False
    schedule: str = Field(default="cron:0 4 * * *", min_length=1)
    retention_count: int = Field(default=7, ge=1, le=365)
    include_config: bool = True
    include_workspaces: bool = True
    include_skill_packages: bool = True
    include_plugins: bool = True
    include_knowledge: bool = True
    include_chats: bool = True


class CreateBackupBody(BaseModel):
    include_config: bool = True
    include_workspaces: bool = True
    include_skill_packages: bool = True
    include_plugins: bool = True
    include_knowledge: bool = True
    include_chats: bool = True


def _agent_rows(server: Any) -> list[Any]:
    assert server.app_runtime is not None
    return cast(list[Any], server.app_runtime.agent_registry.list_rows())


def _cron_scheduled(server: Any) -> bool:
    runtime = getattr(server, "app_runtime", None)
    if runtime is not None and runtime.cron_manager is not None:
        return runtime.cron_manager.has_system_job(AUTO_BACKUP_JOB_ID)
    return False


async def _rehydrate_runtime_after_restore(server: Any) -> None:
    """Sync restored providers/agents, IM channels, and cron (no process restart)."""
    runtime = getattr(server, "app_runtime", None)
    if runtime is None:
        return
    registry = getattr(runtime, "agent_registry", None)
    if registry is not None:
        try:
            await registry.on_provider_changed()
        except Exception:
            logger.exception("post-restore provider/agent rehydrate failed")
    gateway = getattr(runtime, "gateway", None)
    if gateway is not None:
        try:
            await gateway.reload_channels_from_db()
        except Exception:
            logger.exception("post-restore channel rehydrate failed")
    cron_manager = getattr(runtime, "cron_manager", None)
    if cron_manager is not None:
        try:
            await cron_manager.reload_from_db()
        except Exception:
            logger.exception("post-restore cron rehydrate failed")


def build_backup_service(server: Any) -> BackupService:
    """Construct a :class:`BackupService` bound to *server*'s runtime."""
    assert server.services is not None

    async def _rehydrate() -> None:
        await _rehydrate_runtime_after_restore(server)

    def _audit(**kwargs: Any) -> None:
        server.services.audit_repo.write(**kwargs)

    return BackupService(
        paths=server.paths,
        db_pool=server.services.db,
        db_config=server.services.config.database,
        agent_rows_provider=lambda: _agent_rows(server),
        cron_scheduled_provider=lambda: _cron_scheduled(server),
        audit_writer=_audit,
        runtime_rehydrator=_rehydrate,
        config_service=LocalConfigService(
            server.paths.config, preloaded=getattr(server, "config", None)
        ),
    )


def get_backup_service(server: Any = Depends(get_server)) -> BackupService:
    return build_backup_service(server)


def _unlink_quiet(path: Any) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("failed to remove ephemeral backup %s", path, exc_info=True)


@router.get("/backup/list", summary="List stored backup archives")
async def list_backups(
    _: Any = Depends(require_permission("backup")),
    service: BackupService = Depends(get_backup_service),
) -> dict[str, Any]:
    """List ``.tar.gz`` files in ``~/.octop/backups/``."""
    files = await service.alist_backups()
    return {
        "dir": str(service._paths.backups_dir),
        "items": [f.to_dict() for f in files],
    }


@router.get("/backup/status", summary="Whether a backup or restore is in progress")
async def get_backup_status(
    _: Any = Depends(require_permission("backup")),
) -> dict[str, Any]:
    """Return lock state for dashboard busy UI across navigation / refresh."""
    return BackupService.status()


@router.get("/backup/auto", summary="Get automatic backup settings")
async def get_auto_backup_settings(
    _: Any = Depends(require_permission("backup")),
    service: BackupService = Depends(get_backup_service),
) -> dict[str, Any]:
    """Return auto-backup config and whether the system job is currently scheduled."""
    return service.get_auto_settings()


@router.put("/backup/auto", summary="Update automatic backup settings")
async def put_auto_backup_settings(
    body: AutoBackupSettingsBody,
    _: Any = Depends(require_permission("backup")),
    server: Any = Depends(get_server),
    service: BackupService = Depends(get_backup_service),
) -> dict[str, Any]:
    """Persist auto-backup settings and reschedule the in-process system job."""
    settings = AutoBackupSettings(**body.model_dump())
    backup = settings.to_config()
    update_server_backup_config(server, backup)
    return {"ok": True, **service.get_auto_settings()}


@router.post("/backup/auto/run", summary="Run automatic backup now")
async def run_auto_backup_now(
    _: Any = Depends(require_permission("backup")),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Create one automatic backup immediately (same path as the scheduled job)."""
    raise_if_backup_busy()
    entry = await run_auto_backup(server)
    if entry is None:
        raise HappyclawError(
            ErrorCode.BACKUP_IN_PROGRESS,
            "auto backup skipped (busy or runtime not ready)",
        )
    return {"ok": True, "item": entry.to_dict()}


@router.post("/backup/create", summary="Create backup and save to backups dir")
async def create_backup(
    body: CreateBackupBody | None = None,
    _: Any = Depends(require_permission("backup")),
    service: BackupService = Depends(get_backup_service),
) -> dict[str, Any]:
    """Create a selected-content backup and persist it under ``backups_dir``."""
    options = body or CreateBackupBody()
    selection = BackupSelection(**options.model_dump())
    entry = await service.acreate_backup(selection)
    return {"ok": True, "item": entry.to_dict()}


@router.get(
    "/backup/files/{filename}",
    summary="Download a stored backup archive",
    response_class=FileResponse,
)
async def download_backup_file(
    filename: str,
    _: Any = Depends(require_permission("backup")),
    service: BackupService = Depends(get_backup_service),
) -> FileResponse:
    """Stream a backup file from ``backups_dir`` without loading it into memory."""
    path = service.resolve_backup_path(filename)
    return FileResponse(
        path,
        media_type="application/gzip",
        filename=normalize_backup_filename(filename),
        headers={"Content-Disposition": content_disposition(normalize_backup_filename(filename))},
    )


@router.post("/backup/files/{filename}/restore", summary="Restore from stored backup")
async def restore_backup_file(
    filename: str,
    restore_config: bool = Query(default=True),
    user: Any = Depends(require_permission("backup")),
    service: BackupService = Depends(get_backup_service),
) -> dict[str, Any]:
    """Restore database and workspaces from a file in ``backups_dir``.

    After the archive is applied, providers/agents, IM channels, and cron jobs
    are reloaded in-process so experts, messaging, and schedules can run without
    a full service restart.
    """
    result = await service.arestore_backup(
        filename,
        restore_config=restore_config,
        owner_user_id=int(user.id),
        actor=getattr(user, "username", None) or ACTOR_ADMIN,
    )
    return result


@router.delete("/backup/files/{filename}", summary="Delete a stored backup", status_code=204)
async def remove_backup_file(
    filename: str,
    _: Any = Depends(require_permission("backup")),
    service: BackupService = Depends(get_backup_service),
) -> None:
    """Remove a backup archive from ``backups_dir``."""
    await service.adelete_backup(filename)


@router.get(
    "/backup/export",
    summary="Download selected system backup (ephemeral)",
    response_class=FileResponse,
)
async def export_backup(
    background_tasks: BackgroundTasks,
    include_config: bool = Query(default=True),
    include_workspaces: bool = Query(default=True),
    include_skill_packages: bool = Query(default=True),
    include_plugins: bool = Query(default=True),
    include_knowledge: bool = Query(default=True),
    include_chats: bool = Query(default=True),
    _: Any = Depends(require_permission("backup")),
    service: BackupService = Depends(get_backup_service),
) -> FileResponse:
    """Create and stream a backup without persisting to ``backups_dir``."""
    selection = BackupSelection(
        include_config=include_config,
        include_workspaces=include_workspaces,
        include_skill_packages=include_skill_packages,
        include_plugins=include_plugins,
        include_knowledge=include_knowledge,
        include_chats=include_chats,
    )
    async with hold_backup_lock("export"):
        tmp_path, filename = await asyncio.to_thread(service.export_backup, selection)
    background_tasks.add_task(_unlink_quiet, tmp_path)
    return FileResponse(
        tmp_path,
        media_type="application/gzip",
        filename=filename,
        headers={"Content-Disposition": content_disposition(filename)},
    )


@router.post("/backup/import", summary="Upload backup archive to backups dir")
async def import_backup(
    file: UploadFile = File(...),  # noqa: B008
    _: Any = Depends(require_permission("backup")),
    service: BackupService = Depends(get_backup_service),
) -> dict[str, Any]:
    """Save an uploaded ``.tar.gz`` into ``backups_dir`` (does not restore)."""
    raw = await file.read()
    name = file.filename or "uploaded-backup.tar.gz"
    entry = await service.aimport_backup(name, raw)
    return {"ok": True, "item": entry.to_dict()}
