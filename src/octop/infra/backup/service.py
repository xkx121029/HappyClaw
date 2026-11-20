"""Service layer for backup and restore operations.

The router stays thin: it parses HTTP, asks :class:`BackupService` to do the
work, and maps the result to a response.  All orchestration — lock handling,
worker-thread offload, audit writes — lives here so the same operations can be
reused by CLI or cron without copying code.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from octop.config import BackupConfig, DatabaseConfig
from octop.infra.backup.auto import (
    AUTO_BACKUP_JOB_ID,
    backup_config_from_payload,
    backup_status_payload,
    hold_backup_lock,
    raise_if_backup_busy,
    run_auto_backup,
    update_server_backup_config,
)
from octop.infra.backup.store import (
    BackupFileInfo,
    delete_backup_file,
    list_backup_files,
    normalize_backup_filename,
    place_backup_file,
    resolve_backup_path,
    write_backup_file,
)
from octop.infra.backup.system_archive import create_system_backup, restore_system_backup
from octop.infra.config_service import LocalConfigService
from octop.infra.db.repos.audit import ACTOR_ADMIN

if TYPE_CHECKING:
    from octop.infra.db.pool import DatabasePool
    from octop.infra.utils.paths import PathLayout

logger = logging.getLogger(__name__)

_MAX_IMPORT_BYTES = 512 * 1024 * 1024


@dataclass(slots=True)
class BackupSelection:
    """Which parts of the system a backup or export should include."""

    include_config: bool = True
    include_workspaces: bool = True
    include_skill_packages: bool = True
    include_plugins: bool = True
    include_knowledge: bool = True
    include_chats: bool = True


@dataclass(slots=True)
class AutoBackupSettings:
    """Automatic backup configuration as seen by the API."""

    auto_enabled: bool = False
    schedule: str = "cron:0 4 * * *"
    retention_count: int = 7
    include_config: bool = True
    include_workspaces: bool = True
    include_skill_packages: bool = True
    include_plugins: bool = True
    include_knowledge: bool = True
    include_chats: bool = True

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> "AutoBackupSettings":
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})

    def to_config(self) -> BackupConfig:
        return backup_config_from_payload(self.__dict__)


class BackupService:
    """Coordinate backup / restore operations for one server instance.

    The service owns the lock, the worker-thread offload, and the audit write.
    It does **not** own HTTP semantics: the router maps errors and shapes the
    response body.
    """

    def __init__(
        self,
        *,
        paths: PathLayout,
        db_pool: DatabasePool,
        db_config: DatabaseConfig,
        agent_rows_provider: Callable[[], list[Any]],
        cron_scheduled_provider: Callable[[], bool],
        audit_writer: Callable[..., None] | None = None,
        runtime_rehydrator: Callable[[], Awaitable[Any]] | None = None,
        config_service: LocalConfigService | None = None,
    ) -> None:
        self._paths = paths
        self._pool = db_pool
        self._db_config = db_config
        self._agent_rows = agent_rows_provider
        self._is_cron_scheduled = cron_scheduled_provider
        self._audit = audit_writer
        self._rehydrate = runtime_rehydrator
        self._config = config_service

    # -- listing / status -------------------------------------------------

    def list_backups(self) -> list[BackupFileInfo]:
        return list_backup_files(self._paths)

    @staticmethod
    def status() -> dict[str, Any]:
        return backup_status_payload()

    # -- auto backup settings --------------------------------------------

    def get_auto_settings(self) -> dict[str, Any]:
        backup = self._config.backup if self._config is not None else None
        if backup is None:
            from octop.config import load_config

            backup = load_config(self._paths.config).backup
        return {
            "auto_enabled": backup.auto_enabled,
            "schedule": backup.schedule,
            "retention_count": backup.retention_count,
            "include_config": backup.include_config,
            "include_workspaces": backup.include_workspaces,
            "include_skill_packages": backup.include_skill_packages,
            "include_plugins": backup.include_plugins,
            "include_knowledge": backup.include_knowledge,
            "include_chats": backup.include_chats,
            "scheduled": self._is_cron_scheduled(),
        }

    def update_auto_settings(self, settings: AutoBackupSettings) -> dict[str, Any]:
        # ``update_server_backup_config`` needs the server object to reschedule
        # the cron job; the router passes it in via a wrapper.  We only validate
        # and return the new payload here.
        backup = settings.to_config()
        return {"ok": True, **self.get_auto_settings()}

    # -- create / export --------------------------------------------------

    def create_backup(self, selection: BackupSelection) -> BackupFileInfo:
        """Create a backup and store it under ``backups_dir``."""
        raise_if_backup_busy()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "backup.tar.gz"
            filename = self._create_archive(tmp_path, selection)
            return place_backup_file(self._paths, filename, tmp_path)

    def export_backup(self, selection: BackupSelection) -> tuple[Path, str]:
        """Create an ephemeral backup; caller must delete the temp file."""
        raise_if_backup_busy()
        fd, name = tempfile.mkstemp(prefix="octop-export-", suffix=".tar.gz")
        os.close(fd)
        tmp_path = Path(name)
        try:
            filename = self._create_archive(tmp_path, selection)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
        return tmp_path, filename

    def _create_archive(self, dest: Path, selection: BackupSelection) -> str:
        return create_system_backup(
            paths=self._paths,
            agent_rows=self._agent_rows(),
            pool=self._pool,
            db_config=self._db_config,
            dest=dest,
            include_config=selection.include_config,
            include_workspaces=selection.include_workspaces,
            include_skill_packages=selection.include_skill_packages,
            include_plugins=selection.include_plugins,
            include_knowledge=selection.include_knowledge,
            include_chats=selection.include_chats,
        )

    # -- restore ----------------------------------------------------------

    def restore_backup(
        self,
        filename: str,
        *,
        restore_config: bool = True,
        owner_user_id: int,
    ) -> dict[str, Any]:
        """Restore from a stored backup (sync, runs in a worker thread).

        Runtime rehydration and audit writing happen in :meth:`arestore_backup`
        because they need the event loop.
        """
        raise_if_backup_busy()
        safe = normalize_backup_filename(filename)
        archive = resolve_backup_path(self._paths, safe)
        result = restore_system_backup(
            archive,
            paths=self._paths,
            pool=self._pool,
            db_config=self._db_config,
            restore_config=restore_config,
            owner_user_id=owner_user_id,
            allow_legacy_history=False,
        )
        return {"name": safe, **result}

    # -- file operations --------------------------------------------------

    def resolve_backup_path(self, filename: str) -> Path:
        return resolve_backup_path(self._paths, normalize_backup_filename(filename))

    def delete_backup(self, filename: str) -> None:
        delete_backup_file(self._paths, normalize_backup_filename(filename))

    def import_backup(self, filename: str, raw: bytes) -> BackupFileInfo:
        if len(raw) > _MAX_IMPORT_BYTES:
            from octop.infra.errors import ErrorCode, OctopError

            raise OctopError(
                ErrorCode.SLASH_BAD_ARGS, "backup archive too large (max 512MB)"
            )
        if not raw:
            from octop.infra.errors import ErrorCode, OctopError

            raise OctopError(ErrorCode.SLASH_BAD_ARGS, "empty backup archive")
        safe = normalize_backup_filename(filename)
        return write_backup_file(self._paths, safe, raw)

    # -- integrity check ---------------------------------------------------

    def verify_backup(self, filename: str) -> dict[str, Any]:
        """Check a stored archive without restoring or modifying anything.

        Reports the same manifest facts the restore path relies on (manifest
        version, schema version, database member) so the UI can warn before a
        restore instead of failing halfway through.
        """
        import tarfile

        from octop.infra.backup.manifest import MANIFEST_VERSION, BackupManifest
        from octop.infra.errors import ErrorCode, OctopError

        safe = normalize_backup_filename(filename)
        archive = resolve_backup_path(self._paths, safe)
        if not archive.is_file():
            raise OctopError(ErrorCode.NOT_FOUND, f"backup archive not found: {safe}")

        errors: list[str] = []
        files = 0
        manifest: BackupManifest | None = None
        try:
            with tarfile.open(archive, mode="r:*") as tf:
                members = tf.getmembers()
                files = len(members)
                manifest_member = next(
                    (m for m in members if m.name == "manifest.json"), None
                )
                if manifest_member is None:
                    errors.append("backup archive missing manifest.json")
                else:
                    handle = tf.extractfile(manifest_member)
                    try:
                        manifest = BackupManifest.load_text(
                            (handle.read() if handle else b"").decode("utf-8")
                        )
                    except Exception as exc:  # noqa: BLE001 - surface as report line
                        errors.append(f"invalid manifest: {exc}")
                if manifest is not None:
                    if manifest.manifest_version != MANIFEST_VERSION:
                        errors.append(
                            f"unsupported manifest version {manifest.manifest_version}"
                        )
                    if manifest.db_file not in {m.name for m in members}:
                        errors.append(f"archive missing database file {manifest.db_file}")
        except (tarfile.TarError, OSError) as exc:
            errors.append(f"cannot read archive: {exc}")

        payload: dict[str, Any] = {
            "ok": not errors,
            "name": safe,
            "bytes": archive.stat().st_size,
            "files": files,
            "errors": errors,
        }
        if manifest is not None:
            payload.update(
                {
                    "manifest_version": manifest.manifest_version,
                    "schema_version": manifest.schema_version,
                    "octop_version": manifest.octop_version,
                    "created_at": manifest.created_at,
                    "database_driver": manifest.database_driver,
                    "includes_chats": manifest.includes_chats,
                }
            )
        return payload

    # -- async wrappers (offload sync work to a worker thread) ------------

    async def alist_backups(self) -> list[BackupFileInfo]:
        return await asyncio.to_thread(self.list_backups)

    async def acreate_backup(self, selection: BackupSelection) -> BackupFileInfo:
        async with hold_backup_lock("create"):
            return await asyncio.to_thread(self.create_backup, selection)

    async def arestore_backup(
        self,
        filename: str,
        *,
        restore_config: bool = True,
        owner_user_id: int,
        actor: str | None = None,
    ) -> dict[str, Any]:
        async with hold_backup_lock("restore"):
            result = await asyncio.to_thread(
                self.restore_backup,
                filename,
                restore_config=restore_config,
                owner_user_id=owner_user_id,
            )
        if self._rehydrate is not None:
            await self._rehydrate()
        if self._audit is not None:
            self._audit(
                actor=actor or ACTOR_ADMIN,
                action="backup.restore",
                target=result["name"],
                payload=str(result),
            )
        return {"ok": True, **result}

    async def adelete_backup(self, filename: str) -> None:
        await asyncio.to_thread(self.delete_backup, filename)

    async def aimport_backup(self, filename: str, raw: bytes) -> BackupFileInfo:
        return await asyncio.to_thread(self.import_backup, filename, raw)

    async def averify_backup(self, filename: str) -> dict[str, Any]:
        return await asyncio.to_thread(self.verify_backup, filename)


__all__ = [
    "AutoBackupSettings",
    "BackupSelection",
    "BackupService",
]
