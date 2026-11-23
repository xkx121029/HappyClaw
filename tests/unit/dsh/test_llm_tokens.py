"""Token estimation: CJK weighting, request accounting, drift thresholds."""

from __future__ import annotations

from happyclaw.infra.dsh.llm import (
    LlmRequest,
    Role,
    TokenAuditPolicy,
    TokenEstimate,
    TokenUsage,
    ToolSchema,
    audit_input_usage,
    estimate_blocks,
    estimate_message,
    estimate_request,
    estimate_text,
    text_message,
)


def test_chinese_counts_one_token_per_character() -> None:
    estimate = estimate_text("你好世界")
    assert estimate == TokenEstimate(tokens=4, cjk_chars=4, other_chars=0)


def test_english_keeps_dsh_four_chars_per_token() -> None:
    assert estimate_text("abcdefgh").tokens == 2
    assert estimate_text("abcdefghi").tokens == 3


def test_mixed_text_sums_cjk_chars_and_folded_ascii() -> None:
    # 2 CJK chars + 10 non-space ASCII chars -> 2 + ceil(10 / 4)
    assert estimate_text("你好 hello world").tokens == 5


def test_cjk_punctuation_is_weighted_as_cjk() -> None:
    assert estimate_text("你好，世界").tokens == 5


def test_message_and_block_overhead_are_included() -> None:
    message = text_message(Role.USER, "abcd")
    assert estimate_blocks(message.content) == 1 + 4
    assert estimate_message(message) == 9


def test_request_estimate_includes_system_and_tools() -> None:
    base = LlmRequest(
        provider="fake",
        model="m",
        messages=(text_message(Role.USER, "abcd"),),
    )
    with_system = LlmRequest(
        provider="fake",
        model="m",
        system="abcd",
        messages=(text_message(Role.USER, "abcd"),),
    )
    with_tools = LlmRequest(
        provider="fake",
        model="m",
        messages=(text_message(Role.USER, "abcd"),),
        tools=(ToolSchema("read_file", "Read a file", {"type": "object"}),),
    )
    assert estimate_request(with_system) == estimate_request(base) + 5
    assert estimate_request(with_tools) > estimate_request(base)


def test_drift_reported_only_above_threshold_and_minimum() -> None:
    policy = TokenAuditPolicy(ratio_threshold=0.25, min_provider_tokens=256)

    large_drift = audit_input_usage(100, TokenUsage(input_tokens=400), policy)
    assert large_drift is not None
    assert large_drift.ratio == 0.75

    assert audit_input_usage(390, TokenUsage(input_tokens=400), policy) is None
    # Below the minimum the sample is too small to be meaningful.
    assert audit_input_usage(1, TokenUsage(input_tokens=100), policy) is None


def test_cache_tokens_count_toward_billed_input() -> None:
    usage = TokenUsage(input_tokens=100, cache_read_tokens=300)
    assert usage.billed_input_tokens == 400
    assert audit_input_usage(100, usage) is not None
