"""Reading plugin.yaml: UI surfaces, icon, group and version."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml

from octop.infra.agents.plugins.constants import (
    PLUGIN_UI_SLOTS,
    PLUGIN_UI_SURFACE_REASON_DUPLICATE,
    PLUGIN_UI_SURFACE_REASON_SLOT,
)

logger = logging.getLogger(__name__)


_ICON_FILE_SUFFIXES = {".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif"}

_MARKET_ASSET_SUFFIXES = frozenset({".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif"})

PLUGIN_GROUPS: frozenset[str] = frozenset(
    {
        "lifestyle",
        "news",
        "finance",
        "media",
        "fun",
        "games",
        "tools",
        "ops",
    },
)


def _read_plugin_yaml(plugin_dir: Path) -> dict[str, Any]:
    raw = yaml.safe_load((plugin_dir / "plugin.yaml").read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def parse_plugin_ui_meta(plugin_dir: Path) -> dict[str, Any] | None:
    """Return ``{entry, manifest, surfaces}`` when ``plugin.yaml`` declares ``ui``.

    Missing entry file → ``None`` (treat as backend-only). Harness ignores the
    ``ui`` key; Octop surfaces it for Dashboard dynamic loading.

    ``surfaces`` is additive: legacy plugins that only declare ``entry`` keep
    working, and a bad slot is reported instead of silently mounting nowhere.
    """
    try:
        data = _read_plugin_yaml(plugin_dir)
    except Exception:
        return None
    ui = data.get("ui")
    if not isinstance(ui, dict):
        return None
    entry = str(ui.get("entry") or "ui/dist/index.js").strip()
    manifest = str(ui.get("manifest") or "ui/dist/manifest.json").strip()
    if not entry or ".." in entry.replace("\\", "/").split("/"):
        return None
    if ".." in manifest.replace("\\", "/").split("/"):
        return None
    if not (plugin_dir / entry).is_file():
        logger.warning(
            "plugin %s declares ui.entry=%s but file is missing",
            plugin_dir.name,
            entry,
        )
        return None
    return {
        "entry": entry,
        "manifest": manifest,
        "surfaces": _parse_ui_surfaces(ui.get("surfaces")),
    }


def _parse_ui_surfaces(raw: Any) -> list[dict[str, Any]]:
    """Normalize the declarative surface list; never raises."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        surface_id = str(item.get("id") or "").strip()
        if not surface_id or re.fullmatch(r"[A-Za-z0-9._-]+", surface_id) is None:
            continue
        slot = str(item.get("slot") or "").strip()
        title = str(item.get("title") or "").strip() or surface_id
        duplicate = surface_id in seen
        if not duplicate:
            seen.add(surface_id)
        supported = slot in PLUGIN_UI_SLOTS and not duplicate
        reason_code = None
        if duplicate:
            reason_code = PLUGIN_UI_SURFACE_REASON_DUPLICATE
        elif slot not in PLUGIN_UI_SLOTS:
            reason_code = PLUGIN_UI_SURFACE_REASON_SLOT
        out.append(
            {
                "id": surface_id,
                "slot": slot,
                "title": title,
                "supported": supported,
                "reason_code": reason_code,
            }
        )
    return out


def parse_plugin_group(plugin_dir: Path) -> str | None:
    """Optional ``group`` slug from ``plugin.yaml`` (e.g. ``lifestyle``, ``games``)."""
    try:
        data = _read_plugin_yaml(plugin_dir)
    except Exception:
        return None
    raw = data.get("group")
    if raw is None:
        return None
    group = str(raw).strip().lower().replace("_", "-")
    if not group or len(group) > 64:
        return None
    if not all(ch.isalnum() or ch == "-" for ch in group):
        return None
    return group


def parse_plugin_icon(
    plugin_dir: Path,
    *,
    asset_prefix: str | None = None,
) -> str | None:
    """Optional ``icon`` from ``plugin.yaml`` for Dashboard cards.

    Accepts emoji text, absolute ``http(s)://`` / ``/api/...`` URLs, or a
    plugin-relative image path (e.g. ``icon.svg``) resolved to
    ``/api/plugins/{id}/ui/...`` (or ``asset_prefix`` when listing the market).
    """
    try:
        data = _read_plugin_yaml(plugin_dir)
    except Exception:
        return None
    raw = data.get("icon")
    if raw is None:
        return None
    icon = str(raw).strip()
    if not icon or len(icon) > 2048:
        return None
    if icon.startswith(("http://", "https://", "/api/", "data:image/")) or icon.startswith("//"):
        return icon
    # Relative image file shipped with the plugin package.
    cleaned = icon.lstrip("/").replace("\\", "/")
    if (
        cleaned
        and ".." not in cleaned.split("/")
        and Path(cleaned).suffix.lower() in _ICON_FILE_SUFFIXES
    ):
        target = (plugin_dir / cleaned).resolve()
        try:
            target.relative_to(plugin_dir.resolve())
        except ValueError:
            return icon
        if target.is_file():
            plugin_id = str(data.get("id") or plugin_dir.name).strip() or plugin_dir.name
            prefix = (asset_prefix or f"/api/plugins/{plugin_id}/ui").rstrip("/")
            return f"{prefix}/{cleaned}"
    return icon


def parse_plugin_requires(plugin_dir: Path) -> list[str]:
    try:
        data = _read_plugin_yaml(plugin_dir)
    except Exception:
        return []
    raw = data.get("requires") or []
    if not isinstance(raw, list):
        return []
    return [str(r).strip() for r in raw if str(r).strip()]


def _read_installed_version(plugin_dir: Path) -> str | None:
    try:
        data = _read_plugin_yaml(plugin_dir)
    except Exception:
        return None
    ver = data.get("version")
    if ver is None:
        return None
    text = str(ver).strip()
    return text or None


def _read_tree(root: Path) -> list[tuple[str, bytes]]:
    payloads: list[tuple[str, bytes]] = []
    if not root.is_dir():
        return payloads
    for dirpath, _dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        for filename in filenames:
            path = current / filename
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                payloads.append((path.relative_to(root).as_posix(), path.read_bytes()))
            except OSError:
                continue
    return payloads


def _version_tuple(version: str | None) -> tuple[int, ...]:
    ver = str(version or "0").strip() or "0"
    parts: list[int] = []
    for bit in ver.split("."):
        try:
            parts.append(int(bit))
        except ValueError:
            parts.append(0)
    return tuple(parts) or (0,)
