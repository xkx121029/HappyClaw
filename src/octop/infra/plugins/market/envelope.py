"""The unified install envelope written next to every installed plugin.

``plugin.json`` is exactly ``PluginEnvelope.to_dict()`` from
``octop.infra.plugins.runtime.contract`` -- the loader reads it without any
id or field rewriting. Market-only facts (catalog index, archive digest,
installed_at) live in ``metadata`` and in the sibling ``.market.json``.

``requires`` carries plugin-level dependencies only. Package dependencies,
``engines.dsh`` runtime constraints and raw catalog fields stay in metadata.
"""

from __future__ import annotations

from typing import Any, Mapping

from octop.infra.plugins.market.models import MarketEntry, PluginRelease
from octop.infra.plugins.market.source import InstalledPayload
from octop.infra.plugins.runtime.contract import (
    CapabilityKind,
    PluginEnvelope,
    PluginSource,
    PluginSourceKind,
    parse_permission_list,
)

ENVELOPE_FILENAME = "plugin.json"
MARKET_META_FILENAME = ".market.json"

_CAPABILITY_VALUES = {item.value for item in CapabilityKind}


def build_envelope(
    *,
    entry: MarketEntry,
    release: PluginRelease,
    payload: InstalledPayload,
    installed_at: str,
) -> dict[str, Any]:
    """Build the ``plugin.json`` object for one install slot."""
    capabilities = _capabilities(entry, payload.manifest)
    envelope = PluginEnvelope(
        id=entry.plugin_id,
        kind=entry.source,
        version=release.version,
        entry=payload.entry_path or payload.manifest_name,
        source=PluginSource(
            kind=PluginSourceKind.MARKET,
            reference=str(entry.extra.get("index_url") or entry.plugin_id),
        ),
        capabilities=capabilities,
        permissions=parse_permission_list(payload.manifest.get("permissions"))[0],
        config_schema=_config_schema(payload.manifest),
        requires=entry.requires,
        metadata=_metadata(entry, release, payload, installed_at),
    )
    return envelope.to_dict()


def _config_schema(manifest: Mapping[str, Any]) -> dict[str, Any]:
    schema = manifest.get("config_schema")
    return dict(schema) if isinstance(schema, Mapping) else {}


def _capabilities(
    entry: MarketEntry, manifest: Mapping[str, Any]
) -> tuple[CapabilityKind, ...]:
    declared: list[CapabilityKind] = list(entry.capabilities)
    bundle = manifest.get("dsh")
    if isinstance(bundle, dict):
        patch = bundle.get("bundle")
        if isinstance(patch, dict):
            raw = patch.get("capabilities")
            if isinstance(raw, list):
                for item in raw:
                    if isinstance(item, str) and item in _CAPABILITY_VALUES:
                        declared.append(CapabilityKind(item))
    return tuple(dict.fromkeys(declared))


def _metadata(
    entry: MarketEntry,
    release: PluginRelease,
    payload: InstalledPayload,
    installed_at: str,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "native_id": entry.native_id,
        "market": {
            "source": entry.source.value,
            "index": entry.extra.get("index_url"),
            "origin": entry.extra.get("origin"),
            "release": release.version,
        },
        "artifact": {
            "url": payload.artifact_url,
            "sha256": payload.archive_sha256,
            "size": payload.size,
            "checksum_verified": payload.checksum_verified,
        },
        "content": {
            "root": ".",
            "manifest": payload.manifest_name,
            "sha256": payload.content_sha256,
            "files": payload.files,
        },
        "installed_at": installed_at,
    }
    package = {
        key: entry.extra[key]
        for key in ("package_name", "group", "requires_raw", "ui", "metadata", "runtime")
        if entry.extra.get(key) is not None
    }
    python_requires = entry.extra.get("python_requires")
    if python_requires:
        metadata["python_requires"] = list(python_requires)
    if release.requires:
        package["runtime_constraints"] = dict(release.requires)
    if package:
        metadata["package"] = package
    return metadata


def envelope_index_excludes(envelope_filename: str = ENVELOPE_FILENAME) -> tuple[str, ...]:
    """Top-level entries that are install metadata, not plugin content."""
    return (envelope_filename, MARKET_META_FILENAME)
