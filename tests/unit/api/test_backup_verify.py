"""Backup integrity check: read-only verify before a restore."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from octop.api.deps import current_user, get_server
from octop.api.routers import backup as backup_router
from octop.infra.backup.manifest import MANIFEST_VERSION, BackupManifest
from octop.infra.backup.service import BackupService
from octop.infra.errors import OctopError


class _Paths:
    """Minimal PathLayout stand-in: only the backup store is exercised."""

    def __init__(self, root: Path) -> None:
        self.backups_dir = root

    def backup_file(self, name: str) -> Path:
        return self.backups_dir / name


def _service(tmp_path: Path) -> BackupService:
    return BackupService(
        paths=_Paths(tmp_path),
        db_pool=MagicMock(),
        db_config=MagicMock(),
        agent_rows_provider=lambda: [],
        cron_scheduled_provider=lambda: False,
    )


def _add_member(tf: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    tf.addfile(info, io.BytesIO(data))


def _write_archive(
    tmp_path: Path, *, with_manifest: bool = True, with_db: bool = True
) -> Path:
    path = tmp_path / "octop-backup.tar.gz"
    with tarfile.open(path, "w:gz") as tf:
        if with_manifest:
            manifest = BackupManifest(
                manifest_version=MANIFEST_VERSION,
                octop_version="1.0.0",
                schema_version=1,
                created_at="2026-01-01T00:00:00Z",
                home=str(tmp_path),
            )
            _add_member(tf, "manifest.json", manifest.to_json().encode("utf-8"))
        if with_db:
            _add_member(tf, "db/octop.db", b"sqlite-bytes")
    return path


def test_verify_reports_manifest_facts(tmp_path: Path) -> None:
    _write_archive(tmp_path)

    result = _service(tmp_path).verify_backup("octop-backup.tar.gz")

    assert result["ok"] is True
    assert result["errors"] == []
    assert result["manifest_version"] == MANIFEST_VERSION
    assert result["schema_version"] == 1
    assert result["database_driver"] == "sqlite"
    assert result["files"] == 2


def test_verify_flags_missing_manifest(tmp_path: Path) -> None:
    _write_archive(tmp_path, with_manifest=False)

    result = _service(tmp_path).verify_backup("octop-backup.tar.gz")

    assert result["ok"] is False
    assert any("manifest.json" in err for err in result["errors"])


def test_verify_flags_missing_database_member(tmp_path: Path) -> None:
    _write_archive(tmp_path, with_db=False)

    result = _service(tmp_path).verify_backup("octop-backup.tar.gz")

    assert result["ok"] is False
    assert any("database file" in err for err in result["errors"])


def test_verify_missing_archive_raises_not_found(tmp_path: Path) -> None:
    with pytest.raises(OctopError):
        _service(tmp_path).verify_backup("nope.tar.gz")


def test_verify_endpoint_returns_service_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    payload: dict[str, Any] = {"ok": True, "name": "octop-backup.tar.gz", "errors": []}
    calls: list[str] = []

    async def _fake_verify(filename: str) -> dict[str, Any]:
        calls.append(filename)
        return payload

    server = MagicMock()
    service = MagicMock(spec=BackupService)
    service.averify_backup = _fake_verify
    monkeypatch.setattr(backup_router, "build_backup_service", lambda _s: service)

    app = FastAPI()
    app.include_router(backup_router.router, prefix="/api/admin")
    app.dependency_overrides[current_user] = lambda: MagicMock(id=1, username="owner")
    app.dependency_overrides[get_server] = lambda: server

    response = TestClient(app).get(
        "/api/admin/backup/verify", params={"filename": "octop-backup.tar.gz"}
    )

    assert response.status_code == 200, response.text
    assert response.json() == payload
    assert calls == ["octop-backup.tar.gz"]
