"""Bridge between DSH plugin tool definitions and Octop's agent tool runtime.

Entry points:

* :class:`DshToolRegistry` — register / unregister DSH ``ToolDefinition`` objects
  per scope, project the model-facing schema, and map them into Octop's
  ``happyclaw_harness.plugins.PluginRegistry``.
* :class:`ToolPipeline` — one call through the guard-railed pipeline.
* :class:`ToolBatcher` — concurrency-safe batching with ordered settlement.
* :class:`ToolDefinition` — the DSH contract mirror (parameters / output /
  timeout / concurrency classifier / policy hooks).
"""

from happyclaw.infra.plugins.bridge.approval import (
    ApprovalChannel,
    ApprovalChannelError,
    ApprovalDecision,
    ApprovalLedger,
    ApprovalRecord,
    CapabilityDecision,
    Guardrail,
    GuardrailContext,
    GuardrailDecision,
    InMemoryApprovalLedger,
    PolicyVerdict,
    RiskAssessment,
    RiskLevel,
    SandboxBacking,
    ToolGuardrail,
)
from happyclaw.infra.plugins.bridge.batch import ToolBatcher
from happyclaw.infra.plugins.bridge.contract import (
    ApprovalOutcome,
    ApprovalRequest,
    PostToolDecision,
    PreToolDecision,
    ToolDefinition,
    ToolExecutionContext,
    ToolOutputSpec,
)
from happyclaw.infra.plugins.bridge.contract_types import (
    ContentBlock,
    ContentBlocks,
    normalize_content,
    text_content,
)
from happyclaw.infra.plugins.bridge.errors import (
    DshToolError,
    DshToolErrorCode,
    describe_exception,
)
from happyclaw.infra.plugins.bridge.hitl import (
    DEFAULT_APPROVAL_TIMEOUT_S,
    ApprovalTransport,
    HitlApprovalChannel,
    LangGraphInterruptTransport,
    build_hitl_request,
)
from happyclaw.infra.plugins.bridge.pipeline import (
    DEFAULT_MAX_RESULT_BYTES,
    ToolCall,
    ToolCallRecord,
    ToolInvocation,
    ToolPipeline,
    ToolResultRecord,
)
from happyclaw.infra.plugins.bridge.registry import (
    DEFAULT_PLUGIN_ID,
    GLOBAL_SCOPE,
    DshToolRegistry,
    default_plugin_id,
    run_definition,
    synthetic_signature,
)

__all__ = [
    "DEFAULT_APPROVAL_TIMEOUT_S",
    "DEFAULT_MAX_RESULT_BYTES",
    "DEFAULT_PLUGIN_ID",
    "GLOBAL_SCOPE",
    "ApprovalChannel",
    "ApprovalChannelError",
    "ApprovalDecision",
    "ApprovalLedger",
    "ApprovalOutcome",
    "ApprovalRecord",
    "ApprovalRequest",
    "ApprovalTransport",
    "CapabilityDecision",
    "ContentBlock",
    "ContentBlocks",
    "DshToolError",
    "DshToolErrorCode",
    "DshToolRegistry",
    "Guardrail",
    "GuardrailContext",
    "GuardrailDecision",
    "HitlApprovalChannel",
    "InMemoryApprovalLedger",
    "LangGraphInterruptTransport",
    "PolicyVerdict",
    "PostToolDecision",
    "PreToolDecision",
    "RiskAssessment",
    "RiskLevel",
    "SandboxBacking",
    "ToolBatcher",
    "ToolCall",
    "ToolCallRecord",
    "ToolDefinition",
    "ToolExecutionContext",
    "ToolGuardrail",
    "ToolInvocation",
    "ToolOutputSpec",
    "ToolPipeline",
    "ToolResultRecord",
    "build_hitl_request",
    "default_plugin_id",
    "describe_exception",
    "normalize_content",
    "run_definition",
    "synthetic_signature",
    "text_content",
]
