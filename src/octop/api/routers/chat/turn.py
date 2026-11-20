"""Dashboard turn preparation — API-side re-exports.

The logic lives in :mod:`octop.infra.gateway.process.dashboard_turn` so that
``infra`` callers (Bao follow-ups, bridge peers) never import this package.
Routers and tests keep importing from here.
"""

from __future__ import annotations

from octop.infra.gateway.process.dashboard_turn import (
    DashboardTurn,
    PreparedDashboardTurn,
    build_dashboard_inbound,
    client_message_id_from_turn,
    content_parts_from_dashboard_turn,
    merge_turn_target_agents,
    prepare_dashboard_turn,
    resolve_thread_id,
    turn_has_content,
)
from octop.infra.gateway.process.message_keys import (
    COMPOSER_CTX_KEY,
    INBOUND_ATTACHMENTS_KEY,
    build_composer_context,
)
from octop.infra.gateway.process.usage_record import extract_usage_from_chunk

__all__ = [
    "COMPOSER_CTX_KEY",
    "INBOUND_ATTACHMENTS_KEY",
    "DashboardTurn",
    "PreparedDashboardTurn",
    "build_composer_context",
    "build_dashboard_inbound",
    "client_message_id_from_turn",
    "content_parts_from_dashboard_turn",
    "extract_usage_from_chunk",
    "merge_turn_target_agents",
    "prepare_dashboard_turn",
    "resolve_thread_id",
    "turn_has_content",
]
