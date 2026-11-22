"""Provider-neutral LLM seam for the DSH integration.

Public surface:

* request/message/stream vocabulary: :mod:`happyclaw.infra.dsh.llm.types`
* routable failure codes: :mod:`happyclaw.infra.dsh.llm.errors`
* retry policy and step guard: :mod:`happyclaw.infra.dsh.llm.retry`
* CJK-aware token estimation: :mod:`happyclaw.infra.dsh.llm.tokens`
* adapters: :mod:`happyclaw.infra.dsh.llm.openai_compat`,
  :mod:`happyclaw.infra.dsh.llm.anthropic`
* orchestration: :mod:`happyclaw.infra.dsh.llm.runtime`
"""

from happyclaw.infra.dsh.llm.adapter import ChunkStream, ProviderAdapter, RawChunkStream, Transport, adapter_for
from happyclaw.infra.dsh.llm.anthropic import AnthropicAdapter
from happyclaw.infra.dsh.llm.assembly import AssistantTurnBuilder
from happyclaw.infra.dsh.llm.compression import SessionCompressionHook, messages_from_surface
from happyclaw.infra.dsh.llm.errors import FailureCode, ProviderFailure, TransportError
from happyclaw.infra.dsh.llm.factory import (
    DshModelFactory,
    InstallOutcome,
    InstallResult,
    LlmInstallStatus,
    describe_installation,
    install_dsh_model_factory,
)
from happyclaw.infra.dsh.llm.http_transport import (
    HttpStreamTransport,
    build_http_transport,
    is_loopback_url,
)
from happyclaw.infra.dsh.llm.langchain_model import (
    DshChatModel,
    build_dsh_chat_model,
    harness_version_warning,
    installed_harness_version,
)
from happyclaw.infra.dsh.llm.openai_compat import OpenAICompatibleAdapter
from happyclaw.infra.dsh.llm.retry import (
    FailureAction,
    RetryPolicy,
    StepCommittedError,
    StepTracker,
)
from happyclaw.infra.dsh.llm.runtime import CancellationToken, CompressionHook, LlmRuntime
from happyclaw.infra.dsh.llm.tokens import (
    TokenAuditPolicy,
    TokenEstimate,
    audit_input_usage,
    estimate_blocks,
    estimate_message,
    estimate_request,
    estimate_text,
)
from happyclaw.infra.dsh.llm.types import (
    AssistantTurn,
    FinishChunk,
    FinishReason,
    LlmRequest,
    Message,
    ReasoningBlock,
    ReasoningDelta,
    Role,
    StepRestart,
    StreamChunk,
    TextBlock,
    TextDelta,
    TokenUsage,
    ToolCallBlock,
    ToolCallDelta,
    ToolResultBlock,
    ToolSchema,
    UsageChunk,
    UsageDrift,
    text_message,
)

__all__ = [
    "AnthropicAdapter",
    "AssistantTurn",
    "AssistantTurnBuilder",
    "CancellationToken",
    "ChunkStream",
    "CompressionHook",
    "DshChatModel",
    "DshModelFactory",
    "FailureAction",
    "FailureCode",
    "FinishChunk",
    "FinishReason",
    "HttpStreamTransport",
    "InstallOutcome",
    "InstallResult",
    "LlmInstallStatus",
    "LlmRequest",
    "LlmRuntime",
    "Message",
    "OpenAICompatibleAdapter",
    "ProviderAdapter",
    "ProviderFailure",
    "RawChunkStream",
    "ReasoningBlock",
    "ReasoningDelta",
    "RetryPolicy",
    "Role",
    "SessionCompressionHook",
    "StepCommittedError",
    "StepRestart",
    "StepTracker",
    "StreamChunk",
    "TextBlock",
    "TextDelta",
    "TokenAuditPolicy",
    "TokenEstimate",
    "TokenUsage",
    "ToolCallBlock",
    "ToolCallDelta",
    "ToolResultBlock",
    "ToolSchema",
    "Transport",
    "TransportError",
    "UsageChunk",
    "UsageDrift",
    "adapter_for",
    "audit_input_usage",
    "build_dsh_chat_model",
    "build_http_transport",
    "describe_installation",
    "estimate_blocks",
    "estimate_message",
    "estimate_request",
    "estimate_text",
    "harness_version_warning",
    "install_dsh_model_factory",
    "installed_harness_version",
    "is_loopback_url",
    "messages_from_surface",
    "text_message",
]
