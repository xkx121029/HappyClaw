"""HappyClaw ↔ 设备服务链路（跨局域网直连，App 主动发起 TLS 连接）。

模块构成：
- :mod:`protocol`  协议常量，唯一来源是同目录的 ``protocol.json``（设备侧同一份文件）
- :mod:`wire`      帧编解码、信封、配对证明
- :mod:`client`    asyncio TLS 客户端（指纹固定 / hello 鉴权 / 心跳 / 重连 / 幂等语义）
- :mod:`manager`   进程级单例：连接状态、命令历史、事件分发、截图落盘
"""
