"""Bounded archive extraction for plugin packages.

Only relative, non-symlink members are written. Limits mirror the legacy
plugin installer so a hostile archive cannot exhaust disk or inodes.
"""

from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

from octop.infra.plugins.market.errors import PayloadError

MAX_ENTRIES = 2_000
MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100.0


def extract_archive(data: bytes, dest: Path, *, media_type: str) -> None:
    """Extract ``data`` into ``dest`` using the declared media type."""
    dest.mkdir(parents=True, exist_ok=True)
    if media_type in {"application/gzip", "application/x-gzip", "application/x-tar"}:
        _extract_tar(data, dest)
        return
    _extract_zip(data, dest)


def _check_member(target: Path, root: Path, filename: str) -> None:
    if not filename or filename.endswith("/"):
        return
    if target.is_symlink():
        raise PayloadError(f"archive member is a symlink: {filename}")
    if not target.resolve().is_relative_to(root):
        raise PayloadError(f"archive member escapes the plugin root: {filename}")


def _extract_zip(data: bytes, dest: Path) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise PayloadError("package is not a zip archive") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ENTRIES:
            raise PayloadError(f"archive has more than {MAX_ENTRIES} entries")
        root = dest.resolve()
        total = 0
        for member in infos:
            relative = Path(member.filename)
            if relative.is_absolute() or ".." in relative.parts:
                raise PayloadError(f"unsafe archive path: {member.filename}")
            total += max(member.file_size, 0)
            if member.file_size > MAX_MEMBER_BYTES or total > MAX_UNCOMPRESSED_BYTES:
                raise PayloadError("archive is too large")
            compressed = member.compress_size or 0
            if (
                compressed > 0
                and member.file_size > 1024 * 1024
                and member.file_size / compressed > MAX_COMPRESSION_RATIO
            ):
                raise PayloadError(f"suspicious compression ratio: {member.filename}")
            target = (dest / member.filename).resolve()
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            _check_member(target, root, member.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as sink:
                while chunk := source.read(64 * 1024):
                    sink.write(chunk)


def _extract_tar(data: bytes, dest: Path) -> None:
    try:
        archive = tarfile.open(fileobj=io.BytesIO(data), mode="r:*")
    except tarfile.TarError as exc:
        raise PayloadError("package is not a tar archive") from exc
    with archive:
        members = archive.getmembers()
        if len(members) > MAX_ENTRIES:
            raise PayloadError(f"archive has more than {MAX_ENTRIES} entries")
        root = dest.resolve()
        total = 0
        for member in members:
            relative = Path(member.name)
            if relative.is_absolute() or ".." in relative.parts:
                raise PayloadError(f"unsafe archive path: {member.name}")
            if member.isdir():
                (dest / member.name).mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise PayloadError(f"archive member is not a file: {member.name}")
            total += max(member.size, 0)
            if member.size > MAX_MEMBER_BYTES or total > MAX_UNCOMPRESSED_BYTES:
                raise PayloadError("archive is too large")
            target = (dest / member.name).resolve()
            _check_member(target, root, member.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise PayloadError(f"archive member is unreadable: {member.name}")
            with source, target.open("wb") as sink:
                while chunk := source.read(64 * 1024):
                    sink.write(chunk)
