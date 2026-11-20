"""Shared agent ownership / existence checks for HTTP routers.

The rules themselves live in :mod:`octop.infra.agents.access`; this module keeps
the historical import path used by ~30 routers.
"""

from __future__ import annotations

from octop.infra.agents.access import (
    agent_is_shared,
    apply_agent_audience,
    assert_agent_access,
    assert_agent_access_row,
    assert_agent_owner,
    require_agent_owner_row,
    require_agent_row,
    user_owns_agent,
)

__all__ = [
    "agent_is_shared",
    "apply_agent_audience",
    "assert_agent_access",
    "assert_agent_access_row",
    "assert_agent_owner",
    "require_agent_owner_row",
    "require_agent_row",
    "user_owns_agent",
]
