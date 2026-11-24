"""Tests for the DSH → Octop tool bridge."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from typing import Any

import pytest
from happyclaw_harness.plugins import PluginRegistry, build_plugin_tools

from happyclaw.infra.plugins.bridge import (
    ApprovalOutcome,
    DshToolErrorCode,
    DshToolRegistry,
    PreToolDecision,
    ToolBatcher,
    ToolCall,
    ToolDefinition,
    ToolOutputSpec,
    describe_exception,
    text_content,
)
from happyclaw.infra.plugins.runtime.contract import (
    CapabilityKind,
    PluginErrorCode,
    PluginRequirement,
)

ADD_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "a": {"type": "integer", "description": "left operand"},
        "b": {"type": "integer", "description": "right operand"},
    },
    "required": ["a", "b"],
    "additionalProperties": False,
}

ADD_OUTPUT = {
    "type": "object",
    "properties": {"sum": {"type": "integer"}},
    "required": ["sum"],
    "additionalProperties": False,
}


def _add_definition(
    execute: Any,
    *,
    name: str = "add",
    description: str = "Add two integers.",
    timeout_ms: float | None = None,
    is_safe: Any = None,
    pre_execute: tuple[Any, ...] = (),
    max_result_bytes: int | None = None,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=description,
        parameters=ADD_PARAMETERS,
        output=ToolOutputSpec(
            schema=ADD_OUTPUT,
            render=lambda _args, value: text_content(f"sum={value['sum']}"),
        ),
        execute=execute,
        timeout_ms=timeout_ms,
        is_concurrency_safe=is_safe,
        pre_execute=pre_execute,
        max_result_bytes=max_result_bytes,
    )


async def _add(args: Mapping[str, Any], _ctx: Any) -> dict[str, Any]:
    return {"sum": args["a"] + args["b"]}


@pytest.fixture(autouse=True)
def _clean_octop_registry() -> Any:
    PluginRegistry.reset()
    yield
    PluginRegistry.reset()


def _registry_with(definition: ToolDefinition) -> DshToolRegistry:
    registry = DshToolRegistry()
    registry.register(definition)
    return registry


async def test_full_chain_register_dispatch_validate_writeback() -> None:
    """注册 → agent 调起 → 参数校验 → 输出校验 → 结果回写，全链路一次跑通。"""
    events: list[tuple[str, Any]] = []
    seen = {"calls": 0}

    async def execute(args: Mapping[str, Any], _ctx: Any) -> dict[str, Any]:
        seen["calls"] += 1
        return {"sum": args["a"] + args["b"]}

    registry = DshToolRegistry(plugin_id="dsh:demo")
    registry.register(_add_definition(execute))
    pipeline = registry.build_pipeline(
        on_event=lambda kind, record: events.append((kind, record)),
    )
    plugin_id = registry.register_into_octop(pipeline=pipeline)
    assert plugin_id == "dsh:demo"

    tools = build_plugin_tools(agent_plugins={}, global_plugins={})
    assert [tool.name for tool in tools] == ["dsh__demo__add"]
    assert set(tools[0].args) == {"a", "b"}
    assert tools[0].args["a"]["type"] == "integer"

    result = await tools[0].ainvoke({"a": 2, "b": 3})
    assert result == "sum=5"
    assert seen["calls"] == 1

    assert [kind for kind, _ in events] == ["tool/call", "tool/result"]
    call_record = events[0][1]
    result_record = events[1][1]
    assert call_record.name == "dsh__demo__add"
    assert call_record.arguments == {"a": 2, "b": 3}
    assert result_record.source_call_id == call_record.call_id
    assert result_record.is_error is False
    assert result_record.error is None

    assert registry.unregister_from_octop(plugin_id=plugin_id) is True
    assert build_plugin_tools(agent_plugins={}, global_plugins={}) == []


async def test_invalid_arguments_fail_before_dispatch() -> None:
    calls = {"count": 0}

    async def execute(args: Mapping[str, Any], _ctx: Any) -> dict[str, Any]:
        calls["count"] += 1
        return {"sum": args["a"] + args["b"]}

    pipeline = _registry_with(_add_definition(execute)).build_pipeline()
    invocation = await pipeline.invoke(
        ToolCall(call_id="c1", name="add", arguments={"a": "two", "b": 3}),
    )

    assert calls["count"] == 0
    assert invocation.result.is_error is True
    assert invocation.result.error is not None
    assert invocation.result.error["code"] == DshToolErrorCode.TOOL_INVALID_ARGUMENTS.value
    assert invocation.result.content[0]["text"].startswith("Error: invalid arguments")


async def test_output_is_validated_against_output_schema() -> None:
    async def execute(_args: Mapping[str, Any], _ctx: Any) -> dict[str, Any]:
        return {"sum": "not-an-integer"}

    pipeline = _registry_with(_add_definition(execute)).build_pipeline()
    invocation = await pipeline.invoke(
        ToolCall(call_id="c1", name="add", arguments={"a": 1, "b": 2}),
    )

    assert invocation.result.is_error is True
    assert invocation.result.error is not None
    assert invocation.result.error["code"] == DshToolErrorCode.TOOL_OUTPUT_INVALID.value


async def test_timeout_is_reported_with_stable_code() -> None:
    async def slow(_args: Mapping[str, Any], _ctx: Any) -> dict[str, Any]:
        await asyncio.sleep(0.5)
        return {"sum": 0}

    pipeline = _registry_with(_add_definition(slow, timeout_ms=20)).build_pipeline()
    started = time.perf_counter()
    invocation = await pipeline.invoke(
        ToolCall(call_id="c1", name="add", arguments={"a": 1, "b": 2}),
    )
    elapsed = time.perf_counter() - started

    assert elapsed < 0.5
    assert invocation.result.is_error is True
    assert invocation.result.error is not None
    assert invocation.result.error["code"] == DshToolErrorCode.TOOL_TIMEOUT.value


async def test_non_concurrency_safe_calls_run_serialized() -> None:
    state: dict[str, Any] = {"active": 0, "max_active": 0, "order": []}

    async def execute(args: Mapping[str, Any], _ctx: Any) -> dict[str, Any]:
        state["active"] += 1
        state["max_active"] = max(state["max_active"], state["active"])
        state["order"].append(("start", args["a"]))
        await asyncio.sleep(0.02)
        state["order"].append(("end", args["a"]))
        state["active"] -= 1
        return {"sum": args["a"] + args["b"]}

    pipeline = _registry_with(
        _add_definition(execute, is_safe=lambda _args: False),
    ).build_pipeline()
    batcher = ToolBatcher(pipeline, max_parallel=10)
    calls = [
        ToolCall(call_id=f"c{index}", name="add", arguments={"a": index, "b": 0})
        for index in range(2)
    ]

    results = await batcher.execute(calls)

    assert state["max_active"] == 1
    assert state["order"] == [("start", 0), ("end", 0), ("start", 1), ("end", 1)]
    assert [invocation.result.is_error for invocation in results] == [False, False]


async def test_concurrency_safe_calls_run_parallel() -> None:
    state: dict[str, Any] = {"active": 0, "max_active": 0}

    async def execute(args: Mapping[str, Any], _ctx: Any) -> dict[str, Any]:
        state["active"] += 1
        state["max_active"] = max(state["max_active"], state["active"])
        await asyncio.sleep(0.05)
        state["active"] -= 1
        return {"sum": args["a"] + args["b"]}

    pipeline = _registry_with(
        _add_definition(execute, is_safe=lambda _args: True),
    ).build_pipeline()
    batcher = ToolBatcher(pipeline, max_parallel=10)
    calls = [
        ToolCall(call_id=f"c{index}", name="add", arguments={"a": index, "b": 0})
        for index in range(2)
    ]

    results = await batcher.execute(calls)

    assert state["max_active"] == 2
    assert [invocation.result.is_error for invocation in results] == [False, False]


async def test_checkpoint_failure_aborts_without_side_effects() -> None:
    executed = {"value": False}

    async def execute(_args: Mapping[str, Any], _ctx: Any) -> dict[str, Any]:
        executed["value"] = True
        return {"sum": 0}

    def checkpoint() -> None:
        raise RuntimeError("session flush failed")

    pipeline = _registry_with(_add_definition(execute)).build_pipeline(checkpoint=checkpoint)
    invocation = await pipeline.invoke(
        ToolCall(call_id="c1", name="add", arguments={"a": 1, "b": 2}),
    )

    assert executed["value"] is False
    assert invocation.result.is_error is True
    assert invocation.result.error is not None
    assert (
        invocation.result.error["code"]
        == DshToolErrorCode.TOOL_ABORTED_BEFORE_DISPATCH.value
    )


async def test_pre_execute_deny_and_single_approver() -> None:
    async def execute(_args: Mapping[str, Any], _ctx: Any) -> dict[str, Any]:
        return {"sum": 3}

    denied = _registry_with(
        _add_definition(
            execute,
            pre_execute=(lambda _ctx, _args: PreToolDecision.deny("policy says no"),),
        ),
    ).build_pipeline()
    invocation = await denied.invoke(
        ToolCall(call_id="c1", name="add", arguments={"a": 1, "b": 2}),
    )
    assert invocation.result.error is not None
    assert invocation.result.error["code"] == DshToolErrorCode.TOOL_DENIED.value

    asked = _registry_with(
        _add_definition(
            execute,
            pre_execute=(lambda _ctx, _args: PreToolDecision.ask("allow add?"),),
        ),
    ).build_pipeline(approver=lambda _req: ApprovalOutcome.ALLOWED_ONCE)
    approved = await asked.invoke(
        ToolCall(call_id="c2", name="add", arguments={"a": 1, "b": 2}),
    )
    assert approved.result.is_error is False
    assert approved.text == "sum=3"

    unapproved = await _registry_with(
        _add_definition(
            execute,
            pre_execute=(lambda _ctx, _args: PreToolDecision.ask("allow add?"),),
        ),
    ).build_pipeline().invoke(
        ToolCall(call_id="c3", name="add", arguments={"a": 1, "b": 2}),
    )
    assert unapproved.result.error is not None
    assert unapproved.result.error["code"] == DshToolErrorCode.TOOL_DENIED.value


async def test_result_size_limit_is_enforced() -> None:
    pipeline = _registry_with(
        _add_definition(_add, max_result_bytes=8),
    ).build_pipeline()
    invocation = await pipeline.invoke(
        ToolCall(call_id="c1", name="add", arguments={"a": 1, "b": 2}),
    )

    assert invocation.result.is_error is True
    assert invocation.result.error is not None
    assert invocation.result.error["code"] == DshToolErrorCode.TOOL_RESULT_TOO_LARGE.value


def test_scope_visibility_and_shadowing() -> None:
    registry = DshToolRegistry()
    registry.register(_add_definition(_add))
    registry.register(
        _add_definition(_add, description="Agent-specific variant."),
        scope="agent-1",
    )
    registry.register(
        _add_definition(_add, name="extra"),
        scope="agent-1",
    )

    assert set(registry.visible()) == {"dsh__tools__add"}
    assert set(registry.visible("agent-1")) == {"dsh__tools__add", "dsh__tools__extra"}
    assert registry.visible("agent-1")["dsh__tools__add"].description == (
        "Agent-specific variant."
    )
    assert registry.get("dsh__tools__add", scope="agent-1") is not None
    assert registry.get("add", scope="agent-1") is not None

    assert registry.unregister("add", scope="agent-1") is True
    assert registry.get("add", scope="agent-1") is not None  # falls back to global
    assert registry.unregister("add") is True
    assert registry.get("add", scope="agent-1") is None


def test_envelope_uses_contract_ids_and_tool_capability() -> None:
    registry = DshToolRegistry(plugin_id="dsh:demo")
    registry.register(_add_definition(_add))
    envelope = registry.to_envelope(
        version="1.2.0",
        requires=(PluginRequirement(plugin_id="octop:core", constraint=">=0.1"),),
    )

    assert envelope.id == "dsh:demo"
    assert envelope.native_id == "demo"
    assert envelope.capabilities == (CapabilityKind.TOOL,)
    assert envelope.requires[0].plugin_id == "octop:core"
    assert envelope.metadata["tools"] == ["dsh__demo__add"]
    assert envelope.metadata["native_id"] == "demo"


def test_execution_error_codes_do_not_overlap_plugin_runtime_codes() -> None:
    plugin_codes = {code.value for code in PluginErrorCode}
    tool_codes = {code.value for code in DshToolErrorCode}
    assert plugin_codes.isdisjoint(tool_codes)


async def test_execution_failure_is_readable_without_traceback() -> None:
    async def execute(_args: Mapping[str, Any], _ctx: Any) -> dict[str, Any]:
        raise ValueError("disk full")

    invocation = await _registry_with(_add_definition(execute)).build_pipeline().invoke(
        ToolCall(call_id="c1", name="add", arguments={"a": 1, "b": 2}),
    )

    assert invocation.result.error is not None
    assert invocation.result.error["code"] == DshToolErrorCode.TOOL_EXECUTION_FAILED.value
    text = invocation.result.content[0]["text"]
    assert text.startswith("Error: ValueError: disk full")
    assert "Traceback" not in text

    class Hostile(Exception):
        def __str__(self) -> str:
            raise RuntimeError("unprintable")

    assert describe_exception(Hostile()) == "<unprintable thrown value>"


def test_definition_rejects_missing_output_schema() -> None:
    with pytest.raises(Exception) as excinfo:
        ToolDefinition(
            name="broken",
            description="broken",
            parameters={"type": "object"},
            output=ToolOutputSpec(schema={"type": "nonsense"}, render=lambda _a, _v: "x"),
            execute=_add,
        )
    assert "output.schema" in str(excinfo.value) or "type" in str(excinfo.value)
