"""The plugin sandbox gate: declaration, path, command, audit.

The gate is layer 1 of the local tool guardrail. It answers "may this tool do
this at all" from declared capabilities and the plugin's own workspace, and it
answers *before* any approval request is made. A sandbox denial is final: the
approval layer is never consulted, so "sandbox says no, approval says yes" is
not a reachable combination.

``probe()`` additionally inspects the tool arguments and runs the same path and
command checks execution will run, so a call that is certain to be rejected
never produces an approval dialog. Probe results distinguish *denied* from
*not covered*: ``coverage=not_applicable`` means no path or command was found in
the declared arguments, so the approval has no sandbox backing.

Execution still re-checks everything. If it refuses something the probe let
through, the ledger records ``SANDBOX_EARLY_CHECK_MISS`` with the underlying
code in ``root_error_code`` — a miss of the moved-forward check, not a normal
denial.

Permissions come from the plugin manifest (``PluginEnvelope.permissions``),
not from the tool list: a tool may only use what its plugin declared. An empty
declaration means least privilege, never "no limits" — a tool that needs
nothing passes, and a tool that needs anything is denied.

Decision order (first denial wins):

1. the tool declared capabilities at all;
2. every capability the tool declares is inside the plugin's declared
   permissions (a tool declaring nothing needs nothing and passes);
3. the capability this operation needs is among the tool's declarations;
4. the workspace root is usable (file or exec operations);
5. an executor exists (exec operations);
6. the requested path stays inside the workspace;
7. the command spec is valid and within the timeout / output ceilings.

Steps 1–5 run in ``probe()``; step 6–7 run in both ``probe()`` (for declared
inspectable arguments) and execution. Every denial writes one
:class:`SandboxAuditRecord`; allowed probes leave an aggregated, sampled trace
(``check_ledger``) so "not denied" and "never checked" stay distinguishable
without turning the ledger into a per-call log.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from octop.infra.plugins.sandbox.audit import (
    InMemorySandboxLedger,
    SandboxCheckLedger,
    SandboxLedger,
    new_audit_record,
)
from octop.infra.plugins.sandbox.capabilities import (
    FILE_CAPABILITIES,
    CapabilityDeclaration,
    SandboxCapability,
    capability_labels,
    parse_capabilities,
)
from octop.infra.plugins.sandbox.command import (
    CommandExecutor,
    CommandOutcome,
    CommandRequest,
    PreparedCommand,
    SandboxLimits,
    truncate_output,
)
from octop.infra.plugins.sandbox.errors import (
    SandboxConfigError,
    SandboxDeniedError,
    SandboxErrorCode,
    describe_exception,
)
from octop.infra.plugins.sandbox.inspection import (
    SandboxCoverage,
    SandboxProbeResult,
    ToolInspection,
)
from octop.infra.plugins.sandbox.ledger import CheckAggregator
from octop.infra.plugins.sandbox.paths import WorkspaceRoot

__all__ = ["PluginSandbox"]

LOGGER = logging.getLogger(__name__)

STAGE_PROBE = "probe"
STAGE_EXECUTE = "execute"


@dataclass(frozen=True, slots=True)
class _Denial:
    tool_name: str
    operation: str
    capability: SandboxCapability | None
    target: str | None
    code: SandboxErrorCode
    message: str
    stage: str
    # True when this is a static check the probe could have performed; only
    # those can be labelled as an early-check miss.
    check: bool


class PluginSandbox:
    """Enforces the declared capabilities and workspace boundary of one plugin."""

    def __init__(
        self,
        *,
        plugin_id: str,
        workspace_root: str | Path,
        declarations: Mapping[str, object],
        permissions: Iterable[object] | None = None,
        inspections: Mapping[str, ToolInspection] | None = None,
        limits: SandboxLimits | None = None,
        executor: CommandExecutor | None = None,
        ledger: SandboxLedger | None = None,
        check_ledger: SandboxCheckLedger | None = None,
        check_flush_every: int = 100,
    ) -> None:
        if not plugin_id.strip():
            raise SandboxConfigError("沙箱配置错误：缺少插件 id。")
        self.plugin_id = plugin_id
        self._root = WorkspaceRoot.create(plugin_id, workspace_root)
        self._declarations = self._build_declarations(plugin_id, declarations)
        self._permissions = self._build_permissions(permissions)
        self._inspections = self._build_inspections(inspections or {})
        # Last probe result per tool, used to label execution-time denials as
        # early-check misses. Single-user, sequential tool execution assumed.
        self._last_probe: dict[str, SandboxProbeResult] = {}
        self.limits = limits or SandboxLimits()
        self.executor = executor
        self.ledger: SandboxLedger = ledger or InMemorySandboxLedger()
        self._checks = (
            CheckAggregator(
                check_ledger,
                plugin_id=plugin_id,
                flush_every=check_flush_every,
            )
            if check_ledger is not None
            else None
        )

    @property
    def workspace_root(self) -> Path:
        return self._root.path

    @property
    def declared_permissions(self) -> frozenset[SandboxCapability]:
        return self._permissions

    @property
    def permissions_declared(self) -> bool:
        return bool(self._permissions)

    def probe(
        self,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> SandboxProbeResult:
        """Bridge-compatible capability probe that also inspects arguments.

        Runs the same path/command checks as execution, using the tool's
        declared :class:`ToolInspection`. Arguments not declared there are not
        guessed at: the result is ``not_applicable`` rather than a pass.
        """

        result = self._inspect(tool_name, arguments or {})
        self._last_probe[tool_name] = result
        if result.available and self._checks is not None:
            self._checks.note(
                tool_name=tool_name,
                stage=STAGE_PROBE,
                coverage=result.coverage.value,
                checked=result.checked,
            )
        return result

    def flush_checks(self) -> None:
        """Flush pending allowed-check aggregates to the check ledger."""

        if self._checks is not None:
            self._checks.flush()

    def resolve_path(
        self,
        tool_name: str,
        capability: SandboxCapability,
        requested: str | Path,
    ) -> Path:
        """Resolve a file request to an absolute path inside the workspace."""

        return self._check_path(
            tool_name,
            capability,
            requested,
            stage=STAGE_EXECUTE,
        )

    def prepare_command(self, tool_name: str, request: CommandRequest) -> PreparedCommand:
        """Validate a command request; nothing runs until this returns."""

        return self._build_command(tool_name, request, stage=STAGE_EXECUTE)

    def run_command(self, tool_name: str, request: CommandRequest) -> CommandOutcome:
        """Validate, execute, and apply the output cap to one command."""

        prepared = self._build_command(tool_name, request, stage=STAGE_EXECUTE)
        target = " ".join(prepared.argv)
        executor = self.executor
        if executor is None:
            self._deny(
                _Denial(
                    tool_name=tool_name,
                    operation="exec",
                    capability=SandboxCapability.EXEC,
                    target=target,
                    code=SandboxErrorCode.EXECUTOR_UNAVAILABLE,
                    message=(
                        f"沙箱拒绝：插件 {self.plugin_id} 的工具 {tool_name} 需要执行命令，"
                        "但没有配置执行器。"
                    ),
                    stage=STAGE_EXECUTE,
                    check=False,
                )
            )

        try:
            output = executor.run(prepared)
        except SandboxDeniedError as exc:
            self._deny(
                _Denial(
                    tool_name=tool_name,
                    operation="exec",
                    capability=SandboxCapability.EXEC,
                    target=target,
                    code=exc.code,
                    message=exc.message,
                    stage=STAGE_EXECUTE,
                    check=False,
                ),
                extra_details=exc.details,
            )
        except Exception as exc:
            self._deny(
                _Denial(
                    tool_name=tool_name,
                    operation="exec",
                    capability=SandboxCapability.EXEC,
                    target=target,
                    code=SandboxErrorCode.EXECUTOR_FAILED,
                    message=f"沙箱拒绝：命令执行失败（{describe_exception(exc)}）。",
                    stage=STAGE_EXECUTE,
                    check=False,
                )
            )

        if output.timed_out:
            self._deny(
                _Denial(
                    tool_name=tool_name,
                    operation="exec",
                    capability=SandboxCapability.EXEC,
                    target=target,
                    code=SandboxErrorCode.COMMAND_TIMEOUT,
                    message=f"沙箱拒绝：命令在 {prepared.timeout_s}s 内没有结束，已停止。",
                    stage=STAGE_EXECUTE,
                    check=False,
                )
            )

        stdout, stderr, dropped = truncate_output(
            output.stdout,
            output.stderr,
            prepared.max_output_bytes,
        )
        return CommandOutcome(
            exit_code=output.exit_code,
            stdout=stdout,
            stderr=stderr,
            truncated=dropped > 0,
            dropped_bytes=dropped,
            timeout_s=prepared.timeout_s,
        )

    # ------------------------------------------------------------------
    # Probe internals
    # ------------------------------------------------------------------

    def _inspect(self, tool_name: str, arguments: Mapping[str, Any]) -> SandboxProbeResult:
        denial = self._readiness(tool_name)
        if denial is not None:
            self._record(denial)
            return SandboxProbeResult(
                False,
                denial.message,
                SandboxCoverage.NOT_APPLICABLE,
                (),
                denial.code,
                False,
            )

        plan = self._inspections.get(tool_name)
        if plan is None or plan.is_empty:
            return SandboxProbeResult(
                True,
                f"沙箱未覆盖：插件 {self.plugin_id} 的工具 {tool_name} 没有声明可检查的路径或命令，"
                "本次审批没有沙箱背书。",
                SandboxCoverage.NOT_APPLICABLE,
                (),
                None,
                False,
            )

        declaration = self._declarations[tool_name]
        checked: list[str] = []
        try:
            for key in plan.path_args:
                raw = arguments.get(key)
                if not self._is_path_value(raw):
                    continue
                checked.append(key)
                capability = (
                    SandboxCapability.FS_WRITE
                    if declaration.declares(SandboxCapability.FS_WRITE)
                    else SandboxCapability.FS_READ
                )
                self._check_path(tool_name, capability, raw, stage=STAGE_PROBE)

            if plan.command_arg is not None:
                argv = self._coerce_argv(arguments.get(plan.command_arg))
                if argv is not None:
                    checked.append(plan.command_arg)
                    self._build_command(
                        tool_name,
                        CommandRequest(argv=argv, cwd=self._probe_cwd(plan, arguments)),
                        stage=STAGE_PROBE,
                    )
        except SandboxDeniedError as exc:
            return SandboxProbeResult(
                False,
                exc.message,
                SandboxCoverage.COVERED,
                tuple(checked),
                exc.code,
                True,
            )

        if not checked:
            return SandboxProbeResult(
                True,
                f"沙箱未覆盖：插件 {self.plugin_id} 的工具 {tool_name} 的参数里没有可检查的路径或命令，"
                "本次审批没有沙箱背书。",
                SandboxCoverage.NOT_APPLICABLE,
                (),
                None,
                True,
            )
        return SandboxProbeResult(
            True,
            f"沙箱已覆盖：已检查 {', '.join(checked)}。",
            SandboxCoverage.COVERED,
            tuple(checked),
            None,
            True,
        )

    def _readiness(self, tool_name: str) -> _Denial | None:
        """Checks 1–5: tool declaration, plugin permission, workspace, executor."""

        declaration = self._declarations.get(tool_name)
        if declaration is None:
            return _Denial(
                tool_name=tool_name,
                operation="probe",
                capability=None,
                target=None,
                code=SandboxErrorCode.CAPABILITY_UNDECLARED,
                message=f"沙箱拒绝：插件 {self.plugin_id} 的工具 {tool_name} 没有能力声明。",
                stage=STAGE_PROBE,
                check=False,
            )

        missing = declaration.capabilities - self._permissions
        if missing:
            return _Denial(
                tool_name=tool_name,
                operation="probe",
                capability=None,
                target=None,
                code=self._permission_code(),
                message=self._permission_message(tool_name, missing),
                stage=STAGE_PROBE,
                check=False,
            )

        needs_workspace = bool(
            declaration.capabilities & (FILE_CAPABILITIES | {SandboxCapability.EXEC})
        )
        if needs_workspace:
            try:
                self._root.require_usable()
            except SandboxDeniedError as exc:
                return _Denial(
                    tool_name=tool_name,
                    operation="probe",
                    capability=SandboxCapability.FS_READ,
                    target=None,
                    code=exc.code,
                    message=exc.message,
                    stage=STAGE_PROBE,
                    check=False,
                )

        if SandboxCapability.EXEC in declaration.capabilities and self.executor is None:
            return _Denial(
                tool_name=tool_name,
                operation="probe",
                capability=SandboxCapability.EXEC,
                target=None,
                code=SandboxErrorCode.EXECUTOR_UNAVAILABLE,
                message=(
                    f"沙箱拒绝：插件 {self.plugin_id} 的工具 {tool_name} 需要执行命令，"
                    "但没有配置执行器。"
                ),
                stage=STAGE_PROBE,
                check=False,
            )
        return None

    @staticmethod
    def _is_path_value(raw: object) -> bool:
        if isinstance(raw, Path):
            return True
        return isinstance(raw, str) and bool(raw.strip())

    @staticmethod
    def _coerce_argv(raw: object) -> tuple[str, ...] | None:
        if isinstance(raw, (str, bytes, bytearray)) or not isinstance(raw, Sequence):
            return None
        parts: list[str] = []
        for item in raw:
            if not isinstance(item, str):
                return None
            parts.append(item)
        return tuple(parts) if parts else None

    @staticmethod
    def _probe_cwd(plan: ToolInspection, arguments: Mapping[str, Any]) -> str:
        if plan.cwd_arg is None:
            return "."
        raw = arguments.get(plan.cwd_arg)
        if isinstance(raw, str) and raw.strip():
            return raw
        return "."

    # ------------------------------------------------------------------
    # Shared checks (probe and execution use the same code)
    # ------------------------------------------------------------------

    def _check_path(
        self,
        tool_name: str,
        capability: SandboxCapability,
        requested: str | Path,
        *,
        stage: str,
    ) -> Path:
        if capability not in FILE_CAPABILITIES:
            raise SandboxConfigError(
                "沙箱配置错误：文件操作只能使用读文件或写文件能力。",
                details={"capability": capability.value},
            )
        self._require(
            tool_name,
            capability,
            operation="fs",
            target=str(requested),
            stage=stage,
        )
        try:
            self._root.require_usable()
            return self._root.resolve(requested)
        except SandboxDeniedError as exc:
            self._deny(
                _Denial(
                    tool_name=tool_name,
                    operation="fs",
                    capability=capability,
                    target=str(requested),
                    code=exc.code,
                    message=exc.message,
                    stage=stage,
                    check=True,
                ),
                extra_details=exc.details,
            )

    def _build_command(
        self,
        tool_name: str,
        request: CommandRequest,
        *,
        stage: str,
    ) -> PreparedCommand:
        target = " ".join(str(part) for part in request.argv)
        self._require(
            tool_name,
            SandboxCapability.EXEC,
            operation="exec",
            target=target,
            stage=stage,
        )

        argv = self._validate_argv(tool_name, request.argv, target, stage=stage)
        try:
            self._root.require_usable()
            cwd = self._root.resolve(request.cwd)
        except SandboxDeniedError as exc:
            self._deny(
                _Denial(
                    tool_name=tool_name,
                    operation="exec",
                    capability=SandboxCapability.EXEC,
                    target=str(request.cwd),
                    code=exc.code,
                    message=exc.message,
                    stage=stage,
                    check=True,
                ),
                extra_details=exc.details,
            )

        timeout_s = (
            request.timeout_s if request.timeout_s is not None else self.limits.default_timeout_s
        )
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            self._deny(
                _Denial(
                    tool_name=tool_name,
                    operation="exec",
                    capability=SandboxCapability.EXEC,
                    target=target,
                    code=SandboxErrorCode.COMMAND_INVALID,
                    message=f"沙箱拒绝：命令超时时间 {timeout_s!r} 不是有效正数。",
                    stage=stage,
                    check=True,
                )
            )
        if timeout_s > self.limits.max_timeout_s:
            self._deny(
                _Denial(
                    tool_name=tool_name,
                    operation="exec",
                    capability=SandboxCapability.EXEC,
                    target=target,
                    code=SandboxErrorCode.COMMAND_INVALID,
                    message=(
                        f"沙箱拒绝：命令超时时间 {timeout_s}s 超过上限 "
                        f"{self.limits.max_timeout_s}s。"
                    ),
                    stage=stage,
                    check=True,
                )
            )

        requested_limit = (
            request.max_output_bytes
            if request.max_output_bytes is not None
            else self.limits.max_output_bytes
        )
        if requested_limit <= 0:
            self._deny(
                _Denial(
                    tool_name=tool_name,
                    operation="exec",
                    capability=SandboxCapability.EXEC,
                    target=target,
                    code=SandboxErrorCode.COMMAND_INVALID,
                    message=f"沙箱拒绝：输出上限 {requested_limit} 字节不是正整数。",
                    stage=stage,
                    check=True,
                )
            )
        effective_limit = min(requested_limit, self.limits.max_output_bytes)

        return PreparedCommand(
            argv=argv,
            cwd=cwd,
            timeout_s=timeout_s,
            max_output_bytes=effective_limit,
        )

    # ------------------------------------------------------------------
    # Declaration, records, and denial
    # ------------------------------------------------------------------

    def _build_declarations(
        self,
        plugin_id: str,
        declarations: Mapping[str, object],
    ) -> dict[str, CapabilityDeclaration]:
        built: dict[str, CapabilityDeclaration] = {}
        for tool_name, declared in declarations.items():
            built[tool_name] = CapabilityDeclaration(
                plugin_id=plugin_id,
                tool_name=tool_name,
                capabilities=parse_capabilities(declared),
            )
        return built

    def _build_permissions(
        self,
        permissions: Iterable[object] | None,
    ) -> frozenset[SandboxCapability]:
        # ``None`` and an empty list both mean "declared nothing": least
        # privilege, never "everything is allowed".
        return parse_capabilities(permissions)

    def _permission_code(self) -> SandboxErrorCode:
        """Distinguish "declared nothing" from "declared something else"."""

        if self._permissions:
            return SandboxErrorCode.PERMISSION_OUT_OF_SCOPE
        return SandboxErrorCode.PERMISSION_UNDECLARED

    def _permission_message(
        self,
        tool_name: str,
        missing: Iterable[SandboxCapability],
    ) -> str:
        labels = capability_labels(missing)
        if not self._permissions:
            return (
                f"沙箱拒绝：插件 {self.plugin_id} 未声明任何权限（最小权限），"
                f"但工具 {tool_name} 需要「{labels}」。"
            )
        return (
            f"沙箱拒绝：插件 {self.plugin_id} 的工具 {tool_name} 需要「{labels}」，"
            f"但插件只声明了「{capability_labels(self._permissions)}」，未声明该权限。"
        )

    def _build_inspections(
        self,
        inspections: Mapping[str, ToolInspection],
    ) -> dict[str, ToolInspection]:
        built: dict[str, ToolInspection] = {}
        for tool_name, plan in inspections.items():
            declaration = self._declarations.get(tool_name)
            if declaration is None:
                raise SandboxConfigError(
                    f"沙箱配置错误：工具 {tool_name} 有检查声明但没有能力声明。",
                    details={"plugin": self.plugin_id, "tool_name": tool_name},
                )
            if not isinstance(plan, ToolInspection):
                raise SandboxConfigError(
                    f"沙箱配置错误：工具 {tool_name} 的检查声明类型不正确。",
                    details={"plugin": self.plugin_id, "tool_name": tool_name},
                )
            if plan.path_args and not (declaration.capabilities & FILE_CAPABILITIES):
                raise SandboxConfigError(
                    f"沙箱配置错误：工具 {tool_name} 声明了路径参数，但没有声明读/写文件能力。",
                    details={"plugin": self.plugin_id, "tool_name": tool_name},
                )
            if plan.command_arg is not None and not declaration.declares(
                SandboxCapability.EXEC
            ):
                raise SandboxConfigError(
                    f"沙箱配置错误：工具 {tool_name} 声明了命令参数，但没有声明执行命令能力。",
                    details={"plugin": self.plugin_id, "tool_name": tool_name},
                )
            built[tool_name] = plan
        return built

    def _require(
        self,
        tool_name: str,
        capability: SandboxCapability,
        *,
        operation: str,
        target: str | None,
        stage: str,
    ) -> CapabilityDeclaration:
        declaration = self._declarations.get(tool_name)
        if declaration is None:
            self._deny(
                _Denial(
                    tool_name=tool_name,
                    operation=operation,
                    capability=capability,
                    target=target,
                    code=SandboxErrorCode.CAPABILITY_UNDECLARED,
                    message=f"沙箱拒绝：插件 {self.plugin_id} 的工具 {tool_name} 没有能力声明。",
                    stage=stage,
                    check=True,
                )
            )
        if not declaration.declares(capability):
            self._deny(
                _Denial(
                    tool_name=tool_name,
                    operation=operation,
                    capability=capability,
                    target=target,
                    code=SandboxErrorCode.CAPABILITY_UNDECLARED,
                    message=(
                        f"沙箱拒绝：插件 {self.plugin_id} 的工具 {tool_name} 未声明"
                        f"「{capability_labels({capability})}」能力。"
                    ),
                    stage=stage,
                    check=True,
                )
            )
        if capability not in self._permissions:
            self._deny(
                _Denial(
                    tool_name=tool_name,
                    operation=operation,
                    capability=capability,
                    target=target,
                    code=self._permission_code(),
                    message=self._permission_message(tool_name, {capability}),
                    stage=stage,
                    check=True,
                )
            )
        return declaration

    def _validate_argv(
        self,
        tool_name: str,
        raw: Iterable[object],
        target: str,
        *,
        stage: str,
    ) -> tuple[str, ...]:
        argv: list[str] = []
        for part in raw:
            if not isinstance(part, str):
                self._deny(
                    _Denial(
                        tool_name=tool_name,
                        operation="exec",
                        capability=SandboxCapability.EXEC,
                        target=target,
                        code=SandboxErrorCode.COMMAND_INVALID,
                        message="沙箱拒绝：命令参数必须是字符串列表。",
                        stage=stage,
                        check=True,
                    )
                )
            if "\x00" in part:
                self._deny(
                    _Denial(
                        tool_name=tool_name,
                        operation="exec",
                        capability=SandboxCapability.EXEC,
                        target=target,
                        code=SandboxErrorCode.COMMAND_INVALID,
                        message="沙箱拒绝：命令参数包含非法字符。",
                        stage=stage,
                        check=True,
                    )
                )
            argv.append(part)
        if not argv:
            self._deny(
                _Denial(
                    tool_name=tool_name,
                    operation="exec",
                    capability=SandboxCapability.EXEC,
                    target=target,
                    code=SandboxErrorCode.COMMAND_INVALID,
                    message="沙箱拒绝：命令为空。",
                    stage=stage,
                    check=True,
                )
            )
        return tuple(argv)

    def _stamp(self, denial: _Denial) -> tuple[str, str | None, str]:
        """Return the ledger's ``(error_code, root_error_code, reason)``.

        An execution-stage static denial is a miss when the probe for this tool
        let the call through without actually checking the argument that
        execution just rejected.
        """

        if denial.stage != STAGE_EXECUTE or not denial.check:
            return denial.code.value, None, denial.message
        last = self._last_probe.get(denial.tool_name)
        if last is None or not last.available:
            return denial.code.value, None, denial.message
        if last.coverage is SandboxCoverage.NOT_APPLICABLE:
            prefix = "前移漏判：探针没有检查到本次使用的路径或命令，本次审批没有沙箱背书"
        else:
            prefix = "前移漏判：探针检查的参数与执行时使用的参数不一致"
        return (
            SandboxErrorCode.EARLY_CHECK_MISS.value,
            denial.code.value,
            f"{prefix}，执行阶段才拒绝（{denial.code.value}：{denial.message}）。",
        )

    def _deny(
        self,
        denial: _Denial,
        *,
        extra_details: Mapping[str, Any] | None = None,
    ) -> NoReturn:
        _, root_code, _ = self._stamp(denial)
        self._record(denial)
        details: dict[str, Any] = {
            "plugin_id": self.plugin_id,
            "tool_name": denial.tool_name,
            "operation": denial.operation,
            "capability": denial.capability.value if denial.capability else None,
            "target": denial.target,
            "stage": denial.stage,
        }
        if extra_details:
            details.update(extra_details)
        if root_code is not None:
            details["early_check_miss"] = True
            details["root_error_code"] = root_code
        raise SandboxDeniedError(denial.code, denial.message, details=details)

    def _record(self, denial: _Denial) -> None:
        error_code, root_code, reason = self._stamp(denial)
        record = new_audit_record(
            plugin_id=self.plugin_id,
            tool_name=denial.tool_name,
            operation=denial.operation,
            capability=denial.capability.value if denial.capability else None,
            target=denial.target,
            stage=denial.stage,
            error_code=error_code,
            root_error_code=root_code,
            reason=reason,
        )
        try:
            self.ledger.append(record)
        except Exception as exc:
            # An audit sink failure must not change the security decision: the
            # denial stands and keeps its original error code. One warning is
            # enough; a denial storm must not turn into a log storm.
            LOGGER.warning(
                "沙箱审计写入失败，拒绝判定保持不变（plugin=%s tool=%s code=%s）：%s",
                self.plugin_id,
                record.tool_name,
                record.error_code,
                describe_exception(exc),
            )
