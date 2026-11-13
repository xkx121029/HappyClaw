"""Fixture manifests and their contract-aligned ``PluginEnvelope`` objects.

The fixtures keep each ecosystem's native manifest (``plugin.yaml`` for Octop,
``package.json`` for DSH). This module is the scaffold-side adapter: it turns
those manifests into the envelopes defined by
``octop.infra.plugins.runtime.contract``, so the fixture half of the contract is
verified even while the runtime adapters are still unimplemented.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from octop.infra.plugins.runtime import (
    PluginEnvelope,
    PluginKind,
    PluginSource,
    PluginSourceKind,
)

PLUGINS_ROOT = Path(__file__).resolve().parent / "fixtures" / "plugins"
OCTOP_FIXTURE_DIR = PLUGINS_ROOT / "octop_fixture"
DSH_FIXTURE_DIR = PLUGINS_ROOT / "dsh_fixture"
DSH_BARE_FIXTURE_DIR = PLUGINS_ROOT / "dsh_bare_fixture"

OCTOP_FIXTURE_ID = "octop:fixture-octop-tool"
DSH_FIXTURE_ID = "dsh:dsh-fixture-tool"
DSH_BARE_FIXTURE_ID = "dsh:dsh-fixture-bare"
EXPECTED_IDS: tuple[str, ...] = (
    OCTOP_FIXTURE_ID,
    DSH_FIXTURE_ID,
    DSH_BARE_FIXTURE_ID,
)


@dataclass(frozen=True)
class FixtureSpec:
    """One fixture plugin: its envelope, directory, and native manifest."""

    envelope: PluginEnvelope
    root: Path
    manifest_path: Path

    @property
    def entry_path(self) -> Path:
        return self.root / self.envelope.entry


def load_fixture_specs() -> tuple[FixtureSpec, ...]:
    """Load every fixture; raises when a manifest does not fit the contract."""
    return _octop_spec(), _dsh_spec(DSH_FIXTURE_DIR), _dsh_spec(DSH_BARE_FIXTURE_DIR)


def _octop_spec() -> FixtureSpec:
    manifest_path = OCTOP_FIXTURE_DIR / "plugin.yaml"
    manifest = _read_scalar_yaml(manifest_path)
    for key in ("id", "version", "entry", "kind"):
        if not manifest.get(key):
            raise ValueError(f"{manifest_path} is missing required field {key!r}")
    declared = manifest.get("capabilities")
    capabilities = _split_capabilities(declared or manifest["kind"])
    capabilities_declared = bool(declared or manifest["kind"])
    envelope = PluginEnvelope(
        id=f"octop:{manifest['id']}",
        kind=PluginKind.OCTOP,
        version=manifest["version"],
        entry=manifest["entry"],
        source=PluginSource(kind=PluginSourceKind.LOCAL, reference=str(manifest_path)),
        capabilities=capabilities,
        metadata={
            "native_manifest": "plugin.yaml",
            "native_kind": manifest["kind"],
            "name": manifest.get("name", manifest["id"]),
            "description": manifest.get("description", ""),
            "capabilities_declared": capabilities_declared,
            "capabilities_source": "manifest" if capabilities_declared else "undeclared",
        },
    )
    return FixtureSpec(envelope=envelope, root=OCTOP_FIXTURE_DIR, manifest_path=manifest_path)


def _dsh_spec(fixture_dir: Path) -> FixtureSpec:
    manifest_path = fixture_dir / "package.json"
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    bundle = (manifest.get("dsh") or {}).get("bundle")
    if not isinstance(bundle, dict):
        raise ValueError(f"{manifest_path} must declare dsh.bundle")
    for key in ("name", "version"):
        if not manifest.get(key):
            raise ValueError(f"{manifest_path} is missing required field {key!r}")
    # Expectation comes from the fixture's own manifest, never a hard-coded
    # value: adding a fixture must not require editing the smoke verdict.
    capabilities = _declared_capabilities(manifest)
    capabilities_declared = bool(capabilities)
    engine = (manifest.get("engines") or {}).get("dsh", "")
    envelope = PluginEnvelope(
        id=f"dsh:{manifest['name']}",
        kind=PluginKind.DSH,
        version=manifest["version"],
        entry=str(manifest.get("main") or "index.js"),
        source=PluginSource(kind=PluginSourceKind.LOCAL, reference=str(manifest_path)),
        capabilities=capabilities,
        metadata={
            "native_manifest": "package.json",
            "bundle_patch": str(bundle.get("patch", "")),
            "engine_dsh": str(engine),
            "capabilities_declared": capabilities_declared,
            "capabilities_source": "manifest" if capabilities_declared else "undeclared",
            "description": "DSH bundle fixture for integration smoke checks",
        },
    )
    return FixtureSpec(envelope=envelope, root=fixture_dir, manifest_path=manifest_path)


def _declared_capabilities(manifest: dict[str, Any]) -> tuple[str, ...]:
    raw = manifest.get("capabilities")
    if isinstance(raw, str):
        return tuple(part.strip() for part in raw.split(",") if part.strip())
    if isinstance(raw, (list, tuple)):
        return tuple(str(part).strip() for part in raw if str(part).strip())
    return ()


def _split_capabilities(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _read_scalar_yaml(path: Path) -> dict[str, str]:
    """Read the flat ``key: value`` subset used by the fixture manifest."""
    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition(":")
        if not separator:
            raise ValueError(f"{path}:{number} is not a 'key: value' line")
        values[key.strip()] = value.strip().strip("\"'")
    return values


__all__ = [
    "DSH_BARE_FIXTURE_DIR",
    "DSH_BARE_FIXTURE_ID",
    "DSH_FIXTURE_DIR",
    "DSH_FIXTURE_ID",
    "EXPECTED_IDS",
    "FixtureSpec",
    "OCTOP_FIXTURE_DIR",
    "OCTOP_FIXTURE_ID",
    "PLUGINS_ROOT",
    "load_fixture_specs",
]
