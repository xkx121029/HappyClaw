"""HappySearch 嵌入式检索层（MIT）。

本包只包含搜索编排、免配置引擎与排序逻辑，不包含 HTTP 服务、鉴权、
本地索引或网页抓取。搜索能力通过 ``octop.infra.search.happy_tool``
暴露为 LangChain 工具，默认关闭。

来源：https://github.com/xkx121029/happy-search (commit c1f64f1)
"""

from __future__ import annotations

__all__ = ["__version__", "upstream"]

__version__ = "1.0.0"
upstream = "happy-search@c1f64f1"
