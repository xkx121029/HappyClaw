"""Unit tests for LocalConfigService."""

from __future__ import annotations

import json
from pathlib import Path

from happyclaw.infra.config_service import LocalConfigService


def _write_config(path: Path, backup: dict) -> None:
    path.write_text(
        json.dumps({"backup": backup, "default_timezone": "UTC"}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_load_returns_config(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    _write_config(cfg_path, {"auto_enabled": True, "schedule": "cron:0 3 * * *"})

    service = LocalConfigService(cfg_path)
    config = service.load()
    assert config.backup.auto_enabled is True
    assert config.backup.schedule == "cron:0 3 * * *"


def test_load_caches_config(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    _write_config(cfg_path, {"auto_enabled": False})

    service = LocalConfigService(cfg_path)
    first = service.load()
    # Mutate the file; the cached copy should not change.
    _write_config(cfg_path, {"auto_enabled": True})
    second = service.load()
    assert first is second
    assert second.backup.auto_enabled is False


def test_reload_picks_up_changes(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    _write_config(cfg_path, {"auto_enabled": False})

    service = LocalConfigService(cfg_path)
    assert service.load().backup.auto_enabled is False

    _write_config(cfg_path, {"auto_enabled": True})
    reloaded = service.reload()
    assert reloaded.backup.auto_enabled is True


def test_preloaded_avoids_file_read(tmp_path: Path) -> None:
    from happyclaw.config import BackupConfig, HappyclawConfig

    cfg_path = tmp_path / "does-not-exist.json"
    preloaded = HappyclawConfig(
        backup=BackupConfig(auto_enabled=True),
        default_timezone="UTC",
    )
    service = LocalConfigService(cfg_path, preloaded=preloaded)
    assert service.load().backup.auto_enabled is True


def test_update_backup_writes_and_reloads(tmp_path: Path) -> None:
    from happyclaw.config import BackupConfig

    cfg_path = tmp_path / "config.json"
    _write_config(cfg_path, {"auto_enabled": False, "schedule": "cron:0 4 * * *"})

    service = LocalConfigService(cfg_path)
    new_backup = BackupConfig(auto_enabled=True, schedule="cron:0 2 * * *")
    updated = service.update_backup(new_backup)

    assert updated.backup.auto_enabled is True
    assert updated.backup.schedule == "cron:0 2 * * *"
    # The file on disk reflects the change.
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert raw["backup"]["auto_enabled"] is True
    assert raw["backup"]["schedule"] == "cron:0 2 * * *"
