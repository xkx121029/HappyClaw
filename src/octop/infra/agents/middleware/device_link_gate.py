"""设备链路工具的可见性闸门。

设备离线时，6 个 ``phone_*`` 工具必须从模型可见的工具列表中**消失**，而不是
"出现后调用再报错"。这里在每次模型调用前做一次同步判定并改写 ``request.tools``。

判定失败（任何异常）一律放行，不得因为链路状态读取错误而阻断正常对话。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

from octop.infra.control.device_link.agent_tools import DEVICE_LINK_TOOL_NAMES
from octop.infra.control.device_link.manager import get_device_link_manager

logger = logging.getLogger(__name__)


def _tool_name(tool: Any) -> str:
    if isinstance(tool, dict):
        name = tool.get("name")
        if isinstance(name, str):
            return name
        fn = tool.get("function")
        if isinstance(fn, dict) and isinstance(fn.get("name"), str):
            return str(fn["name"])
        return ""
    return str(getattr(tool, "name", "") or "")


def device_link_online() -> bool:
    try:
        return get_device_link_manager().is_online()
    except Exception:  # noqa: BLE001
        logger.warning("device link online check failed; keeping tools visible", exc_info=True)
        # 读不到状态时按"在线"处理只是为了让工具保持可见；真正执行时工具内部还会再查一次。
        return True


class DeviceLinkToolGateMiddleware(AgentMiddleware[Any, Any]):
    """离线时把设备工具从 ``request.tools`` 中移除。"""

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        return handler(self._gate(request))

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        return await handler(self._gate(request))

    def _gate(self, request: ModelRequest[Any]) -> ModelRequest[Any]:
        try:
            if device_link_online():
                return request
            tools = request.tools or []
            kept = [tool for tool in tools if _tool_name(tool) not in DEVICE_LINK_TOOL_NAMES]
            if len(kept) == len(tools):
                return request
            return request.override(tools=kept)
        except Exception:  # noqa: BLE001
            logger.warning("device link tool gate failed; passing request through", exc_info=True)
            return request


__all__ = ["DeviceLinkToolGateMiddleware", "device_link_online"]
