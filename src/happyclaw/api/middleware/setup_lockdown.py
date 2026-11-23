"""Deprecated setup lockdown middleware (single-user mode).

Historically this returned ``503 {"setup_required": true}`` for every API call
while no account existed. Single-user builds create the local owner before
serving traffic, so the lockdown is now an intentional no-op.
"""

from __future__ import annotations

from typing import Any


def install(app: Any, server: Any) -> None:
    """Deprecated (single-user mode): startup never waits for a setup wizard.

    Kept as a no-op so older call sites and tests do not break. The local owner
    is created before the server starts, so a 503 lockdown would only lock the
    user out of their own machine.
    """
    return
