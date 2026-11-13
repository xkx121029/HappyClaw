"""Adapter that maps DSH bundle manifests onto the unified contract.

Only manifest-level parsing happens here: ``package.json`` plus the sibling
``cordis.patch.yml``. The DSH TypeScript runtime is never imported or executed;
entry rows are kept as graph metadata so later integration lines can decide how
to activate them.

``!!js`` values in DSH patches are preserved as ``{"$js": "<expression>"}``
instead of being evaluated. PyYAML's default safe loader rejects that tag, so a
dedicated loader is registered below.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

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
    PluginLoadError,
    PluginRequirement,
    PluginSource,
    PluginSourceKind,
    VersionConflictError,
    canonical_plugin_id,
    parse_permission_list,
    version_satisfies,
)

logger = logging.getLogger(__name__)

_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "lib",
    "node_modules",
}
_DEFAULT_PATCH = "cordis.patch.yml"
# Bundles do not ship an ``engines`` field, but the harness itself requires
# Node >= 24.9 (root package.json). Record it on every bundle so activation can
# refuse a host that cannot run it.
_DEFAULT_NODE_ENGINE = ">=24.9.0"


class _DshYamlLoader(yaml.SafeLoader):
    """Safe loader that keeps ``!!js`` expressions as data."""


def _construct_js(loader: _DshYamlLoader, node: yaml.Node) -> dict[str, str]:
    return {"$js": loader.construct_scalar(node)}


_DshYamlLoader.add_constructor("tag:yaml.org,2002:js", _construct_js)


@dataclass(frozen=True, slots=True)
class _BundleRow:
    id: str
    name: str
    disabled: Any
    immediately: Any
    inject: tuple[str, ...]
    config: Mapping[str, Any]
    named: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "disabled": self.disabled,
            "immediately": self.immediately,
            "inject": list(self.inject),
            "config": dict(self.config),
        }


def _default_roots() -> list[Path]:
    raw = os.environ.get("DSH_HARNESS_ROOT", "").strip()
    return [Path(raw).expanduser()] if raw else []


_host_node_version_cache: list[str | None] = []


def _host_node_version() -> str | None:
    """Probe ``node --version`` once; plugin code is never executed."""

    if _host_node_version_cache:
        return _host_node_version_cache[0]
    version: str | None = None
    try:
        completed = subprocess.run(
            ["node", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        completed = None
    if completed is not None and completed.returncode == 0:
        version = completed.stdout.strip().lstrip("v") or None
    _host_node_version_cache.append(version)
    return version


def _node_version(ctx: ActivationContext) -> str | None:
    supplied = ctx.services.get("node_version") if ctx.services else None
    if isinstance(supplied, str) and supplied.strip():
        return supplied.strip().lstrip("v")
    return _host_node_version()


def _ensure_engine(envelope: PluginEnvelope, ctx: ActivationContext) -> None:
    """Refuse activation when the host cannot satisfy ``required_engines``."""

    required = (envelope.metadata.get("required_engines") or {}).get("node")
    if not isinstance(required, str) or not required.strip():
        return
    actual = _node_version(ctx)
    if actual is not None and version_satisfies(actual, required):
        return
    raise PluginLoadError(
        "host node runtime does not satisfy the bundle requirement",
        details={
            "plugin_id": envelope.id,
            "reason": "engine_unsatisfied",
            "engine": "node",
            "required": required,
            "actual": actual,
        },
    )


def _package_json_paths(roots: Iterable[str | Path]) -> list[Path]:
    found: list[Path] = []
    for raw_root in roots:
        root = Path(raw_root).expanduser()
        if root.is_file():
            if root.name == "package.json":
                found.append(root)
            continue
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(name for name in dirnames if name not in _SKIP_DIRS)
            if "package.json" in filenames:
                found.append(Path(dirpath) / "package.json")
    return sorted(dict.fromkeys(found), key=str)


def _parse_patch(patch_path: Path) -> tuple[list[_BundleRow], dict[str, dict[str, Any]]]:
    try:
        raw = yaml.load(patch_path.read_text(encoding="utf-8"), Loader=_DshYamlLoader)
    except (OSError, yaml.YAMLError) as exc:
        raise InvalidManifestError(
            "DSH bundle patch cannot be read",
            details={"path": str(patch_path)},
        ) from exc
    if raw is None:
        return [], {}
    if not isinstance(raw, list):
        raise InvalidManifestError(
            "DSH bundle patch must be a list of operations",
            details={"path": str(patch_path)},
        )

    rows: dict[str, _BundleRow] = {}
    for item in raw:
        if not isinstance(item, dict):
            raise InvalidManifestError(
                "DSH bundle patch entries must be mappings",
                details={"path": str(patch_path)},
            )
        if "insert" in item:
            inserted = item["insert"]
            if not isinstance(inserted, list):
                raise InvalidManifestError(
                    "'insert' must contain a list of entries",
                    details={"path": str(patch_path)},
                )
            candidates = inserted
        else:
            # Whole-row patches (used by bundle presets) target an existing id.
            candidates = [item]

        for row in candidates:
            if not isinstance(row, dict):
                raise InvalidManifestError(
                    "DSH bundle row must be a mapping",
                    details={"path": str(patch_path)},
                )
            entry_id = str(row.get("id") or "").strip()
            if not entry_id:
                raise InvalidManifestError(
                    "DSH bundle row is missing 'id'",
                    details={"path": str(patch_path)},
                )
            inject = row.get("inject") or []
            if isinstance(inject, str):
                inject_values = (inject,)
            elif isinstance(inject, list):
                inject_values = tuple(str(value) for value in inject)
            else:
                raise InvalidManifestError(
                    "'inject' must be a string or list",
                    details={"path": str(patch_path), "entry": entry_id},
                )
            config = row.get("config") or {}
            if not isinstance(config, dict):
                raise InvalidManifestError(
                    "'config' must be a mapping",
                    details={"path": str(patch_path), "entry": entry_id},
                )
            # ``disabled``/``immediately`` may be ``!!js`` expressions. Keep the
            # raw value (``{"$js": ...}``) instead of coercing to bool, so the
            # expression survives for the line that eventually evaluates it.
            explicit_name = str(row.get("name") or "").strip()
            rows[entry_id] = _BundleRow(
                id=entry_id,
                name=explicit_name or entry_id,
                disabled=row.get("disabled", False),
                immediately=row.get("immediately", False),
                inject=inject_values,
                config=config,
                named=bool(explicit_name),
            )

    graph = {
        row.id: {
            "injects": list(row.inject),
            "disabled": row.disabled,
        }
        for row in rows.values()
    }
    return list(rows.values()), graph


def _native_id(package_name: str) -> str:
    short = package_name.rsplit("/", 1)[-1].strip()
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "-", short)
    cleaned = cleaned.lstrip("._-")
    return cleaned or "unnamed"


_PACKAGE_NAME_RE = re.compile(
    r"^(?:@[A-Za-z0-9][A-Za-z0-9._-]*/)?[A-Za-z0-9][A-Za-z0-9._-]*$"
)


def _dependency_constraint(dependencies: Mapping[str, Any], name: str) -> str:
    """Return the npm-level version constraint declared for a bundled package."""

    raw = dependencies.get(name)
    if not isinstance(raw, str) or not raw.strip():
        return "*"
    text = raw.strip()
    if text.startswith("workspace:"):
        text = text[len("workspace:") :]
    return text or "*"


def _row_package_name(name: str) -> str:
    """Strip a subpath export (``@scope/pkg/startup``) down to the package name."""

    parts = name.split("/")
    if name.startswith("@") and len(parts) >= 2:
        return "/".join(parts[:2])
    return parts[0]


def _split_bundle_rows(
    rows: Sequence[_BundleRow],
    plugin_id: str,
    external_bundles: Mapping[str, str],
    dependencies: Mapping[str, Any],
) -> tuple[tuple[PluginRequirement, ...], tuple[dict[str, str], ...]]:
    """Split composed rows into external bundle dependencies and internal packages.

    Only a row pointing at another package that is itself discovered as a bundle
    becomes a ``requires`` entry. Everything the bundle composes internally stays
    in ``metadata.bundled_plugins`` (diagnostics only): the bundle is responsible
    for those packages, so a missing one is an installation-integrity problem,
    not an unresolvable dependency. Rows without ``name`` are whole-row patches
    that retune an existing entry and reference no package at all.
    """

    requires: dict[str, PluginRequirement] = {}
    bundled: dict[str, dict[str, str]] = {}
    for row in rows:
        if not row.named:
            continue
        package_name = _row_package_name(row.name)
        if not _PACKAGE_NAME_RE.match(package_name):
            continue
        dependency_id = canonical_plugin_id(PluginKind.DSH, _native_id(package_name))
        if dependency_id == plugin_id:
            continue
        if package_name in external_bundles:
            requires.setdefault(dependency_id, PluginRequirement(dependency_id, "*"))
            continue
        bundled.setdefault(
            package_name,
            {
                "name": package_name,
                "constraint": _dependency_constraint(dependencies, package_name),
            },
        )
    return tuple(requires.values()), tuple(bundled.values())


def _declared_capabilities(
    manifest: Mapping[str, Any],
) -> tuple[CapabilityKind, ...]:
    """Read an explicit ``capabilities`` list from package.json.

    Native DSH bundles ship no such field, but integrations that need sandbox
    permissions must declare them; package-name heuristics never qualify.
    """

    raw = manifest.get("capabilities")
    if isinstance(raw, str):
        values = [part.strip().lower() for part in raw.split(",") if part.strip()]
    elif isinstance(raw, (list, tuple)):
        values = [str(part).strip().lower() for part in raw if str(part).strip()]
    else:
        values = []
    try:
        return tuple(dict.fromkeys(CapabilityKind(value) for value in values))
    except ValueError as exc:
        raise InvalidManifestError(
            "unsupported declared capability",
            details={"capabilities": values},
        ) from exc


def _infer_capabilities(package_name: str) -> tuple[CapabilityKind, ...]:
    text = package_name.lower()
    checks = (
        ("tool", CapabilityKind.TOOL),
        ("skill", CapabilityKind.SKILL),
        ("provider", CapabilityKind.PROVIDER),
        ("llm", CapabilityKind.PROVIDER),
        ("panel", CapabilityKind.PANEL),
        ("ui-", CapabilityKind.PANEL),
        ("channel", CapabilityKind.CHANNEL),
        ("hook", CapabilityKind.HOOK),
    )
    for needle, capability in checks:
        if needle in text:
            return (capability,)
    return (CapabilityKind.SERVICE,)


def _envelope_from_package(
    package_path: Path,
    manifest: Mapping[str, Any],
    bundle: Mapping[str, Any],
    patch_path: Path,
    external_bundles: Mapping[str, str],
) -> PluginEnvelope:
    package_name = str(manifest.get("name") or "").strip()
    version = str(manifest.get("version") or "").strip()
    if not package_name:
        raise InvalidManifestError(
            "DSH package.json is missing 'name'",
            details={"path": str(package_path)},
        )
    if not version:
        raise InvalidManifestError(
            "DSH package.json is missing 'version'",
            details={"path": str(package_path)},
        )

    rows, graph = _parse_patch(patch_path)
    engines = manifest.get("engines")
    if not isinstance(engines, Mapping):
        engines = {}
    declared_node = engines.get("node")
    if isinstance(declared_node, str) and declared_node.strip():
        required_engines = {"node": declared_node.strip(), "source": "manifest"}
    else:
        required_engines = {"node": _DEFAULT_NODE_ENGINE, "source": "default"}
    dependencies = manifest.get("dependencies") or {}
    if not isinstance(dependencies, Mapping):
        dependencies = {}
    plugin_id = canonical_plugin_id(PluginKind.DSH, _native_id(package_name))
    requires, bundled_plugins = _split_bundle_rows(
        rows, plugin_id, external_bundles, dependencies
    )
    # DSH has no capability declaration; package-name heuristics are surfaced as
    # inferred metadata only and never enter ``capabilities`` (sandbox gate).
    capabilities = _declared_capabilities(manifest)
    capabilities_declared = bool(capabilities)
    inferred_capabilities = _infer_capabilities(package_name)
    # Permissions are a separate vocabulary (what the sandbox may let it touch)
    # and are never derived from capabilities or the package name.
    permissions, permissions_declared = parse_permission_list(
        manifest.get("permissions")
    )

    return PluginEnvelope(
        id=plugin_id,
        kind=PluginKind.DSH,
        version=version,
        entry=str(manifest.get("main") or "index.js"),
        source=PluginSource(
            kind=PluginSourceKind.LOCAL,
            reference=str(package_path),
        ),
        capabilities=capabilities,
        permissions=permissions,
        config_schema={},
        requires=requires,
        metadata={
            "native_manifest": "package.json",
            "package_name": package_name,
            "bundle_patch": str(patch_path),
            "engine_dsh": str(engines.get("dsh") or ""),
            "required_engines": required_engines,
            "capabilities_declared": capabilities_declared,
            "capabilities_source": "manifest" if capabilities_declared else "undeclared",
            "inferred_capabilities": [item.value for item in inferred_capabilities],
            "permissions_declared": permissions_declared,
            "permissions_source": "manifest" if permissions_declared else "undeclared",
            "description": str(manifest.get("description") or ""),
            "entries": [row.to_dict() for row in rows],
            "entry_graph": graph,
            "bundled_plugins": list(bundled_plugins),
            "immediately": bundle.get("immediately", False) is True
            or any(row.immediately is True for row in rows),
            "npm_dependencies": dict(dependencies),
        },
    )


class DshPluginLoader:
    """Unified loader facade for DSH ``bundle/*`` manifests.

    ``DSH_HARNESS_ROOT`` may point at a DSH checkout (or any directory tree);
    callers can also inject explicit roots. Nothing is executed.
    """

    kind = PluginKind.DSH

    def __init__(self) -> None:
        self._store = ActivationStore(PluginKind.DSH)

    def discover(
        self,
        roots: Sequence[str | Path] | None = None,
        *,
        strict: bool = False,
    ) -> list[PluginEnvelope]:
        candidates: list[tuple[Path, dict[str, Any], dict[str, Any], Path]] = []
        for package_path in _package_json_paths(roots or _default_roots()):
            try:
                manifest = json.loads(package_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                if strict:
                    raise InvalidManifestError(
                        "DSH package.json cannot be read",
                        details={"path": str(package_path)},
                    ) from exc
                continue
            if not isinstance(manifest, dict):
                if strict:
                    raise InvalidManifestError(
                        "DSH package.json must be an object",
                        details={"path": str(package_path)},
                    )
                continue

            bundle = (manifest.get("dsh") or {}).get("bundle")
            if bundle is not None and not isinstance(bundle, dict):
                if strict:
                    raise InvalidManifestError(
                        "dsh.bundle must be an object",
                        details={"path": str(package_path)},
                    )
                continue

            if isinstance(bundle, dict):
                patch_value = str(bundle.get("patch") or _DEFAULT_PATCH)
                patch_path = (package_path.parent / patch_value).resolve()
            else:
                patch_path = package_path.parent / _DEFAULT_PATCH

            if not patch_path.is_file():
                # Not a DSH bundle package (most packages in a DSH checkout).
                continue
            candidates.append(
                (package_path, manifest, bundle if isinstance(bundle, dict) else {}, patch_path)
            )

        # Only packages that are themselves discoverable bundles can satisfy a
        # bundle-to-bundle reference; everything else a patch composes counts as
        # an internal package of the bundle that owns the row.
        external_bundles: dict[str, str] = {}
        for _, manifest, _, _ in candidates:
            name = str(manifest.get("name") or "").strip()
            version = str(manifest.get("version") or "").strip()
            if name and version:
                external_bundles.setdefault(name, version)

        envelopes: list[PluginEnvelope] = []
        seen: dict[str, PluginEnvelope] = {}
        for package_path, manifest, bundle, patch_path in candidates:
            try:
                envelope = _envelope_from_package(
                    package_path,
                    manifest,
                    bundle,
                    patch_path,
                    external_bundles,
                )
            except InvalidManifestError as exc:
                if strict:
                    raise
                logger.warning("skip invalid DSH bundle %s: %s", package_path, exc)
                continue

            previous = seen.get(envelope.id)
            if previous is not None:
                if previous.version != envelope.version and strict:
                    raise VersionConflictError(
                        "duplicate DSH bundle with different versions",
                        details={
                            "plugin_id": envelope.id,
                            "first": previous.version,
                            "second": envelope.version,
                        },
                    )
                logger.debug("skip duplicate DSH bundle %s", envelope.id)
                continue
            seen[envelope.id] = envelope
            envelopes.append(envelope)
        return envelopes

    def activate(self, envelope: PluginEnvelope, ctx: ActivationContext) -> PluginHandle:
        ensure_entry_available(envelope)
        _ensure_engine(envelope, ctx)
        return self._store.activate(envelope, ctx)

    def deactivate(self, handle: PluginHandle) -> None:
        self._store.deactivate(handle)


__all__ = ["DshPluginLoader"]
