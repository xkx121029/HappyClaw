"""Migration file discovery and schema-version reads."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from octop.infra.db.pool import DatabasePool

_MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


def _discover(dialect: str = "sqlite") -> list[tuple[int, Path]]:
    out: list[tuple[int, Path]] = []
    if not _MIGRATIONS_DIR.exists():
        return out
    for entry in sorted(_MIGRATIONS_DIR.iterdir()):
        name = entry.name
        if dialect == "postgresql":
            m = re.match(r"^(\d{3})_.*\.pg\.sql$", name)
        else:
            if name.endswith(".pg.sql"):
                continue
            m = re.match(r"^(\d{3})_.*\.sql$", name)
        if m:
            out.append((int(m.group(1)), entry))
    seen: dict[int, Path] = {}
    for version, path in out:
        prior = seen.get(version)
        if prior is not None:
            raise RuntimeError(
                f"Duplicate migration version {version:03d}: {prior.name} and {path.name}. "
                "Fold unreleased schema into a single NNN_*.sql / NNN_*.pg.sql pair."
            )
        seen[version] = path
    return out


def _current_version(db: DatabasePool) -> int:
    with db.connect() as conn:
        try:
            row = conn.execute("SELECT version FROM _schema_version").fetchone()
            if row is None:
                return 0
            version = row["version"] if isinstance(row, Mapping) else row[0]
            return int(version)
        except Exception:
            return 0
