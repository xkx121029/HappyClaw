"""Dashboard/peer turn preparation — domain half of a chat turn.

This module owns the decision making that used to live in
``octop.api.routers.chat.turn``: validating the per-turn MCP/skill selection,
resolving (or creating) the conversation thread, and projecting the turn into a
gateway :class:`InboundMessage`. Keeping it in ``infra`` lets non-HTTP callers
(Bao follow-ups, bridge peers, cron) build a dashboard-shaped turn without
importing the API package.

HTTP-specific shape (Pydantic request models, WebSocket frames) stays in
``octop.api.routers.chat``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from octop_gateway.models import (
    ChannelSubject,
    ContentPart,
    FileContent,
    ImageContent,
    InboundMessage,
    TextContent,
)

from octop.infra.errors import ErrorCode, OctopError
from octop.infra.gateway.media.attachment_hints import (
    inbound_attachments_from_parts,
    is_vision_attachment,
)
from octop.infra.gateway.media.inbound_store import inbound_rel_path
from octop.infra.gateway.process.message_keys import (
    COMPOSER_CTX_KEY,
    INBOUND_ATTACHMENTS_KEY,
    build_composer_context,
)
from octop.infra.gateway.threads import ThreadRegistry, thread_visible_to
from octop.infra.gateway.ws import WS_CHANNEL_ID
from octop.infra.projects.session import QUICK_KIND

__all__ = [
    "DashboardTurn",
    "DashboardTurnLike",
    "PreparedDashboardTurn",
    "build_dashboard_inbound",
    "client_message_id_from_turn",
    "content_parts_from_dashboard_turn",
    "merge_turn_target_agents",
    "prepare_dashboard_turn",
    "resolve_thread_id",
    "turn_has_content",
]


class DashboardTurnLike(Protocol):
    """Fields of a dashboard turn this module reads.

    Structural typing keeps ``infra`` free of the Pydantic model that the
    HTTP layer validates; any object with these attributes works.
    """

    messages: list[dict[str, Any]]
    thread_id: str | None
    session_key: str | None
    mcp_servers: list[str] | None
    knowledge_base_ids: list[str] | None
    skills: list[str] | None
    default_model: str | None
    reasoning_mode: str | None
    reasoning_effort: str | None
    conversation_mode: str | None
    hitl_policy: Any | None
    target_agent_ids: list[str] | None
    text: str | None


@dataclass
class DashboardTurn:
    """Programmatic dashboard turn for non-HTTP callers (cron, Bao, bridge).

    The HTTP layer validates and fills :class:`ChatTurnBody` instead; both
    satisfy :class:`DashboardTurnLike`.
    """

    messages: list[dict[str, Any]] = field(default_factory=list)
    thread_id: str | None = None
    session_key: str | None = None
    mcp_servers: list[str] | None = None
    knowledge_base_ids: list[str] | None = None
    skills: list[str] | None = None
    default_model: str | None = None
    reasoning_mode: str | None = None
    reasoning_effort: str | None = None
    conversation_mode: str | None = None
    hitl_policy: Any | None = None
    target_agent_ids: list[str] | None = None
    text: str | None = None


@dataclass
class PreparedDashboardTurn:
    thread_id: str
    session_key: str
    mcp_servers: list[str] | None
    skills: list[str] | None
    model_ref: str | None
    inbound_content: list[ContentPart]
    composer_context: dict[str, Any] | None
    inbound_attachments: list[dict[str, str]]


async def resolve_thread_id(
    *,
    agent_id: str,
    user_id: int,
    thread_registry: Any,
    thread_id: str | None,
    session_key: str | None,
) -> tuple[str, str]:
    sk = session_key or ThreadRegistry.dashboard_key(agent_id=agent_id, user_id=user_id)
    if thread_id:
        row = thread_registry.get_thread(thread_id)
        if row is None or row.agent_id != agent_id:
            raise OctopError(ErrorCode.AGENT_NOT_FOUND, f"thread {thread_id!r} not found")
        if not thread_visible_to(row, user_id):
            raise OctopError(ErrorCode.FORBIDDEN, "thread not owned by user")
        # Quick chats keep their own session key: replying must never move the
        # user's normal dashboard conversation onto the quick thread.
        if (getattr(row, "workspace_kind", None) or "") == QUICK_KIND:
            return thread_id, row.session_key
        await thread_registry.rebind(
            session_key=sk,
            thread_id=thread_id,
            agent_id=agent_id,
            acting_user_id=user_id,
        )
        return thread_id, sk
    bound = thread_registry.get_bound_thread_id(sk)
    if bound:
        return bound, sk
    tid = await thread_registry.get_or_create_by_key(
        session_key=sk,
        agent_id=agent_id,
        user_id=user_id,
        channel_type=ThreadRegistry.CHANNEL_DASHBOARD,
    )
    return tid, sk


# Optimistic dashboard bubble ids (`Date.now()` plus a short base36 suffix).
_CLIENT_MESSAGE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def client_message_id_from_turn(turn: DashboardTurnLike) -> str | None:
    """Id of the user bubble this turn should be stored as.

    The dashboard sends the id it already drew. Anything else is ignored so a
    channel turn keeps a server-assigned id.
    """
    for message in reversed(turn.messages):
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "user").lower() != "user":
            continue
        raw = message.get("id")
        if isinstance(raw, str) and _CLIENT_MESSAGE_ID_RE.fullmatch(raw.strip()):
            return raw.strip()
        return None
    return None


def _turn_plain_text(turn: DashboardTurnLike) -> str:
    text = (turn.text or "").strip()
    if text:
        return text
    if not turn.messages:
        return ""
    last = turn.messages[-1]
    if not isinstance(last, dict) or str(last.get("role") or "").lower() != "user":
        return ""
    content = last.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and str(block.get("type") or "") == "text":
                t = str(block.get("text") or "").strip()
                if t:
                    return t
    return ""


def _message_content_nonempty(content: Any) -> bool:
    if isinstance(content, str):
        return bool(content.strip())
    if not isinstance(content, list):
        return False
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = str(block.get("type") or "")
        if btype == "text" and str(block.get("text") or "").strip():
            return True
        if btype in ("image", "file", "image_url"):
            return True
    return False


def turn_has_content(turn: DashboardTurnLike) -> bool:
    """True when the turn has user text or structured message blocks."""
    if _turn_plain_text(turn):
        return True
    for msg in reversed(turn.messages):
        if str(msg.get("role") or "").lower() != "user":
            continue
        return _message_content_nonempty(msg.get("content"))
    return False


def _mime_from_block(block: dict[str, Any]) -> str:
    source_raw = block.get("source")
    source: dict[str, Any] = source_raw if isinstance(source_raw, dict) else {}
    for key in ("media_type", "mime_type"):
        raw = source.get(key) if key in source else block.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip().split(";", 1)[0].lower()
    return "application/octet-stream"


def _workspace_path_from_block(block: dict[str, Any]) -> str | None:
    for key in ("workspace_path", "workspacePath"):
        raw = block.get(key)
        if isinstance(raw, str) and raw.strip():
            return inbound_rel_path(raw.strip())
    return None


def content_parts_from_dashboard_turn(turn: DashboardTurnLike) -> list[ContentPart]:
    """Convert dashboard WS ``messages`` / ``text`` into gateway ContentParts.

    Attachments must already live under workspace ``inbound/`` (via upload).
    Preview URLs are ignored — only ``workspace_path`` matters.
    """
    parts: list[ContentPart] = []
    text = _turn_plain_text(turn)
    if text:
        parts.append(TextContent(text=text))

    user_content: Any = None
    for msg in reversed(turn.messages):
        if not isinstance(msg, dict):
            continue
        if str(msg.get("role") or "").lower() != "user":
            continue
        user_content = msg.get("content")
        break

    if not isinstance(user_content, list):
        return parts

    seen_text = bool(text)
    for block in user_content:
        if not isinstance(block, dict):
            continue
        btype = str(block.get("type") or "")
        if btype == "text":
            t = str(block.get("text") or "").strip()
            if t and not seen_text:
                parts.append(TextContent(text=t))
                seen_text = True
            continue

        if btype not in ("image", "file", "image_url"):
            continue

        path = _workspace_path_from_block(block)
        if not path:
            # Upload always returns workspace_path; ignore preview-only blocks.
            continue

        media_type = _mime_from_block(block)
        filename = str(
            block.get("filename") or block.get("name") or Path(path).name or "attachment"
        )
        use_vision = is_vision_attachment(
            kind="image" if btype in ("image", "image_url") else btype,
            media_type=media_type,
            path=path,
        )
        if use_vision:
            parts.append(
                ImageContent(
                    local_path=path,
                    mime_type=media_type if media_type.startswith("image/") else "image/png",
                    alt_text=filename,
                )
            )
        else:
            parts.append(
                FileContent(
                    local_path=path,
                    filename=filename,
                    mime_type=media_type or "application/octet-stream",
                )
            )
    return parts


async def prepare_dashboard_turn(
    server: Any,
    *,
    agent_id: str,
    user: Any,
    turn: DashboardTurnLike,
) -> PreparedDashboardTurn:
    """Validate MCP/skills, resolve thread, return data for gateway enqueue."""
    from octop.infra.agents.access import require_agent_row  # noqa: PLC0415
    from octop.infra.gateway.process.turn_selection import (  # noqa: PLC0415
        validate_chat_mcp_servers,
        validate_chat_skills,
    )

    row = require_agent_row(agent_id, user=user, as_user=None, server=server)
    # Refuse before the gateway dispatches: an agent that never started (no
    # model configured) would otherwise blow up inside octop_harness with a raw
    # ``KeyError: '<agent_id>'``. This raises AGENT_NO_MODEL / AGENT_NOT_RUNNING
    # (409) so channels can surface actionable copy instead of a model failure.
    server.app_runtime.agent_registry.ensure_dispatchable(agent_id)
    default_model = (row.default_model or "").strip() or None

    mcp_servers = await validate_chat_mcp_servers(server, user_id=user.id, names=turn.mcp_servers)
    skills = await validate_chat_skills(
        server,
        agent_id=agent_id,
        user=user,
        names=turn.skills,
    )
    if mcp_servers:
        failed = await server.app_runtime.agent_registry.prepare_chat_mcp(
            agent_id,
            mcp_servers,
            connector_user_id=user.id,
        )
        if failed:
            locale = getattr(user, "locale", None) or "zh"
            raise OctopError.localized(
                ErrorCode.CONNECTOR_MCP_LOAD_FAILED,
                locale,
                servers=", ".join(failed),
            )

    thread_registry = server.app_runtime.gateway.thread_registry
    thread_id, session_key = await resolve_thread_id(
        agent_id=agent_id,
        user_id=user.id,
        thread_registry=thread_registry,
        thread_id=turn.thread_id,
        session_key=turn.session_key,
    )
    model_ref = (turn.default_model or "").strip() or None
    if (
        model_ref is not None
        and not server.app_runtime.agent_registry.providers.is_model_ref_usable(model_ref)
    ):
        raise OctopError(
            ErrorCode.SLASH_BAD_ARGS,
            "default_model must reference an enabled model",
        )
    if model_ref is not None and not server.app_runtime.agent_registry.model_ref_allowed_for_user(
        user.id,
        model_ref,
    ):
        raise OctopError(ErrorCode.RESOURCE_NOT_ALLOWED, "resource is not visible to this user")
    composer_updates: dict[str, Any] = {}
    if model_ref is not None:
        composer_updates["model_ref"] = model_ref
    if turn.reasoning_mode is not None:
        composer_updates["reasoning_mode"] = turn.reasoning_mode
    if turn.reasoning_effort is not None:
        composer_updates["reasoning_effort"] = turn.reasoning_effort.strip().lower() or None
    if composer_updates:
        thread_registry.update_composer(thread_id, **composer_updates)
    target_ids = [str(x) for x in turn.target_agent_ids] if turn.target_agent_ids else None
    composer_ctx = build_composer_context(
        mcp_servers=mcp_servers,
        skills=skills,
        target_agent_ids=target_ids,
        model_ref=model_ref,
        default_model=default_model,
    )
    inbound_content = content_parts_from_dashboard_turn(turn)
    inbound_attachments = inbound_attachments_from_parts(inbound_content)
    return PreparedDashboardTurn(
        thread_id=thread_id,
        session_key=session_key,
        mcp_servers=mcp_servers,
        skills=skills,
        model_ref=model_ref,
        inbound_content=inbound_content,
        composer_context=composer_ctx,
        inbound_attachments=inbound_attachments,
    )


def build_dashboard_inbound(
    *,
    agent_id: str,
    user_id: int,
    prepared: PreparedDashboardTurn,
    turn: DashboardTurnLike,
    ws_connection_id: str,
    user_is_admin: bool = False,
) -> InboundMessage:
    metadata: dict[str, Any] = {
        "ws_connection_id": ws_connection_id,
        "session_key": prepared.session_key,
        "thread_id": prepared.thread_id,
        "user_is_admin": user_is_admin,
    }
    if prepared.mcp_servers is not None:
        # Including [] — Dashboard opt-out of default_open for this turn.
        metadata["mcp_servers"] = list(prepared.mcp_servers)
    if turn.knowledge_base_ids is not None:
        # Including [] — Dashboard opt-out of default_open knowledge bases for this turn.
        metadata["knowledge_base_ids"] = list(turn.knowledge_base_ids)
    if prepared.skills is not None:
        metadata["skills"] = prepared.skills
    if prepared.model_ref:
        metadata["model"] = prepared.model_ref
    if turn.reasoning_mode is not None:
        metadata["reasoning_mode"] = turn.reasoning_mode
    if turn.reasoning_effort:
        metadata["reasoning_effort"] = turn.reasoning_effort
    if turn.conversation_mode:
        metadata["conversation_mode"] = turn.conversation_mode
    if turn.hitl_policy is not None:
        metadata["hitl_policy"] = turn.hitl_policy.model_dump()
    if prepared.composer_context:
        metadata[COMPOSER_CTX_KEY] = prepared.composer_context
    if prepared.inbound_attachments:
        metadata[INBOUND_ATTACHMENTS_KEY] = prepared.inbound_attachments
    client_message_id = client_message_id_from_turn(turn)
    if client_message_id:
        metadata["client_message_id"] = client_message_id
    merge_turn_target_agents(turn, metadata)

    return InboundMessage(
        channel_id=WS_CHANNEL_ID,
        channel_type=ThreadRegistry.CHANNEL_DASHBOARD,
        tenant_id=agent_id,
        channel_subject=ChannelSubject(subject_id=str(user_id)),
        channel_session_id=prepared.session_key,
        content=list(prepared.inbound_content),
        metadata=metadata,
    )


def merge_turn_target_agents(turn: DashboardTurnLike, metadata: dict[str, Any]) -> None:
    if turn.target_agent_ids:
        metadata["target_agent_ids"] = [str(x) for x in turn.target_agent_ids]
