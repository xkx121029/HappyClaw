"""Dashboard chat helpers: polish prompt and HITL resume (SSE)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from octop.api.common.agent import assert_agent_access
from octop.api.deps import current_user, get_server
from octop.api.routers.chat.models import HitlResumeBody, PolishBody
from octop.api.routers.chat.responses import (
    ChatPolishOut,
    ChatWelcomeOut,
    HitlPendingListOut,
)
from octop.api.routers.chat.sse import format_sse
from octop.i18n.domains.stream import format_stream_error
from octop.infra.agents.experts.catalog import (
    default_welcome_payload,
    display_task_examples_for_agent,
    parse_task_examples,
    read_workspace_manifest_data,
    welcome_payload_from_manifest_data,
    welcome_payload_has_content,
)
from octop.infra.agents.settings.profile import welcome_from_row
from octop.infra.agents.teams import is_team_agent
from octop.infra.agents.teams.welcome import team_host_welcome_payload
from octop.infra.gateway.hitl.coordinator import (
    HitlChannelCoordinator,
    HitlStreamContext,
    decision_rejection_reason,
)
from octop.infra.gateway.hitl.format import (
    extract_questions,
    is_ask_action_requests,
    normalize_hitl_request,
)
from octop.infra.gateway.hitl.store import HitlPendingRecord
from octop.infra.text_assist import require_host_models, run_text_assist
from octop.infra.utils.locale import resolve_request_locale

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get(
    "/agents/{agent_id}/chat/welcome",
    summary="Chat welcome quick cards",
    response_model=ChatWelcomeOut,
)
async def get_chat_welcome(
    agent_id: str,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Welcome copy for the empty chat screen.

    Resolution order:
    1. Agent row ``welcome_message`` (instance-owned; set at create/edit).
    2. Agent workspace ``.octop/manifest.json`` (seeded at create; quick cards + fallback copy).
    3. Default quick cards (``general-assistant`` or a small built-in set).

    Team hosts keep the team intro and show members' own quick cards — the host
    is not turned into cards.
    """
    assert_agent_access(server, agent_id, user)
    assert server.app_runtime is not None
    registry = server.app_runtime.agent_registry
    catalog = server.expert_catalog_lazy
    row = registry.get_row(agent_id)
    if is_team_agent(row):
        team_payload = await team_host_welcome_payload(row, registry, catalog)
        return {**team_payload, "task_examples": None}

    workspace = registry.workspace_for_agent(agent_id)
    payload: dict[str, Any] | None = None
    parsed_examples = None
    if workspace is not None:
        manifest = await read_workspace_manifest_data(workspace)
        if manifest is not None:
            welcome = welcome_payload_from_manifest_data(manifest)
            if welcome_payload_has_content(welcome):
                payload = welcome
            parsed_examples = parse_task_examples(manifest)

    if payload is None:
        payload = default_welcome_payload(catalog)

    db_welcome = welcome_from_row(row) if row is not None else None
    if db_welcome is not None:
        payload = {**payload, "welcome_message": {"zh": db_welcome, "en": db_welcome}}
    task_examples = display_task_examples_for_agent(
        parsed=parsed_examples,
        catalog=catalog,
        row=row,
    )
    return {**payload, "task_examples": task_examples}


