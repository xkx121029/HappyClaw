"""Bind custom MCP tool sets onto a live harness agent."""

from __future__ import annotations

from typing import Any

__all__ = ["bind_custom_mcp_tools"]


def bind_custom_mcp_tools(
    agent: Any,
    name: str,
    tools: list[Any],
    *,
    user_id: int | None,
) -> None:
    """Attach custom MCP tools, replacing that server when another user owns the slot.

    A shared expert's harness has one short name. The owner's tools and a
    viewer's same-named server both land on ``{name}_*``, and ``append`` keeps
    the first set. Record who was bound so the next turn can swap.
    """
    prefix = f"{name}_"
    current_names: Any = getattr(agent, "_mcp_tool_name_set", frozenset())
    occupied = isinstance(current_names, frozenset) and any(
        isinstance(tool_name, str) and tool_name.startswith(prefix) for tool_name in current_names
    )
    if occupied:
        existing = getattr(agent, "_mcp_tools", None)
        kept = (
            [
                tool
                for tool in existing
                if not str(getattr(tool, "name", "") or "").startswith(prefix)
            ]
            if isinstance(existing, list)
            else []
        )
        agent.replace_mcp_tools([*kept, *tools])
    else:
        agent.append_mcp_tools(tools)
    if user_id is None:
        return
    book = getattr(agent, "_mcp_attached_user", None)
    attached: dict[str, int] = book if isinstance(book, dict) else {}
    attached[name] = user_id
    agent._mcp_attached_user = attached
