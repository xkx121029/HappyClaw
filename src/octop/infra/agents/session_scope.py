"""Resolve the current turn's session scope for tools.

Some built-in tools were written as if they had to locate a *user* before they
could act.  With one local owner that lookup is unnecessary and can fail in
ways that are invisible to the model (an empty result, a headless fallback, a
silently skipped pause).  Every turn already belongs to exactly one
conversation, so tools scope themselves to that conversation instead:

    thread_id + agent_id (+ session_key / user columns when data needs them)

When the conversation identity is missing the tool must fail loudly with the
reason, never degrade silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langgraph.config import get_config

from octop.infra.utils.browser_media import parse_octop_user_id


class SessionScopeError(RuntimeError):
    """The current turn is not attached to a conversation scope."""


@dataclass(frozen=True)
class SessionScope:
    """Identity of the conversation that owns the current tool call."""

    thread_id: str | None
    agent_id: str
    session_key: str | None
    user_id: int | None

    def require_user(self, tool: str) -> int:
        """Return the turn's user column, or explain why the tool cannot run."""
        if self.user_id is not None:
            return self.user_id
        raise SessionScopeError(
            f"{tool} cannot run: the current conversation has no user to attribute "
            f"this data to (thread_id={self.thread_id!r}, agent_id={self.agent_id!r}). "
            "Start the call from an agent conversation."
        )


def current_session_scope(*, tool: str) -> SessionScope:
    """Read the session identity LangGraph pinned for this turn."""
    raw = get_config()
    configurable: dict[str, Any] = dict(raw.get("configurable") or {})
    agent_id = str(configurable.get("agent_id") or "").strip()
    if not agent_id:
        raise SessionScopeError(
            f"{tool} is scoped to the current conversation, but this turn has no "
            "agent_id. Refusing to guess which expert should act; start the call "
            "from an expert conversation."
        )
    thread_id = str(configurable.get("thread_id") or raw.get("thread_id") or "").strip() or None
    session_key = str(configurable.get("session_key") or "").strip() or None
    return SessionScope(
        thread_id=thread_id,
        agent_id=agent_id,
        session_key=session_key,
        user_id=parse_octop_user_id(configurable.get("user")),
    )


__all__ = ["SessionScope", "SessionScopeError", "current_session_scope"]
