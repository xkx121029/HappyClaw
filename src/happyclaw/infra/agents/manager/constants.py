"""Module-level constants shared by the manager submodules."""

from __future__ import annotations

from dataclasses import fields

from happyclaw_harness import HarnessAgentConfig

_HARNESS_AGENT_CONFIG_FIELDS = frozenset(item.name for item in fields(HarnessAgentConfig))
