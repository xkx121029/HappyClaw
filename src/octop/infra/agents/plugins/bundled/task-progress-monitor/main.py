"""Real-time task progress — visual plugin for the Home sidebar.

The panel itself is plain ESM under ``ui/dist``. This backend entry only adds a
read-only tool so the plugin also has a callable presence in chat; it never
writes data or talks to the network.
"""

from __future__ import annotations

from octop_harness.plugins import PluginContext


async def task_progress_about() -> str:
    """Explain where the real-time task progress panel lives and what it shows."""
    return (
        "实时任务进度面板位于首页右侧栏。\n"
        "数据来源：GET /api/runtime/activity 与运行中 Agent 的会话状态，每 3 秒刷新。\n"
        "面板只读，不修改任何任务；卸载插件后面板会随插件一起消失。"
    )


def setup(ctx: PluginContext) -> None:
    ctx.tool(
        "task_progress_about",
        task_progress_about,
        description="说明「实时任务进度」面板的位置、数据来源与刷新频率",
    )
