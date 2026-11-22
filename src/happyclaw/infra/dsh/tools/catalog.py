"""Assemble read-only DSH plugin tools for the agent tool list (S2).

Inputs are already-admitted plugins (see :mod:`.discovery`) plus a mapping from
plugin id to a tool **provider**. The provider is the only way a tool body can
enter S2: DSH bundles ship JavaScript, and this stage never executes it, so no
declarative on-disk tool format is invented here.

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

from happyclaw.infra.plugins.bridge.approval import ApprovalChannel, ApprovalLedger
from happyclaw.infra.plugins.bridge.contract import ToolDefinition
from happyclaw.infra.plugins.bridge.errors import DshToolError
from happyclaw.infra.plugins.bridge.registry import DshToolRegistry
from happyclaw.infra.plugins.runtime.contract import PluginEnvelope
from happyclaw.infra.plugins.sandbox import ToolInspection

from .discovery import ORIGIN_MARKET, DiscoveredPlugin, DshToolSkip, discover_dsh_plugins
from .gate import (
    BLOCKING_PERMISSIONS,
    SKIP_DEFINITION_INVALID,
    SKIP_DISCOVERY_FAILED,
    SKIP_NAME_CONFLICT,
    SKIP_NO_PROVIDER,
    SKIP_PROVIDER_FAILED,
    permission_name,
)
from .guardrail import build_read_only_guardrail
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

    def report(self) -> dict[str, Any]:
        return {
            "mounted": list(self.mounted),
            "tools": [str(getattr(tool, "name", "")) for tool in self.tools],
            "skipped": [skip.to_dict() for skip in self.skipped],
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
) -> DshToolBuild:
    """Return the read-only tool list for ``scope``; never raises.

    ``sandbox_root`` is the workspace the sandbox confines calls to. Without it
    the absence gate is used, which warns once and records ``unavailable``
    coverage on every call; ``sandbox_absence`` (``allow`` / ``strict``, default
    from ``HAPPYCLAW_DSH_SANDBOX_ABSENCE``) decides whether such calls may run.

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
) -> DshToolBuild:
    candidates, skipped = discover_dsh_plugins(
        market_root=market_root,
        local_roots=local_roots,
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
) -> None:
    envelope = candidate.envelope
    provider = providers.get(candidate.plugin_id)
    if provider is None:
        build.skipped.append(
            DshToolSkip(
                candidate.plugin_id,
                candidate.origin,
                SKIP_NO_PROVIDER,
                "no tool provider registered for this plugin",
            )
        )
        return
    try:
        definitions = list(provider(envelope))
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
    declared = tuple(
        permission_name(kind)
        for kind in envelope.permissions
        if kind in BLOCKING_PERMISSIONS
    )

    # Host-facing maps are keyed by native tool name; the sandbox sees the
    # exposed names the pipeline uses.
    by_exposed = {
        registry.exposed_name(definition.name): definition.name for definition in accepted
    }
    tool_defaults: dict[str, Sequence[str]] = {}
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
        permissions=envelope.permissions,
        declarations=tool_defaults,
        workspace_root=sandbox_root,
        inspections=plans,
        absence_mode=absence_mode,
    )
    build.sandboxes.append(probe.state)

    guardrail = build_read_only_guardrail(
        capability=probe,
        hitl=hitl,
        approval=approval,
        risky_tools={name: declared for name in exposed_names} if declared else {},
        known_tools=exposed_names,
        plugin_id=candidate.plugin_id,
        ledger=ledger,
    )
    pipeline = registry.build_pipeline(scope=scope, guardrail=guardrail)
    build.tools.extend(registry.to_structured_tools(scope=scope, pipeline=pipeline))
    build.mounted.append(candidate.plugin_id)
    reserved.update(exposed_names)


__all__ = ["DshToolBuild", "ToolProvider", "build_dsh_plugin_tools"]
