"""Unit tests for admin backup restore rehydrate and non-blocking paths."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from happyclaw.api.routers import backup as backup_router
from happyclaw.infra.backup.service import BackupService
from happyclaw.infra.errors import ErrorCode, HappyclawError


@pytest.mark.asyncio
async def test_restore_backup_file_rehydrates_providers_channels_and_cron(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After restore, sync providers/agents, channels, and cron without process restart."""
    restored: dict[str, Any] = {
        "schema_version": 1,
        "octop_version": "0.0.0",
        "agents": 1,
        "workspace_files": 2,
        "restore_config": True,
    }

    on_provider_changed = AsyncMock()
    reload_channels = AsyncMock()
    reload_cron = AsyncMock()

    server = MagicMock()
    server.services = MagicMock()
    server.services.db = MagicMock()
    server.services.config.database = MagicMock()
    server.services.audit_repo.write = MagicMock()
    server.paths = MagicMock()
    server.app_runtime = MagicMock()
    server.app_runtime.agent_registry.on_provider_changed = on_provider_changed
    server.app_runtime.gateway.reload_channels_from_db = reload_channels
    server.app_runtime.cron_manager.reload_from_db = reload_cron

    service = backup_router.build_backup_service(server)

    # Mock the sync restore so no real archive work happens.
    with patch(
        "happyclaw.infra.backup.service.restore_system_backup",
        return_value=restored,
    ), patch(
        "happyclaw.infra.backup.service.resolve_backup_path",
        return_value="/tmp/fake.tar.gz",
    ), patch(
        "happyclaw.infra.backup.service.raise_if_backup_busy",
    ), patch(
        "happyclaw.infra.backup.service.hold_backup_lock",
    ):
        result = await service.arestore_backup(
            "octop-backup.tar.gz",
            restore_config=True,
            owner_user_id=1,
            actor="admin",
        )

    on_provider_changed.assert_awaited_once_with()
    reload_channels.assert_awaited_once_with()
    reload_cron.assert_awaited_once_with()
    assert result["ok"] is True


@pytest.mark.asyncio
async def test_create_backup_rejects_when_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    """A second create while one is running returns BACKUP_IN_PROGRESS."""
    service = MagicMock(spec=BackupService)

    async def _busy_create(*_a: Any, **_k: Any) -> Any:
        raise HappyclawError(ErrorCode.BACKUP_IN_PROGRESS, "busy")

    service.acreate_backup = _busy_create

    with pytest.raises(HappyclawError) as exc:
        await backup_router.create_backup(body=None, service=service)
    assert exc.value.code == ErrorCode.BACKUP_IN_PROGRESS
