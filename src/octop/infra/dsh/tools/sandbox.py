"""S4: the capability probe every mounted DSH tool is bound to.

The probe is a real :class:`~octop.infra.plugins.sandbox.PluginSandbox` when a
workspace root is available; otherwise it is the sandbox absence gate, which
says out loud that no path/permission check ran.

Two rules shape this module:

* **Permissions come from the plugin manifest.** ``PluginEnvelope.permissions``
  is the grant; nothing here widens it. A tool declares, by default, exactly what
  its plugin declared, and a declaration outside that grant is denied.
* **A missing sandbox is never a silent pass.** Allow mode logs one explicit
  warning per plugin and keeps ``coverage=unavailable`` on every call, so the
  approval record never looks like it had sandbox backing; strict mode denies
  with ``TOOL_SANDBOX_NOT_ASSEMBLED``.

The probe result is tagged with a bridge error code here, not in the sandbox
package: the sandbox decides, the host decides how to report it.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from octop.infra.plugins.bridge.approval import CapabilityProbe
from octop.infra.plugins.bridge.errors import DshToolErrorCode
from octop.infra.plugins.runtime.contract import PermissionKind
from octop.infra.plugins.sandbox import (
    CommandExecutor,
    PluginSandbox,
    SandboxAbsenceGate,
    SandboxAbsenceMode,
    SandboxConfigError,
    SandboxErrorCode,
    SandboxProbeResult,
    ToolInspection,
    resolve_absence_mode,
)

logger = logging.getLogger(__name__)

ENV_SANDBOX_ABSENCE = "OCTOP_DSH_SANDBOX_ABSENCE"

ANNOUNCED: set[tuple[str, str]] = set()


@dataclass(frozen=True, slots=True)
class DshSandboxState:
    """Which sandbox posture one plugin's tools ran under."""

    plugin_id: str
    assembled: bool
    mode: str
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "assembled": self.assembled,
            "mode": self.mode,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class SandboxProbe:
    """A callable probe plus the posture it was built with.

    ``sandbox`` is the assembled :class:`PluginSandbox` when one exists. The
    exec stage needs it to run a command *through* the same sandbox that vetted
    the call, instead of a second instance that could drift from the probe.
    """

    state: DshSandboxState
    probe: CapabilityProbe
    sandbox: PluginSandbox | None = None

    def __call__(
        self, tool_name: str, arguments: Mapping[str, Any] | None = None
    ) -> SandboxProbeResult:
        return self.probe(tool_name, arguments or {})


def resolve_absence_mode_strict(raw: object | None) -> SandboxAbsenceMode:
    """Resolve the configured absence policy; an unknown value means strict.

    Falling back to ``allow`` would let a typo silently disable the warning's
    only consequence, so an invalid value is reported and treated as the
    stricter mode.
    """

    value = raw if raw is not None else os.environ.get(ENV_SANDBOX_ABSENCE)
    try:
        return resolve_absence_mode(value)
    except SandboxConfigError:
        logger.warning(
            "DSH sandbox absence policy %r is invalid; treating it as strict "
            "(%s). Valid values are allow / strict.",
            value,
            SandboxErrorCode.NOT_ASSEMBLED.value,
        )
        return SandboxAbsenceMode.STRICT


def build_capability_probe(
    *,
    plugin_id: str,
    tool_names: Iterable[str],
    permissions: Iterable[PermissionKind] = (),
    declarations: Mapping[str, Iterable[object]] | None = None,
    workspace_root: str | Path | None = None,
    inspections: Mapping[str, ToolInspection] | None = None,
    absence_mode: object | None = None,
    executor: CommandExecutor | None = None,
) -> SandboxProbe:
    """Build the probe for one plugin's mounted tools.

    ``tool_names`` are the exposed names the pipeline passes to the probe.
    ``declarations`` (exposed name -> capability names) lets the host narrow
    what one tool needs; it never widens ``permissions``.
    """

    names = [str(name) for name in tool_names]
    granted = tuple(
        item.value if isinstance(item, PermissionKind) else str(item)
        for item in permissions
    )
    declared: dict[str, tuple[object, ...]] = {}
    for name in names:
        raw = (declarations or {}).get(name)
        declared[name] = granted if raw is None else tuple(raw)

    mode = resolve_absence_mode_strict(absence_mode)

    if workspace_root is not None:
        try:
            sandbox = PluginSandbox(
                plugin_id=plugin_id,
                workspace_root=workspace_root,
                declarations=declared,
                permissions=granted,
                inspections=dict(inspections or {}),
                executor=executor,
            )
        except Exception as exc:
            # A configured sandbox that cannot be built is a missing sandbox,
            # not a reason to skip the check quietly.
            reason = f"sandbox could not be assembled: {type(exc).__name__}: {exc}"
            logger.warning("DSH %s; using the absence gate instead", reason)
            return _absence_probe(
                plugin_id=plugin_id,
                declared=declared,
                mode=mode,
                reason=reason,
            )
        return SandboxProbe(
            state=DshSandboxState(plugin_id, True, mode.value),
            probe=_with_bridge_code(sandbox.probe),
            sandbox=sandbox,
        )

    return _absence_probe(
        plugin_id=plugin_id,
        declared=declared,
        mode=mode,
        reason="no workspace root was configured",
    )


def _absence_probe(
    *,
    plugin_id: str,
    declared: Mapping[str, tuple[object, ...]],
    mode: SandboxAbsenceMode,
    reason: str,
) -> SandboxProbe:
    gate = SandboxAbsenceGate(
        mode=mode,
        plugin_id=plugin_id,
        required_capabilities=dict(declared),
    )
    key = (plugin_id, mode.value)
    if key not in ANNOUNCED:
        ANNOUNCED.add(key)
        gate.announce()
    return SandboxProbe(
        state=DshSandboxState(plugin_id, False, mode.value, reason),
        probe=_with_bridge_code(gate.probe),
    )


def _with_bridge_code(probe: CapabilityProbe) -> CapabilityProbe:
    """Map a sandbox denial to a precise bridge code.

    Absence and a real sandbox denial must stay distinguishable in the tool
    result, otherwise "no sandbox" and "path escape" look the same.
    """

    def call(
        tool_name: str, arguments: Mapping[str, Any] | None = None
    ) -> SandboxProbeResult:
        result = probe(tool_name, arguments or {})
        if not isinstance(result, SandboxProbeResult) or result.available:
            return result
        code = (
            DshToolErrorCode.TOOL_SANDBOX_NOT_ASSEMBLED
            if result.error_code is SandboxErrorCode.NOT_ASSEMBLED
            else DshToolErrorCode.TOOL_SANDBOX_DENIED
        )
        reason = result.reason
        if result.error_code is not None and result.error_code.value not in reason:
            # Make the exact sandbox code visible in the tool result, not only
            # in the ledger: path escape and permission refusals differ here.
            reason = f"[{result.error_code.value}] {reason}"
        return replace(result, bridge_code=code, reason=reason)

    return call


__all__ = [
    "ENV_SANDBOX_ABSENCE",
    "DshSandboxState",
    "SandboxProbe",
    "build_capability_probe",
    "resolve_absence_mode_strict",
]
