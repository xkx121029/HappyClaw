"""Smoke 2: invoke the fixture tool through the DSH tool pipeline."""

from __future__ import annotations

import asyncio
import json

from .report import CheckResult, Status

_NAME = "冒烟② 调起 fixture 工具并校验输出"


def run() -> CheckResult:
    return asyncio.run(_run())


async def _run() -> CheckResult:
    try:
        from octop.infra.plugins.bridge import ToolCall, ToolPipeline

        from .fixtures.tools.fixture_tool import (
            EXPECTED_RESULT,
            TIMEOUT_MS,
            TOOL_NAME,
            build_definition,
        )
    except ImportError as exc:
        return CheckResult(
            _NAME,
            Status.UNIMPLEMENTED,
            f"DSH 工具桥接尚不可导入: {type(exc).__name__}: {exc}",
        )

    try:
        definition = build_definition()
    except Exception as exc:  # noqa: BLE001 - a rejected declaration is a failure
        return CheckResult(
            _NAME,
            Status.FAIL,
            f"fixture 工具声明被契约拒绝: {type(exc).__name__}: {exc}",
        )

    evidence = [
        f"声明: name={definition.name} timeout_ms={definition.timeout_ms}",
        f"参数 schema: {json.dumps(definition.parameters, ensure_ascii=False, sort_keys=True)}",
        f"输出 schema: {json.dumps(definition.output.schema, ensure_ascii=False, sort_keys=True)}",
    ]

    if definition.timeout_ms != TIMEOUT_MS:
        return CheckResult(
            _NAME,
            Status.FAIL,
            f"timeout 声明丢失: 期望 {TIMEOUT_MS}，实际 {definition.timeout_ms}",
            tuple(evidence),
        )

    if definition.classify_concurrency({"message": "smoke"}) is not True:
        return CheckResult(
            _NAME,
            Status.FAIL,
            "isConcurrencySafe 未返回 True",
            tuple(evidence),
        )
    evidence.append("isConcurrencySafe: True")

    pipeline = ToolPipeline(
        lookup=lambda name: definition if name == TOOL_NAME else None,
    )
    invocation = await pipeline.invoke(
        ToolCall(call_id="smoke-tool", name=TOOL_NAME, arguments={"message": "smoke"}),
    )
    if invocation.result.is_error:
        error = invocation.result.error or {}
        return CheckResult(
            _NAME,
            Status.FAIL,
            f"工具执行失败: {error.get('code', '未知')} {error.get('message', invocation.text)}",
            tuple(evidence),
        )

    try:
        value = json.loads(invocation.text)
    except json.JSONDecodeError as exc:
        return CheckResult(
            _NAME,
            Status.FAIL,
            f"工具输出不是 JSON: {exc}（原文 {invocation.text!r}）",
            tuple(evidence),
        )

    evidence.append(f"输出: {json.dumps(value, ensure_ascii=False, sort_keys=True)}")
    if value != EXPECTED_RESULT:
        return CheckResult(
            _NAME,
            Status.FAIL,
            f"输出与固定 JSON 不一致: 期望 {EXPECTED_RESULT}，实际 {value}",
            tuple(evidence),
        )

    return CheckResult(_NAME, Status.PASS, "工具通过管道执行并返回固定 JSON", tuple(evidence))
