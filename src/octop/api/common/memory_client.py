"""Backward-compatible import path for the per-agent memory client.

The implementation moved to :mod:`octop.infra.agents.memory.client` so that
``infra`` collectors no longer import the API package.
"""

from __future__ import annotations

from octop.infra.agents.memory.client import (
    call_memory_rpc,
    invalidate_cached_memory,
    memory_db_path,
    memory_db_path_for_cfg,
    memory_namespace,
    require_agent_owner_row,
)

__all__ = [
    "call_memory_rpc",
    "invalidate_cached_memory",
    "memory_db_path",
    "memory_db_path_for_cfg",
    "memory_namespace",
    "require_agent_owner_row",
]
