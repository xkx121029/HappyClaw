"""Per-turn injection of DSH skill changes into the system message.

The stable skill listing is already part of the graph's system prompt. When the
skill set changes while a thread is alive, ``AgentManager`` diffs it against the
session cursor and puts only the changed lines on
``configurable["dsh_skills_delta"]``. This middleware appends that text to the
model request's system message, and leaves the request untouched when the key is
absent or empty (the default, flag-off path).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage
from langgraph.config import get_config

__all__ = [
    "CONFIG_KEY",
    "DshSkillPromptMiddleware",
    "append_dsh_delta",
    "dsh_delta_from_config",
]

CONFIG_KEY = "dsh_skills_delta"


def dsh_delta_from_config() -> str:
    """Read this turn's incremental DSH skill text from the graph config."""

    configurable = get_config().get("configurable") or {}
    raw = configurable.get(CONFIG_KEY)
    return raw if isinstance(raw, str) else ""


def append_dsh_delta(request: ModelRequest[Any], delta: str) -> ModelRequest[Any]:
    """Return *request* with *delta* appended to its system message.

    An empty delta returns the original request object, so a turn without skill
    changes renders exactly the same bytes as before the integration existed.
    """

    if not delta:
        return request
    base = request.system_message.text if request.system_message is not None else ""
    content = f"{base}\n\n{delta}" if base else delta
    return request.override(system_message=SystemMessage(content=content))


class DshSkillPromptMiddleware(AgentMiddleware[Any, Any]):
    """Append the session's DSH skill delta to each model call in this turn."""

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        return handler(append_dsh_delta(request, dsh_delta_from_config()))

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        return await handler(append_dsh_delta(request, dsh_delta_from_config()))
