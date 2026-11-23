"""Bounded command execution for plugins.

There is deliberately no command blacklist. Pattern-matching command strings is
bypassable (encoding, aliases, wrapper scripts) and turns "did not match" into a
false "safe". The boundary is four concrete facts instead:

1. the tool declared the ``exec`` capability;
2. the working directory resolves inside the plugin workspace;
3. the timeout is a positive number within the policy ceiling;
4. the captured output is capped by bytes and marked when it was cut.

A request that violates the spec is denied before anything runs; output above
the cap is truncated and the result says so.
"""

from __future__ import annotations

import math
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from happyclaw.infra.plugins.sandbox.errors import (
    SandboxConfigError,
    SandboxDeniedError,
    SandboxErrorCode,
    describe_exception,
)

__all__ = [
    "CommandExecutor",
    "CommandOutcome",
    "CommandRequest",
    "ExecutorOutput",
    "PreparedCommand",
    "SandboxLimits",
    "SubprocessExecutor",
    "truncate_output",
]

DEFAULT_TIMEOUT_S = 30.0
DEFAULT_MAX_TIMEOUT_S = 120.0
DEFAULT_MAX_OUTPUT_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    """Ceilings the sandbox enforces regardless of what a tool asks for."""

    default_timeout_s: float = DEFAULT_TIMEOUT_S
    max_timeout_s: float = DEFAULT_MAX_TIMEOUT_S
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES

    def __post_init__(self) -> None:
        for name, value in (
            ("default_timeout_s", self.default_timeout_s),
            ("max_timeout_s", self.max_timeout_s),
        ):
            if not math.isfinite(value) or value <= 0:
                raise SandboxConfigError(
                    f"沙箱配置错误：{name} 必须是正数。",
                    details={"code": SandboxErrorCode.LIMITS_INVALID.value, "value": value},
                )
        if self.default_timeout_s > self.max_timeout_s:
            raise SandboxConfigError(
                "沙箱配置错误：default_timeout_s 不能大于 max_timeout_s。",
                details={
                    "code": SandboxErrorCode.LIMITS_INVALID.value,
                    "default_timeout_s": self.default_timeout_s,
                    "max_timeout_s": self.max_timeout_s,
                },
            )
        if self.max_output_bytes <= 0:
            raise SandboxConfigError(
                "沙箱配置错误：max_output_bytes 必须是正整数。",
                details={
                    "code": SandboxErrorCode.LIMITS_INVALID.value,
                    "max_output_bytes": self.max_output_bytes,
                },
            )


@dataclass(frozen=True, slots=True)
class CommandRequest:
    """What a tool asked to run; validated into a :class:`PreparedCommand`."""

    argv: Sequence[str]
    cwd: str = "."
    timeout_s: float | None = None
    max_output_bytes: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "argv", tuple(self.argv))


@dataclass(frozen=True, slots=True)
class PreparedCommand:
    """A command that passed the sandbox checks and may be handed to an executor."""

    argv: tuple[str, ...]
    cwd: Path
    timeout_s: float
    max_output_bytes: int


@dataclass(frozen=True, slots=True)
class ExecutorOutput:
    """Raw executor result before the sandbox applies the output cap."""

    exit_code: int
    stdout: bytes = b""
    stderr: bytes = b""
    timed_out: bool = False


@dataclass(frozen=True, slots=True)
class CommandOutcome:
    """What the plugin gets back; ``truncated`` means output was cut."""

    exit_code: int
    stdout: bytes
    stderr: bytes
    truncated: bool
    dropped_bytes: int
    timeout_s: float


class CommandExecutor(Protocol):
    """Runs one prepared command. Tests use a fake; production uses subprocess."""

    def run(self, command: PreparedCommand) -> ExecutorOutput: ...


class SubprocessExecutor:
    """Runs a command without a shell, with the sandbox timeout applied."""

    def run(self, command: PreparedCommand) -> ExecutorOutput:
        try:
            completed = subprocess.run(
                list(command.argv),
                cwd=str(command.cwd),
                timeout=command.timeout_s,
                capture_output=True,
                shell=False,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ExecutorOutput(exit_code=-1, timed_out=True)
        except OSError as exc:
            raise SandboxDeniedError(
                SandboxErrorCode.EXECUTOR_FAILED,
                f"沙箱拒绝：命令无法启动（{describe_exception(exc)}）。",
                details={"argv0": command.argv[0] if command.argv else ""},
            ) from None
        return ExecutorOutput(
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


def truncate_output(stdout: bytes, stderr: bytes, limit: int) -> tuple[bytes, bytes, int]:
    """Cap combined stdout+stderr at ``limit`` bytes.

    stdout keeps priority so an error message is not crowded out by a verbose
    success stream. Returns the kept streams and how many bytes were dropped.
    """

    total = len(stdout) + len(stderr)
    if total <= limit:
        return stdout, stderr, 0
    kept_stdout = stdout[:limit]
    kept_stderr = stderr[: max(0, limit - len(kept_stdout))]
    return kept_stdout, kept_stderr, total - (len(kept_stdout) + len(kept_stderr))