async def iter_dashboard_hitl_resume_sse(
    *,
    server: Any,
    processor: Any,
    hitl_coordinator: HitlChannelCoordinator,
    agent_id: str,
    thread_id: str,
    user_id: int,
    decisions: list[dict[str, Any]],
    pending: HitlPendingRecord | None,
    session_key: str,
    channel_type: str,
    locale: str,
    is_disconnected: Callable[[], Awaitable[bool]],
) -> AsyncIterator[str]:
    """Stream dashboard HITL resume chunks and persist any nested ``hitl_required``.

    Follow-up interrupts during resume must land in the pending store so history
    reload / refresh can reinject the approval card (same as the initial turn).
    """
    rejected = any(isinstance(d, dict) and d.get("type") == "reject" for d in decisions)
    if pending is not None and pending.resume_agent_id:
        from octop.i18n.domains.slash import tr as slash_tr  # noqa: PLC0415
        from octop.infra.utils.locale import normalize_locale  # noqa: PLC0415

        teams = getattr(processor, "teams", None)
        deliver = getattr(teams, "deliver_member_hitl", None) if teams is not None else None
        handed = hitl_coordinator.hand_member_pause(
            pending,
            decisions,
            deliver=deliver if callable(deliver) else None,
            rejected=rejected,
        )
        if handed:
            # The member job keeps streaming on the room socket. A normal
            # ``done`` makes the dashboard reload history immediately, which
            # drops the live member answer before fan-in has saved it.
            yield format_sse(
                "chunk",
                {"type": "done", "team_member_continuing": True},
            )
            return
        yield format_sse(
            "chunk",
            {"type": "error", "message": slash_tr("hitl.expired", normalize_locale(locale))},
        )
        return
    hitl_ctx = HitlStreamContext(
        thread_id=thread_id,
        agent_id=agent_id,
        user_id=user_id,
        session_key=session_key,
        channel_type=channel_type,
    )
    disconnected = False
    followup_pause = False
    resume_text_parts: list[str] = []
    resume_error: str | None = None
    bao_task_repo = getattr(getattr(server, "services", None), "bao_task_repo", None)
    # Clear the in-memory pause before the (possibly long) resume stream so
    # history reload cannot reinject the same card while the turn continues.
    if pending is not None:
        hitl_coordinator.store.mark_resolved(
            pending.pending_id,
            "rejected" if rejected else "approved",
        )
    try:
        async for chunk in processor.iter_hitl_resume_chunks(
            agent_id=agent_id,
            thread_id=thread_id,
            user_id=user_id,
            decisions=decisions,
        ):
            if not disconnected:
                disconnected = await is_disconnected()
            if isinstance(chunk, dict) and chunk.get("type") == "hitl_required":
                followup_pause = True
                request_payload = chunk.get("request")
                if isinstance(request_payload, dict):
                    request_payload = normalize_hitl_request(request_payload)
                    record = hitl_coordinator.register_from_request(request_payload, ctx=hitl_ctx)
                    request_payload["pending_id"] = record.pending_id
                    chunk["request"] = request_payload
            if isinstance(chunk, dict):
                chunk_type = chunk.get("type")
                if chunk_type == "token":
                    token = chunk.get("content")
                    if isinstance(token, str) and token:
                        resume_text_parts.append(token)
                elif chunk_type == "error":
                    raw_error = chunk.get("message")
                    if isinstance(raw_error, str) and raw_error.strip():
                        resume_error = raw_error.strip()
            if not disconnected:
                yield format_sse("chunk", chunk)
        # A new approval card is still pending. Draining now would start a
        # turn that expires that card. Keep the queue until a resume finishes
        # without another pause. A plain ``done`` would also make the
        # dashboard flush locally queued messages and reload history.
        if followup_pause:
            if bao_task_repo is not None:
                bao_task_repo.complete_running(
                    thread_id=thread_id,
                    agent_id=agent_id,
                    status="awaiting",
                )
            if not disconnected:
                yield format_sse("chunk", {"type": "done", "hitl_paused": True})
            return
        if bao_task_repo is not None:
            bao_task_repo.complete_running(
                thread_id=thread_id,
                agent_id=agent_id,
                status="done",
                result_text="".join(resume_text_parts),
            )
        if not disconnected:
            yield format_sse("chunk", {"type": "done"})
        # Steers parked across the HITL pause drain at this
        # boundary and continue through a normal WS turn — also when the SSE
        # client disconnected, because the resume itself completed here.
        from octop.infra.gateway.ws.ws_channel import resume_parked_steers  # noqa: PLC0415

        try:
            await resume_parked_steers(
                server,
                agent_id=agent_id,
                thread_id=thread_id,
                session_key=session_key,
                channel_type=channel_type,
                user_id=user_id,
            )
        except Exception:
            logging.getLogger(__name__).exception("steer resume drain failed thread=%s", thread_id)
    except Exception as exc:
        # Resume failed after we cleared the pause for reinject safety — do not
        # leave the record looking like a successful approve/reject.
        if pending is not None:
            hitl_coordinator.store.mark_resolved(pending.pending_id, "expired")
        if bao_task_repo is not None:
            bao_task_repo.complete_running(
                thread_id=thread_id,
                agent_id=agent_id,
                status="failed",
                error_text=resume_error or str(exc),
            )
        yield format_sse(
            "chunk",
            {"type": "error", "message": format_stream_error(exc, locale)},
        )


def _dashboard_hitl_stream_context(
    server: Any,
    *,
    agent_id: str,
    thread_id: str,
    user_id: int,
    pending: HitlPendingRecord | None,
) -> tuple[str, str]:
    if pending is not None:
        return pending.session_key, pending.channel_type
    row = server.app_runtime.gateway.thread_registry.get_thread(thread_id)
    if row is not None:
        return row.session_key, row.channel_type or "dashboard"
    return f"{agent_id}:dashboard:{user_id}:dm", "dashboard"


