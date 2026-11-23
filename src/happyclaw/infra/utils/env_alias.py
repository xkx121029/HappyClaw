"""Accept the pre-rename ``OCTOP_*`` environment variables under the new prefix.

Reader code now asks for ``HAPPYCLAW_*`` names. Deployments that still export
``OCTOP_*`` — the documented variables, docker compose files and the fnOS
packages all do — keep working because the process mirrors the old spelling onto
the new one once at import time and warns, so nothing changes silently.
"""

from __future__ import annotations

import os
import warnings
from collections.abc import MutableMapping

LEGACY_PREFIX = "OCTOP_"
CURRENT_PREFIX = "HAPPYCLAW_"

__all__ = ["CURRENT_PREFIX", "LEGACY_PREFIX", "alias_legacy_env", "current_env_name", "legacy_env_name"]

_warned: set[str] = set()


def current_env_name(legacy: str) -> str:
    """The post-rename spelling of an ``OCTOP_*`` variable name."""
    return CURRENT_PREFIX + legacy[len(LEGACY_PREFIX):]


def legacy_env_name(current: str) -> str:
    """The pre-rename spelling of a ``HAPPYCLAW_*`` variable name."""
    return LEGACY_PREFIX + current[len(CURRENT_PREFIX):]


def _warn(legacy: str, current: str) -> None:
    if legacy in _warned or os.environ.get("HAPPYCLAW_SILENCE_RENAME_NOTICE"):
        return
    _warned.add(legacy)
    warnings.warn(f"{legacy} is deprecated; set {current} instead", DeprecationWarning, stacklevel=3)


def alias_legacy_env(environ: MutableMapping[str, str] | None = None) -> list[str]:
    """Mirror every ``OCTOP_*`` variable onto its ``HAPPYCLAW_*`` name.

    An explicitly set new name always wins, so a half-migrated environment never
    silently reverts to the old value. Returns the new names that were filled in.
    """
    env: MutableMapping[str, str] = os.environ if environ is None else environ
    aliased: list[str] = []
    for name, value in list(env.items()):
        if not name.startswith(LEGACY_PREFIX) or len(name) == len(LEGACY_PREFIX):
            continue
        current = current_env_name(name)
        if current in env:
            if env[current] != value:
                _warn(name, current)
            continue
        env[current] = value
        aliased.append(current)
        _warn(name, current)
    return aliased


def env_get(suffix: str, default: str | None = None) -> str | None:
    """Read ``HAPPYCLAW_<suffix>``, falling back to the pre-rename ``OCTOP_<suffix>``."""
    current = CURRENT_PREFIX + suffix
    value = os.environ.get(current)
    if value is not None:
        return value
    legacy = LEGACY_PREFIX + suffix
    value = os.environ.get(legacy)
    if value is not None:
        _warn(legacy, current)
    return value if value is not None else default


def env_has(suffix: str) -> bool:
    """True when either spelling of the variable is set."""
    return CURRENT_PREFIX + suffix in os.environ or LEGACY_PREFIX + suffix in os.environ
