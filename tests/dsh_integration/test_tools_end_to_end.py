"""S2 end to end: the model asks for a DSH tool, the pipeline runs it, the
result goes back into the conversation.

No provider, network or harness graph is involved: a scripted chat model emits
one real ``tool_call``, the mounted ``StructuredTool`` executes through the
bridge pipeline, and the result is fed back as a ``ToolMessage``.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from happyclaw.infra.dsh.tools import build_dsh_plugin_tools
from tests.dsh_integration.fixtures.tools import fixture_tool
from tests.unit.infra.dsh.plugin_fixtures import write_package

TOOL_NAME = "dsh__demo__echo"


class _ScriptedModel(FakeMessagesListChatModel):
    bound_tools: list[str] = []

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        type(self).bound_tools = [str(getattr(tool, "name", "")) for tool in tools]
        return self


async def test_model_tool_call_runs_through_pipeline_and_returns_to_chat(
    tmp_path: Path,
) -> None:
    root = tmp_path / "local"
    write_package(root / "demo", "demo")
    build = build_dsh_plugin_tools(
        scope="01AGENT",
        local_roots=[root],
        providers={
            "dsh:demo": lambda envelope: [replace(fixture_tool.build_definition(), name="echo")]
        },
        hitl=False,
    )
    assert [tool.name for tool in build.tools] == [TOOL_NAME]

    model = _ScriptedModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": TOOL_NAME,
                        "args": {"message": "from-model"},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="工具已完成"),
        ]
    )
    tools = build.tools
    model.bind_tools(tools)
    assert TOOL_NAME in _ScriptedModel.bound_tools

    messages: list[Any] = [HumanMessage(content="please report")]
    request = model.invoke(messages)
    messages.append(request)
    assert [call["name"] for call in request.tool_calls] == [TOOL_NAME]

    tools_by_name = {tool.name: tool for tool in tools}
    for call in request.tool_calls:
        tool = tools_by_name[call["name"]]
        result = await tool.ainvoke(call["args"])
        assert "fixture-tool-ok" in str(result)
        messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))

    final = model.invoke(messages)
    assert final.content == "工具已完成"

    tool_message = next(item for item in messages if isinstance(item, ToolMessage))
    assert tool_message.tool_call_id == "call-1"
    assert "fixture-tool-ok" in tool_message.content
