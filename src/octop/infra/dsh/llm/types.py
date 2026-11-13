"""Provider-neutral vocabulary for the DSH LLM seam.

Adapters translate provider wire messages into these types and nothing above
this package reads a provider-specific field. The vocabulary intentionally
mirrors the parts of DSH's ``llm`` package that the Octop loop needs, without
importing the TypeScript runtime.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, TypeAlias

if TYPE_CHECKING:
    from octop.infra.dsh.llm.errors import ProviderFailure

__all__ = [
    "AssistantTurn",
    "BlockEnd",
    "BlockKind",
    "BlockStart",
    "ContentBlock",
    "FinishChunk",
    "FinishReason",
    "LlmRequest",
    "Message",
    "ReasoningBlock",
    "ReasoningDelta",
    "Role",
    "RuntimeEvent",
    "StepRestart",
    "StreamChunk",
    "TextBlock",
    "TextDelta",
    "TokenUsage",
    "ToolCallBlock",
    "ToolCallDelta",
    "ToolResultBlock",
    "ToolSchema",
    "UsageChunk",
    "UsageDrift",
    "text_message",
]


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class BlockKind(StrEnum):
    TEXT = "text"
    REASONING = "reasoning"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"


class FinishReason(StrEnum):
    STOP = "stop"
    TOOL_CALLS = "tool_calls"
    MAX_TOKENS = "max_tokens"
    ABORTED = "aborted"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class TextBlock:
    text: str


@dataclass(frozen=True, slots=True)
class ReasoningBlock:
    text: str


@dataclass(frozen=True, slots=True)
class ToolCallBlock:
    """A tool invocation requested by the model.

    ``arguments`` stays the raw JSON string produced by the model so partial
    stream assembly never needs to re-serialize it.
    """

    id: str
    name: str
    arguments: str = ""

    def parsed_arguments(self) -> dict[str, Any]:
        parsed = json.loads(self.arguments or "{}")
        if not isinstance(parsed, dict):
            raise ValueError("tool call arguments must be a JSON object")
        return parsed


@dataclass(frozen=True, slots=True)
class ToolResultBlock:
    tool_call_id: str
    content: str
    is_error: bool = False


ContentBlock: TypeAlias = TextBlock | ReasoningBlock | ToolCallBlock | ToolResultBlock


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: tuple[ContentBlock, ...]


def text_message(role: Role, text: str) -> Message:
    """Build a single-text-block message; convenience for callers and tests."""
    return Message(role=role, content=(TextBlock(text),))


@dataclass(frozen=True, slots=True)
class ToolSchema:
    name: str
    description: str = ""
    parameters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LlmRequest:
    """One fully assembled model request.

    ``provider`` is the route key (the adapter instance already knows its
    vendor); ``metadata`` carries adapter-private options without widening this
    type for every vendor extension.
    """

    provider: str
    model: str
    messages: tuple[Message, ...]
    system: str | None = None
    tools: tuple[ToolSchema, ...] = ()
    temperature: float | None = None
    max_tokens: int | None = None
    stop: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Disjoint token counts reported by a provider.

    ``input_tokens`` excludes cache reads/writes, matching DSH: billed input is
    the sum of the three input fields.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int | None = None
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    # Detail keys the provider actually reported (even when the value is 0).
    # Downstream adapters must reproduce presence, not invent defaults.
    reported_details: frozenset[str] = frozenset()

    @property
    def billed_input_tokens(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens

    def resolved_total(self) -> int:
        if self.total_tokens is not None:
            return self.total_tokens
        return self.output_tokens + self.billed_input_tokens


@dataclass(frozen=True, slots=True)
class BlockStart:
    index: int
    block_kind: BlockKind


@dataclass(frozen=True, slots=True)
class TextDelta:
    index: int
    text: str


@dataclass(frozen=True, slots=True)
class ReasoningDelta:
    index: int
    text: str


@dataclass(frozen=True, slots=True)
class ToolCallDelta:
    index: int
    tool_call_id: str
    arguments_delta: str
    name: str | None = None
    # Wire-faithful echoes for adapters that must reproduce provider chunks:
    # ``wire_id`` is only set when the provider actually sent an id in this
    # delta, ``slot`` is the provider's tool index (``None`` when unspecified).
    wire_id: str | None = None
    slot: int | None = None


@dataclass(frozen=True, slots=True)
class BlockEnd:
    index: int
    block: ContentBlock


@dataclass(frozen=True, slots=True)
class UsageChunk:
    usage: TokenUsage


@dataclass(frozen=True, slots=True)
class FinishChunk:
    reason: FinishReason
    incomplete: bool = False
    failure: ProviderFailure | None = None


StreamChunk: TypeAlias = (
    BlockStart | TextDelta | ReasoningDelta | ToolCallDelta | BlockEnd | UsageChunk | FinishChunk
)


@dataclass(frozen=True, slots=True)
class StepRestart:
    """The runtime discarded a partial attempt and restarted the same step.

    Every event yielded before this notice belongs to an attempt that is now
    abandoned; consumers assembling output must reset. ``discarded_partial``
    is true when model output had already been streamed.
    """

    attempt: int
    reason: str
    failure: ProviderFailure
    discarded_partial: bool


@dataclass(frozen=True, slots=True)
class UsageDrift:
    """Estimated input tokens diverged from the provider-reported count."""

    estimated_input_tokens: int
    provider_input_tokens: int
    ratio: float
    threshold: float


@dataclass(frozen=True, slots=True)
class AssistantTurn:
    """Consumer view of one settled assistant step (after any retries)."""

    content: tuple[ContentBlock, ...] = ()
    usage: TokenUsage | None = None
    finish_reason: FinishReason | None = None
    incomplete: bool = False
    failure: ProviderFailure | None = None

    @property
    def tool_calls(self) -> tuple[ToolCallBlock, ...]:
        return tuple(block for block in self.content if isinstance(block, ToolCallBlock))


RuntimeEvent: TypeAlias = StreamChunk | StepRestart | UsageDrift
