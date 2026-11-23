"""Host protocol keys exchanged with the agent harness.

The harness still writes the pre-rename ``octop_*`` keys and reads them back on
its own side, so this side accepts both spellings when reading and emits both
when writing. Historical checkpoints stay readable, and a harness that switches
to the new names later keeps working against messages written here.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

CURRENT_PREFIX = "happyclaw_"
LEGACY_PREFIX = "octop_"

__all__ = ["CURRENT_PREFIX", "LEGACY_PREFIX", "both", "current", "legacy", "read"]


def current(suffix: str) -> str:
    """The post-rename spelling of a protocol key."""
    return CURRENT_PREFIX + suffix


def legacy(suffix: str) -> str:
    """The pre-rename spelling of a protocol key."""
    return LEGACY_PREFIX + suffix


def both(suffix: str, value: Any) -> dict[str, Any]:
    """Both spellings of one key, for a dict literal that a harness will read."""
    return {current(suffix): value, legacy(suffix): value}


def read(mapping: Mapping[str, Any], suffix: str, default: Any = None) -> Any:
    """Read a protocol key under either spelling, preferring the current one."""
    for name in (current(suffix), legacy(suffix)):
        if name in mapping:
            return mapping[name]
    return default
