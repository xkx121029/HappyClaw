"""Keep the pre-rename ``OCTOP_*`` environment variables working under the new prefix.

Readers across the codebase still ask for ``OCTOP_*`` names. Rather than touch
every call site, the process mirrors each ``HAPPYCLAW_*`` variable onto its
``OCTOP_*`` twin at startup when the old name is unset, so both spellings select
the same value and existing deployments keep working unchanged.
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping

LEGACY_PREFIX = "OCTOP_"
CURRENT_PREFIX = "HAPPYCLAW_"

__all__ = ["LEGACY_PREFIX", "CURRENT_PREFIX", "alias_legacy_env", "legacy_env_name"]


def legacy_env_name(name: str) -> str:
    """Return the pre-rename spelling of a ``HAPPYCLAW_*`` variable name."""
    return LEGACY_PREFIX + name[len(CURRENT_PREFIX) :]


def alias_legacy_env(environ: MutableMapping[str, str] | None = None) -> list[str]:
    """Mirror every ``HAPPYCLAW_*`` variable onto its ``OCTOP_*`` name.

    An explicitly set ``OCTOP_*`` value always wins, so a deployment that has not
    migrated yet is never overridden. Returns the legacy names that were filled
    in, which is what the tests assert on.
    """
    env: MutableMapping[str, str] = os.environ if environ is None else environ
    aliased: list[str] = []
    for name, value in list(env.items()):
        if not name.startswith(CURRENT_PREFIX) or len(name) == len(CURRENT_PREFIX):
            continue
        legacy = legacy_env_name(name)
        if legacy not in env:
            env[legacy] = value
            aliased.append(legacy)
    return aliased
