"""Desktop shell ownership for the Octop Python sidecar.

The Electron shell marks the Python process it owns with
``HAPPYCLAW_DESKTOP_SHELL=1``.  This flag is authoritative for "this process is the
desktop-hosted sidecar" and is intentionally distinct from ``HAPPYCLAW_DESKTOP`` /
``HAPPYCLAW_GREEN_PACKAGES``: a standalone green portable install may set those
without being shell-owned, and it must keep its self-upgrade ability.

``happyclaw.config`` must stay free of ``infra`` imports (AGENTS.md §5), so this
module lives in ``happyclaw.infra`` and is only imported by ``infra`` / ``cli`` /
``api`` code paths that are allowed to depend on it.
"""

from __future__ import annotations

from happyclaw.infra.utils.env_alias import CURRENT_PREFIX, LEGACY_PREFIX, env_get

import os

_DESKTOP_SHELL_ENV = "HAPPYCLAW_DESKTOP_SHELL"

# Shell-owned keys that the ``~/.octop/env`` file and ``/api/envs`` must never
# override: they control process identity, bind address, and update ownership.
SHELL_OWNED_ENV_KEYS = frozenset(
    {
        "HAPPYCLAW_DESKTOP_SHELL",
        "HAPPYCLAW_DESKTOP",
        "HAPPYCLAW_GREEN_PACKAGES",
        "HAPPYCLAW_BIND_HOST",
        "HAPPYCLAW_PORT",
        "HAPPYCLAW_HOME",
        "PYTHONNOUSERSITE",
    }
)

# Product decisions the desktop shell makes on the user's behalf.  They stay
# ordinary user-settable variables everywhere else (``docs/configuration.md``),
# but a persisted env file must not flip them back while the shell runs: a
# settings-page write would otherwise resurrect the sign-in wall the desktop
# build deliberately removed.
SHELL_POLICY_ENV_KEYS = frozenset(
    {
        "HAPPYCLAW_REQUIRE_SETUP_PASSWORD",
    }
)


def desktop_shell_enabled() -> bool:
    """Return true when this process is the desktop-hosted sidecar."""
    raw = (env_get(_DESKTOP_SHELL_ENV[len(CURRENT_PREFIX):]) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def shell_owned_env_key(key: str) -> bool:
    """Return true when ``key`` is pinned by the desktop shell for this process."""
    current = CURRENT_PREFIX + key[len(LEGACY_PREFIX):] if key.startswith(LEGACY_PREFIX) else key
    if current in SHELL_OWNED_ENV_KEYS:
        return True
    return desktop_shell_enabled() and current in SHELL_POLICY_ENV_KEYS
