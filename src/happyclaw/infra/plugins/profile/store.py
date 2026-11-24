"""On-disk profile store: one JSON file per profile plus the active pointer.

Writes go through a temporary file and ``os.replace`` so a crash mid-write can
never leave a half-written profile that the next switch would read.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from happyclaw.infra.plugins.profile.errors import ProfileNotFoundError
from happyclaw.infra.plugins.profile.model import Profile, validate_profile_name
from happyclaw.infra.plugins.runtime.contract import InvalidManifestError

__all__ = ["ActiveProfile", "ProfileStore"]

_PROFILE_DIR = "profiles"
_ACTIVE_FILE = "active.json"


@dataclass(frozen=True, slots=True)
class ActiveProfile:
    """The profile pointer written after a successful switch."""

    name: str
    previous: str | None = None
    revision: int = 0
    switched_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "previous": self.previous,
            "revision": self.revision,
            "switched_at": self.switched_at,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ActiveProfile:
        previous = raw.get("previous")
        return cls(
            name=str(raw.get("name") or ""),
            previous=None if previous is None else str(previous),
            revision=int(raw.get("revision") or 0),
            switched_at=str(raw.get("switched_at") or ""),
        )


class ProfileStore:
    """Reads and writes profiles below ``root``."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._profiles = self._root / _PROFILE_DIR

    @property
    def root(self) -> Path:
        return self._root

    def save(self, profile: Profile) -> Path:
        self._profiles.mkdir(parents=True, exist_ok=True)
        path = self._profiles / f"{profile.name}.json"
        self._write(path, profile.to_dict())
        return path

    def get(self, name: str) -> Profile:
        cleaned = validate_profile_name(name)
        path = self._profiles / f"{cleaned}.json"
        if not path.is_file():
            raise ProfileNotFoundError(
                f"找不到组合 {cleaned}",
                details={"profile": cleaned, "root": str(self._root)},
            )
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidManifestError(
                f"组合 {cleaned} 的文件无法读取",
                details={"profile": cleaned, "path": str(path)},
            ) from exc
        if not isinstance(raw, dict):
            raise InvalidManifestError(
                f"组合 {cleaned} 的文件必须是 JSON 对象",
                details={"profile": cleaned, "path": str(path)},
            )
        return Profile.from_dict(raw)

    def names(self) -> tuple[str, ...]:
        if not self._profiles.is_dir():
            return ()
        return tuple(sorted(path.stem for path in self._profiles.glob("*.json") if path.is_file()))

    def save_active(self, state: ActiveProfile) -> None:
        self._write(self._root / _ACTIVE_FILE, state.to_dict())

    def load_active(self) -> ActiveProfile | None:
        path = self._root / _ACTIVE_FILE
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict) or not raw.get("name"):
            return None
        return ActiveProfile.from_dict(raw)

    def _write(self, path: Path, payload: Mapping[str, Any]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
