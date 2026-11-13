"""Normalized market records shared by every catalog source.

``MarketEntry.plugin_id`` is always the runtime-canonical id from
``octop.infra.plugins.runtime.contract`` (``octop:<native>`` / ``dsh:<native>``)
so an installed envelope needs no id rewriting before the loader sees it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from octop.infra.plugins.market.errors import MarketError, ReleaseNotFound
from octop.infra.plugins.market.versions import compare_versions, is_prerelease
from octop.infra.plugins.runtime.contract import (
    CapabilityKind,
    PluginKind,
    PluginRequirement,
    split_plugin_id,
)

#: Tie-break order when two catalogs publish the same plugin id and version.
#: The octop market wins because its packages already carry ``plugin.yaml``.
SOURCE_PRIORITY: Mapping[PluginKind, int] = {
    PluginKind.OCTOP: 100,
    PluginKind.DSH: 10,
}


@dataclass(frozen=True, slots=True)
class Artifact:
    """Download location and published integrity data for one release."""

    url: str
    sha256: str | None = None
    size: int | None = None
    media_type: str = "application/zip"


@dataclass(frozen=True, slots=True)
class PluginRelease:
    """One installable version of a plugin."""

    version: str
    artifact: Artifact
    published_at: int | None = None
    #: Runtime constraints declared by the catalog, e.g. ``{"dsh": ">=0.2.0"}``.
    #: These are *not* plugin dependencies and never enter envelope ``requires``.
    requires: Mapping[str, str] = field(default_factory=dict)
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MarketEntry:
    """One plugin as listed by one catalog, normalized across markets."""

    plugin_id: str
    source: PluginKind
    name: str
    description: str
    capabilities: tuple[CapabilityKind, ...]
    releases: tuple[PluginRelease, ...]
    #: Plugin-level dependencies only; package dependencies stay in ``extra``.
    requires: tuple[PluginRequirement, ...] = ()
    homepage: str | None = None
    icon: str | None = None
    tags: tuple[str, ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        kind, _native = split_plugin_id(self.plugin_id)
        if kind is not self.source:
            raise MarketError(
                f"entry {self.plugin_id!r} does not belong to source {self.source.value!r}"
            )

    @property
    def native_id(self) -> str:
        return split_plugin_id(self.plugin_id)[1]

    @property
    def priority(self) -> int:
        return SOURCE_PRIORITY[self.source]

    @property
    def version(self) -> str:
        return self.release().version

    def release(self, version: str | None = None) -> PluginRelease:
        """Return one release; ``None`` picks the catalog's recommended release."""
        if not self.releases:
            raise MarketError(f"plugin {self.plugin_id!r} lists no releases")
        if version is None:
            return recommended_release(self.releases)
        for release in self.releases:
            if release.version == version:
                return release
        raise ReleaseNotFound(self.plugin_id, version)


@dataclass(frozen=True, slots=True)
class RejectedEntry:
    """One catalog row that could not be normalized, kept for diagnostics.

    ``raw`` holds the row exactly as the catalog returned it (or the offending
    value when the row was not an object). ``reason`` is the original Chinese
    error message and ``suggestion`` says how to repair the row, so a portal
    owner can fix the catalog without reading this module.
    """

    plugin_id: str | None
    raw: Any
    error_code: str
    reason: str
    suggestion: str


def recommended_release(releases: tuple[PluginRelease, ...]) -> PluginRelease:
    """Highest stable release; highest prerelease when no stable release exists."""
    stable = [item for item in releases if not is_prerelease(item.version)]
    return _highest(stable or list(releases))


def _highest(releases: list[PluginRelease]) -> PluginRelease:
    best = releases[0]
    for candidate in releases[1:]:
        comparison = compare_versions(candidate.version, best.version)
        if comparison is not None and comparison > 0:
            best = candidate
    return best
