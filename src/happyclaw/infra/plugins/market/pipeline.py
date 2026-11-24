"""Install pipeline shared by the octop and DSH marketplaces.

Conflict rules (deterministic, see ``marketplace.md``):

1. Higher version wins.
2. Equal versions: the octop market wins over DSH (``SOURCE_PRIORITY``).
3. Unparseable versions: source priority wins, then catalog order.
4. Installing a lower version than the recorded one is rejected unless
   ``force=True``.
5. Re-installing the recorded version with identical content is a no-op and
   does not touch the network when the ledger already has the digest.

Uninstall rules:

* ``uninstall(plugin_id, dest_root, version=None)`` removes the current slot,
  or the exact slot named by ``version``.
* It refuses while another installed plugin's ``requires`` matches the version
  being removed (``PLUGIN_DEPENDENCY_IN_USE``, message in Chinese).
* The slot is renamed into a ``.trash-*`` sibling before anything is deleted,
  so the plugin path always holds either the whole tree or nothing; a failed
  ledger write renames it back.
* Removing the current version falls back to the highest remaining version;
  with no versions left the ledger and plugin directory are removed.

Dry-run rules:

* ``MarketplaceIndex.plan(operation, plugin_id, dest_root, version=None)``
  reports target version, slots added/removed, dependent plugins, file delta
  and the capability diff without writing to ``dest_root`` or its ledger.
* An upgrade that adds capabilities is refused unless the caller passes
  ``allow_capability_expansion=True``; narrowing is reported by ``plan`` but
  needs no confirmation.

Install layout (installing never deletes an existing slot; each ecosystem owns
its own subtree so an octop plugin and a DSH plugin with the same native id
never share files)::

    <dest_root>/octop/<native>/     # or <dest_root>/dsh/<native>/
        index.json                  # ledger: current + every install record
        <version>/plugin.json       # unified envelope (contract alignment)
        <version>/.market.json      # provenance of this install
        <version>/<payload files>   # plugin.yaml or package.json + code
        <version>-<digest8>/...     # same version, different content
        .trash-<slot>-<hex>/        # transient; only exists during uninstall
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from happyclaw.infra.plugins.market.digest import count_files, sha256_tree
from happyclaw.infra.plugins.market.envelope import (
    ENVELOPE_FILENAME,
    MARKET_META_FILENAME,
    build_envelope,
    envelope_index_excludes,
)
from happyclaw.infra.plugins.market.errors import (
    CapabilityExpansionError,
    ConfigSchemaChangedError,
    DependencyConstraintError,
    DependencyInUseError,
    IndexUnusableError,
    InstallConflictError,
    MarketError,
)
from happyclaw.infra.plugins.market.models import (
    MarketEntry,
    PluginRelease,
    RejectedEntry,
)
from happyclaw.infra.plugins.market.source import Source
from happyclaw.infra.plugins.market.versions import compare_versions
from happyclaw.infra.plugins.runtime.contract import (
    InvalidManifestError,
    PluginKind,
    PluginRequirement,
    PluginRuntimeError,
    split_plugin_id,
)

LEDGER_SCHEMA = 1
LEDGER_FILENAME = "index.json"
_STAGING_PREFIX = ".staging-"
_TRASH_PREFIX = ".trash-"
_DIR_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,199}$")
_WINDOWS_RESERVED = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
)

InstallStatus = Literal["installed", "unchanged", "replaced"]
PlanOperation = Literal["install", "upgrade", "uninstall"]


@dataclass(frozen=True, slots=True)
class InstallResult:
    """Outcome of one ``MarketplaceIndex.install`` call."""

    plugin_id: str
    version: str
    source: str
    status: InstallStatus
    install_dir: Path
    envelope: Mapping[str, Any]
    alternate_sources: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class UpgradeResult:
    """Outcome of one ``MarketplaceIndex.upgrade`` call."""

    plugin_id: str
    previous_version: str | None
    version: str
    source: str
    status: InstallStatus
    install_dir: Path
    envelope: Mapping[str, Any]
    downgraded: bool


@dataclass(frozen=True, slots=True)
class DependencyImpact:
    """One installed plugin that depends on the plugin being planned."""

    plugin_id: str
    version: str
    constraint: str
    satisfied_after: bool


@dataclass(frozen=True, slots=True)
class PlanResult:
    """What one install/upgrade/uninstall would change, without touching disk."""

    operation: str
    plugin_id: str
    status: str
    current_version: str | None
    target_version: str | None
    slots_added: tuple[str, ...]
    slots_removed: tuple[str, ...]
    file_delta: int
    capabilities_before: tuple[str, ...]
    capabilities_after: tuple[str, ...]
    added_capabilities: tuple[str, ...]
    removed_capabilities: tuple[str, ...]
    expands_capabilities: bool
    narrows_capabilities: bool
    dependency_impacts: tuple[DependencyImpact, ...]


@dataclass(frozen=True, slots=True)
class ReleaseInspection:
    """What a downloaded release declares, read without installing it."""

    capabilities: tuple[str, ...]
    config_schema: dict[str, Any]
    files: int
    content_sha256: str


@dataclass(frozen=True, slots=True)
class UninstallResult:
    """Outcome of one ``uninstall`` call."""

    plugin_id: str
    version: str
    install_dir: Path
    current_version: str | None
    remaining_versions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IndexConflict:
    """The same plugin id was listed by more than one catalog."""

    plugin_id: str
    winner: MarketEntry
    losers: tuple[MarketEntry, ...]


class MarketplaceIndex:
    """Merges catalogs, resolves conflicts and installs into ``dest_root``."""

    def __init__(self, sources: Sequence[Source]) -> None:
        if not sources:
            raise MarketError("marketplace needs at least one source")
        self._sources = list(sources)
        self._by_key: dict[tuple[PluginKind, str], MarketEntry] = {}
        self._winners: dict[str, MarketEntry] = {}
        self._conflicts: dict[str, IndexConflict] = {}
        self._fetched = False

    # -- catalog -----------------------------------------------------------

    def fetch(self) -> list[MarketEntry]:
        """Fetch every catalog once and return the winning entry per native id.

        A source whose rows were all rejected is skipped so one broken catalog
        cannot hide the other; the error is raised only when no source yields a
        single usable entry.
        """
        if self._fetched:
            return [self._winners[key] for key in sorted(self._winners)]
        grouped: dict[str, list[MarketEntry]] = {}
        unusable: list[IndexUnusableError] = []
        for source in self._sources:
            try:
                entries = source.fetch_index()
            except IndexUnusableError as exc:
                unusable.append(exc)
                continue
            for entry in entries:
                self._by_key[(entry.source, entry.plugin_id)] = entry
                grouped.setdefault(entry.native_id, []).append(entry)
        for native_id, entries in grouped.items():
            winner = pick_winner(entries)
            self._winners[native_id] = winner
            losers = tuple(item for item in entries if item is not winner)
            if losers:
                self._conflicts[native_id] = IndexConflict(winner.plugin_id, winner, losers)
        if not self._winners and unusable:
            raise unusable[0]
        self._fetched = True
        return [self._winners[key] for key in sorted(self._winners)]

    def rejected(self) -> tuple[RejectedEntry, ...]:
        """Every row the catalogs refused, for read-only diagnostics.

        Works even when the index is unusable: the failed fetch is tolerated
        here because diagnosis is exactly what the caller needs then.
        """
        self._fetch_tolerating_unusable()
        return tuple(item for source in self._sources for item in source.rejected)

    def diagnostics(self) -> str:
        """Human-readable rejection report; empty when every row was accepted."""
        self._fetch_tolerating_unusable()
        reports = [source.diagnostics() for source in self._sources]
        return "\n".join(report for report in reports if report)

    def _fetch_tolerating_unusable(self) -> None:
        try:
            self.fetch()
        except IndexUnusableError:
            return

    def conflicts(self) -> list[IndexConflict]:
        self.fetch()
        return [self._conflicts[key] for key in sorted(self._conflicts)]

    def find(self, plugin_id: str, *, source: str | None = None) -> MarketEntry:
        """Look up one exact catalog row by its canonical id."""
        self.fetch()
        try:
            kind, _native = split_plugin_id(plugin_id)
        except InvalidManifestError as exc:
            raise MarketError(str(exc)) from exc
        if source is not None:
            kind = PluginKind(source)
        entry = self._by_key.get((kind, plugin_id))
        if entry is None:
            raise MarketError(f"plugin {plugin_id!r} is not listed by {kind.value!r}")
        return entry

    # -- install -----------------------------------------------------------

    def install(
        self,
        plugin_id: str,
        dest_root: Path,
        *,
        version: str | None = None,
        source: str | None = None,
        force: bool = False,
    ) -> InstallResult:
        entry = self.find(plugin_id, source=source)
        release = entry.release(version)
        return install_entry(
            entry,
            release,
            self._source_for(entry),
            dest_root,
            force=force,
            alternate_sources=self._alternate_sources(entry.native_id, entry.source),
        )

    def upgrade(
        self,
        plugin_id: str,
        dest_root: Path,
        *,
        version: str | None = None,
        allow_capability_expansion: bool = False,
    ) -> UpgradeResult:
        """Move an installed plugin to another version without a broken state.

        ``version=None`` picks the highest release the catalog offers and never
        downgrades. An explicit ``version`` may downgrade, but a downgrade whose
        config schema differs is refused instead of dropping stored config. The
        previous slots are kept, so a failed switch leaves the old version as
        ``current``.

        A release that declares capabilities the installed version did not have
        is refused unless ``allow_capability_expansion=True``: the host owner
        must confirm the wider permission surface. Narrowing needs no consent.
        """
        entry = self.find(plugin_id)
        release = entry.release(version)
        plugin_root = dest_root / plugin_dir_name(plugin_id)
        current = _current_record(_read_ledger(plugin_root))
        previous = None if current is None else str(current.get("version") or "")
        comparison = compare_versions(release.version, previous) if previous else None
        downgrading = comparison is not None and comparison < 0
        if downgrading and version is None:
            raise InstallConflictError(
                f"{plugin_id} 当前为 {previous}，目录里最高版本是 {release.version}；"
                "默认不降级，请显式指定 version",
                plugin_id=plugin_id,
                installed_version=previous or "",
                incoming_version=release.version,
            )
        if previous is not None:
            inspection = _inspect_release(entry, release, self._source_for(entry))
            before_caps = _capabilities_of(plugin_root, current)
            added_caps = tuple(sorted(set(inspection.capabilities) - set(before_caps)))
            if added_caps and not allow_capability_expansion:
                raise CapabilityExpansionError(plugin_id, previous, release.version, added_caps)
            old_schema = _config_schema_of(plugin_root, current)
            if downgrading and old_schema != inspection.config_schema:
                raise ConfigSchemaChangedError(
                    plugin_id,
                    previous,
                    release.version,
                    tuple(sorted(set(inspection.config_schema) - set(old_schema))),
                    tuple(sorted(set(old_schema) - set(inspection.config_schema))),
                )
        _reject_breaking_dependents(plugin_id, release.version, dest_root)

        before = _slot_names(plugin_root)
        try:
            result = install_entry(
                entry,
                release,
                self._source_for(entry),
                dest_root,
                force=downgrading,
                alternate_sources=self._alternate_sources(entry.native_id, entry.source),
            )
        except BaseException as exc:
            _remove_orphan_slots(plugin_root, before)
            if isinstance(exc, PluginRuntimeError):
                raise
            raise MarketError(
                f"升级 {plugin_id} 到 {release.version} 失败，"
                f"已保留 {previous or '原状态'} 为当前版本：{exc}"
            ) from exc
        return UpgradeResult(
            plugin_id=plugin_id,
            previous_version=previous,
            version=result.version,
            source=result.source,
            status=result.status,
            install_dir=result.install_dir,
            envelope=result.envelope,
            downgraded=downgrading,
        )

    def plan(
        self,
        operation: PlanOperation,
        plugin_id: str,
        dest_root: Path,
        *,
        version: str | None = None,
    ) -> PlanResult:
        """Describe an install, upgrade or uninstall without changing anything.

        ``dest_root`` and its ledger are read only; the target release is
        downloaded into a temporary directory and discarded. ``uninstall`` needs
        no catalog, so it works even for a plugin the current catalogs dropped.
        """
        if operation == "uninstall":
            return _plan_uninstall(plugin_id, dest_root, version)
        if operation not in ("install", "upgrade"):
            raise MarketError(f"unknown plan operation: {operation!r}")
        entry = self.find(plugin_id)
        release = entry.release(version)
        return _plan_install(entry, release, self._source_for(entry), dest_root, operation)

    def _source_for(self, entry: MarketEntry) -> Source:
        for source in self._sources:
            if source.source_id == entry.source:
                return source
        raise MarketError(f"no source registered for {entry.source!r}")

    def _alternate_sources(self, native_id: str, winner_source: PluginKind) -> tuple[str, ...]:
        found = [
            entry.source.value
            for entry in self._by_key.values()
            if entry.native_id == native_id and entry.source is not winner_source
        ]
        return tuple(sorted(set(found)))


def pick_winner(entries: Sequence[MarketEntry]) -> MarketEntry:
    """Apply the documented conflict rules to entries sharing one plugin id."""
    best = entries[0]
    for candidate in entries[1:]:
        if _outranks(candidate, best):
            best = candidate
    return best


def _outranks(candidate: MarketEntry, incumbent: MarketEntry) -> bool:
    comparison = compare_versions(candidate.version, incumbent.version)
    if comparison is None:
        return candidate.priority > incumbent.priority
    if comparison != 0:
        return comparison > 0
    return candidate.priority > incumbent.priority


def install_entry(
    entry: MarketEntry,
    release: PluginRelease,
    source: Source,
    dest_root: Path,
    *,
    force: bool = False,
    alternate_sources: tuple[str, ...] = (),
) -> InstallResult:
    """Install one resolved entry. Used by ``MarketplaceIndex`` and by tests."""
    _validate_plugin_id(entry.plugin_id)
    plugin_root = dest_root / plugin_dir_name(entry.plugin_id)
    plugin_root.mkdir(parents=True, exist_ok=True)
    ledger = _read_ledger(plugin_root)
    current = _current_record(ledger)
    if current is not None:
        _guard_current(current, entry, release, force=force)
        if (
            str(current.get("version") or "") == release.version
            and str(current.get("source") or "") == entry.source
        ):
            existing = _existing_result(plugin_root, current, entry, alternate_sources)
            if existing is not None:
                return existing

    staging = Path(tempfile.mkdtemp(prefix=_STAGING_PREFIX, dir=plugin_root))
    try:
        payload = source.install(entry, staging, release=release)
        source.verify(entry, payload, release=release)
        if current is not None and current.get("content_sha256") == payload.content_sha256:
            shutil.rmtree(staging)
            existing = _existing_result(plugin_root, current, entry, alternate_sources)
            if existing is not None:
                return existing
        installed_at = _utc_now()
        envelope = build_envelope(
            entry=entry, release=release, payload=payload, installed_at=installed_at
        )
        record: dict[str, Any] = {
            "version": release.version,
            "source": entry.source.value,
            "slot": "",
            "requires": [requirement.to_dict() for requirement in entry.requires],
            "config_schema": dict(envelope.get("config_schema") or {}),
            "content_sha256": payload.content_sha256,
            "archive_sha256": payload.archive_sha256,
            "artifact_url": payload.artifact_url,
            "checksum_verified": payload.checksum_verified,
            "installed_at": installed_at,
        }
        slot = _slot_dir(plugin_root, release.version, payload.content_sha256)
        record["slot"] = slot.name
        _write_json(staging / ENVELOPE_FILENAME, envelope)
        _write_json(
            staging / MARKET_META_FILENAME,
            {
                "schema": 1,
                "source": entry.source,
                "index": entry.extra.get("index_url"),
                "artifact": payload.artifact_url,
                "archive_sha256": payload.archive_sha256,
                "content_sha256": payload.content_sha256,
                "checksum_verified": payload.checksum_verified,
                "installed_at": installed_at,
            },
        )
        os.replace(staging, slot)
        installs = [item for item in _records(ledger) if item.get("slot") != record["slot"]]
        installs.append(record)
        _write_ledger(
            plugin_root,
            {
                "schema": LEDGER_SCHEMA,
                "plugin_id": entry.plugin_id,
                "current": record,
                "installs": installs,
            },
        )
        envelope_path = slot / ENVELOPE_FILENAME
        status: InstallStatus = "replaced" if current is not None else "installed"
        return InstallResult(
            plugin_id=entry.plugin_id,
            version=release.version,
            source=entry.source.value,
            status=status,
            install_dir=slot,
            envelope=_load_json(envelope_path),
            alternate_sources=alternate_sources,
        )
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise


def uninstall(
    plugin_id: str,
    dest_root: Path,
    *,
    version: str | None = None,
) -> UninstallResult:
    """Remove the current slot, or the slot named by ``version``.

    Nothing is deleted before the slot has been renamed into ``.trash-*`` and
    the ledger has been rewritten, so the plugin path never holds half a tree.
    """
    _validate_plugin_id(plugin_id)
    plugin_root = dest_root / plugin_dir_name(plugin_id)
    ledger = _read_ledger(plugin_root)
    current = _current_record(ledger)
    records = _records(ledger)
    if current is None and not records:
        raise MarketError(f"plugin {plugin_id!r} is not installed under {dest_root}")

    target = _target_record(plugin_id, version, current, records)
    removed_version = str(target.get("version") or "")
    _reject_if_required(plugin_id, removed_version, dest_root)

    slot_name = str(target.get("slot") or "")
    slot = plugin_root / slot_name
    if not slot_name or not slot.is_dir():
        raise MarketError(f"install directory is missing: {slot}")

    remaining = [item for item in records if item.get("slot") != slot_name]
    removing_current = current is not None and current.get("slot") == target.get("slot")
    new_current = _highest_record(remaining) if removing_current else current

    trash = plugin_root / f"{_TRASH_PREFIX}{slot.name}-{uuid4().hex[:8]}"
    os.replace(slot, trash)
    try:
        _write_ledger(
            plugin_root,
            {
                "schema": LEDGER_SCHEMA,
                "plugin_id": plugin_id,
                "current": new_current,
                "installs": remaining,
            },
        )
    except BaseException:
        os.replace(trash, slot)
        raise

    try:
        shutil.rmtree(trash)
    except OSError as exc:
        if _tree_digest(trash) == str(target.get("content_sha256") or ""):
            os.replace(trash, slot)
            _write_ledger(plugin_root, ledger)
            raise MarketError(
                f"failed to delete {slot.name}; the install was rolled back: {exc}"
            ) from exc
        raise MarketError(
            f"{plugin_id!r} is uninstalled but its files remain at {trash}: {exc}",
            details={"plugin_id": plugin_id, "trash": str(trash), "uninstalled": True},
        ) from exc

    if not remaining:
        _remove_plugin_root(plugin_root)
    return UninstallResult(
        plugin_id=plugin_id,
        version=removed_version,
        install_dir=slot,
        current_version=None if new_current is None else str(new_current.get("version") or ""),
        remaining_versions=tuple(str(item.get("version") or "") for item in remaining),
    )


def _plan_install(
    entry: MarketEntry,
    release: PluginRelease,
    source: Source,
    dest_root: Path,
    operation: str,
) -> PlanResult:
    plugin_root = dest_root / plugin_dir_name(entry.plugin_id)
    current = _current_record(_read_ledger(plugin_root))
    previous = None if current is None else str(current.get("version") or "")
    inspection = _inspect_release(entry, release, source)
    unchanged = (
        current is not None
        and previous == release.version
        and str(current.get("content_sha256") or "") == inspection.content_sha256
    )
    if unchanged:
        status = "unchanged"
        slots_added: tuple[str, ...] = ()
    else:
        comparison = compare_versions(release.version, previous) if previous else None
        if previous is None:
            status = "install"
        elif comparison is not None and comparison > 0:
            status = "upgrade"
        elif comparison is not None and comparison < 0:
            status = "downgrade"
        else:
            status = "reinstall"
        slots_added = (_slot_dir(plugin_root, release.version, inspection.content_sha256).name,)

    before_caps = _capabilities_of(plugin_root, current)
    added_caps = tuple(sorted(set(inspection.capabilities) - set(before_caps)))
    removed_caps = tuple(sorted(set(before_caps) - set(inspection.capabilities)))
    return PlanResult(
        operation=operation,
        plugin_id=entry.plugin_id,
        status=status,
        current_version=previous,
        target_version=release.version,
        slots_added=slots_added,
        slots_removed=(),
        file_delta=inspection.files - _record_files(plugin_root, current),
        capabilities_before=before_caps,
        capabilities_after=inspection.capabilities,
        added_capabilities=added_caps,
        removed_capabilities=removed_caps,
        expands_capabilities=current is not None and bool(added_caps),
        narrows_capabilities=bool(removed_caps),
        dependency_impacts=_dependency_impacts(entry.plugin_id, release.version, dest_root),
    )


def _plan_uninstall(plugin_id: str, dest_root: Path, version: str | None) -> PlanResult:
    _validate_plugin_id(plugin_id)
    plugin_root = dest_root / plugin_dir_name(plugin_id)
    ledger = _read_ledger(plugin_root)
    current = _current_record(ledger)
    records = _records(ledger)
    if current is None and not records:
        raise MarketError(f"plugin {plugin_id!r} is not installed under {dest_root}")
    target = _target_record(plugin_id, version, current, records)
    removed_version = str(target.get("version") or "")
    removing_current = current is not None and current.get("slot") == target.get("slot")
    remaining = [item for item in records if item.get("slot") != target.get("slot")]
    new_current = _highest_record(remaining) if removing_current else current
    before_caps = _capabilities_of(plugin_root, current)
    after_caps = _capabilities_of(plugin_root, new_current)
    return PlanResult(
        operation="uninstall",
        plugin_id=plugin_id,
        status="uninstall",
        current_version=None if current is None else str(current.get("version") or ""),
        target_version=removed_version,
        slots_added=(),
        slots_removed=(str(target.get("slot") or ""),),
        file_delta=-_record_files(plugin_root, target),
        capabilities_before=before_caps,
        capabilities_after=after_caps,
        added_capabilities=(),
        removed_capabilities=tuple(sorted(set(before_caps) - set(after_caps))),
        expands_capabilities=False,
        narrows_capabilities=bool(set(before_caps) - set(after_caps)),
        dependency_impacts=_dependency_impacts(
            plugin_id, removed_version, dest_root, uninstalling=True
        ),
    )


def verify_install(plugin_id: str, dest_root: Path) -> None:
    """Re-check the recorded install on disk: envelope, digest and manifest id."""
    plugin_root = dest_root / plugin_dir_name(plugin_id)
    current = _current_record(_read_ledger(plugin_root))
    if current is None:
        raise MarketError(f"plugin {plugin_id!r} is not installed under {dest_root}")
    slot = plugin_root / str(current.get("slot") or "")
    envelope_path = slot / ENVELOPE_FILENAME
    if not envelope_path.is_file():
        raise MarketError(f"install envelope is missing: {envelope_path}")
    envelope = _load_json(envelope_path)
    if envelope.get("id") != plugin_id:
        raise MarketError("install envelope id does not match the request")
    metadata = envelope.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    content = metadata.get("content")
    content = content if isinstance(content, dict) else {}
    expected = str(content.get("sha256") or "")
    actual = sha256_tree(slot, exclude=envelope_index_excludes())
    if expected != actual:
        raise MarketError(f"content digest mismatch for {plugin_id!r}")
    entry_path = envelope.get("entry")
    if isinstance(entry_path, str) and entry_path and not (slot / entry_path).is_file():
        raise MarketError(f"entry file is missing: {entry_path}")


def plugin_dir_name(plugin_id: str) -> Path:
    """Map a canonical id to its install directory relative to ``dest_root``.

    The path is ``<kind>/<native>`` so ``octop:weather`` and ``dsh:weather``
    are independent plugins that never overwrite each other's files or ledger.
    The canonical id, including its ecosystem prefix, is recorded in
    ``plugin.json`` and the ledger.
    """
    try:
        kind, native = split_plugin_id(plugin_id)
    except InvalidManifestError as exc:
        raise MarketError(str(exc)) from exc
    name = f"_{native}" if native.lower() in _WINDOWS_RESERVED else native
    if _DIR_NAME_RE.fullmatch(name) is None:
        raise MarketError(f"invalid plugin id: {plugin_id!r} ({kind.value})")
    return Path(kind.value) / name


def _validate_plugin_id(plugin_id: str) -> None:
    try:
        split_plugin_id(plugin_id)
    except InvalidManifestError as exc:
        raise MarketError(str(exc)) from exc


def _guard_current(
    current: Mapping[str, Any],
    entry: MarketEntry,
    release: PluginRelease,
    *,
    force: bool,
) -> None:
    installed_version = str(current.get("version") or "")
    if force:
        return
    comparison = compare_versions(release.version, installed_version)
    if comparison is not None and comparison < 0:
        raise InstallConflictError(
            f"refusing to downgrade {entry.plugin_id!r} from {installed_version} "
            f"to {release.version}; pass force=True to override",
            plugin_id=entry.plugin_id,
            installed_version=installed_version,
            incoming_version=release.version,
        )


def _existing_result(
    plugin_root: Path,
    current: Mapping[str, Any],
    entry: MarketEntry,
    alternate_sources: tuple[str, ...] = (),
) -> InstallResult | None:
    slot = plugin_root / str(current.get("slot") or "")
    envelope_path = slot / ENVELOPE_FILENAME
    if not envelope_path.is_file():
        return None
    envelope = _load_json(envelope_path)
    return InstallResult(
        plugin_id=entry.plugin_id,
        version=str(current.get("version") or ""),
        source=str(current.get("source") or ""),
        status="unchanged",
        install_dir=slot,
        envelope=envelope,
        alternate_sources=alternate_sources,
    )


def _slot_dir(plugin_root: Path, version: str, digest: str) -> Path:
    base = plugin_root / version
    if not base.exists():
        return base
    candidate = plugin_root / f"{version}-{digest[:8]}"
    suffix = 2
    while candidate.exists():
        candidate = plugin_root / f"{version}-{digest[:8]}-{suffix}"
        suffix += 1
    return candidate


def _read_ledger(plugin_root: Path) -> dict[str, Any]:
    path = plugin_root / LEDGER_FILENAME
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MarketError(f"install ledger is corrupt: {path}") from exc
    if not isinstance(loaded, dict):
        raise MarketError(f"install ledger is corrupt: {path}")
    return loaded


def _current_record(ledger: Mapping[str, Any]) -> Mapping[str, Any] | None:
    current = ledger.get("current")
    return current if isinstance(current, dict) else None


def _records(ledger: Mapping[str, Any]) -> list[dict[str, Any]]:
    records = ledger.get("installs")
    if not isinstance(records, list):
        return []
    return [item for item in records if isinstance(item, dict)]


def _write_ledger(plugin_root: Path, ledger: Mapping[str, Any]) -> None:
    _write_json(plugin_root / LEDGER_FILENAME, ledger)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MarketError(f"unreadable json: {path}") from exc
    if not isinstance(loaded, dict):
        raise MarketError(f"expected a json object: {path}")
    return loaded


def _target_record(
    plugin_id: str,
    version: str | None,
    current: Mapping[str, Any] | None,
    records: Sequence[dict[str, Any]],
) -> Mapping[str, Any]:
    if version is None:
        if current is None:
            raise MarketError(f"plugin {plugin_id!r} has no current install to remove")
        return current
    matches = [item for item in records if str(item.get("version") or "") == version]
    if not matches:
        raise MarketError(f"plugin {plugin_id!r} version {version!r} is not installed")
    if current is not None:
        for item in matches:
            if item.get("slot") == current.get("slot"):
                return item
    if len(matches) == 1:
        return matches[0]
    raise MarketError(
        f"plugin {plugin_id!r} version {version!r} has several installs; "
        "remove them one slot at a time"
    )


def _highest_record(records: Sequence[dict[str, Any]]) -> Mapping[str, Any] | None:
    best: Mapping[str, Any] | None = None
    for record in records:
        if best is None:
            best = record
            continue
        comparison = compare_versions(
            str(record.get("version") or ""), str(best.get("version") or "")
        )
        if comparison is not None and comparison > 0:
            best = record
    return best


def _reject_if_required(plugin_id: str, version: str, dest_root: Path) -> None:
    dependents: list[tuple[str, str, str]] = []
    for dependent_id, dependent_version, requirement in _installed_requirements(dest_root):
        if requirement.plugin_id != plugin_id:
            continue
        if not requirement.matches(version):
            continue
        dependents.append((dependent_id, dependent_version, requirement.constraint))
    if dependents:
        raise DependencyInUseError(plugin_id, version, tuple(dependents))


def _installed_requirements(
    dest_root: Path,
) -> Iterator[tuple[str, str, PluginRequirement]]:
    for kind in (PluginKind.OCTOP, PluginKind.DSH):
        base = dest_root / kind.value
        if not base.is_dir():
            continue
        for plugin_root in sorted(path for path in base.iterdir() if path.is_dir()):
            ledger = _read_ledger(plugin_root)
            dependent_id = str(ledger.get("plugin_id") or "")
            for record in _records(ledger):
                version = str(record.get("version") or "")
                for requirement in _record_requirements(plugin_root, record):
                    yield dependent_id, version, requirement


def _record_requirements(
    plugin_root: Path, record: Mapping[str, Any]
) -> tuple[PluginRequirement, ...]:
    raw = record.get("requires")
    if isinstance(raw, list):
        return _parse_requirements(raw)
    # Ledgers written before ``requires`` was recorded fall back to the envelope.
    slot = plugin_root / str(record.get("slot") or "")
    envelope_path = slot / ENVELOPE_FILENAME
    if not envelope_path.is_file():
        return ()
    try:
        envelope = _load_json(envelope_path)
    except MarketError:
        return ()
    return _parse_requirements(envelope.get("requires"))


def _parse_requirements(raw: Any) -> tuple[PluginRequirement, ...]:
    parsed: list[PluginRequirement] = []
    if not isinstance(raw, list):
        return ()
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        try:
            parsed.append(
                PluginRequirement(
                    str(item.get("plugin_id") or ""),
                    str(item.get("constraint") or "*"),
                )
            )
        except InvalidManifestError:
            continue
    return tuple(parsed)


def _tree_digest(root: Path) -> str:
    try:
        return sha256_tree(root, exclude=envelope_index_excludes())
    except OSError:
        return ""


def _remove_plugin_root(plugin_root: Path) -> None:
    try:
        (plugin_root / LEDGER_FILENAME).unlink(missing_ok=True)
        plugin_root.rmdir()
    except OSError:
        # An empty ledger directory is harmless; the next install reuses it.
        return


def _reject_breaking_dependents(plugin_id: str, version: str, dest_root: Path) -> None:
    mismatched: list[tuple[str, str, str]] = []
    for dependent_id, dependent_version, requirement in _installed_requirements(dest_root):
        if requirement.plugin_id != plugin_id or dependent_id == plugin_id:
            continue
        if requirement.matches(version):
            continue
        mismatched.append((dependent_id, dependent_version, requirement.constraint))
    if mismatched:
        raise DependencyConstraintError(plugin_id, version, tuple(mismatched))


def _config_schema_of(plugin_root: Path, record: Mapping[str, Any] | None) -> dict[str, Any]:
    current = record or {}
    schema = current.get("config_schema")
    if isinstance(schema, Mapping):
        return dict(schema)
    envelope_path = plugin_root / str(current.get("slot") or "") / ENVELOPE_FILENAME
    if not envelope_path.is_file():
        return {}
    try:
        envelope = _load_json(envelope_path)
    except MarketError:
        return {}
    fallback = envelope.get("config_schema")
    return dict(fallback) if isinstance(fallback, Mapping) else {}


def _inspect_release(
    entry: MarketEntry, release: PluginRelease, source: Source
) -> ReleaseInspection:
    """Download the target release into a temp dir, read its envelope, discard it."""
    staging = Path(tempfile.mkdtemp(prefix=_STAGING_PREFIX))
    try:
        payload = source.install(entry, staging, release=release)
        envelope = build_envelope(
            entry=entry, release=release, payload=payload, installed_at=_utc_now()
        )
        return ReleaseInspection(
            capabilities=tuple(sorted(str(item) for item in envelope.get("capabilities") or ())),
            config_schema=dict(envelope.get("config_schema") or {}),
            files=payload.files,
            content_sha256=payload.content_sha256,
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _capabilities_of(plugin_root: Path, record: Mapping[str, Any] | None) -> tuple[str, ...]:
    if record is None:
        return ()
    envelope_path = plugin_root / str(record.get("slot") or "") / ENVELOPE_FILENAME
    if not envelope_path.is_file():
        return ()
    try:
        envelope = _load_json(envelope_path)
    except MarketError:
        return ()
    raw = envelope.get("capabilities")
    if not isinstance(raw, list):
        return ()
    return tuple(sorted(str(item) for item in raw))


def _record_files(plugin_root: Path, record: Mapping[str, Any] | None) -> int:
    if record is None:
        return 0
    slot = plugin_root / str(record.get("slot") or "")
    envelope_path = slot / ENVELOPE_FILENAME
    if envelope_path.is_file():
        try:
            envelope = _load_json(envelope_path)
        except MarketError:
            envelope = {}
        metadata = envelope.get("metadata")
        content = metadata.get("content") if isinstance(metadata, Mapping) else None
        files = content.get("files") if isinstance(content, Mapping) else None
        if isinstance(files, int):
            return files
    if slot.is_dir():
        return count_files(slot, exclude=envelope_index_excludes())
    return 0


def _dependency_impacts(
    plugin_id: str,
    version: str,
    dest_root: Path,
    *,
    uninstalling: bool = False,
) -> tuple[DependencyImpact, ...]:
    """Installed plugins that require ``plugin_id`` and how ``version`` affects them."""
    impacts: list[DependencyImpact] = []
    for dependent_id, dependent_version, requirement in _installed_requirements(dest_root):
        if requirement.plugin_id != plugin_id or dependent_id == plugin_id:
            continue
        matches = requirement.matches(version)
        impacts.append(
            DependencyImpact(
                plugin_id=dependent_id,
                version=dependent_version,
                constraint=requirement.constraint,
                satisfied_after=not matches if uninstalling else matches,
            )
        )
    return tuple(impacts)


def _slot_names(plugin_root: Path) -> set[str]:
    if not plugin_root.is_dir():
        return set()
    return {path.name for path in plugin_root.iterdir() if path.is_dir()}


def _remove_orphan_slots(plugin_root: Path, before: set[str]) -> None:
    """Drop slots created by a failed upgrade; committed slots are left alone."""
    if not plugin_root.is_dir():
        return
    keep = {str(item.get("slot") or "") for item in _records(_read_ledger(plugin_root))}
    for path in plugin_root.iterdir():
        if not path.is_dir() or path.name.startswith("."):
            continue
        if path.name in before or path.name in keep:
            continue
        shutil.rmtree(path, ignore_errors=True)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
