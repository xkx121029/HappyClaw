"""Both backup prefixes must serve the same handler and produce the same archive."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from octop.api.deps import current_user, get_server
from octop.api.routers import backup as backup_router
from octop.infra.backup.store import BackupFileInfo


async def _owner() -> Any:
    return MagicMock(id=1, username="owner")


def _build_client(monkeypatch: pytest.MonkeyPatch, server: Any) -> TestClient:
    app = FastAPI()
    # Mirrors ``build_app``: public prefix plus the legacy admin alias.
    app.include_router(backup_router.router, prefix="/api")
    app.include_router(backup_router.router, prefix="/api/admin")
    app.dependency_overrides[current_user] = _owner
    app.dependency_overrides[get_server] = lambda: server
    return TestClient(app)


def test_create_backup_served_on_public_and_admin_prefixes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``/api/backup/create`` must not require the ``/api/admin`` prefix."""
    calls: list[dict[str, Any]] = []

    def _fake_create(**kwargs: Any) -> BackupFileInfo:
        calls.append(kwargs)
        return BackupFileInfo(
            name="octop-backup-20260101T000000Z.tar.gz",
            size=12,
            modified_at="2026-01-01T00:00:00+00:00",
            created_at="2026-01-01T00:00:00+00:00",
        )

    monkeypatch.setattr(backup_router, "_create_and_store_manual_backup", _fake_create)
    monkeypatch.setattr(backup_router, "_agent_rows", lambda _server: [])

    server = MagicMock()
    server.services.db = object()
    server.services.config.database = object()
    server.paths = object()

    client = _build_client(monkeypatch, server)
    public = client.post("/api/backup/create", json={})
    admin = client.post("/api/admin/backup/create", json={})

    assert public.status_code == 200, public.text
    assert admin.status_code == 200, admin.text
    # Same handler, same inputs, same package metadata.
    assert public.json() == admin.json()
    assert len(calls) == 2
    assert calls[0]["paths"] is calls[1]["paths"]
    assert calls[0]["pool"] is calls[1]["pool"]
    assert public.json()["item"]["name"] == "octop-backup-20260101T000000Z.tar.gz"
