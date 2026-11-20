"""Expose tools registered by DSH bundles to the model.

Tool names are namespaced (``dsh_compat_<native>_<tool>``) so a bundle can never
shadow a built-in. The call itself goes back through the plugin's own Node
runner; the tool result is the runner's JSON, not a fabricated summary.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Sequence

from octop.infra.dsh.compat.errors import DshCompatError
from octop.infra.dsh.compat.registry import get_registry
from octop.infra.dsh.compat.switch import compat_enabled

logger = logging.getLogger(__name__)


def _tool_name(native: str, name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", f"dsh_compat_{native}_{name}")
    return cleaned[:64]


def compat_structured_tools(*, reserved: Sequence[Any] = ()) -> list[Any]:
    """LangChain tools for every mounted bundle, ready to append to ``tools``."""

    if not compat_enabled():
        return []
    from langchain_core.tools import StructuredTool  # noqa: PLC0415

    reserved_names = {str(getattr(tool, "name", "")) for tool in reserved}
    registry = get_registry()
    tools: list[Any] = []
    for state in registry.ensure_started():
        if state.host_state != "mounted":
            continue
        for definition in state.tools:
            name = _tool_name(state.native_id, str(definition.get("name") or ""))
            if not name or name in reserved_names:
                continue
            parameters = definition.get("parameters") or {"type": "object", "properties": {}}
            if not isinstance(parameters, dict):
                parameters = {"type": "object", "properties": {}}
            description = str(definition.get("description") or f"DSH bundle tool {definition.get('name')}")
            tools.append(
                StructuredTool(
                    name=name,
                    description=description,
                    args_schema=parameters,
                    coroutine=_callable(registry, state.plugin_id, str(definition.get("name")), name),
                )
            )
    return tools


def _callable(registry: Any, plugin_id: str, tool_name: str, exposed_name: str):
    async def invoke(**kwargs: Any) -> str:
        try:
            result = registry.call_tool(plugin_id, tool_name, kwargs)
        except DshCompatError as exc:
            return f"{exposed_name} failed: {exc.code.value}: {exc.message}"
        if not result.get("ok", False):
            return f"{exposed_name} failed: {result.get('code', 'RUNTIME_THROW')}: {result.get('message', '')}"
        payload = result.get("result")
        return payload if isinstance(payload, str) else str(payload)

    return invoke


__all__ = ["compat_structured_tools"]