@router.get(
    "/agents/{agent_id}/chat/hitl/pending",
    summary="List pending HITL pauses",
    response_model=HitlPendingListOut,
)
async def list_pending_hitl(
    agent_id: str,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Pending questions/approvals the Home inbox can render.

    Read-only projection of the same ``HitlPendingStore`` the chat page uses;
    answering still goes through ``/chat/hitl/resume`` so there is no second
    source of truth.
    """
    assert_agent_access(server, agent_id, user)
    assert server.app_runtime is not None  # noqa: S101
    gateway = server.app_runtime.gateway
    records = gateway.processor.hitl_coordinator.store.list_pending_for_agent(
        agent_id=agent_id,
        user_id=user.id,
    )
    items: list[dict[str, Any]] = []
    for record in records:
        # Team member pauses live on the room thread but resume through the
        # member agent/thread stored separately.
        owner_agent = record.resume_agent_id or record.agent_id
        owner_thread = record.resume_thread_id or record.thread_id
        row = gateway.thread_registry.get_thread(owner_thread)
        title = getattr(row, "title", None) if row is not None else None
        is_ask = is_ask_action_requests(record.action_requests)
        items.append(
            {
                "pendingId": record.pending_id,
                "agentId": owner_agent,
                "threadId": owner_thread,
                "sessionTitle": str(title) if title else None,
                "createdAtMs": int(record.created_at * 1000),
                "kind": "question" if is_ask else "approval",
                "questions": extract_questions(record.action_requests) if is_ask else [],
                "actionRequests": [
                    {
                        "name": str(action.get("name") or "tool"),
                        "description": action.get("description"),
                    }
                    for action in record.action_requests
                ],
            }
        )
    return {"ok": True, "items": items}


@router.post(
    "/agents/{agent_id}/chat/hitl/resume",
    summary="Resume HITL approval (SSE)",
    responses={
        200: {
            "description": (
                "Server-sent events. Each frame is `event: chunk` followed by one "
                "JSON `ChatStreamChunk` payload (`data: {...}`), ending with "
                "`{\"type\": \"done\"}` or an error chunk."
            ),
            "content": {
                "text/event-stream": {"schema": {"$ref": "#/components/schemas/ChatStreamChunk"}}
            },
        }
    },
)
async def resume_hitl(
    agent_id: str,
    body: HitlResumeBody,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> StreamingResponse:
    """Resume a paused human-in-the-loop tool approval and stream subsequent chunks."""
    from octop.api.routers.chat.history import _require_thread  # noqa: PLC0415

    thread_row = _require_thread(server, agent_id, body.thread_id, user, None)
    processor = server.app_runtime.gateway.processor
    hitl_coordinator = processor.hitl_coordinator
    requested_id = (body.pending_id or "").strip()
    pending = hitl_coordinator.store.resolve_pending_for_thread(
        body.thread_id,
        agent_id=agent_id,
        user_id=None if thread_row.contributed else user.id,
        pending_id=requested_id or None,
    )
    if requested_id and pending is None:
        from octop.i18n.domains.slash import tr as slash_tr  # noqa: PLC0415
        from octop.infra.utils.locale import normalize_locale  # noqa: PLC0415

        locale = normalize_locale(resolve_request_locale(request))

        async def missing() -> AsyncIterator[str]:
            yield format_sse(
                "chunk",
                {"type": "error", "message": slash_tr("hitl.expired", locale)},
            )

        return StreamingResponse(missing(), media_type="text/event-stream")
    session_key, channel_type = _dashboard_hitl_stream_context(
        server,
        agent_id=agent_id,
        thread_id=body.thread_id,
        user_id=user.id,
        pending=pending,
    )
    if pending is not None:
        reason = decision_rejection_reason(pending, body.decisions)
        if reason is not None:
            raise HTTPException(status_code=400, detail=reason)

    if body.hitl_policy is not None and thread_row.user_id == user.id:
        hitl_coordinator.session_policies.set(body.thread_id, body.hitl_policy.model_dump())

    # The Home inbox reflects the same pause outside the chat page; tell it the
    # card was answered elsewhere so both surfaces converge without polling.
    if pending is not None:
        try:
            await server.app_runtime.gateway.ws_hub.push_to_user(
                user.id,
                {
                    "type": "hitl_resolved",
                    "agentId": agent_id,
                    "threadId": body.thread_id,
                    "pendingId": pending.pending_id,
                },
            )
        except Exception:  # noqa: BLE001 - a notify failure must not block resume
            logger.warning("hitl resolved notify failed thread=%s", body.thread_id)

    async def gen() -> AsyncIterator[str]:
        async for frame in iter_dashboard_hitl_resume_sse(
            server=server,
            processor=processor,
            hitl_coordinator=hitl_coordinator,
            agent_id=agent_id,
            thread_id=body.thread_id,
            user_id=user.id,
            decisions=body.decisions,
            pending=pending,
            session_key=session_key,
            channel_type=channel_type,
            locale=resolve_request_locale(request),
            is_disconnected=request.is_disconnected,
        ):
            yield frame

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post(
    "/agents/{agent_id}/chat/polish",
    summary="Polish prompt (compat)",
    deprecated=True,
    response_model=ChatPolishOut,
)
async def polish_prompt(
    agent_id: str,
    body: PolishBody,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, str]:
    """Compat alias for ``POST /api/text/assist`` with ``kind=chat.prompt``."""
    assert_agent_access(server, agent_id, user)
    polished = await run_text_assist(
        models=require_host_models(server),
        kind="chat.prompt",
        text=body.text,
        locale=resolve_request_locale(request),
        default_model=body.default_model,
    )
    return {"text": polished}
