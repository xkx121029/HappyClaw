"""Message-level helpers shared by the GlobalProcessor modules."""

from __future__ import annotations

import time
from typing import Any

from happyclaw_gateway.models import InboundMessage
from langchain_core.messages import HumanMessage

from happyclaw.i18n.domains.stream import format_stream_error
from happyclaw.infra.errors import HappyclawError


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def _inbound_thread_id(msg: InboundMessage) -> str | None:
    """Dashboard turns stamp ``metadata.thread_id``; IM often omits it."""
    raw = (msg.metadata or {}).get("thread_id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _stream_error(exc: Exception, locale: str) -> tuple[str, str | None]:
    if isinstance(exc, HappyclawError):
        return exc.localized_message(locale), exc.code.value
    return format_stream_error(exc, locale), None


def _overwrite_last_user_text(request: dict[str, Any], text: str) -> None:
    """Replace the latest user-turn body without rebuilding the harness request."""
    messages = request.get("messages")
    if not isinstance(messages, list) or not messages:
        return
    last = messages[-1]
    if isinstance(last, dict):
        last["content"] = text
        return
    extra = getattr(last, "additional_kwargs", None)
    kwargs = dict(extra) if isinstance(extra, dict) else {}
    kept_id = getattr(last, "id", None)
    messages[-1] = HumanMessage(
        content=text,
        additional_kwargs=kwargs,
        **({"id": kept_id} if isinstance(kept_id, str) and kept_id else {}),
    )
