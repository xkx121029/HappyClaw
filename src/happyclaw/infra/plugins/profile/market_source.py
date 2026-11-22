"""Discover installed plugins from the market install root.

Layout owned by ``happyclaw.infra.plugins.market``::

    <dest_root>/octop/<native>/index.json      # ledger: current slot + history
    <dest_root>/octop/<native>/<slot>/plugin.yaml
    <dest_root>/octop/<native>/<slot>/plugin.json
    <dest_root>/dsh/<native>/<slot>/package.json

Only the ledger's ``current`` slot is read, so an upgrade that keeps old slots
on disk still resolves to the new version. Nothing here writes, and the market
and adapter modules stay untouched.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from happyclaw.infra.plugins.runtime.contract import (
    PluginEnvelope,
    PluginKind,
    PluginLoader,
    PluginRequirement,
)
from happyclaw.infra.plugins.runtime.dsh_plugin import DshPluginLoader
from happyclaw.infra.plugins.runtime.octop_plugin import OctopPluginLoader

__all__ = ["InstalledSlot", "MarketInstallSource"]

logger = logging.getLogger(__name__)

_LEDGER = "index.json"
_ENVELOPE = "plugin.json"


@dataclass(frozen=True, slots=True)
class InstalledSlot:
    """One installed plugin selected by its ledger ``current`` pointer."""

    plugin_id: str
    kind: PluginKind
    version: str
    slot: Path
    envelope: PluginEnvelope


class MarketInstallSource:
    """Read installed plugins below ``dest_root`` as envelopes."""

    def __init__(
        self,
        dest_root: Path,
        *,
        adapters: Mapping[PluginKind, PluginLoader] | None = None,
    ) -> None:
        self._dest_root = Path(dest_root)
        if adapters is None:
            adapters = {
                PluginKind.OCTOP: OctopPluginLoader(),
                PluginKind.DSH: DshPluginLoader(),
            }
        self._adapters = dict(adapters)
        self._broken: dict[str, str] = {}

    @property
    def dest_root(self) -> Path:
        return self._dest_root

    def installed_slots(self) -> dict[str, InstalledSlot]:
        """Return the ``current`` slot of every installed plugin, keyed by id."""

        self._broken = {}
        slots: dict[str, InstalledSlot] = {}
        for kind, adapter in self._adapters.items():
            base = self._dest_root / kind.value
            if not base.is_dir():
                continue
            for plugin_root in sorted(
                path for path in base.iterdir() if path.is_dir() and not path.name.startswith(".")
            ):
                record, ledger_id = _current_record(plugin_root)
                if record is None:
                    continue
                plugin_id = ledger_id
                slot_name = str(record.get("slot") or "")
                slot = plugin_root / slot_name
                if not plugin_id or not slot_name or not slot.is_dir():
                    self._broken[plugin_id or plugin_root.name] = (
                        f"账本指向的安装目录不存在：{slot}"
                    )
                    continue
                try:
                    envelope = self._envelope_for(kind, adapter, plugin_id, slot)
                except Exception as exc:
                    self._broken[plugin_id] = f"安装目录无法解析：{exc}"
                    continue
                slots[envelope.id] = InstalledSlot(
                    plugin_id=envelope.id,
                    kind=kind,
                    version=envelope.version,
                    slot=slot,
                    envelope=envelope,
                )
        return slots

    def envelopes(self) -> dict[str, PluginEnvelope]:
        """Provider compatible with ``ProfileRuntime(envelope_provider=...)``."""

        return {
            plugin_id: slot.envelope
            for plugin_id, slot in self.installed_slots().items()
        }

    def broken(self) -> Mapping[str, str]:
        return dict(self._broken)

    def slot_for(self, plugin_id: str) -> Path | None:
        slot = self.installed_slots().get(plugin_id)
        return None if slot is None else slot.slot

    def _envelope_for(
        self,
        kind: PluginKind,
        adapter: PluginLoader,
        plugin_id: str,
        slot: Path,
    ) -> PluginEnvelope:
        discovered = adapter.discover(roots=[slot])
        native = next(
            (item for item in discovered if item.id == plugin_id),
            discovered[0] if len(discovered) == 1 else None,
        )
        if native is None:
            raise ValueError(f"{slot} 下没有发现 {plugin_id} 的 manifest")
        payload = _read_json(slot / _ENVELOPE)
        if not payload:
            return native
        requirements = _merge_requirements(
            native.requires, _market_requirements(payload.get("requires"))
        )
        metadata = payload.get("metadata")
        metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
        metadata.update(native.metadata)
        return replace(
            native,
            requires=requirements,
            metadata=metadata,
        )


def _current_record(plugin_root: Path) -> tuple[dict[str, Any] | None, str]:
    ledger = _read_json(plugin_root / _LEDGER)
    current = ledger.get("current")
    plugin_id = str(ledger.get("plugin_id") or "")
    if not isinstance(current, Mapping):
        return None, plugin_id
    return dict(current), plugin_id


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        logger.warning("无法读取 %s", path)
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _market_requirements(raw: Any) -> tuple[PluginRequirement, ...]:
    """Read ``plugin.json`` requirements, the catalog-level dependency record.

    The unified market envelope stores ``requires`` as objects, while the
    contract dataclass takes ``PluginRequirement`` values; native manifests do
    not always repeat catalog dependencies, so this merge keeps them visible.
    """

    if not isinstance(raw, list):
        return ()
    requirements: list[PluginRequirement] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        try:
            requirements.append(
                PluginRequirement(
                    str(item.get("plugin_id") or ""),
                    str(item.get("constraint") or "*"),
                )
            )
        except Exception:
            continue
    return tuple(requirements)


def _merge_requirements(
    native: tuple[PluginRequirement, ...],
    market: tuple[PluginRequirement, ...],
) -> tuple[PluginRequirement, ...]:
    """Combine native and catalog requirements, keeping the stricter version.

    The catalog often records a bare id (``*``) while ``plugin.yaml`` carries
    the real range such as ``>=1.0.0,<2.0.0``. A wildcard must never erase that
    range, otherwise an upgrade past the pin would silently look valid.
    """

    merged = {requirement.plugin_id: requirement for requirement in native}
    order = [requirement.plugin_id for requirement in native]
    for requirement in market:
        current = merged.get(requirement.plugin_id)
        if current is None:
            merged[requirement.plugin_id] = requirement
            order.append(requirement.plugin_id)
        elif current.constraint == "*" and requirement.constraint != "*":
            merged[requirement.plugin_id] = requirement
    return tuple(merged[plugin_id] for plugin_id in order)
