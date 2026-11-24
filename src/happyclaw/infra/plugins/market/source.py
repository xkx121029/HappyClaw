"""Catalog source abstraction shared by the octop and DSH marketplaces."""

from __future__ import annotations

import contextlib
import os
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from happyclaw.infra.plugins.market.archive import extract_archive
from happyclaw.infra.plugins.market.digest import count_files, sha256_bytes, sha256_tree
from happyclaw.infra.plugins.market.download import MAX_ARCHIVE_BYTES, Transport, fetch_bytes
from happyclaw.infra.plugins.market.errors import (
    ChecksumMismatchError,
    MarketError,
    PayloadError,
    UnsupportedSourceError,
)
from happyclaw.infra.plugins.market.models import MarketEntry, PluginRelease, RejectedEntry
from happyclaw.infra.plugins.runtime.contract import PluginKind


@dataclass(frozen=True, slots=True)
class InstalledPayload:
    """One extracted plugin tree, ready to be wrapped in an envelope."""

    content_root: Path
    manifest_path: Path
    manifest_name: str
    manifest: Mapping[str, Any]
    entry_path: str | None
    archive_sha256: str
    content_sha256: str
    size: int
    files: int
    checksum_verified: bool
    artifact_url: str


class Source(ABC):
    """A plugin catalog plus the rules for downloading one of its releases."""

    source_id: ClassVar[PluginKind]
    index_label: str = ""

    def __init__(self, *, transport: Transport | None = None) -> None:
        self._transport = transport or fetch_bytes

    @abstractmethod
    def fetch_index(self) -> list[MarketEntry]:
        """Read the catalog and return normalized entries."""

    @property
    def rejected(self) -> tuple[RejectedEntry, ...]:
        """Rows the last ``fetch_index()`` could not normalize, for diagnostics.

        Sources that validate their index as one document return nothing here.
        """
        return ()

    def diagnostics(self) -> str:
        """Read-only report of rejected rows; empty when there are none."""
        rejected = self.rejected
        if not rejected:
            return ""
        lines = [f"索引 {self.index_label or self.source_id.value} 有 {len(rejected)} 个条目被拒："]
        for entry in rejected:
            label = entry.plugin_id or "<无 id>"
            lines.append(f"- [{label}] {entry.error_code}: {entry.reason}")
            lines.append(f"  建议：{entry.suggestion}")
        return "\n".join(lines)

    @abstractmethod
    def _validate_manifest(
        self,
        entry: MarketEntry,
        release: PluginRelease,
        manifest: Mapping[str, Any],
        content_root: Path,
    ) -> str | None:
        """Check that the package matches the catalog row and return its entry file."""

    @property
    @abstractmethod
    def manifest_names(self) -> tuple[str, ...]:
        """Manifest filenames this source accepts at the package root."""

    def install(
        self,
        entry: MarketEntry,
        dest: Path,
        *,
        release: PluginRelease | None = None,
    ) -> InstalledPayload:
        """Download, verify and extract one release into ``dest``."""
        chosen = release or entry.release()
        if not chosen.artifact.url:
            raise UnsupportedSourceError(
                f"plugin {entry.plugin_id!r} {chosen.version} has no downloadable archive"
            )
        data = self._transport(chosen.artifact.url)
        if len(data) > MAX_ARCHIVE_BYTES:
            raise PayloadError("package is larger than the download limit")
        archive_sha256 = sha256_bytes(data)
        expected = chosen.artifact.sha256
        if expected is not None and expected.lower() != archive_sha256:
            raise ChecksumMismatchError(expected, archive_sha256)
        dest.mkdir(parents=True, exist_ok=True)
        extract_archive(data, dest, media_type=chosen.artifact.media_type)
        manifest_path = self._locate_manifest(dest, chosen)
        manifest = read_manifest(manifest_path)
        content_root = _flatten_into(manifest_path.parent, dest)
        manifest_path = content_root / manifest_path.name
        entry_path = self._validate_manifest(entry, chosen, manifest, content_root)
        if entry_path is not None and not (content_root / entry_path).is_file():
            raise PayloadError(f"manifest entry file is missing: {entry_path}")
        return InstalledPayload(
            content_root=content_root,
            manifest_path=manifest_path,
            manifest_name=manifest_path.name,
            manifest=manifest,
            entry_path=entry_path,
            archive_sha256=archive_sha256,
            content_sha256=sha256_tree(content_root),
            size=len(data),
            files=count_files(content_root),
            checksum_verified=expected is not None,
            artifact_url=chosen.artifact.url,
        )

    def verify(
        self,
        entry: MarketEntry,
        payload: InstalledPayload,
        *,
        release: PluginRelease | None = None,
    ) -> None:
        """Re-check an installed payload without touching the network."""
        manifest = read_manifest(payload.manifest_path)
        self._validate_manifest(entry, release or entry.release(), manifest, payload.content_root)
        actual = sha256_tree(payload.content_root)
        if actual != payload.content_sha256:
            raise ChecksumMismatchError(payload.content_sha256, actual)
        if payload.archive_sha256 == "":
            raise MarketError("installed payload has no archive digest")

    def _locate_manifest(self, dest: Path, release: PluginRelease | None = None) -> Path:
        direct = self._manifest_at(dest)
        if direct is not None:
            return direct
        children = [child for child in dest.iterdir() if child.is_dir()]
        if len(children) == 1:
            nested = self._manifest_at(children[0])
            if nested is not None:
                return nested
            deeper = self._nested_content_root(children[0], release)
            if deeper is not None:
                found = self._manifest_at(deeper)
                if found is not None:
                    return found
        raise PayloadError(f"package has no {' or '.join(self.manifest_names)}")

    def _manifest_at(self, root: Path) -> Path | None:
        for name in self.manifest_names:
            candidate = root / name
            if candidate.is_file():
                return candidate
        return None

    def _nested_content_root(self, wrapper: Path, release: PluginRelease | None) -> Path | None:
        """Extra directory level declared by the release (e.g. git ``path``)."""
        del wrapper, release
        return None


def read_manifest(path: Path) -> Mapping[str, Any]:
    if path.name.endswith((".yaml", ".yml")):
        import yaml

        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as exc:
            raise PayloadError(f"manifest is unreadable: {path.name}") from exc
        except yaml.YAMLError as exc:
            raise PayloadError(f"manifest is invalid yaml: {path.name}") from exc
        if not isinstance(loaded, dict):
            raise PayloadError(f"manifest is not an object: {path.name}")
        return {str(key): value for key, value in loaded.items()}
    import json

    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PayloadError(f"manifest is unreadable: {path.name}") from exc
    if not isinstance(loaded, dict):
        raise PayloadError(f"manifest is not an object: {path.name}")
    return {str(key): value for key, value in loaded.items()}


def _flatten_into(source_root: Path, dest: Path) -> Path:
    """Move ``source_root``'s children up into ``dest`` when a wrapper dir exists."""
    if source_root == dest:
        return dest
    for child in list(source_root.iterdir()):
        target = dest / child.name
        if target.exists():
            raise PayloadError(f"archive has a duplicate path: {child.name}")
        os.replace(child, target)
    with contextlib.suppress(OSError):
        source_root.rmdir()
    return dest


def manifest_text(manifest: Mapping[str, Any], key: str) -> str:
    value = manifest.get(key)
    return str(value).strip() if value is not None else ""


__all__ = ["InstalledPayload", "Source", "manifest_text", "read_manifest"]
