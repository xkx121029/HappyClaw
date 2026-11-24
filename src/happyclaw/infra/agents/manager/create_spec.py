"""Agent creation spec and custom-id validation."""

from __future__ import annotations

import json
import re
from dataclasses import (
    dataclass,
    field,
)
from typing import Any

from happyclaw.infra.errors import (
    ErrorCode,
    HappyclawError,
)

# Custom agent ids become workspace directory names (~/.octop/agents/<id>/),
# so restrict to a conservative slug charset — no separators, dots, or
# unicode — to keep every downstream path/URL usage safe.
_CUSTOM_AGENT_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{1,62}[a-zA-Z0-9]$")


def validate_custom_agent_id(agent_id: str) -> str:
    """Validate a user-supplied agent id; raise ``HappyclawError`` when invalid."""
    if not _CUSTOM_AGENT_ID_RE.fullmatch(agent_id):
        raise HappyclawError(
            ErrorCode.AGENT_ID_INVALID,
            "agent id must be 3-64 chars of letters/digits/underscore/hyphen, "
            "starting and ending with a letter or digit",
        )
    lowered = agent_id.lower()
    if lowered in _RESERVED_AGENT_IDS:
        raise HappyclawError(ErrorCode.AGENT_ID_INVALID, f"agent id {agent_id!r} is reserved")
    return agent_id


# Lowercase names that would collide with workspace-adjacent directories or
# well-known URL/route segments.
_RESERVED_AGENT_IDS = frozenset({"api", "admin", "agents", "experts"})


@dataclass
class AgentCreateSpec:
    """Input for :meth:`AgentManager.create`."""

    name: str
    agent_id: str | None = None
    user_id: int | None = None
    description: str | None = None
    persona_mbti: str | None = None
    default_model: str | None = None
    system_prompt: str | None = None
    icon: str | None = None
    template_name: str | None = None
    is_shared: bool = False
    icon_name: str | None = None
    icon_url: str | None = None
    color: str | None = None
    skill_package_ids: list[str] | None = None
    published_expert_id: str | None = None
    welcome_message: str | None = None
    knowledge_base_ids: list[str] | None = None
    mcp_servers: list[str] | None = None
    runtime_config: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    kind: str = "expert"
    member_ids: list[str] = field(default_factory=list)


def _stored_id_list(value: Any) -> list[str]:
    """Normalize a persisted id list, whether it is already a list or JSON text."""
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item).strip()]
    return []
