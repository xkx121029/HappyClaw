"""Room turn bookkeeping: pinning, steering and host follow-up."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage
from octop_harness.teams.processor import ReplyEvent

from octop.i18n.domains.stream import format_stream_error
from octop.infra.agents.teams.service import is_team_agent
from octop.infra.utils.turn_failure import log_failed_tool_results
from octop.infra.utils.ulid import new_ulid

if TYPE_CHECKING:
    pass

from octop.infra.agents.teams.room.base import TeamRoomBase
from octop.infra.agents.teams.room.constants import (
    _HOST_IDLE_POLL_SEC,
    _HOST_IDLE_WAIT_SEC,
    _RELAY_CHUNK_TYPES,
)
from octop.infra.agents.teams.room.projection import (
    _assistant_text,
    _chat_request_payload,
    _decision_from_messages,
    _ensure_reasoning,
    _is_decision_custom,
    _message_is_assistant,
    _octop_user_id,
    _room_peer_messages,
    _with_speaker,
)

logger = logging.getLogger(__name__)


class RoomTurnMixin(TeamRoomBase):
    """Room turn bookkeeping: pinning, steering and host follow-up."""

    def _host_turn_busy(self, host_id: str, room_thread_id: str) -> bool:
        hub = getattr(self._gateway, "ws_hub", None) if self._gateway is not None else None
        check_turn = getattr(hub, "is_turn_active", None)
        check_host = getattr(self._agent_manager, "is_agent_active", None)
        turn_active = check_turn(room_thread_id) is True if callable(check_turn) else False
        host_busy = bool(host_id) and check_host(host_id) is True if callable(check_host) else False
        return turn_active or host_busy

    def _steer(self) -> Any:
        gateway = self._gateway
        if gateway is None:
            return None
        return getattr(gateway, "steer", None)

    def _pin_room_turn(self, room_thread_id: str) -> str:
        steer = self._steer()
        pin = getattr(steer, "pin_room_followup", None)
        if not callable(pin) or not room_thread_id:
            return ""
        turn_id = pin(room_thread_id)
        return turn_id if isinstance(turn_id, str) else ""

    def _release_room_turn(self, room_thread_id: str, *, expect_wrapup: bool) -> None:
        steer = self._steer()
        release = getattr(steer, "release_room_followup", None)
        if callable(release) and room_thread_id:
            release(room_thread_id, expect_wrapup=expect_wrapup)

    def _finish_room_turn(self, room_thread_id: str) -> None:
        steer = self._steer()
        finish = getattr(steer, "finish_room_followup", None)
        if callable(finish) and room_thread_id:
            finish(room_thread_id)

    def _room_followup_turn_id(self, room_thread_id: str) -> str:
        steer = self._steer()
        current = getattr(steer, "room_followup_turn_id", None)
        if not callable(current) or not room_thread_id:
            return ""
        turn_id = current(room_thread_id)
        return turn_id if isinstance(turn_id, str) else ""

    async def _wait_host_dispatch_idle(self, host_id: str, room_thread_id: str) -> bool:
        """Wait until the host turn is idle.

        Returns False when the wait expires and the host is still streaming.
        """
        deadline = asyncio.get_running_loop().time() + _HOST_IDLE_WAIT_SEC
        while True:
            if not self._host_turn_busy(host_id, room_thread_id):
                return True
            if asyncio.get_running_loop().time() >= deadline:
                logger.warning(
                    "team room waited %.0fs for host idle host=%s room=%s",
                    _HOST_IDLE_WAIT_SEC,
                    host_id,
                    room_thread_id,
                )
                return False
            await asyncio.sleep(_HOST_IDLE_POLL_SEC)

    async def stream_host_followup_to_room(
        self,
        request: Any,
        *,
        room_thread_id: str,
        speaker_id: str,
    ) -> dict[str, Any]:
        """Stream the host wrap-up onto the team page (inbox wakeup)."""
        await self._wait_host_dispatch_idle(speaker_id, room_thread_id)
        payload = _chat_request_payload(request, speaker_id)
        payload["thread_id"] = room_thread_id
        result = await self.stream_peer_to_room(
            payload,
            room_thread_id=room_thread_id,
            speaker_id=speaker_id,
            extra_stamp={"team_wrapup": True},
        )
        text = str(result.get("stream_text") or "").strip()
        if not text:
            for msg in reversed(result.get("messages") or []):
                text = _assistant_text(msg)
                if text:
                    break
        if text:
            decision = _decision_from_messages(result.get("messages") or [])
            if decision is None and isinstance(result.get("decision"), dict):
                decision = dict(result["decision"])
            self._persist_room_assistant(
                room_thread_id,
                speaker_id,
                text,
                wrapup=True,
                decision=decision,
            )
        live = bool(result.get("team_live_streamed"))
        # Some models finish wrap-up in checkpoint/values only — no token
        # frames. Push the final text so the open room still sees it.
        if text and not live:
            await self._push_room_snapshot(
                room_thread_id,
                speaker_id,
                text,
                wrapup=True,
            )
            live = self._thread_is_watched(room_thread_id)
        # ``on_reply`` fires after this method even when nobody watches the
        # room. Mark the reply handled once it has been persisted, otherwise
        # the fallback path appends the same wrap-up a second time.
        if room_thread_id and text:
            self._live_host_replies.add(room_thread_id)
        return result

    def stamp_host_runtime(self, request: dict[str, Any], agent_id: str) -> None:
        """Force the host turn onto async ``ask_agent`` (inbox), not sync."""
        row = self._agent_manager.get_row(agent_id)
        if not is_team_agent(row):
            return
        cfg = dict(request.get("configurable") or {})
        cfg["peer_invoke_mode"] = "async"
        cfg.pop("mcp_use_default", None)
        request["configurable"] = cfg
        request.pop("mcp_servers", None)
        request.pop("mcp_use_default", None)
        strip = getattr(self._agent_manager, "strip_team_host_runtime_tools", None)
        if callable(strip):
            strip(agent_id)

    def stash_peer_prompt(
        self,
        agent_id: str,
        thread_id: str | None,
        *,
        question: str,
        dispatch: str,
    ) -> None:
        if not thread_id:
            return
        question = question.strip()
        dispatch = dispatch.strip()
        if not question and not dispatch:
            return
        self._peer_prompts[(agent_id, thread_id)] = (question, dispatch)

    def take_peer_prompt(self, agent_id: str, thread_id: str | None) -> tuple[str, str] | None:
        if not thread_id:
            return None
        return self._peer_prompts.pop((agent_id, thread_id), None)

    def peek_peer_prompt(self, agent_id: str, thread_id: str | None) -> tuple[str, str] | None:
        if not thread_id:
            return None
        return self._peer_prompts.get((agent_id, thread_id))

    def install_host_dispatch(self, harness_team: Any) -> None:
        """Force team hosts onto inbox dispatch and room streaming."""
        from octop.infra.agents.teams.room.wiring import wire_host_dispatch

        wire_host_dispatch(
            harness_team,
            is_team=lambda agent_id: is_team_agent(self._agent_manager.get_row(agent_id)),
            stream_peer=self.stream_peer_to_room,
            stream_host=self.stream_host_followup_to_room,
            take_prompt=self.take_peer_prompt,
        )

    def _take_live_host_reply(self, thread_id: str | None) -> bool:
        tid = str(thread_id or "").strip()
        if not tid or tid not in self._live_host_replies:
            return False
        self._live_host_replies.discard(tid)
        return True

    async def _peer_result_messages(
        self,
        speaker_id: str,
        member_tid: str,
        text_parts: list[str],
        reasoning_parts: list[str] | None = None,
    ) -> list[Any]:
        reasoning = "".join(reasoning_parts or []).strip()
        messages = await self._history(speaker_id, member_tid)
        if messages:
            room = _room_peer_messages(messages)
            if room:
                stamped = [_with_speaker(msg, speaker_id) for msg in room]
                if reasoning:
                    for msg in reversed(stamped):
                        if _message_is_assistant(msg):
                            _ensure_reasoning(msg, reasoning)
                            break
                return stamped
        text = "".join(text_parts).strip()
        if not text and not reasoning:
            return []
        extra: dict[str, Any] = {"speaker_agent_id": speaker_id}
        if reasoning:
            extra["reasoning_content"] = reasoning
        return [
            AIMessage(
                content=text,
                id=f"team-peer:{new_ulid()}:assistant",
                additional_kwargs=extra,
            )
        ]

    async def _publish_reply(self, event: ReplyEvent, room: str) -> None:
        speaker = event.source_agent_id
        text = (
            event.error_text or "Background task did not complete."
            if event.status != "done"
            else (event.reply_text or "(empty)")
        )
        failed = event.status == "failed"
        if failed:
            text = format_stream_error(text, self._locale_for(_octop_user_id(event.user_id)))
        if room:
            await self._push_room_to_channels(room, speaker, text, wrapup=True)
        live_ws = self._take_live_host_reply(room) and event.status == "done"
        if live_ws:
            if room:
                self._thread_registry.touch_last_active(room)
            return
        session_key = event.metadata.get("session_key")
        session = (
            self._thread_registry.get_session(session_key.strip())
            if isinstance(session_key, str) and session_key.strip()
            else None
        )
        if session is not None and not self._thread_registry.is_im_session(session):
            await self._deliver_text(
                session,
                str(session.session_key),
                text,
                speaker_id=speaker,
                **({"error": True} if failed else {}),
            )
            return
        if session is not None:
            return
        if room:
            await self._publish_room_text(
                room, speaker, text, **({"error": True} if failed else {})
            )
            self._thread_registry.touch_last_active(room)
            return
        logger.warning("team reply %s: no room to publish", event.inbox_id)

    async def on_reply(self, event: ReplyEvent) -> None:
        self._end_job_from_reply(event)
        room = str(event.source_thread_id or "").strip()
        try:
            await self._publish_reply(event, room)
        finally:
            self._finish_room_turn(room)

    async def stream_peer_to_room(
        self,
        request: Any,
        *,
        room_thread_id: str,
        speaker_id: str,
        extra_stamp: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run one peer turn and fan tokens to the member page and, once the host is idle, the room.

        The host draft is a single token accumulator. Starting the member model
        while that turn is still streaming splices the two speakers together, so
        a member waits until the host turn is idle. If the wait expires, member
        frames still reach the member thread immediately and stay off the room
        wall until the host goes idle.

        A ``hitl_required`` pause does not finish the job. The room shows the
        approval card and this call blocks until the user answers, then resumes
        the member graph. Inbox fan-in and the host wrap-up run only after the
        member turn actually ends.
        """
        payload = _chat_request_payload(request, speaker_id)
        member_tid = str(payload.get("thread_id") or "").strip()
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        relayed_visible = False
        saw_tool_call = False
        decision_payload: dict[str, Any] | None = None
        emitted_tool_error_ids: set[str] = set()
        hold_room = self._defer_member_wall(speaker_id, member_tid, room_thread_id)
        host_id = self._room_agent_id(room_thread_id) if hold_room else ""
        room_open = True
        room_turn_id = ""
        completed = False
        buffered: list[dict[str, Any]] = []
        resume_pending: str | None = None

        def note_visible(chunk: dict[str, Any]) -> None:
            nonlocal relayed_visible
            kind = str(chunk.get("type") or "")
            if kind in {"token", "reasoning", "attachment"} and self._thread_is_watched(
                room_thread_id
            ):
                relayed_visible = True

        async def release_held_room() -> None:
            nonlocal room_open
            if hold_room and not room_open and self._host_turn_busy(host_id, room_thread_id):
                opened = await self._wait_host_dispatch_idle(host_id, room_thread_id)
                if not opened and self._host_turn_busy(host_id, room_thread_id):
                    logger.warning(
                        "member wall released while host still streaming host=%s room=%s",
                        host_id,
                        room_thread_id,
                    )
            if buffered:
                frames = list(buffered)
                buffered.clear()
                for frame in frames:
                    await self._push_room_frame(
                        frame,
                        room_thread_id,
                        speaker_id,
                        turn_id=room_turn_id,
                    )
                    note_visible(frame)
                    if str(frame.get("type") or "") == "hitl_required":
                        await self._announce_member_hitl(frame, room_thread_id, speaker_id)
            room_open = True

        async def emit(chunk: dict[str, Any]) -> None:
            if hold_room and not room_open and self._host_turn_busy(host_id, room_thread_id):
                await self._relay_chunk(
                    chunk,
                    room_thread_id=room_thread_id,
                    member_thread_id=member_tid,
                    speaker_id=speaker_id,
                    include_room=False,
                    turn_id=room_turn_id,
                )
                buffered.append(chunk)
                return
            await release_held_room()
            await self._relay_chunk(
                chunk,
                room_thread_id=room_thread_id,
                member_thread_id=member_tid,
                speaker_id=speaker_id,
                turn_id=room_turn_id,
            )
            note_visible(chunk)
            if str(chunk.get("type") or "") == "hitl_required":
                await self._announce_member_hitl(chunk, room_thread_id, speaker_id)

        try:
            # Capture the host turn before waiting it out. ``end_turn`` drops
            # steer state as soon as the host goes idle, which is when members
            # usually start.
            room_turn_id = self._pin_room_turn(room_thread_id)
            if hold_room and self._host_turn_busy(host_id, room_thread_id):
                room_open = await self._wait_host_dispatch_idle(host_id, room_thread_id)
            agen = self._agent_manager.stream(speaker_id, payload)
            while True:
                pause: dict[str, Any] | None = None
                async for chunk in agen:
                    if not isinstance(chunk, dict):
                        continue
                    kind = str(chunk.get("type") or "")
                    if kind == "tool_call_chunk":
                        saw_tool_call = True
                    elif kind == "tool_result":
                        log_failed_tool_results(
                            chunk,
                            agent_id=speaker_id,
                            thread_id=member_tid or room_thread_id,
                            seen=emitted_tool_error_ids,
                            live=saw_tool_call,
                        )
                    if kind == "token":
                        piece = str(chunk.get("content") or "")
                        if piece:
                            text_parts.append(piece)
                    elif kind == "reasoning":
                        piece = str(chunk.get("content") or "")
                        if piece:
                            reasoning_parts.append(piece)
                    if kind == "hitl_required":
                        pause = chunk
                        resume_pending = None
                        break
                    # Host wrap-up runs the decision model. Member streams stay
                    # off the room wall, including their custom events.
                    decision_custom = (
                        kind == "custom" and _is_decision_custom(chunk) and not hold_room
                    )
                    if decision_custom:
                        data = chunk.get("data")
                        if isinstance(data, dict):
                            decision_payload = dict(data)
                    if kind in _RELAY_CHUNK_TYPES or decision_custom:
                        relay = chunk
                        if extra_stamp and (kind in {"token", "reasoning"} or decision_custom):
                            relay = {**chunk, **extra_stamp}
                        await emit(relay)
                if pause is None:
                    resume_pending = None
                    break
                relay, pending_id = await self._open_member_hitl(
                    pause,
                    speaker_id=speaker_id,
                    member_thread_id=member_tid,
                    room_thread_id=room_thread_id,
                    payload=payload,
                )
                decisions: list[dict[str, Any]] = []
                answered = False
                try:
                    await emit(relay)
                    await release_held_room()
                    decisions = await self._wait_member_hitl(pending_id)
                    answered = True
                finally:
                    if not answered:
                        fut = self._hitl_waiters.pop(pending_id, None)
                        if fut is not None and not fut.done():
                            fut.cancel()
                        self._expire_hitl(pending_id)
                resume_pending = pending_id
                agen = self._agent_manager.resume_hitl(speaker_id, member_tid, decisions)
            completed = True
        except Exception:
            if resume_pending:
                self._expire_hitl(resume_pending)
            logger.warning(
                "team peer stream failed speaker=%s room=%s",
                speaker_id,
                room_thread_id,
                exc_info=True,
            )
            raise
        finally:
            try:
                await release_held_room()
                done: dict[str, Any] = {"type": "done"}
                if extra_stamp:
                    done = {**done, **extra_stamp}
                await self._relay_chunk(
                    done,
                    room_thread_id=room_thread_id,
                    member_thread_id=member_tid,
                    speaker_id=speaker_id,
                    turn_id=room_turn_id,
                )
            finally:
                await self._clear_live_member(room_thread_id, speaker_id)
                self._release_room_turn(
                    room_thread_id,
                    expect_wrapup=hold_room and completed,
                )
        stream_text = "".join(text_parts).strip()
        return {
            "messages": await self._peer_result_messages(
                speaker_id,
                member_tid,
                text_parts,
                reasoning_parts,
            ),
            "team_live_streamed": relayed_visible,
            "stream_text": stream_text,
            "decision": decision_payload,
        }


__all__ = ["RoomTurnMixin"]
