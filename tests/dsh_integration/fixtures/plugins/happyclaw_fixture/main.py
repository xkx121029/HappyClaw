"""Entry module of the Octop-native fixture plugin.

The scaffold only needs the manifest and an existing entry file. A real Octop
loader may call ``setup`` while activating the plugin, so it stays a no-op.
"""

from __future__ import annotations


def setup(ctx: object) -> None:
    """Register nothing; this plugin exists to exercise discovery."""
    return None
