"""Small value types shared by the bridge contract and its errors."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol


class AbortSignal(Protocol):
    """Structural stand-in for ``asyncio.Event`` and DSH abort signals."""

    def is_set(self) -> bool: ...


ContentBlock = dict[str, Any]
ContentBlocks = list[ContentBlock]


def text_content(text: str) -> ContentBlocks:
    return [{"type": "text", "text": text}]


def normalize_content(value: object) -> ContentBlocks:
    """Coerce a render result into DSH content blocks.

    ``str`` becomes one text block; a sequence of blocks is validated shallowly.
    Anything else is a contract violation.
    """
    if isinstance(value, str):
        return text_content(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        blocks: ContentBlocks = []
        for item in value:
            if not isinstance(item, Mapping):
                raise ValueError("content block must be a mapping")
            block = dict(item)
            if not isinstance(block.get("type"), str):
                raise ValueError("content block requires a string 'type'")
            blocks.append(block)
        return blocks
    raise ValueError(f"unsupported content value: {type(value).__name__}")


__all__ = [
    "AbortSignal",
    "ContentBlock",
    "ContentBlocks",
    "normalize_content",
    "text_content",
]
