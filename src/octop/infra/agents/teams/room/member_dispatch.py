"""Member dispatch: session prep, job tracking, history transcripts."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage
from octop_harness.teams.inbox import InboxMessage
from octop_harness.teams.processor import ReplyEvent
from octop_harness.teams.util import (
    PeerCall,
)

from octop.i18n import tr
from octop.infra.agents.teams.service import is_team_agent
from octop.infra.history.projection import (
    live_message_inputs,
    message_inputs,
)
from octop.infra.utils.locale import DEFAULT_LOCALE, resolve_user_locale

if TYPE_CHECKING:
    pass

from octop.infra.agents.teams.room.base import TeamRoomBase
from octop.infra.agents.teams.room.constants import (
    _FOLLOWUP_RESULT_MAX_CHARS,
    _ROOM_HISTORY_LIMIT,
)
from octop.infra.agents.teams.room.projection import (
    _apply_edited_files_stamp,
    _assistant_text,
    _edited_files_from_messages,
    _history_projection_messages,
    _is_team_system_prompt,
    _message_role,
    _message_tool_calls,
    _octop_user_id,
    _peer_turn_messages,
    _peer_user_message_id,
    _projected_row_text,
    _projected_speaker,
    _room_peer_messages,
    _truncate_tool_result_text,
    _with_speaker,
)

logger = logging.getLogger(__name__)


class MemberDispatchMixin(TeamRoomBase):
    """Member dispatch: session prep, job tracking, history transcripts."""

    def _defer_member_wall(self, speaker_id: str, member_tid: str, room_thread_id: str) -> bool:
        """Member speech waits for the host. The host wrap-up is already the room voice."""
        if not room_thread_id or not speaker_id:
            return False
        if member_tid and member_tid == room_thread_id:
            return False
        return not is_team_agent(self._agent_manager.get_row(speaker_id))

    def _room_agent_id(self, room_thread_id: str) -> str:
        getter = getattr(self._thread_registry, "get_thread", None)
        if not callable(getter) or not room_thread_id:
            return ""
        row = getter(room_thread_id)
        return str(getattr(row, "agent_id", "") or "")

    def _is_group_dispatch(self, call: PeerCall) -> bool:
        """Async ``ask_agent`` is a group room; sync is a 1:1 tool return.

        Inbox jobs always have ``job_id``. A team host without a job id is
        still treated as a room (hosts cannot sync-dispatch).
        """
        if not str(getattr(call, "source_thread_id", None) or "").strip():
            return False
        if getattr(call, "job_id", None):
            return True
        return is_team_agent(self._agent_manager.get_row(call.from_agent_id))

    def _member_runtime(self, call: PeerCall) -> dict[str, Any] | None:
        if not self._is_group_dispatch(call):
            return None
        extra: dict[str, Any] = {"peer_invoke_mode": "sync"}
        host = self._agent_manager.get_row(call.from_agent_id)
        if is_team_agent(host):
            extra["team_peers"] = [
                member_id
                for member_id in self._agent_manager.teams.member_ids(call.from_agent_id)
                if member_id != call.to_agent_id
            ]
        return extra

    def _jobs(self) -> Any:
        return getattr(self._agent_manager, "_team_jobs", None)

    def _track_job(self, call: PeerCall, *, begin: bool) -> None:
        host = self._agent_manager.get_row(call.from_agent_id)
        if not is_team_agent(host):
            return
        jobs = self._jobs()
        if jobs is None:
            return
        job_id = getattr(call, "job_id", None)
        if begin:
            jobs.begin(call.from_agent_id, call.to_agent_id, job_id=job_id)
        else:
            jobs.end(call.from_agent_id, call.to_agent_id, job_id=job_id)

    def _end_job_from_reply(self, event: ReplyEvent) -> None:
        jobs = self._jobs()
        if jobs is None:
            return
        source = str(event.source_agent_id or "")
        target = str(event.target_agent_id or "")
        if source and target:
            jobs.end(source, target, job_id=event.inbox_id)

    def _ensure_projection(self, thread_id: str) -> None:
        """Mark a brand-new empty peer thread ready so we can append.

        Do not flip an existing pending thread to ready — that skips checkpoint
        backfill for legacy / 1:1 history.
        """
        repo = self._thread_message_repo
        if repo is None:
            return
        try:
            status = repo.projection_status(thread_id)
        except Exception:
            return
        if status != "pending":
            return
        try:
            page = repo.page(thread_id, limit=1, offset=0)
            rows = page[0] if isinstance(page, tuple) else page
        except Exception:
            return
        if rows:
            return
        repo.mark_projection(thread_id, "ready")

    def _seed_member_user_question(
        self,
        thread_id: str | None,
        prompt: str,
        *,
        turn_id: str | None = None,
    ) -> None:
        text = (prompt or "").strip()
        if not thread_id or not text or self._thread_message_repo is None:
            return
        self._ensure_projection(thread_id)
        try:
            self._thread_message_repo.append_if_ready(
                thread_id,
                message_inputs(
                    [HumanMessage(content=text, id=_peer_user_message_id(thread_id, turn_id))],
                    dedupe_missing_ids=True,
                ),
            )
        except Exception:
            logger.warning(
                "failed to seed peer user question thread=%s",
                thread_id,
                exc_info=True,
            )

    async def _assignment_text(self, call: PeerCall) -> str:
        """Host-rewritten task; fall back to the last room user line if empty."""
        text = str(call.message or "").strip()
        if text:
            return text
        if self._is_group_dispatch(call):
            return await self._visible_user_prompt(call)
        return ""

    def _locale_for(self, user_id: int | None) -> str:
        if user_id is None:
            return DEFAULT_LOCALE
        return resolve_user_locale(user_repo=self._user_repo, user_id=user_id)

    async def _dispatch_message(self, call: PeerCall, user_id: int | None) -> str:
        locale = self._locale_for(user_id)
        transcript = await self._room_transcript(
            call.source_thread_id,
            call.from_agent_id,
            locale,
        )
        if transcript:
            return tr(
                "teams.member_briefing_with_history",
                locale,
                history=transcript,
            )
        return tr("teams.member_briefing", locale)

    async def _visible_user_prompt(self, call: PeerCall) -> str:
        last = await self._last_room_user_text(call.source_thread_id, call.from_agent_id)
        if last:
            return last
        last = self._last_projected_user_text(call.source_thread_id)
        return last or str(call.message or "").strip()

    def _last_projected_user_text(self, thread_id: str | None) -> str:
        repo = self._thread_message_repo
        if not thread_id or repo is None:
            return ""
        try:
            if repo.projection_status(thread_id) != "ready":
                return ""
            rows, _ = repo.page(thread_id, limit=_ROOM_HISTORY_LIMIT, offset=0)
        except Exception:
            return ""
        for row in reversed(rows or []):
            if str(getattr(row, "role", "")).lower() not in {"human", "user"}:
                continue
            text = _projected_row_text(row)
            if text and not _is_team_system_prompt(text):
                return text
        return ""

    async def _last_room_user_text(self, thread_id: str | None, host_id: str) -> str:
        messages = await self._history(host_id, thread_id)
        for msg in reversed(messages or []):
            if _message_role(msg) not in {"human", "user"}:
                continue
            if _message_tool_calls(msg):
                continue
            text = _assistant_text(msg)
            if text and not _is_team_system_prompt(text):
                return text
        return ""

    async def _room_transcript(
        self,
        thread_id: str | None,
        host_id: str,
        locale: str,
    ) -> str:
        projected = self._projected_transcript(thread_id, host_id, locale)
        if projected:
            return projected
        messages = await self._history(host_id, thread_id)
        lines: list[str] = []
        for msg in messages or []:
            line = self._transcript_line(msg, host_id, locale)
            if line:
                lines.append(line)
        return "\n".join(lines)

    def _projected_transcript(
        self,
        thread_id: str | None,
        host_id: str,
        locale: str,
    ) -> str:
        repo = self._thread_message_repo
        if not thread_id or repo is None:
            return ""
        try:
            if repo.projection_status(thread_id) != "ready":
                return ""
            rows, _ = repo.page(thread_id, limit=_ROOM_HISTORY_LIMIT, offset=0)
        except Exception:
            return ""
        lines: list[str] = []
        for row in rows or []:
            line = self._projected_transcript_line(row, host_id, locale)
            if line:
                lines.append(line)
        return "\n".join(lines)

    def _projected_transcript_line(self, row: Any, host_id: str, locale: str) -> str | None:
        role = str(getattr(row, "role", "")).lower()
        text = _projected_row_text(row)
        if not text or _is_team_system_prompt(text):
            return None
        if role in {"human", "user"}:
            return self._channel_line(locale, tr("teams.speaker_user", locale), text)
        if role not in {"ai", "assistant"}:
            return None
        speaker = _projected_speaker(row) or host_id
        return self._channel_line(locale, self._display_name(speaker), text)

    async def _history(self, agent_id: str, thread_id: str | None) -> list[Any]:
        if not thread_id:
            return []
        getter = getattr(self._agent_manager, "get_agent", None)
        if getter is None:
            return []
        try:
            harness = getter(agent_id)
            hist = getattr(harness, "aget_history", None)
            if hist is None:
                return []
            return list(await hist(thread_id, limit=_ROOM_HISTORY_LIMIT) or [])
        except Exception:
            logger.warning(
                "failed to read team history thread=%s agent=%s",
                thread_id,
                agent_id,
                exc_info=True,
            )
            return []

    def _transcript_line(self, msg: Any, host_id: str, locale: str) -> str | None:
        role = _message_role(msg)
        if role in {"tool", "system"}:
            return None
        if _message_tool_calls(msg):
            return None
        text = _assistant_text(msg)
        if not text:
            return None
        if role in {"human", "user"}:
            return self._channel_line(locale, tr("teams.speaker_user", locale), text)
        if role not in {"ai", "assistant"}:
            return None
        kwargs = (
            msg.get("additional_kwargs")
            if isinstance(msg, dict)
            else getattr(msg, "additional_kwargs", None)
        ) or {}
        speaker = str(kwargs.get("speaker_agent_id") or host_id)
        return self._channel_line(locale, self._display_name(speaker), text)

    def _channel_line(self, locale: str, name: str, text: str) -> str:
        return tr("teams.channel_line", locale, name=name, text=text)

    def _title_member_thread(self, call: PeerCall, thread_id: str, user_id: int) -> None:
        host = self._agent_manager.get_row(call.from_agent_id)
        if not is_team_agent(host):
            return
        locale = self._locale_for(user_id)
        title = tr(
            "teams.peer_thread_title", locale, name=host.name if host else call.from_agent_id
        )
        self._thread_registry.set_title_if_null(thread_id, title)

    def _display_name(self, agent_id: str) -> str:
        row = self._agent_manager.get_row(agent_id)
        return row.name if row is not None else agent_id[-6:]

    def _touch_thread(self, thread_id: str, title_source: str | None) -> None:
        self._thread_registry.touch_last_active(thread_id)
        if title_source:
            self._thread_registry.set_title_if_null(thread_id, title_source)

    def compose_followup(
        self,
        msg: InboxMessage,
        *,
        result_text: str | None,
        error_text: str | None,
    ) -> str:
        child_name = self._display_name(msg.target_agent_id)
        locale = self._locale_for(_octop_user_id(msg.user_id))
        if error_text:
            return tr(
                "teams.followup_failed",
                locale,
                name=child_name,
                task=msg.message,
                error=error_text,
            )
        # Member answers live on the room wall / peer checkpoint, not the host
        # graph — inject a truncated excerpt so wrap-up can follow their advice.
        result = _truncate_tool_result_text(
            (result_text or "").strip(),
            max_chars=_FOLLOWUP_RESULT_MAX_CHARS,
        )
        if not result:
            result = "(empty)"
        return tr(
            "teams.followup_done",
            locale,
            name=child_name,
            task=msg.message,
            result=result,
        )

    async def record_peer_turn(
        self,
        call: PeerCall,
        thread_id: str,
        result: dict[str, Any],
    ) -> None:
        """Write the callee page, then copy the final answer onto the room if async."""
        try:
            if not thread_id:
                return
            self._touch_thread(thread_id, call.message)
            if self._thread_message_repo is None:
                return
            messages = result.get("messages")
            msg_list = messages if isinstance(messages, list) else []
            edited = _edited_files_from_messages(msg_list)
            visible = _peer_turn_messages(msg_list)
            visible = [msg for msg in visible if _message_role(msg) not in {"human", "user"}]
            visible, _ = _apply_edited_files_stamp(visible, edited)
            prompt = await self._assignment_text(call)
            if prompt:
                visible = [
                    HumanMessage(
                        content=prompt,
                        id=_peer_user_message_id(thread_id, getattr(call, "job_id", None)),
                    ),
                    *visible,
                ]
            if not visible:
                return
            self._ensure_projection(thread_id)
            try:
                self._thread_message_repo.append_if_ready(
                    thread_id,
                    message_inputs(
                        _history_projection_messages(visible),
                        dedupe_missing_ids=True,
                    ),
                )
            except Exception:
                logger.warning(
                    "failed to append peer history projection for thread=%s",
                    thread_id,
                    exc_info=True,
                )
            await self.fan_in_peer_turn(
                call,
                messages if isinstance(messages, list) else [],
                live_streamed=bool(result.get("team_live_streamed")),
            )
        finally:
            self._track_job(call, begin=False)

    async def fan_in_peer_turn(
        self,
        call: PeerCall,
        visible: list[Any],
        *,
        live_streamed: bool = False,
    ) -> None:
        """Persist the member's tool trail + final bubble on the caller's room thread."""
        if not self._is_group_dispatch(call):
            return
        speaker = call.to_agent_id
        stamped = [_with_speaker(msg, speaker) for msg in _room_peer_messages(visible)]
        if not stamped:
            return
        edited = _edited_files_from_messages(stamped)
        stamped, final = _apply_edited_files_stamp(stamped, edited)
        if self._thread_message_repo is not None:
            try:
                self._thread_message_repo.append_if_ready(
                    call.source_thread_id,
                    live_message_inputs(
                        _history_projection_messages(stamped),
                        dedupe_missing_ids=True,
                    ),
                )
            except Exception:
                logger.warning(
                    "failed to fan-in team peer history thread=%s speaker=%s",
                    call.source_thread_id,
                    speaker,
                    exc_info=True,
                )
        room = str(call.source_thread_id or "").strip()
        text = _assistant_text(final) if final is not None else ""
        if not room or not text:
            return
        await self._push_room_to_channels(room, speaker, text)
        if not live_streamed:
            await self._push_room_snapshot(room, speaker, text)


__all__ = ["MemberDispatchMixin"]
