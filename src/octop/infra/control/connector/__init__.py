"""手机端连接器：配对、设备令牌与消息推送状态。

HTTP/WebSocket 路由已迁至 :mod:`octop.api.routers.connector`；这里只保留
与传输无关的配对状态与推送集线器。
"""

from octop.infra.control.connector import state

__all__ = ["state"]
