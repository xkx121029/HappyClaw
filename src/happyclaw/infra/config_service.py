"""Local configuration service.

Wraps :func:`happyclaw.config.load_config` so callers don't scatter path handling
and re-reads across the codebase.  The service caches the loaded config; use
:meth:`reload` after a config write to pick up changes.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from happyclaw.config import OctopConfig, load_config

if TYPE_CHECKING:
    from happyclaw.config import BackupConfig


class LocalConfigService:
    """Read and update the local ``config.json``."""

    def __init__(self, config_path: Path, *, preloaded: OctopConfig | None = None) -> None:
        self._path = config_path
        self._cached: OctopConfig | None = preloaded

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> OctopConfig:
        if self._cached is None:
            self._cached = load_config(self._path)
        return self._cached

    def reload(self) -> OctopConfig:
        self._cached = load_config(self._path)
        return self._cached

    @property
    def backup(self) -> "BackupConfig":
        return self.load().backup

    def update_backup(self, backup: "BackupConfig") -> OctopConfig:
        """Replace the backup section in ``config.json`` and reload.

        The file is rewritten via ``OctopConfig``'s own serialization so the
        rest of the document stays intact.
        """
        config = self.load()
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        raw["backup"] = asdict(backup)
        self._path.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return self.reload()


__all__ = ["LocalConfigService"]
