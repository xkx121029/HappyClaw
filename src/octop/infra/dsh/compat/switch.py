"""Switches for the DSH compatibility adapter.

Two opt-ins mirror the existing exec stage: ``OCTOP_DSH_COMPAT`` turns the
adapter on, and ``OCTOP_DSH_COMPAT_PLUGINS`` names the bundles allowed to run.
An empty allow-list means "inventory only": plugins can be classified but no
Node process is started.
"""

from __future__ import annotations

import os

ENV_COMPAT = "OCTOP_DSH_COMPAT"
ENV_PLUGINS = "OCTOP_DSH_COMPAT_PLUGINS"

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUTHY


def compat_enabled() -> bool:
    """True only when the host opted into the adapter."""

    return _flag(ENV_COMPAT)


def allowed_plugins(raw: str | None = None) -> frozenset[str]:
    """Parse ``OCTOP_DSH_COMPAT_PLUGINS``: comma-separated canonical ids."""

    value = os.environ.get(ENV_PLUGINS, "") if raw is None else raw
    return frozenset(part.strip() for part in value.split(",") if part.strip())


def _native_of(plugin_id: str) -> str:
    text = plugin_id.strip()
    return text[4:] if text.startswith("dsh:") else text


def plugin_allowed(plugin_id: str, raw: str | None = None) -> bool:
    """Whether a plugin id is covered by the allow-list.

    ``dsh:*`` grants every DSH bundle; a bare native id (``dsh-auto-memory``)
    and the canonical form (``dsh:dsh-auto-memory``) are equivalent.
    """

    if not compat_enabled():
        return False
    allowed = allowed_plugins(raw)
    native = _native_of(plugin_id)
    return "*" in allowed or f"dsh:*" in allowed or native in allowed
