"""Assemble read-only DSH plugin tools for the agent tool list (S2).

Inputs are already-admitted plugins (see :mod:`.discovery`) plus a mapping from
plugin id to a tool **provider**. The provider is the only way a tool body can
enter this stage, and the default providers never execute plugin JavaScript.

The one exception is explicit and opt-in: ``runtime`` (S10) maps a host-granted
plugin id to a :class:`~.runtime.RuntimeTools` invoker. Those tools still go
through the same pipeline; what changes is that their body runs the bundle's
built entry in a Node child process via ``PluginSandbox.run_command``, and the
guardrail rates them HIGH so approval is mandatory.

Every mounted tool is bound to one ``ToolPipeline`` built by its plugin's
``DshToolRegistry``. Parameter validation, the guardrail (capability, approval,
policy), dispatch, output validation and post hooks therefore all run; there is
no second code path that could bypass them.

Name collisions are never resolved by overwriting or by re-prefixing: the
colliding exposed name is reported with the plugin id and the tool name, and
that tool is left out.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool

from octop.infra.plugins.bridge.approval import ApprovalChannel, ApprovalLedger
from octop.infra.plugins.bridge.contract import ToolDefinition
from octop.infra.plugins.bridge.errors import DshToolError
from octop.infra.plugins.bridge.registry import DshToolRegistry
from octop.infra.plugins.runtime.contract import PluginEnvelope
from octop.infra.plugins.sandbox import ToolInspection
from octop.infra.plugins.sandbox.command import SubprocessExecutor

from .discovery import (
    ORIGIN_LOCAL,
    ORIGIN_MARKET,
    DiscoveredPlugin,
    DshToolSkip,
    discover_dsh_plugins,
)
from .gate import (
    BLOCKING_PERMISSIONS,
    SKIP_DEFINITION_INVALID,
    SKIP_DISCOVERY_FAILED,
    SKIP_NAME_CONFLICT,
    SKIP_NO_PROVIDER,
    SKIP_PROVIDER_FAILED,
    SKIP_RUNTIME_GRANT_NOT_FOUND,
    SKIP_RUNTIME_NO_WORKSPACE,
    permission_name,
)
from .guardrail import build_read_only_guardrail
from .runtime import (
    RuntimeTools,
    exec_declarations,
    exec_permissions,
    exec_reason,
)
from .sandbox import DshSandboxState, build_capability_probe, resolve_absence_mode_strict

logger = logging.getLogger(__name__)

ToolProvider = Callable[[PluginEnvelope], Sequence[ToolDefinition]]


@dataclass
class DshToolBuild:
    """Tools that made it in, plus one record per plugin or tool that did not."""

    tools: list[StructuredTool] = field(default_factory=list)
    mounted: list[str] = field(default_factory=list)
    skipped: list[DshToolSkip] = field(default_factory=list)
    sandboxes: list[DshSandboxState] = field(default_factory=list)
    sandbox_mode: str = ""
    runtime: list[str] = field(default_factory=list)

    def report(self) -> dict[str, Any]:
        return {
            "mounted": list(self.mounted),
            "tools": [str(getattr(tool, "name", "")) for tool in self.tools],
            "skipped": [skip.to_dict() for skip in self.skipped],
            "runtime": list(self.runtime),
            "sandbox": {
                "mode": self.sandbox_mode,
                "assembled": bool(self.sandboxes)
                and all(state.assembled for state in self.sandboxes),
                "plugins": [state.to_dict() for state in self.sandboxes],
            },
        }


def build_dsh_plugin_tools(
    *,
    scope: str,
    market_root: str | Path | None = None,
    local_roots: Sequence[str | Path] = (),
    providers: Mapping[str, ToolProvider],
    hitl: bool,
    approval: ApprovalChannel | None = None,
    ledger: ApprovalLedger | None = None,
    reserved_names: Iterable[str] = (),
    sandbox_root: str | Path | None = None,
    capability_declarations: Mapping[str, Mapping[str, Sequence[str]]] | None = None,
    inspections: Mapping[str, Mapping[str, ToolInspection]] | None = None,
    sandbox_absence: str | None = None,
    runtime: Mapping[str, RuntimeTools] | None = None,
) -> DshToolBuild:
    """Return the read-only tool list for ``scope``; never raises.

    ``runtime`` is the S10 exec stage: a map of plugin id to the host-granted
    invoker. Listing a plugin here is itself the capability and ``exec`` grant,
    so a bundle whose manifest declares no tools can still be mounted — but only
    those exact ids, only when the caller turned the stage on, and every call
    still goes through the sandbox, approval and output-cap layers.

    ``sandbox_root`` is the workspace the sandbox confines calls to. Without it
    the absence gate is used, which warns once and records ``unavailable``
    coverage on every call; ``sandbox_absence`` (``allow`` / ``strict``, default
    from ``OCTOP_DSH_SANDBOX_ABSENCE``) decides whether such calls may run.

    ``capability_declarations`` and ``inspections`` are keyed by plugin id and
    then by native tool name; they let the host narrow a tool's capabilities and
    declare which arguments hold paths. They never widen the plugin manifest's
    ``permissions``.
    """

    try:
        return _build(
            scope=scope,
            market_root=market_root,
            local_roots=local_roots,
            providers=providers,
            hitl=hitl,
            approval=approval,
            ledger=ledger,
            reserved_names=reserved_names,
            sandbox_root=sandbox_root,
            capability_declarations=capability_declarations,
            inspections=inspections,
            sandbox_absence=sandbox_absence,
            runtime=runtime,
        )
    except Exception as exc:  # pragma: no cover - last-resort isolation
        logger.warning("DSH tool assembly failed: %s", exc, exc_info=True)
        return DshToolBuild(
            skipped=[
                DshToolSkip(
                    "",
                    ORIGIN_MARKET,
                    SKIP_DISCOVERY_FAILED,
                    f"{type(exc).__name__}: {exc}",
                )
            ]
        )


def _build(
    *,
    scope: str,
    market_root: str | Path | None,
    local_roots: Sequence[str | Path],
    providers: Mapping[str, ToolProvider],
    hitl: bool,
    approval: ApprovalChannel | None,
    ledger: ApprovalLedger | None,
    reserved_names: Iterable[str],
    sandbox_root: str | Path | None,
    capability_declarations: Mapping[str, Mapping[str, Sequence[str]]] | None,
    inspections: Mapping[str, Mapping[str, ToolInspection]] | None,
    sandbox_absence: str | None,
    runtime: Mapping[str, RuntimeTools] | None,
) -> DshToolBuild:
    grants = {plugin_id: "host exec grant" for plugin_id in (runtime or {})}
    candidates, skipped = discover_dsh_plugins(
        market_root=market_root,
        local_roots=local_roots,
        granted=grants,
    )
    mode = resolve_absence_mode_strict(sandbox_absence)
    build = DshToolBuild(skipped=list(skipped), sandbox_mode=mode.value)
    reserved = {str(name) for name in reserved_names if str(name).strip()}
    for candidate in candidates:
        _mount_plugin(
            candidate,
            scope=scope,
            providers=providers,
            hitl=hitl,
            approval=approval,
            ledger=ledger,
            reserved=reserved,
            build=build,
            sandbox_root=sandbox_root,
            declarations=(capability_declarations or {}).get(candidate.plugin_id, {}),
            inspections=(inspections or {}).get(candidate.plugin_id, {}),
            absence_mode=mode,
            runtime=(runtime or {}).get(candidate.plugin_id),
        )
    # An explicitly granted id that never showed up must be reported, not
    # dropped: a typo in the grant list would otherwise look like success.
    reported = {skip.plugin_id for skip in build.skipped} | set(build.mounted)
    for plugin_id in sorted(set(runtime or {}) - reported):
        build.skipped.append(
            DshToolSkip(
                plugin_id,
                ORIGIN_LOCAL,
                SKIP_RUNTIME_GRANT_NOT_FOUND,
                "the exec grant names this plugin id but discovery found no such bundle",
            )
        )
    return build


def _mount_plugin(
    candidate: DiscoveredPlugin,
    *,
    scope: str,
    providers: Mapping[str, ToolProvider],
    hitl: bool,
    approval: ApprovalChannel | None,
    ledger: ApprovalLedger | None,
    reserved: set[str],
    build: DshToolBuild,
    sandbox_root: str | Path | None,
    declarations: Mapping[str, Sequence[str]],
    inspections: Mapping[str, ToolInspection],
    absence_mode: object | None,
    runtime: RuntimeTools | None = None,
) -> None:
    envelope = candidate.envelope
    provider = providers.get(candidate.plugin_id)
    if provider is None and runtime is None:
        build.skipped.append(
            DshToolSkip(
                candidate.plugin_id,
                candidate.origin,
                SKIP_NO_PROVIDER,
                "no tool provider registered for this plugin",
            )
        )
        return
    if runtime is not None and sandbox_root is None:
        build.skipped.append(
            DshToolSkip(
                candidate.plugin_id,
                candidate.origin,
                SKIP_RUNTIME_NO_WORKSPACE,
                "exec stage needs a workspace root: the sandbox cannot confine a command without one",
            )
        )
        return
    try:
        definitions = (
            runtime.definitions(envelope)
            if runtime is not None
            else list(provider(envelope))  # type: ignore[misc]
        )
    except Exception as exc:
        build.skipped.append(
            DshToolSkip(
                candidate.plugin_id,
                candidate.origin,
                SKIP_PROVIDER_FAILED,
                f"{type(exc).__name__}: {exc}",
            )
        )
        return
    if not definitions:
        build.skipped.append(
            DshToolSkip(
                candidate.plugin_id,
                candidate.origin,
                SKIP_NO_PROVIDER,
                "provider returned no tool definitions",
            )
        )
        return

    registry = DshToolRegistry(plugin_id=candidate.plugin_id)
    accepted: list[ToolDefinition] = []
    for definition in definitions:
        if not isinstance(definition, ToolDefinition):
            build.skipped.append(
                DshToolSkip(
                    candidate.plugin_id,
                    candidate.origin,
                    SKIP_DEFINITION_INVALID,
                    "provider returned a non-ToolDefinition value",
                )
            )
            continue
        exposed = registry.exposed_name(definition.name)
        if exposed in reserved:
            build.skipped.append(
                DshToolSkip(
                    candidate.plugin_id,
                    candidate.origin,
                    SKIP_NAME_CONFLICT,
                    "name is already used by an existing tool",
                    tool=exposed,
                )
            )
            continue
        accepted.append(definition)

    if not accepted:
        return

    for definition in accepted:
        try:
            registry.register(definition, scope=scope)
        except DshToolError as exc:
            build.skipped.append(
                DshToolSkip(
                    candidate.plugin_id,
                    candidate.origin,
                    SKIP_DEFINITION_INVALID,
                    exc.message,
                    tool=definition.name,
                )
            )
            return

    exposed_names = [registry.exposed_name(definition.name) for definition in accepted]
    is_runtime = runtime is not None
    permissions = exec_permissions(envelope) if is_runtime else envelope.permissions
    declared = tuple(
        permission_name(kind) for kind in permissions if kind in BLOCKING_PERMISSIONS
    )

    # Host-facing maps are keyed by native tool name; the sandbox sees the
    # exposed names the pipeline uses.
    by_exposed = {
        registry.exposed_name(definition.name): definition.name for definition in accepted
    }
    if is_runtime:
        # A granted bundle's tools declare exactly ``exec``; the host grant is
        # the only source of that permission, and it is never widened by the
        # manifest or by ``capability_declarations``.
        tool_defaults: dict[str, Sequence[str]] = dict(
            exec_declarations(envelope, exposed_names)
        )
    else:
        tool_defaults = {}
        for exposed, native in by_exposed.items():
            if native in declarations:
                tool_defaults[exposed] = declarations[native]
    plans = {
        exposed: inspections[native]
        for exposed, native in by_exposed.items()
        if native in inspections
    }
    unknown = set(inspections) - set(by_exposed.values())
    for native in sorted(unknown):
        logger.warning(
            "DSH sandbox inspection for plugin %s tool %r ignored: no such mounted tool",
            candidate.plugin_id,
            native,
        )

    probe = build_capability_probe(
        plugin_id=candidate.plugin_id,
        tool_names=exposed_names,
        permissions=permissions,
        declarations=tool_defaults,
        workspace_root=sandbox_root,
        inspections=plans,
        absence_mode=absence_mode,
        executor=SubprocessExecutor() if is_runtime else None,
    )
    build.sandboxes.append(probe.state)

    if is_runtime:
        runtime.bind(
            {definition.name: registry.exposed_name(definition.name) for definition in accepted},
            probe.sandbox,
        )
        build.runtime.append(candidate.plugin_id)

    guardrail = build_read_only_guardrail(
        capability=probe,
        hitl=hitl,
        approval=approval,
        risky_tools={} if is_runtime else ({name: declared for name in exposed_names} if declared else {}),
        exec_tools=(
            {name: exec_reason(candidate.plugin_id) for name in exposed_names}
            if is_runtime
            else None
        ),
        known_tools=exposed_names,
        plugin_id=candidate.plugin_id,
        ledger=ledger,
    )
    pipeline = registry.build_pipeline(scope=scope, guardrail=guardrail)
    build.tools.extend(registry.to_structured_tools(scope=scope, pipeline=pipeline))
    build.mounted.append(candidate.plugin_id)
    reserved.update(exposed_names)


__all__ = ["DshToolBuild", "ToolProvider", "build_dsh_plugin_tools"]
