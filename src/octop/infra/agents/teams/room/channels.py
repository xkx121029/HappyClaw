"""Room text persistence and channel fan-out."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage

from octop.i18n import tr
from octop.infra.history.projection import (
    message_inputs,
)
from octop.infra.utils.ulid import new_ulid

if TYPE_CHECKING:
    from octop.infra.db.repos.sessions import SessionRow

from octop.infra.agents.teams.room.base import TeamRoomBase
from octop.infra.agents.teams.room.projection import (
    _with_room_turn_id,
    stamp_stream_speaker,
)

logger = logging.getLogger(__name__)


class ChannelPushMixin(TeamRoomBase):
    """Room text persistence and channel fan-out."""

    def _persist_room_assistant(
        self,
        thread_id: str,
        speaker_id: str,
        text: str,
        *,
        wrapup: bool = False,
        error: bool = False,
        decision: dict[str, Any] | None = None,
    ) -> None:
        body = (text or "").strip()
        if not thread_id or not body or self._thread_message_repo is None:
            return
        self._ensure_projection(thread_id)
        extra: dict[str, Any] = {"speaker_agent_id": speaker_id}
        if wrapup:
            extra["team_wrapup"] = True
        if error:
            extra["octop_stream_error"] = {"code": "stream_error", "source": "team_task"}
        if decision:
            extra["octop_decision"] = dict(decision)
        msg = AIMessage(
            content=body,
            id=f"team-room:{new_ulid()}:assistant",
            additional_kwargs=extra,
        )
        try:
            self._thread_message_repo.append_if_ready(
                thread_id,
                message_inputs([msg], dedupe_missing_ids=True),
            )
        except Exception:
            logger.warning(
                "failed to persist team room text thread=%s speaker=%s",
                thread_id,
                speaker_id,
                exc_info=True,
            )

    async def _push_session_channel(self, session: SessionRow, text: str) -> None:
        if self._gateway is None:
            return
        await self._gateway.push_text(
            session.channel_type,
            session.channel_id,
            session.to_channel_subject(),
            text,
        )

    async def _push_room_to_channels(
        self,
        thread_id: str,
        speaker_id: str,
        text: str,
        *,
        prefix_speaker: bool = True,
        wrapup: bool = False,
    ) -> None:
        """Push a finished room bubble to IM sessions bound to this thread.

        Dashboard / CLI already receive the room WebSocket stream. Channels only
        see the host's inbound turn unless we deliver member (and wrap-up) text
        here as a complete outbound message.
        """
        body = (text or "").strip()
        if not thread_id or not body or self._gateway is None:
            return
        for session in self._thread_registry.im_sessions_for_thread(thread_id):
            locale = self._locale_for(int(session.user_id))
            if wrapup:
                outbound = tr("teams.channel_wrapup", locale, text=body)
            elif prefix_speaker:
                outbound = self._channel_line(
                    locale,
                    self._display_name(speaker_id),
                    body,
                )
            else:
                outbound = body
            try:
                await self._push_session_channel(session, outbound)
            except Exception:
                logger.warning(
                    "failed to push team speech to channel thread=%s speaker=%s",
                    thread_id,
                    speaker_id,
                    exc_info=True,
                )

    async def _notify_channel_dispatched(
        self,
        thread_id: str,
        member_id: str,
        user_id: int | None,
    ) -> None:
        """Tell IM users a member was assigned — fills the silence before results."""
        body_thread = (thread_id or "").strip()
        if not body_thread or self._gateway is None:
            return
        name = self._display_name(member_id)
        for session in self._thread_registry.im_sessions_for_thread(body_thread):
            locale = self._locale_for(int(session.user_id))
            text = tr("teams.channel_dispatched", locale, name=name)
            try:
                await self._push_session_channel(session, text)
            except Exception:
                logger.warning(
                    "failed to push team dispatch notice thread=%s member=%s",
                    body_thread,
                    member_id,
                    exc_info=True,
                )

    async def _publish_room_text(
        self, thread_id: str, speaker_id: str, text: str, *, error: bool = False
    ) -> None:
        body = (text or "").strip()
        if not thread_id or not body:
            return
        self._persist_room_assistant(thread_id, speaker_id, body, wrapup=True, error=error)
        await self._push_room_snapshot(
            thread_id,
            speaker_id,
            body,
            wrapup=True,
            error=error,
        )

    async def _push_room_snapshot(
        self,
        thread_id: str,
        speaker_id: str,
        text: str,
        *,
        wrapup: bool = False,
        error: bool = False,
    ) -> None:
        body = (text or "").strip()
        if not thread_id or not body:
            return
        hub = getattr(self._gateway, "ws_hub", None) if self._gateway is not None else None
        if hub is None:
            return
        extra = {"team_wrapup": True} if wrapup else {"team_snapshot": True}
        turn_id = self._room_followup_turn_id(thread_id)
        try:
            await hub.push_to_thread(
                thread_id,
                _with_room_turn_id(
                    stamp_stream_speaker(
                        (
                            {"type": "error", "message": body, **extra}
                            if error
                            else {"type": "token", "content": body, **extra}
                        ),
                        speaker_id,
                    ),
                    turn_id,
                ),
            )
            await hub.push_to_thread(
                thread_id,
                _with_room_turn_id(
                    stamp_stream_speaker(
                        {"type": "done", **extra},
                        speaker_id,
                        include_done=True,
                    ),
                    turn_id,
                ),
            )
        except Exception:
            logger.warning(
                "failed to push team room stream thread=%s speaker=%s",
                thread_id,
                speaker_id,
                exc_info=True,
            )

    def _thread_is_watched(self, thread_id: str) -> bool:
        hub = getattr(self._gateway, "ws_hub", None) if self._gateway is not None else None
        checker = getattr(hub, "has_subscribers", None)
        return bool(callable(checker) and checker(thread_id))

    async def _deliver_text(
        self,
        session: SessionRow,
        session_key: str,
        text: str,
        *,
        speaker_id: str | None = None,
        error: bool = False,
    ) -> None:
        if self._thread_registry.is_im_session(session):
            await self._push_session_channel(session, text)
            return
        await self._publish_room_text(
            session.thread_id,
            speaker_id or session.agent_id,
            text,
            error=error,
        )
        if not self._thread_is_watched(session.thread_id):
            self._thread_registry.increment_unread(session_key)
        self._thread_registry.touch_last_active(session.thread_id)


__all__ = ["ChannelPushMixin"]
