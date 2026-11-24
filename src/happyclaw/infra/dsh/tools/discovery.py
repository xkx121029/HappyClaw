"""Discover DSH plugins that may contribute read-only tools (S2).

Two sources only, both already owned by the plugin runtime:

* the market install root, read through :class:`MarketInstallSource` so the
  ledger's ``current`` slot decides which version is live;
* explicit local plugin directories, read through :class:`DshPluginLoader`.

No manifest parsing happens here. Nothing is imported from the plugin and no
JS is executed. Admission (``tool`` capability, no write/egress permission) is
applied before a plugin becomes a candidate, so disallowed plugins never reach
the provider or the registry.

Failure posture: a missing root, a broken ledger and an unexpected adapter
error each become a skip record. Discovery never raises, so a bad install can
neither hide other plugins nor block startup.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from happyclaw.infra.plugins.profile.market_source import MarketInstallSource
from happyclaw.infra.plugins.runtime.contract import PluginEnvelope, PluginKind
from happyclaw.infra.plugins.runtime.dsh_plugin import DshPluginLoader

from .gate import (
    SKIP_DISCOVERY_FAILED,
    SKIP_DUPLICATE,
    SKIP_INSTALL_BROKEN,
    SKIP_MARKET_ROOT_MISSING,
    SKIP_MARKET_SLOT_UNREADABLE,
    SKIP_NOT_TOOL,
    SKIP_UNSAFE_PERMISSION,
    blocking_permissions,
    is_tool_plugin,
    permission_name,
)

logger = logging.getLogger(__name__)

ORIGIN_MARKET = "market"
ORIGIN_LOCAL = "local"

_LEDGER = "index.json"


@dataclass(frozen=True, slots=True)
class DshToolSkip:
    """One plugin (or tool) that did not make it into the tool list."""

    plugin_id: str
    origin: str
    reason: str
    detail: str = ""
    tool: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "plugin_id": self.plugin_id,
            "origin": self.origin,
            "reason": self.reason,
            "detail": self.detail,
            "tool": self.tool,
        }


@dataclass(frozen=True, slots=True)
class DiscoveredPlugin:
    """A plugin that passed the read-only gate and may mount tools."""

    plugin_id: str
    origin: str
    location: str
    envelope: PluginEnvelope


def discover_dsh_plugins(
    *,
    market_root: str | Path | None = None,
    local_roots: Sequence[str | Path] = (),
) -> tuple[list[DiscoveredPlugin], list[DshToolSkip]]:
    """Return (mountable plugins, skip records); never raises."""

    candidates: dict[str, DiscoveredPlugin] = {}
    skipped: list[DshToolSkip] = []
    if market_root is not None:
        _discover_market(Path(market_root), candidates, skipped)
    roots = [Path(root).expanduser() for root in local_roots if str(root).strip()]
    if roots:
        _discover_local(roots, candidates, skipped)
    ordered = sorted(candidates.values(), key=lambda item: item.plugin_id)
    return ordered, skipped


def _discover_market(
    root: Path,
    candidates: dict[str, DiscoveredPlugin],
    skipped: list[DshToolSkip],
) -> None:
    if not root.is_dir():
        skipped.append(DshToolSkip("", ORIGIN_MARKET, SKIP_MARKET_ROOT_MISSING, str(root)))
        return
    try:
        source = MarketInstallSource(root)
        slots = source.installed_slots()
        broken = source.broken()
    except Exception as exc:  # pragma: no cover - defensive, adapters are read-only
        logger.warning("DSH market discovery failed under %s: %s", root, exc)
        skipped.append(DshToolSkip("", ORIGIN_MARKET, SKIP_DISCOVERY_FAILED, _describe(exc)))
        return

    touched: set[str] = set()
    for slot in sorted(slots.values(), key=lambda item: item.plugin_id):
        if slot.kind is not PluginKind.DSH:
            continue
        touched.add(_native_of(slot.plugin_id))
        _admit(slot.envelope, ORIGIN_MARKET, str(slot.slot), candidates, skipped)
    for plugin_id, reason in sorted(broken.items()):
        touched.add(_native_of(plugin_id))
        skipped.append(DshToolSkip(plugin_id, ORIGIN_MARKET, SKIP_INSTALL_BROKEN, reason))

    # ``installed_slots`` silently drops a plugin root whose ledger has no
    # readable ``current`` pointer. Enumerate the DSH install directories only to
    # report those, never to parse them ourselves.
    base = root / PluginKind.DSH.value
    for directory in _subdirectories(base):
        if directory.name in touched:
            continue
        skipped.append(
            DshToolSkip(
                f"{PluginKind.DSH.value}:{directory.name}",
                ORIGIN_MARKET,
                SKIP_MARKET_SLOT_UNREADABLE,
                f"no readable current slot in {_LEDGER}",
            )
        )


def _discover_local(
    roots: Sequence[Path],
    candidates: dict[str, DiscoveredPlugin],
    skipped: list[DshToolSkip],
) -> None:
    try:
        envelopes = DshPluginLoader().discover(roots=list(roots), strict=False)
    except Exception as exc:  # pragma: no cover - loader already swallows bad files
        logger.warning("DSH local discovery failed for %s: %s", roots, exc)
        skipped.append(DshToolSkip("", ORIGIN_LOCAL, SKIP_DISCOVERY_FAILED, _describe(exc)))
        return
    for envelope in envelopes:
        if envelope.kind is not PluginKind.DSH:
            continue
        if envelope.id in candidates:
            # The market copy is authoritative; the local one is shadowed.
            skipped.append(
                DshToolSkip(
                    envelope.id,
                    ORIGIN_LOCAL,
                    SKIP_DUPLICATE,
                    "already provided by market",
                )
            )
            continue
        _admit(
            envelope,
            ORIGIN_LOCAL,
            str(envelope.source.reference),
            candidates,
            skipped,
        )


def _admit(
    envelope: PluginEnvelope,
    origin: str,
    location: str,
    candidates: dict[str, DiscoveredPlugin],
    skipped: list[DshToolSkip],
) -> None:
    if not is_tool_plugin(envelope):
        skipped.append(
            DshToolSkip(
                envelope.id,
                origin,
                SKIP_NOT_TOOL,
                "plugin declares no 'tool' capability",
            )
        )
        return
    blocked = blocking_permissions(envelope)
    if blocked:
        skipped.append(
            DshToolSkip(
                envelope.id,
                origin,
                SKIP_UNSAFE_PERMISSION,
                ",".join(permission_name(kind) for kind in blocked),
            )
        )
        return
    candidates[envelope.id] = DiscoveredPlugin(
        plugin_id=envelope.id,
        origin=origin,
        location=location,
        envelope=envelope,
    )


def _subdirectories(base: Path) -> Iterator[Path]:
    if not base.is_dir():
        return
    try:
        entries = sorted(base.iterdir(), key=lambda path: path.name)
    except OSError:
        return
    for path in entries:
        if path.is_dir() and not path.name.startswith("."):
            yield path


def _native_of(plugin_id: str) -> str:
    return plugin_id.split(":", 1)[1] if ":" in plugin_id else plugin_id


def _describe(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


__all__ = ["DiscoveredPlugin", "DshToolSkip", "discover_dsh_plugins"]
