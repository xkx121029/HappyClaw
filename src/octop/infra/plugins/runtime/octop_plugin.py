"""Adapter that maps existing Octop plugins onto the unified contract.

Discovery is read-only: it reads ``plugin.yaml`` files and never imports plugin
entry points. The existing ``happyclaw_harness`` loader remains the only code path
that executes Octop plugins, so behavior of installed plugins is unchanged.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import yaml
from happyclaw_harness.plugins import PluginManifest

from octop.infra.agents.plugins.bundled import default_bundled_plugins_root
from octop.infra.plugins.runtime._activation import (
    ActivationStore,
    ensure_entry_available,
)
from octop.infra.plugins.runtime.contract import (
    ActivationContext,
    CapabilityKind,
    InvalidManifestError,
    PluginEnvelope,
    PluginHandle,
    PluginKind,
    PluginRequirement,
    PluginSource,
    PluginSourceKind,
    VersionConflictError,
    canonical_plugin_id,
    parse_permission_list,
)

logger = logging.getLogger(__name__)

_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}


def _default_roots() -> list[Path]:
    return [
        default_bundled_plugins_root(),
        Path.home() / ".octop" / "plugins",
    ]


def _manifest_paths(roots: Iterable[str | Path]) -> list[Path]:
    """Return ``plugin.yaml`` paths below the given roots, deterministically."""

    found: list[Path] = []
    for raw_root in roots:
        root = Path(raw_root).expanduser()
        if root.is_file():
            if root.name == "plugin.yaml":
                found.append(root)
            continue
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(name for name in dirnames if name not in _SKIP_DIRS)
            if "plugin.yaml" in filenames:
                found.append(Path(dirpath) / "plugin.yaml")
    return sorted(dict.fromkeys(found), key=str)


def _parse_plugin_requirement(text: str) -> PluginRequirement | None:
    """Parse ``<octop|dsh>:<native>`` plus an optional version constraint.

    ``plugin.yaml`` declares ``requires`` as *pip* packages, so it has no
    plugin-to-plugin dependency field. Writing a canonical id in the same list
    is the supported extension point; anything that is not plugin-shaped stays a
    Python requirement and is surfaced through ``metadata.python_requires``.
    """

    plugin_id = text
    constraint = "*"
    for index, char in enumerate(text):
        if char in "=<>!~":
            plugin_id = text[:index].strip()
            constraint = text[index:].strip()
            break
    if not plugin_id.startswith(("octop:", "dsh:")):
        return None
    return PluginRequirement(plugin_id, constraint or "*")


def _split_requires(raw: Any) -> tuple[tuple[PluginRequirement, ...], tuple[str, ...]]:
    """Split native ``requires`` into plugin dependencies and pip packages."""

    if not isinstance(raw, (list, tuple)):
        return (), ()
    plugin_requires: list[PluginRequirement] = []
    python_requires: list[str] = []
    for entry in raw:
        text = str(entry).strip()
        if not text:
            continue
        requirement = _parse_plugin_requirement(text)
        if requirement is None:
            python_requires.append(text)
        else:
            plugin_requires.append(requirement)
    return tuple(plugin_requires), tuple(python_requires)


def _capabilities(
    raw: Mapping[str, Any],
    native_kind: str,
) -> tuple[tuple[CapabilityKind, ...], bool]:
    """Return capabilities declared by the manifest and whether they were declared.

    ``kind`` and an explicit ``capabilities`` list are declarations. A manifest
    with neither must stay empty: inferred values would be treated as granted
    permissions by the sandbox gate.
    """

    declared = raw.get("capabilities")
    if isinstance(declared, str):
        values = [part.strip().lower() for part in declared.split(",") if part.strip()]
    elif isinstance(declared, (list, tuple)):
        values = [str(part).strip().lower() for part in declared if str(part).strip()]
    else:
        values = []
    if values:
        try:
            return tuple(dict.fromkeys(CapabilityKind(value) for value in values)), True
        except ValueError as exc:
            raise InvalidManifestError(
                "unsupported plugin capability",
                details={"capabilities": values},
            ) from exc
    if str(raw.get("kind") or "").strip():
        return (CapabilityKind(native_kind),), True
    return (), False


def _envelope_from_manifest(manifest_path: Path) -> PluginEnvelope:
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise InvalidManifestError(
            "plugin manifest cannot be read",
            details={"path": str(manifest_path)},
        ) from exc
    if not isinstance(raw, dict):
        raise InvalidManifestError(
            "plugin manifest must be a mapping",
            details={"path": str(manifest_path)},
        )
    try:
        manifest = PluginManifest.from_dict(raw)
    except ValueError as exc:
        raise InvalidManifestError(
            str(exc),
            details={"path": str(manifest_path)},
        ) from exc

    capabilities, capabilities_declared = _capabilities(raw, manifest.kind)
    permissions, permissions_declared = parse_permission_list(raw.get("permissions"))
    requires, python_requires = _split_requires(raw.get("requires"))
    ui = raw.get("ui")
    ui_entry = str(ui.get("entry") or "").strip() if isinstance(ui, dict) else ""
    if ui_entry:
        # ``ui.entry`` is an explicit manifest field, so the panel is declared.
        capabilities_declared = True
        if CapabilityKind.PANEL not in capabilities:
            capabilities = (*capabilities, CapabilityKind.PANEL)

    metadata: dict[str, Any] = {
        "native_manifest": "plugin.yaml",
        "native_kind": manifest.kind,
        "name": manifest.name,
        "description": manifest.description,
        "plugin_dir": str(manifest_path.parent),
        "python_requires": list(python_requires),
        "capabilities_declared": capabilities_declared,
        "capabilities_source": "manifest" if capabilities_declared else "undeclared",
        "permissions_declared": permissions_declared,
        "permissions_source": "manifest" if permissions_declared else "undeclared",
    }
    if ui_entry:
        metadata["ui_entry"] = ui_entry

    return PluginEnvelope(
        id=canonical_plugin_id(PluginKind.OCTOP, manifest.id),
        kind=PluginKind.OCTOP,
        version=manifest.version,
        entry=manifest.entry,
        source=PluginSource(
            kind=PluginSourceKind.LOCAL,
            reference=str(manifest_path),
        ),
        capabilities=capabilities,
        permissions=permissions,
        config_schema=(
            raw.get("config_schema")
            if isinstance(raw.get("config_schema"), dict)
            else {}
        ),
        requires=requires,
        metadata=metadata,
    )


class OctopPluginLoader:
    """Unified loader facade for Octop's existing ``plugin.yaml`` plugins."""

    kind = PluginKind.OCTOP

    def __init__(self) -> None:
        self._store = ActivationStore(PluginKind.OCTOP)

    def discover(
        self,
        roots: Sequence[str | Path] | None = None,
        *,
        strict: bool = False,
    ) -> list[PluginEnvelope]:
        """Map every ``plugin.yaml`` below ``roots`` to an envelope.

        ``strict`` re-raises manifest/duplicate errors; the default keeps a bad
        plugin from hiding all other plugins and reports it through logging.
        """

        envelopes: list[PluginEnvelope] = []
        seen: dict[str, PluginEnvelope] = {}
        for manifest_path in _manifest_paths(roots or _default_roots()):
            try:
                envelope = _envelope_from_manifest(manifest_path)
            except InvalidManifestError as exc:
                if strict:
                    raise
                logger.warning("skip invalid Octop plugin %s: %s", manifest_path, exc)
                continue

            previous = seen.get(envelope.id)
            if previous is not None:
                if previous.version != envelope.version and strict:
                    raise VersionConflictError(
                        "duplicate Octop plugin with different versions",
                        details={
                            "plugin_id": envelope.id,
                            "first": previous.version,
                            "second": envelope.version,
                        },
                    )
                logger.warning(
                    "skip duplicate Octop plugin %s at %s",
                    envelope.id,
                    manifest_path,
                )
                continue
            seen[envelope.id] = envelope
            envelopes.append(envelope)
        return envelopes

    def activate(self, envelope: PluginEnvelope, ctx: ActivationContext) -> PluginHandle:
        ensure_entry_available(envelope)
        return self._store.activate(envelope, ctx)

    def deactivate(self, handle: PluginHandle) -> None:
        self._store.deactivate(handle)


__all__ = ["OctopPluginLoader"]
