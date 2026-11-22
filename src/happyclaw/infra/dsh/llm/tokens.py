"""CJK-aware token estimation and provider-usage reconciliation.

DSH prices text at four characters per token. That is a reasonable density for
English prose and a poor one for Chinese, where roughly one character is one
token. This module keeps the DSH constant for non-CJK text and counts CJK
characters individually, then compares the estimate with the provider's own
usage so a badly wrong estimate is visible instead of silent.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

from happyclaw.infra.dsh.llm.types import (
    ContentBlock,
    LlmRequest,
    Message,
    ReasoningBlock,
    TextBlock,
    TokenUsage,
    ToolCallBlock,
    ToolResultBlock,
    UsageDrift,
)

__all__ = [
    "BLOCK_OVERHEAD",
    "CHARS_PER_TOKEN",
    "CJK_TOKENS_PER_CHAR",
    "ROLE_OVERHEAD",
    "TokenAuditPolicy",
    "TokenEstimate",
    "audit_input_usage",
    "estimate_blocks",
    "estimate_message",
    "estimate_request",
    "estimate_text",
]

CHARS_PER_TOKEN = 4
CJK_TOKENS_PER_CHAR = 1.0
ROLE_OVERHEAD = 4
BLOCK_OVERHEAD = 4

# CJK ideographs, kana, hangul, and CJK punctuation/fullwidth forms. Each of
# these characters is roughly one token for Chinese-family tokenizers, so the
# four-characters-per-token rule must not be applied to them.
_CJK_RANGES: tuple[tuple[int, int], ...] = (
    (0x2E80, 0x2EFF),
    (0x3000, 0x303F),
    (0x3040, 0x30FF),
    (0x31C0, 0x31EF),
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xAC00, 0xD7AF),
    (0xF900, 0xFAFF),
    (0xFF00, 0xFFEF),
)


def _is_cjk(char: str) -> bool:
    codepoint = ord(char)
    return any(low <= codepoint <= high for low, high in _CJK_RANGES)


@dataclass(frozen=True, slots=True)
class TokenEstimate:
    tokens: int
    cjk_chars: int = 0
    other_chars: int = 0


def estimate_text(text: str) -> TokenEstimate:
    """Estimate tokens for mixed Chinese/English text.

    CJK characters cost one token each; other non-whitespace characters keep
    the DSH four-characters-per-token density. Empty text costs nothing.
    """
    cjk = 0
    other = 0
    for char in text or "":
        if char.isspace():
            continue
        if _is_cjk(char):
            cjk += 1
        else:
            other += 1
    return TokenEstimate(
        tokens=cjk + math.ceil(other / CHARS_PER_TOKEN),
        cjk_chars=cjk,
        other_chars=other,
    )


def _estimate_block(block: ContentBlock) -> int:
    if isinstance(block, (TextBlock, ReasoningBlock)):
        return estimate_text(block.text).tokens + BLOCK_OVERHEAD
    if isinstance(block, ToolCallBlock):
        return (
            estimate_text(block.name).tokens
            + estimate_text(block.arguments).tokens
            + BLOCK_OVERHEAD
        )
    if isinstance(block, ToolResultBlock):
        return estimate_text(block.content).tokens + BLOCK_OVERHEAD
    return BLOCK_OVERHEAD


def estimate_blocks(blocks: tuple[ContentBlock, ...]) -> int:
    return sum(_estimate_block(block) for block in blocks)


def estimate_message(message: Message) -> int:
    return estimate_blocks(message.content) + ROLE_OVERHEAD


def estimate_request(request: LlmRequest) -> int:
    """Estimate the input side of one request: system, messages, and tools."""
    tokens = 0
    if request.system:
        tokens += estimate_text(request.system).tokens + ROLE_OVERHEAD
    tokens += sum(estimate_message(message) for message in request.messages)
    if request.tools:
        schemas = [
            {"name": tool.name, "description": tool.description, "parameters": tool.parameters}
            for tool in request.tools
        ]
        serialized = json.dumps(schemas, ensure_ascii=False, separators=(",", ":"))
        tokens += estimate_text(serialized).tokens + BLOCK_OVERHEAD
    return tokens


@dataclass(frozen=True, slots=True)
class TokenAuditPolicy:
    """Thresholds for reporting an estimate/provider divergence."""

    ratio_threshold: float = 0.25
    min_provider_tokens: int = 256

    def __post_init__(self) -> None:
        if not 0.0 < self.ratio_threshold < 1.0:
            raise ValueError("ratio_threshold must be between 0 and 1")
        if self.min_provider_tokens < 0:
            raise ValueError("min_provider_tokens must not be negative")


def audit_input_usage(
    estimated_input_tokens: int,
    usage: TokenUsage,
    policy: TokenAuditPolicy | None = None,
) -> UsageDrift | None:
    """Return a drift notice when the estimate is far from provider usage.

    Small responses are exempt: a handful of tokens has no statistical value
    and would make the notice noisy. A lowercase-only comparison keeps the
    direction visible through the ratio sign convention (always positive).
    """
    active = policy or TokenAuditPolicy()
    actual = usage.billed_input_tokens
    if actual < active.min_provider_tokens:
        return None
    ratio = abs(estimated_input_tokens - actual) / actual
    if ratio < active.ratio_threshold:
        return None
    return UsageDrift(
        estimated_input_tokens=estimated_input_tokens,
        provider_input_tokens=actual,
        ratio=ratio,
        threshold=active.ratio_threshold,
    )
