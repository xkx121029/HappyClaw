"""Fixture DSH tool: fixed JSON result with a full declaration surface.

The smoke check calls this through ``ToolPipeline``; nothing here talks to the
network or the agent runtime.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from octop.infra.plugins.bridge import (
    ToolDefinition,
    ToolExecutionContext,
    ToolOutputSpec,
    text_content,
)

TOOL_NAME = "dsh_fixture_report"
TIMEOUT_MS = 2000.0

PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "message": {"type": "string", "description": "free-form label echoed by logs"},
        "dry_run": {"type": "boolean", "description": "accepted but ignored"},
    },
    "required": ["message"],
    "additionalProperties": False,
}

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "message": {"type": "string"},
        "checks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["ok", "message", "checks"],
    "additionalProperties": False,
}

EXPECTED_RESULT: dict[str, Any] = {
    "ok": True,
    "message": "fixture-tool-ok",
    "checks": ["parameters-schema", "output-schema", "timeout-ms", "concurrency-safe"],
}


def _execute(_args: Mapping[str, Any], _ctx: ToolExecutionContext) -> dict[str, Any]:
    return dict(EXPECTED_RESULT)


def _render(_args: Mapping[str, Any], value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _concurrency_safe(_args: Mapping[str, Any]) -> bool:
    return True


def build_definition() -> ToolDefinition:
    """Return the fixture declaration consumed by the smoke check."""
    return ToolDefinition(
        name=TOOL_NAME,
        description="Return a fixed JSON report for DSH integration smoke checks.",
        parameters=PARAMETERS,
        output=ToolOutputSpec(schema=OUTPUT_SCHEMA, render=_render),
        execute=_execute,
        timeout_ms=TIMEOUT_MS,
        is_concurrency_safe=_concurrency_safe,
    )


__all__ = [
    "EXPECTED_RESULT",
    "OUTPUT_SCHEMA",
    "PARAMETERS",
    "TIMEOUT_MS",
    "TOOL_NAME",
    "build_definition",
]
