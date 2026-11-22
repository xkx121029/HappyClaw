"""Capability and workspace sandbox for plugins and their tools.

Entry points:

* :class:`PluginSandbox` — one plugin's declaration check, workspace boundary,
  bounded command execution, and denial ledger. ``probe()`` plugs into
  ``happyclaw.infra.plugins.bridge.ToolGuardrail`` as its capability layer, so a
  sandbox denial happens before any approval request.
* :class:`SandboxCapability` / :class:`CapabilityDeclaration` — what a tool must
  declare before it is allowed to read, write, execute, or use the network.
* :class:`SandboxLimits` / :class:`CommandRequest` / :class:`CommandOutcome` —
  the timeout and output ceilings applied to command execution.
* :class:`SandboxAuditRecord` / :class:`SandboxCheckRecord` — one record per
  denial, plus aggregated traces of allowed checks, both traceable to plugin,
  tool, capability, and reason.
* :class:`SandboxAbsenceGate` — what happens when no sandbox is assembled: a
  loud startup warning plus an explicit allow / strict switch, never a silent
  default pass.
"""

from happyclaw.infra.plugins.sandbox.absence import (
    SandboxAbsenceGate,
    SandboxAbsenceMode,
    resolve_absence_mode,
    resolve_sandbox_gate,
)
from happyclaw.infra.plugins.sandbox.audit import (
    MAX_REASON_CHARS,
    MAX_TARGET_CHARS,
    TRUNCATION_MARKER,
    InMemoryCheckLedger,
    InMemorySandboxLedger,
    SandboxAuditRecord,
    SandboxCheckLedger,
    SandboxCheckRecord,
    SandboxLedger,
    clip_text,
    new_audit_record,
    new_check_record,
)
from happyclaw.infra.plugins.sandbox.capabilities import (
    CAPABILITY_LABELS,
    FILE_CAPABILITIES,
    CapabilityDeclaration,
    SandboxCapability,
    capability_labels,
    parse_capabilities,
    parse_capability,
)
from happyclaw.infra.plugins.sandbox.command import (
    CommandExecutor,
    CommandOutcome,
    CommandRequest,
    ExecutorOutput,
    PreparedCommand,
    SandboxLimits,
    SubprocessExecutor,
    truncate_output,
)
from happyclaw.infra.plugins.sandbox.errors import (
    SandboxConfigError,
    SandboxDeniedError,
    SandboxError,
    SandboxErrorCode,
    describe_exception,
)
from happyclaw.infra.plugins.sandbox.gate import PluginSandbox
from happyclaw.infra.plugins.sandbox.inspection import (
    SandboxCoverage,
    SandboxProbeResult,
    ToolInspection,
)
from happyclaw.infra.plugins.sandbox.ledger import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_FILES,
    CheckAggregator,
    CheckBucketSummary,
    CheckSummary,
    DenialSummary,
    JsonlCheckLedger,
    JsonlSandboxLedger,
    PluginDenialSummary,
    default_check_ledger_path,
    default_ledger_path,
    format_check_summary,
    format_denial_summary,
    load_check_records,
    load_denial_records,
    summarize_check_file,
    summarize_checks,
    summarize_denial_file,
    summarize_denials,
)
from happyclaw.infra.plugins.sandbox.paths import WorkspaceRoot

__all__ = [
    "CAPABILITY_LABELS",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_FILES",
    "FILE_CAPABILITIES",
    "MAX_REASON_CHARS",
    "MAX_TARGET_CHARS",
    "TRUNCATION_MARKER",
    "CapabilityDeclaration",
    "CheckAggregator",
    "CheckBucketSummary",
    "CheckSummary",
    "CommandExecutor",
    "CommandOutcome",
    "CommandRequest",
    "DenialSummary",
    "ExecutorOutput",
    "InMemoryCheckLedger",
    "InMemorySandboxLedger",
    "JsonlCheckLedger",
    "JsonlSandboxLedger",
    "PluginDenialSummary",
    "PluginSandbox",
    "PreparedCommand",
    "SandboxAbsenceGate",
    "SandboxAbsenceMode",
    "SandboxAuditRecord",
    "SandboxCapability",
    "SandboxCheckLedger",
    "SandboxCheckRecord",
    "SandboxConfigError",
    "SandboxCoverage",
    "SandboxDeniedError",
    "SandboxError",
    "SandboxErrorCode",
    "SandboxLedger",
    "SandboxLimits",
    "SandboxProbeResult",
    "SubprocessExecutor",
    "ToolInspection",
    "WorkspaceRoot",
    "capability_labels",
    "clip_text",
    "default_check_ledger_path",
    "default_ledger_path",
    "describe_exception",
    "format_check_summary",
    "format_denial_summary",
    "load_check_records",
    "load_denial_records",
    "new_audit_record",
    "new_check_record",
    "parse_capabilities",
    "parse_capability",
    "resolve_absence_mode",
    "resolve_sandbox_gate",
    "summarize_check_file",
    "summarize_checks",
    "summarize_denial_file",
    "summarize_denials",
    "truncate_output",
]
