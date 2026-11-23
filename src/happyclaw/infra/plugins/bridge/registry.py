"""DSH tool registry with scoped visibility and Octop registry mapping.

Scope model is intentionally two layers (``global`` + one agent scope) instead
of DSH's five-layer stack: near-scope definitions shadow global ones, which is
all a single-user local agent needs.

Ids follow the unified plugin runtime contract
(:mod:`happyclaw.infra.plugins.runtime.contract`): the registered plugin id is
``dsh:<native>`` and the ecosystem-native id stays in ``native_id``. Exposed
tool names are prefixed with the plugin's native id (``dsh__<native>__<tool>``)
so two DSH plugins cannot collide on a short name like ``read_file``.

Octop's existing registry is ``happyclaw_harness.plugins.PluginRegistry``. The
bridge maps DSH definitions onto its ``ToolRegistration`` records (same
``plugin_id`` / ``name`` / ``fn`` / ``description`` shape) so registration,
unregistration, and the agent tool-settings listing keep working without
touching the registry implementation.
"""

from __future__ import annotations

import hashlib
import inspect
import keyword
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain_core.tools import StructuredTool

from happyclaw.infra.plugins.bridge.approval import Guardrail
from happyclaw.infra.plugins.bridge.contract import ToolDefinition
from happyclaw.infra.plugins.bridge.contract_types import AbortSignal
from happyclaw.infra.plugins.bridge.errors import DshToolError, DshToolErrorCode
from happyclaw.infra.plugins.bridge.pipeline import (
    DEFAULT_MAX_RESULT_BYTES,
    ToolCall,
    ToolPipeline,
    new_call_id,
)
from happyclaw.infra.plugins.runtime.contract import (
    CapabilityKind,
    PluginEnvelope,
    PluginKind,
    PluginRequirement,
    PluginSource,
    PluginSourceKind,
    canonical_plugin_id,
    split_plugin_id,
)

if TYPE_CHECKING:
    from happyclaw_harness.plugins.registry import ToolRegistration

GLOBAL_SCOPE = "global"
DEFAULT_PLUGIN_ID = "dsh:tools"
_MAX_TOOL_NAME = 64
_PLUGIN_ID_SAFE_RE = re.compile(r"[^A-Za-z0-9_-]+")


