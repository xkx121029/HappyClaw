"""SHA-256 helpers for archives and installed plugin content."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_tree(root: Path, *, exclude: Iterable[str] = ()) -> str:
    """Hash every file under ``root`` by relative path and content.

    ``exclude`` names top-level entries that are install metadata rather than
    plugin content, so the digest stays stable across re-installs.
    """
    skipped = set(exclude)
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if relative.parts[0] in skipped:
            continue
        if not path.is_file() or path.is_symlink():
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def count_files(root: Path, *, exclude: Iterable[str] = ()) -> int:
    skipped = set(exclude)
    total = 0
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if relative.parts[0] in skipped:
            continue
        if path.is_file() and not path.is_symlink():
            total += 1
    return total
