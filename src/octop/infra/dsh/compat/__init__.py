"""DSH plugin compatibility layer.

Three independently switchable pieces live here:

* :mod:`.probe` classifies a real DSH bundle (manifest, entry shape, required
  host services) and can run a sandboxed dynamic mount probe.
* :mod:`.transport` / :mod:`.registry` keep a plugin's host half alive in its
  own Node child process and expose the services it publishes.
* :mod:`.client_asset` resolves the browser half for the dashboard shim.

Nothing in this package runs unless ``OCTOP_DSH_COMPAT`` is on; importing it
spawns no process and reads no plugin code.
"""

from octop.infra.dsh.compat.errors import DshCompatCode, DshCompatError
from octop.infra.dsh.compat.switch import (
    allowed_plugins,
    compat_enabled,
    plugin_allowed,
)

__all__ = [
    "DshCompatCode",
    "DshCompatError",
    "allowed_plugins",
    "compat_enabled",
    "plugin_allowed",
]
