"""Prompt bridge for DSH bundles that contribute system-prompt context.

Called from the agent prompt assembly only when the adapter is on. Every
failure is swallowed: a broken memory plugin must not break a chat turn.
"""

from __future__ import annotations

import logging

from octop.infra.dsh.compat.registry import get_registry
from octop.infra.dsh.compat.switch import compat_enabled

logger = logging.getLogger(__name__)


def compat_prompt_block() -> str:
    """Rendered prompt sections from mounted bundles, or an empty string."""

    if not compat_enabled():
        return ""
    try:
        sections = get_registry().prompt_sections()
    except Exception:  # pragma: no cover - defensive
        logger.debug("DSH compat prompt bridge failed", exc_info=True)
        return ""
    texts = [text.strip() for text in sections if text and text.strip()]
    return "\n\n".join(texts)


__all__ = ["compat_prompt_block"]
