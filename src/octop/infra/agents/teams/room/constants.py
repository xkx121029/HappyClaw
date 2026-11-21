"""Limits and tunables shared by the team room helpers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

_EDIT_CARD_TOOL_BASES = frozenset(
    {
        "write_file",
        "edit_file",
        "send_file",
        "send_file_to_user",
    }
)
_HISTORY_TOOL_RESULT_MAX_CHARS = 4000
_HISTORY_TOOL_RESULT_SUFFIX = "…"
_FOLLOWUP_RESULT_MAX_CHARS = 6000
_ROOM_HISTORY_LIMIT = 40
_HOST_IDLE_POLL_SEC = 0.05
_HOST_IDLE_WAIT_SEC = 45.0
_MEMBER_HITL_WAIT_SEC = 30 * 60
_RELAY_CHUNK_TYPES = frozenset(
    {"token", "reasoning", "tool_call_chunk", "tool_result", "error", "attachment"}
)
_STREAM_SPEAKER_TYPES = frozenset(
    {
        "token",
        "reasoning",
        "tool_call_chunk",
        "tool_result",
        "error",
        "attachment",
        "slash_action",
        "hitl_required",
        "done",
        "custom",
    }
)

logger = logging.getLogger(__name__)

__all__ = [
    "_EDIT_CARD_TOOL_BASES",
    "_HISTORY_TOOL_RESULT_MAX_CHARS",
    "_HISTORY_TOOL_RESULT_SUFFIX",
    "_FOLLOWUP_RESULT_MAX_CHARS",
    "_ROOM_HISTORY_LIMIT",
    "_HOST_IDLE_POLL_SEC",
    "_HOST_IDLE_WAIT_SEC",
    "_MEMBER_HITL_WAIT_SEC",
    "_RELAY_CHUNK_TYPES",
    "_STREAM_SPEAKER_TYPES",
    "logger",
]
