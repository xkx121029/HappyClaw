"""Harness wiring: host briefing, peer allowlists and dispatch hooks."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable, Sequence
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import HumanMessage
from octop_harness.messages import extract_call_response
from octop_harness.teams.util import (
    PeerCall,
    build_one_shot_request,
)

from octop.i18n import tr
from octop.infra.agents.teams.service import _user_may_use_member, is_team_agent
from octop.infra.db.repos.agents import AgentRow
from octop.infra.utils.locale import DEFAULT_LOCALE, resolve_user_locale
from octop.infra.utils.ulid import new_ulid

logger = logging.getLogger(__name__)


def host_system_prompt(row: Any, user_repo: Any) -> str:
    """Runtime host briefing, appended to any custom ``system_prompt``."""
    uid = getattr(row, "user_id", None)
    locale = (
        resolve_user_locale(user_repo=user_repo, user_id=uid)
        if isinstance(uid, int) and uid > 0
        else DEFAULT_LOCALE
    )
    briefing = tr("teams.host_briefing", locale)
    custom = str(getattr(row, "system_prompt", None) or "").strip()
    return f"{custom}\n\n{briefing}".strip() if custom else briefing


async def subscribe_with_member_catchup(
    gateway: Any,
    room_thread_id: str,
    *,
    subscribe: Callable[[], None],
    send: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    """Attach a room subscriber and replay an in-progress member answer."""
    processor = getattr(gateway, "_processor", None)
    teams = getattr(processor, "teams", None)
    deliver = getattr(teams, "deliver_live_member_catchup", None)
    if not callable(deliver):
        subscribe()
        return
    await deliver(room_thread_id, subscribe=subscribe, send=send)


def _is_async_room_invoke(
    *,
    source: str | None,
    job_id: str | None,
    source_thread_id: str | None,
) -> bool:
    """Live-stream a peer when this is an inbox/async room dispatch."""
    if not str(source_thread_id or "").strip():
        return False
    return str(source or "") == "inbox" or bool(job_id)


def _supported_kwargs(fn: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return dict(kwargs)
    if any(item.kind is inspect.Parameter.VAR_KEYWORD for item in params.values()):
        return dict(kwargs)
    return {key: value for key, value in kwargs.items() if key in params}


def _patch_inbox_wrapup(
    inbox: Any,
    *,
    stream_followup: Callable[..., Any] | None,
    is_team: Callable[[str], bool] | None = None,
) -> None:
    """Run async host wrap-up through the room stream, not a blocking ``call()``."""
    if inbox is None or stream_followup is None:
        return
    original = getattr(inbox, "_synthesize_reply", None)
    if original is None:
        return

    async def _fallback(msg: Any, result_text: str | None, error_text: str | None) -> str | None:
        reply = await original(msg, result_text, error_text)
        if reply is None or isinstance(reply, str):
            return reply
        return str(reply)

    async def synthesize(
        msg: Any,
        result_text: str | None,
        error_text: str | None,
    ) -> str | None:
        cancelled = getattr(inbox, "_is_cancelled", None)
        if callable(cancelled) and cancelled(msg):
            return None
        room = str(getattr(msg, "source_thread_id", None) or "").strip()
        host_id = str(getattr(msg, "source_agent_id", None) or "")
        if not host_id or not room:
            return await _fallback(msg, result_text, error_text)
        if callable(is_team) and not is_team(host_id):
            return await _fallback(msg, result_text, error_text)
        processor = getattr(inbox, "_processor", None)
        compose = getattr(processor, "compose_followup", None)
        if compose is None:
            return await _fallback(msg, result_text, error_text)
        prompt = compose(msg, result_text=result_text, error_text=error_text)
        req = build_one_shot_request(
            user_id=msg.user_id,
            agent_id=host_id,
            text=prompt,
            source="inbox",
            configurable={
                **({"octop_memory_capture_exclude": True} if error_text else {}),
                "octop_decision_followup": True,
                "peer_invoke_mode": "async",
                "octop_decision_finished_member": str(getattr(msg, "target_agent_id", "") or ""),
                "octop_decision_task": str(getattr(msg, "message", "") or ""),
            },
        )
        try:
            reply = await stream_followup(
                req,
                room_thread_id=room,
                speaker_id=host_id,
            )
        except Exception:
            logger.exception("team host wrap-up stream failed host=%s room=%s", host_id, room)
            return await _fallback(msg, result_text, error_text)
        if isinstance(reply, dict):
            return extract_call_response(reply)
        return ""

    inbox._synthesize_reply = synthesize


def _clean_peer_names(raw: Sequence[str] | None) -> tuple[str, ...] | None:
    if raw is None:
        return None
    return tuple(str(item).strip().lstrip("@") for item in raw if str(item).strip())


def _request_peer_allowlist() -> tuple[str, ...] | None:
    from octop_harness.teams.team_manager import _request_team_peers  # noqa: PLC0415

    return _clean_peer_names(_request_team_peers())


def _shared_member_allowlist(
    harness_team: Any,
    *,
    exclude_agent_id: str | None,
    team_peers: Sequence[str] | None,
) -> tuple[str, ...] | None:
    """Ids a caller may pull in from outside their own account.

    ``None`` means there is no allowlist (ordinary expert). An empty tuple
    means the allowlist is present and names nobody.
    """
    config_allow = _clean_peer_names(harness_team._peer_allowlist(exclude_agent_id))
    override = _clean_peer_names(team_peers)
    if override is None:
        override = _request_peer_allowlist()
    if config_allow is None and override is None:
        return None
    if config_allow is None:
        return override
    if override is None:
        return config_allow
    allowed = set(config_allow)
    return tuple(name for name in override if name in allowed)


def _peer_viewer(user_id: str | int, load_user: Callable[[int], Any]) -> Any:
    if isinstance(user_id, int):
        uid: int | None = user_id
    elif str(user_id).isdigit():
        uid = int(user_id)
    else:
        uid = None
    row = load_user(uid) if uid is not None else None
    is_admin = (
        bool(getattr(row, "is_admin", False)) or str(getattr(row, "role", "") or "") == "admin"
    )
    viewer_id = getattr(row, "id", None) if row is not None else uid
    return SimpleNamespace(id=viewer_id, is_admin=is_admin)


def _usable_shared_entry(
    harness_team: Any,
    agent_id: str,
    *,
    exclude_agent_id: str | None,
    viewer: Any,
    load_agent: Callable[[str], AgentRow | None],
) -> Any | None:
    if not agent_id or agent_id == exclude_agent_id:
        return None
    try:
        entry = harness_team._registry.get(agent_id)
    except KeyError:
        return None
    if entry.agent_id == exclude_agent_id:
        return None
    row = load_agent(entry.agent_id)
    if row is None or is_team_agent(row) or not _user_may_use_member(row, viewer):
        return None
    return entry


def wire_shared_member_peers(
    harness_team: Any,
    *,
    load_agent: Callable[[str], AgentRow | None],
    load_user: Callable[[int], Any],
) -> None:
    """Let a team allowlist see shared experts owned by other accounts.

    Harness ``list_peers`` and ``_resolve_peer_entry`` keep same-user peers
    only, so a host whose members were shared by someone else gets an empty
    ``agent_list`` and ``ask_agent`` rejects the dispatch. Ids on the host
    ``team_peers`` config, or on a member's request-scoped allowlist, are
    added back when ``_user_may_use_member`` accepts them for the chatting user.
    """
    if harness_team is None or getattr(harness_team, "_octop_shared_member_peers", False):
        return
    original_list = getattr(harness_team, "list_peers", None)
    original_resolve = getattr(harness_team, "_resolve_peer_entry", None)
    if original_list is None or original_resolve is None:
        return

    def list_peers(
        user_id: str | int,
        *,
        exclude_agent_id: str | None = None,
        team_peers: Sequence[str] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        peers = list(
            original_list(
                user_id,
                exclude_agent_id=exclude_agent_id,
                team_peers=team_peers,
                **kwargs,
            )
        )
        allow = _shared_member_allowlist(
            harness_team,
            exclude_agent_id=exclude_agent_id,
            team_peers=team_peers,
        )
        if not allow:
            return peers
        seen = {str(getattr(entry, "agent_id", "")) for entry in peers}
        viewer = _peer_viewer(user_id, load_user)
        added: list[Any] = []
        for member_id in allow:
            if member_id in seen:
                continue
            entry = _usable_shared_entry(
                harness_team,
                member_id,
                exclude_agent_id=exclude_agent_id,
                viewer=viewer,
                load_agent=load_agent,
            )
            if entry is None or entry.agent_id in seen:
                continue
            added.append(entry)
            seen.add(entry.agent_id)
        if added:
            enrich = getattr(harness_team, "_apply_peer_enrich", None)
            if callable(enrich):
                enrich(added)
        peers.extend(added)
        return peers

    def resolve_peer_entry(from_agent_id: str, to_agent_id: str, user_id: str | int) -> Any:
        try:
            return original_resolve(from_agent_id, to_agent_id, user_id)
        except ValueError as exc:
            if "not owned by user" not in str(exc):
                raise
        allow = _shared_member_allowlist(
            harness_team,
            exclude_agent_id=from_agent_id,
            team_peers=None,
        )
        if not allow or to_agent_id not in allow:
            raise ValueError(f"agent {to_agent_id!r} not owned by user")
        entry = _usable_shared_entry(
            harness_team,
            to_agent_id,
            exclude_agent_id=from_agent_id,
            viewer=_peer_viewer(user_id, load_user),
            load_agent=load_agent,
        )
        if entry is None:
            raise ValueError(f"agent {to_agent_id!r} not owned by user")
        return entry

    harness_team.list_peers = list_peers
    harness_team._resolve_peer_entry = resolve_peer_entry
    harness_team._octop_shared_member_peers = True


def wire_host_dispatch(
    harness_team: Any,
    *,
    is_team: Callable[[str], bool],
    stream_peer: Callable[..., Any] | None = None,
    stream_host: Callable[..., Any] | None = None,
    take_prompt: Callable[[str, str | None], tuple[str, str] | None] | None = None,
) -> None:
    """Patch harness TeamManager so async ``ask_agent`` uses inbox + room stream."""
    if harness_team is None:
        return
    original_call = getattr(harness_team, "call_peer", None)

    async def call_peer(
        *,
        from_agent_id: str,
        to_agent_id: str,
        message: str,
        user_id: str | int,
        source: str = "ask_agent",
        source_thread_id: str | None = None,
        session_key: str | None = None,
        **kwargs: Any,
    ) -> Any:
        if getattr(harness_team, "enabled", False) and is_team(from_agent_id):
            return harness_team.submit_peer(
                from_agent_id=from_agent_id,
                to_agent_id=to_agent_id,
                message=message,
                user_id=user_id,
                source_thread_id=source_thread_id,
                metadata={"session_key": session_key} if session_key else None,
            )
        if original_call is None:
            raise TypeError("harness team has no call_peer")
        return await original_call(
            from_agent_id=from_agent_id,
            to_agent_id=to_agent_id,
            message=message,
            user_id=user_id,
            source=source,
            source_thread_id=source_thread_id,
            session_key=session_key,
            **kwargs,
        )

    harness_team.call_peer = call_peer

    stream_followup = stream_host or stream_peer
    original_call_agent = getattr(harness_team, "_call_agent", None)
    if original_call_agent is not None and stream_followup is not None:

        async def call_agent(agent_id: str, request: Any) -> Any:
            source = getattr(request, "source", None)
            if isinstance(request, dict):
                source = request.get("source")
            thread_id = getattr(request, "thread_id", None)
            if isinstance(request, dict):
                thread_id = request.get("thread_id")
            room = str(thread_id or "").strip()
            if source == "inbox" and room and is_team(agent_id):
                return await stream_followup(
                    request,
                    room_thread_id=room,
                    speaker_id=agent_id,
                )
            return await original_call_agent(agent_id, request)

        harness_team._call_agent = call_agent
        inbox = getattr(harness_team, "inbox", None)
        if inbox is not None:
            inbox._call_agent = call_agent

    _patch_inbox_wrapup(
        getattr(harness_team, "inbox", None),
        stream_followup=stream_followup,
        is_team=is_team,
    )

    original_invoke = getattr(harness_team, "_invoke_peer", None)
    if original_invoke is not None and stream_peer is not None:

        async def invoke_peer(
            *,
            from_agent_id: str,
            to_agent_id: str,
            message: str,
            user_id: str | int,
            source: str,
            source_thread_id: str | None,
            source_session_key: str | None,
            job_id: str | None = None,
        ) -> Any:
            peer_kwargs = {
                "from_agent_id": from_agent_id,
                "to_agent_id": to_agent_id,
                "message": message,
                "user_id": user_id,
                "source": source,
                "source_thread_id": source_thread_id,
                "source_session_key": source_session_key,
                "job_id": job_id,
            }
            if not _is_async_room_invoke(
                source=source,
                job_id=job_id,
                source_thread_id=source_thread_id,
            ):
                return await original_invoke(**_supported_kwargs(original_invoke, peer_kwargs))
            request = await harness_team._build_peer_request(
                **_supported_kwargs(harness_team._build_peer_request, peer_kwargs)
            )
            enrich = getattr(harness_team, "_enrich_request", None)
            if enrich is not None:
                request = await enrich(to_agent_id, request)
            result = await stream_peer(
                request,
                room_thread_id=source_thread_id,
                speaker_id=to_agent_id,
            )
            payload = result if isinstance(result, dict) else {}
            after = getattr(harness_team, "_after_peer", None)
            if after is not None:
                call = PeerCall(**_supported_kwargs(PeerCall, peer_kwargs))
                try:
                    await after(call, str(getattr(request, "thread_id", None) or ""), payload)
                except Exception:
                    logger.warning(
                        "peer after-call hook failed for %s -> %s",
                        from_agent_id,
                        to_agent_id,
                        exc_info=True,
                    )
            return request, payload

        harness_team._invoke_peer = invoke_peer

    if take_prompt is None:
        return
    original_enrich = getattr(harness_team, "_enrich_request", None)

    async def enrich(agent_id: str, req: Any) -> Any:
        if original_enrich is not None:
            req = await original_enrich(agent_id, req)
        pair = take_prompt(agent_id, getattr(req, "thread_id", None))
        if not pair:
            return req
        from langchain_core.messages import SystemMessage

        question, dispatch = pair
        messages: list[Any] = []
        if dispatch and dispatch != question:
            messages.append(SystemMessage(content=dispatch))
        if question:
            messages.append(
                HumanMessage(
                    content=question,
                    id=f"team-peer:{getattr(req, 'thread_id', None)}:{new_ulid()}:human",
                )
            )
        if messages:
            req.messages = messages
        return req

    harness_team._enrich_request = enrich


__all__ = [
    "host_system_prompt",
    "subscribe_with_member_catchup",
    "_is_async_room_invoke",
    "_supported_kwargs",
    "_patch_inbox_wrapup",
    "_clean_peer_names",
    "_request_peer_allowlist",
    "_shared_member_allowlist",
    "_peer_viewer",
    "_usable_shared_entry",
    "wire_shared_member_peers",
    "wire_host_dispatch",
]