class DshToolRegistry:
    """Holds DSH tool definitions by scope and exposes Octop-facing views."""

    def __init__(self, *, plugin_id: str = DEFAULT_PLUGIN_ID) -> None:
        kind, native_id = split_plugin_id(plugin_id)
        if kind is not PluginKind.DSH:
            raise DshToolError(
                DshToolErrorCode.TOOL_DEFINITION_INVALID,
                f"bridge plugin id must use the 'dsh:' prefix, got {plugin_id!r}",
            )
        self.plugin_id = plugin_id
        self.native_id = native_id
        self._scopes: dict[str, dict[str, ToolDefinition]] = {}

    def exposed_name(self, native_name: str) -> str:
        """Plugin-prefixed, provider-safe tool name."""
        prefix = f"dsh__{self.native_id}__"
        candidate = f"{prefix}{native_name}"
        if len(candidate) <= _MAX_TOOL_NAME:
            return candidate
        digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:8]
        keep = _MAX_TOOL_NAME - len(prefix) - len(digest) - 1
        return f"{prefix}{native_name[:keep]}-{digest}"

    def register(self, definition: ToolDefinition, *, scope: str = GLOBAL_SCOPE) -> Callable[[], None]:
        """Register a definition and return a disposer that removes it again."""
        bucket = self._scopes.setdefault(scope, {})
        if definition.name in bucket:
            raise DshToolError(
                DshToolErrorCode.TOOL_DEFINITION_INVALID,
                f"tool {definition.name!r} is already registered in scope {scope!r}",
            )
        exposed = self.exposed_name(definition.name)
        if any(self.exposed_name(name) == exposed for name in bucket):
            raise DshToolError(
                DshToolErrorCode.TOOL_DEFINITION_INVALID,
                f"tool name {definition.name!r} collides after prefixing in scope {scope!r}",
            )
        bucket[definition.name] = definition

        def dispose() -> None:
            current = self._scopes.get(scope)
            if current is not None and current.get(definition.name) is definition:
                del current[definition.name]
                if not current:
                    self._scopes.pop(scope, None)

        return dispose

    def unregister(self, name: str, *, scope: str = GLOBAL_SCOPE) -> bool:
        bucket = self._scopes.get(scope)
        if bucket is None or name not in bucket:
            return False
        del bucket[name]
        if not bucket:
            self._scopes.pop(scope, None)
        return True

    def unregister_scope(self, scope: str) -> int:
        return len(self._scopes.pop(scope, {}))

    def get(self, name: str, *, scope: str = GLOBAL_SCOPE) -> ToolDefinition | None:
        """Look up by exposed or native name, local scope first."""
        for bucket in (self._scopes.get(scope, {}), self._scopes.get(GLOBAL_SCOPE, {})):
            for native_name, definition in bucket.items():
                if name == native_name or name == self.exposed_name(native_name):
                    return definition
        return None

    def visible(self, scope: str = GLOBAL_SCOPE) -> dict[str, ToolDefinition]:
        """Exposed-name → definition, global overlaid by the requested scope."""
        merged: dict[str, ToolDefinition] = {}
        for native_name, definition in self._scopes.get(GLOBAL_SCOPE, {}).items():
            merged[self.exposed_name(native_name)] = definition
        if scope != GLOBAL_SCOPE:
            for native_name, definition in self._scopes.get(scope, {}).items():
                merged[self.exposed_name(native_name)] = definition
        return merged

    def schemas(self, scope: str = GLOBAL_SCOPE) -> list[dict[str, Any]]:
        return [
            {
                "name": exposed_name,
                "description": definition.description,
                "parameters": definition.parameters,
            }
            for exposed_name, definition in self.visible(scope).items()
        ]

    def scopes(self) -> tuple[str, ...]:
        return tuple(self._scopes)

    def build_pipeline(
        self,
        *,
        scope: str = GLOBAL_SCOPE,
        max_result_bytes: int = DEFAULT_MAX_RESULT_BYTES,
        checkpoint: Callable[[], object] | None = None,
        approver: Callable[[Any], object] | None = None,
        guardrail: Guardrail | None = None,
        on_event: Callable[[str, Any], None] | None = None,
        default_timeout_ms: float | None = None,
    ) -> ToolPipeline:
        return ToolPipeline(
            lookup=lambda name: self.get(name, scope=scope),
            scope=scope,
            max_result_bytes=max_result_bytes,
            checkpoint=checkpoint,
            approver=approver,
            guardrail=guardrail,
            on_event=on_event,
            default_timeout_ms=default_timeout_ms,
        )

    def to_structured_tools(
        self,
        *,
        scope: str = GLOBAL_SCOPE,
        pipeline: ToolPipeline | None = None,
    ) -> list[StructuredTool]:
        """LangChain tools bound to the bridge pipeline.

        This is the recommended agent binding: the full JSON Schema (including
        property descriptions) is passed through as ``args_schema``.
        """
        active = pipeline or self.build_pipeline(scope=scope)
        tools: list[StructuredTool] = []
        for exposed_name, definition in self.visible(scope).items():
            tools.append(
                StructuredTool.from_function(
                    coroutine=_make_invoker(exposed_name, definition, active),
                    name=exposed_name,
                    description=definition.description,
                    args_schema=definition.parameters,
                )
            )
        return tools

    def to_tool_registrations(
        self,
        *,
        scope: str = GLOBAL_SCOPE,
        pipeline: ToolPipeline | None = None,
    ) -> list[ToolRegistration]:
        """Map definitions onto Octop ``ToolRegistration`` records.

        ``ToolRegistration`` cannot carry a JSON Schema, so the adapter restores
        the model-facing signature from ``parameters`` (names, required flags,
        primitive types). Property descriptions are lost on this path; use
        :meth:`to_structured_tools` when full schema fidelity matters.
        """
        from happyclaw_harness.plugins.registry import ToolRegistration

        active = pipeline or self.build_pipeline(scope=scope)
        registrations: list[ToolRegistration] = []
        for exposed_name, definition in self.visible(scope).items():
            invoker = _make_invoker(exposed_name, definition, active)
            signature, annotations = synthetic_signature(definition.parameters)
            setattr(invoker, "__signature__", signature)
            setattr(invoker, "__annotations__", annotations)
            registrations.append(
                ToolRegistration(
                    plugin_id=self.plugin_id,
                    name=exposed_name,
                    fn=invoker,
                    description=definition.description,
                )
            )
        return registrations

    def register_into_octop(
        self,
        *,
        scope: str = GLOBAL_SCOPE,
        pipeline: ToolPipeline | None = None,
        plugin_registry: Any | None = None,
    ) -> str:
        """Register this scope's tools as one Octop plugin; returns the plugin id."""
        from happyclaw_harness.plugins import LoadedPlugin, PluginManifest, PluginRegistry

        registrations = self.to_tool_registrations(scope=scope, pipeline=pipeline)
        loaded = LoadedPlugin(
            manifest=PluginManifest(
                id=self.plugin_id,
                version="0.0.0",
                name=f"DSH tools ({scope})",
                kind="tool",
                entry="",
                description="Tools bridged from DeepSeek Harness plugin definitions.",
            ),
            source_path=Path("."),
            tools=registrations,
        )
        registry = plugin_registry if plugin_registry is not None else PluginRegistry()
        registry.register(loaded)
        return self.plugin_id

    def unregister_from_octop(
        self,
        *,
        plugin_id: str,
        plugin_registry: Any | None = None,
    ) -> bool:
        from happyclaw_harness.plugins import PluginRegistry

        registry = plugin_registry if plugin_registry is not None else PluginRegistry()
        return registry.unregister(plugin_id) is not None

    def to_envelope(
        self,
        *,
        scope: str = GLOBAL_SCOPE,
        version: str = "0.0.0",
        source_reference: str = "bridge:in-process",
        requires: Sequence[PluginRequirement] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> PluginEnvelope:
        """Ecosystem-neutral declaration for the unified plugin runtime.

        Tools land under the ``tool`` capability; ``requires`` is plugin-level
        only (DSH tool package dependencies stay in the DSH manifest metadata).
        """
        tools = list(self.visible(scope))
        merged_metadata: dict[str, Any] = {
            "native_id": self.native_id,
            "scope": scope,
            "tools": tools,
        }
        if metadata:
            merged_metadata.update(metadata)
        return PluginEnvelope(
            id=self.plugin_id,
            kind=PluginKind.DSH,
            version=version,
            entry=f"bridge:{scope}",
            source=PluginSource(
                kind=PluginSourceKind.LOCAL,
                reference=source_reference,
            ),
            capabilities=(CapabilityKind.TOOL,),
            requires=tuple(requires),
            metadata=merged_metadata,
        )


def default_plugin_id(scope: str) -> str:
    """Canonical ``dsh:<native>`` id for a bridge scope."""
    if scope == GLOBAL_SCOPE:
        return DEFAULT_PLUGIN_ID
    cleaned = _PLUGIN_ID_SAFE_RE.sub("-", scope).strip("-") or "scope"
    return canonical_plugin_id(PluginKind.DSH, f"tools-{cleaned}")


def _make_invoker(
    exposed_name: str,
    definition: ToolDefinition,
    pipeline: ToolPipeline,
) -> Callable[..., Any]:
    async def invoke(**kwargs: Any) -> str:
        return await run_definition(
            definition,
            pipeline,
            kwargs,
            tool_name=exposed_name,
            signal=None,
        )

    invoke.__name__ = exposed_name
    return invoke


async def run_definition(
    definition: ToolDefinition,
    pipeline: ToolPipeline,
    arguments: Mapping[str, Any],
    *,
    tool_name: str | None = None,
    signal: AbortSignal | None = None,
) -> str:
    """Invoke one definition through the pipeline and return its text content."""
    invocation = await pipeline.invoke(
        ToolCall(
            call_id=new_call_id(),
            name=tool_name or definition.name,
            arguments=arguments,
        ),
        signal=signal,
    )
    return invocation.text


def synthetic_signature(parameters: Mapping[str, Any]) -> tuple[inspect.Signature, dict[str, Any]]:
    """Build an ``inspect.Signature`` matching a JSON Schema's top-level properties."""
    properties = parameters.get("properties")
    required_raw = parameters.get("required")
    required = (
        {str(name) for name in required_raw}
        if isinstance(required_raw, list)
        else set()
    )

    params: list[inspect.Parameter] = []
    annotations: dict[str, Any] = {}
    if isinstance(properties, Mapping):
        for raw_name, raw_spec in properties.items():
            name = str(raw_name)
            if not name.isidentifier() or keyword.iskeyword(name):
                continue
            annotation = _python_type(raw_spec)
            default = inspect.Parameter.empty if name in required else None
            params.append(
                inspect.Parameter(
                    name,
                    inspect.Parameter.KEYWORD_ONLY,
                    default=default,
                    annotation=annotation,
                )
            )
            annotations[name] = annotation
    return inspect.Signature(params, return_annotation=str), annotations


def _python_type(spec: object) -> Any:
    if not isinstance(spec, Mapping):
        return Any
    declared = spec.get("type")
    mapping: dict[str, Any] = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "object": dict[str, Any],
        "array": list[Any],
    }
    return mapping.get(str(declared), Any)


__all__ = [
    "DEFAULT_PLUGIN_ID",
    "GLOBAL_SCOPE",
    "DshToolRegistry",
    "default_plugin_id",
    "run_definition",
    "synthetic_signature",
]
