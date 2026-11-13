"""Explicit behavior when the sandbox is not assembled.

A missing sandbox is a state, not an implicit pass. The host calls
:func:`resolve_sandbox_gate` at startup: when no sandbox is wired, it logs a
prominent warning saying path and permission checks will not run, and returns a
probe the guardrail can still use.

Two modes decide whether tools may run without a sandbox:

* ``allow`` (default) — keep executing, but the warning is on the record. The
  probe reports ``coverage=not_applicable``, so a guardrail configured with
  ``require_sandbox_backing`` still refuses calls that need approval.
* ``strict`` — every tool that needs a permission is refused with
  ``SANDBOX_NOT_ASSEMBLED``. Least privilege still applies: an explicitly empty
  required set is allowed, while a tool missing from the supplied map is denied,
  because "cannot prove it needs nothing" is not "needs nothing".

This gate never pretends to be a sandbox: it performs no path, command, or
workspace check. It only makes the absence visible and, optionally, fatal for
tools that would otherwise run unchecked.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from octop.infra.plugins.sandbox.capabilities import SandboxCapability, parse_capabilities
from octop.infra.plugins.sandbox.errors import SandboxConfigError, SandboxErrorCode
from octop.infra.plugins.sandbox.inspection import SandboxCoverage, SandboxProbeResult

__all__ = [
    "SandboxAbsenceGate",
    "SandboxAbsenceMode",
    "resolve_absence_mode",
    "resolve_sandbox_gate",
]

LOGGER_NAME = "octop.infra.plugins.sandbox.absence"

LOGGER = logging.getLogger(LOGGER_NAME)


class SandboxAbsenceMode(StrEnum):
    """What happens to tool calls when no sandbox is assembled."""

    ALLOW = "allow"
    STRICT = "strict"


def resolve_absence_mode(value: object | None) -> SandboxAbsenceMode:
    """Parse the configured absence mode; ``None`` means the default ``allow``.

    An unknown value fails loud instead of falling back to a mode the host did
    not ask for.
    """

    if value is None:
        return SandboxAbsenceMode.ALLOW
    if isinstance(value, SandboxAbsenceMode):
        return value
    text = str(value).strip().lower()
    for mode in SandboxAbsenceMode:
        if text == mode.value:
            return mode
    raise SandboxConfigError(
        f"沙箱配置错误：未知的无沙箱策略 {value!r}，可选值为 "
        f"{' / '.join(mode.value for mode in SandboxAbsenceMode)}。"
    )


@dataclass(frozen=True, slots=True)
class SandboxAbsenceGate:
    """Probe used in place of a sandbox, plus the startup warning.

    ``required_capabilities`` maps tool names to the capabilities their
    declarations require. It is only consulted in strict mode; in allow mode the
    gate does not need to know anything about the tools.
    """

    mode: SandboxAbsenceMode = SandboxAbsenceMode.ALLOW
    plugin_id: str | None = None
    required_capabilities: Mapping[str, object] = field(default_factory=dict)
    _required: Mapping[str, frozenset[SandboxCapability]] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        normalized: dict[str, frozenset[SandboxCapability]] = {}
        for raw_name, raw_caps in self.required_capabilities.items():
            name = str(raw_name).strip()
            if not name:
                raise SandboxConfigError("沙箱配置错误：无沙箱策略里的工具名不能为空。")
            normalized[name] = parse_capabilities(raw_caps)
        object.__setattr__(self, "required_capabilities", normalized)
        object.__setattr__(self, "_required", normalized)

    def announce(self) -> None:
        """Log the startup warning; one call per boot, no per-call noise."""

        plugin = self.plugin_id or "<未指定>"
        if self.mode is SandboxAbsenceMode.ALLOW:
            LOGGER.warning(
                "【沙箱未启用】插件 %s 的工具调用将不经过路径与权限检查，"
                "按默认策略继续执行。如需收紧，请把无沙箱策略设置为 strict。",
                plugin,
            )
            return
        LOGGER.warning(
            "【沙箱未启用】严格模式：需要权限的工具将被直接拒绝"
            "（错误码 %s）；不需要权限的工具仍会执行，且同样没有路径检查。",
            SandboxErrorCode.NOT_ASSEMBLED.value,
        )

    def probe(
        self,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> SandboxProbeResult:
        """Bridge-compatible probe for the no-sandbox case.

        Allow mode returns ``available=True`` with ``coverage=not_applicable``:
        executable, but explicitly not backed by any check. Strict mode denies
        tools that need permissions, and tools whose needs are unknown.
        """

        if self.mode is SandboxAbsenceMode.ALLOW:
            return SandboxProbeResult(
                available=True,
                reason=(
                    f"沙箱未启用：工具 {tool_name} 没有经过路径与权限检查"
                    f"（策略 allow，{SandboxErrorCode.NOT_ASSEMBLED.value}）。"
                ),
                coverage=SandboxCoverage.UNAVAILABLE,
            )

        if tool_name not in self._required:
            return self._deny(
                tool_name,
                "无法确认该工具是否需要权限，按需要权限处理并拒绝",
            )
        required = self._required[tool_name]
        if not required:
            return SandboxProbeResult(
                available=True,
                reason=(
                    f"沙箱未启用：工具 {tool_name} 未声明需要权限，严格模式放行，"
                    "但仍没有路径检查。"
                ),
                coverage=SandboxCoverage.UNAVAILABLE,
            )
        needed = "、".join(sorted(capability.value for capability in required))
        return self._deny(tool_name, f"该工具需要权限 {needed}")

    def _deny(self, tool_name: str, detail: str) -> SandboxProbeResult:
        return SandboxProbeResult(
            available=False,
            reason=(
                f"沙箱未启用且策略为 strict：{detail}，拒绝执行工具 {tool_name}"
                f"（{SandboxErrorCode.NOT_ASSEMBLED.value}）。"
            ),
            coverage=SandboxCoverage.UNAVAILABLE,
            error_code=SandboxErrorCode.NOT_ASSEMBLED,
        )


def resolve_sandbox_gate(
    sandbox: object | None,
    *,
    mode: object | None = None,
    plugin_id: str | None = None,
    required_capabilities: Mapping[str, Iterable[object]] | None = None,
) -> SandboxAbsenceGate | None:
    """Startup entry point: warn when the sandbox is missing, build its gate.

    Returns ``None`` when a sandbox is assembled. Otherwise the absence gate is
    built, the warning is logged once, and the caller wires ``gate.probe`` as
    the guardrail's capability probe.
    """

    if sandbox is not None:
        return None
    gate = SandboxAbsenceGate(
        mode=resolve_absence_mode(mode),
        plugin_id=plugin_id,
        required_capabilities=dict(required_capabilities or {}),
    )
    gate.announce()
    return gate
