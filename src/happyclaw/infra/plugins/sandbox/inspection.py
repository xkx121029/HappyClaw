"""Pre-approval argument inspection for the plugin sandbox.

The probe runs the *same* path and command checks as execution, so an approval
dialog is never shown for a call that is certain to be rejected. Two facts are
kept separate:

* ``available`` — may this tool run at all (capability/workspace/executor);
* ``coverage`` — did the probe actually inspect a path or command from the
  arguments. ``NOT_APPLICABLE`` means it inspected nothing, so the approval has
  no sandbox backing. It is not a pass, and it is not a denial either.

Which arguments are inspectable is declared, never guessed: a tool without a
:class:`ToolInspection` plan is reported as ``NOT_APPLICABLE``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from happyclaw.infra.plugins.bridge.approval import CapabilityDecision
from happyclaw.infra.plugins.bridge.errors import DshToolErrorCode
from happyclaw.infra.plugins.sandbox.errors import SandboxConfigError, SandboxErrorCode

__all__ = [
    "SandboxCoverage",
    "SandboxProbeResult",
    "ToolInspection",
]


class SandboxCoverage(StrEnum):
    """Whether the probe inspected a concrete path or command.

    Three distinct states, never collapsed into one:

    * ``COVERED`` — a declared path/command argument was inspected and passed;
    * ``NOT_APPLICABLE`` — the sandbox is assembled, but this call had nothing
      declared to inspect (no plan, or none of the declared arguments present);
    * ``UNAVAILABLE`` — no sandbox was assembled at all.
    """

    COVERED = "covered"
    NOT_APPLICABLE = "not_applicable"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class SandboxProbeResult(CapabilityDecision):
    """A capability decision plus what the probe actually inspected.

    Subclasses ``CapabilityDecision`` so ``happyclaw.infra.plugins.bridge`` keeps
    working unchanged: its guardrail only reads ``available`` / ``reason``.
    Callers that need to know whether the sandbox backed the call read
    ``coverage`` (or ``backed``).

    ``inspected`` tells "there was an inspection plan" apart from "there was
    nothing to inspect": a plan whose arguments were all absent reports
    ``inspected=True`` with ``checked=()``.
    """

    coverage: SandboxCoverage = SandboxCoverage.NOT_APPLICABLE
    checked: tuple[str, ...] = ()
    error_code: SandboxErrorCode | None = None
    inspected: bool = False
    # Let the host choose a precise bridge error code without making the
    # sandbox package depend on DSH: the bridge reads it duck-typed.
    bridge_code: DshToolErrorCode | None = None

    @property
    def backed(self) -> bool:
        """True only when the probe ran checks and they passed."""

        return self.available and self.coverage is SandboxCoverage.COVERED


@dataclass(frozen=True, slots=True)
class ToolInspection:
    """Declares which tool arguments the probe may treat as paths or commands.

    ``path_args`` names arguments holding a filesystem path; ``command_arg``
    names an argument holding an argv list, with ``cwd_arg`` optionally naming
    its working directory. Anything not listed here is *not* inspected: the
    probe reports ``NOT_APPLICABLE`` instead of inferring.
    """

    path_args: tuple[str, ...] = ()
    command_arg: str | None = None
    cwd_arg: str | None = None

    def __post_init__(self) -> None:
        cleaned: list[str] = []
        for raw in self.path_args:
            key = str(raw).strip()
            if not key:
                raise SandboxConfigError(
                    "沙箱配置错误：待检查的路径参数名不能为空。",
                    details={"code": SandboxErrorCode.DECLARATION_INVALID.value},
                )
            if key not in cleaned:
                cleaned.append(key)
        object.__setattr__(self, "path_args", tuple(cleaned))
        if self.command_arg is not None:
            command_arg = str(self.command_arg).strip()
            if not command_arg:
                raise SandboxConfigError(
                    "沙箱配置错误：待检查的命令参数名不能为空。",
                    details={"code": SandboxErrorCode.DECLARATION_INVALID.value},
                )
            object.__setattr__(self, "command_arg", command_arg)
        if self.cwd_arg is not None:
            cwd_arg = str(self.cwd_arg).strip()
            if not cwd_arg:
                raise SandboxConfigError(
                    "沙箱配置错误：待检查的工作目录参数名不能为空。",
                    details={"code": SandboxErrorCode.DECLARATION_INVALID.value},
                )
            object.__setattr__(self, "cwd_arg", cwd_arg)
        if self.cwd_arg is not None and self.command_arg is None:
            raise SandboxConfigError(
                "沙箱配置错误：声明了工作目录参数就必须同时声明命令参数。",
                details={"code": SandboxErrorCode.DECLARATION_INVALID.value},
            )

    @property
    def is_empty(self) -> bool:
        return not self.path_args and self.command_arg is None
