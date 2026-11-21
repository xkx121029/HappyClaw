"""Member tool-approval pauses mirrored into the room."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from octop.infra.agents.teams.room.base import TeamRoomBase
from octop.infra.agents.teams.room.constants import (
    _MEMBER_HITL_WAIT_SEC,
)
from octop.infra.agents.teams.room.projection import (
    _octop_user_id,
)

logger = logging.getLogger(__name__)


class MemberHitlMixin(TeamRoomBase):
    """Member tool-approval pauses mirrored into the room."""

    def deliver_member_hitl(self, pending_id: str, decisions: list[dict[str, Any]]) -> bool:
        """Hand an approval to the member job that is paused on this card.

        The waiting job resumes the member graph. Callers must not also resume
        the host room thread.
        """
        fut = self._hitl_waiters.get(str(pending_id))
        if fut is None or fut.done():
            return False
        fut.set_result([dict(item) for item in decisions if isinstance(item, dict)])
        return True

    def cancel_member_hitl(self, thread_id: str) -> None:
        """Fail member pauses bound to a thread when that turn is replaced."""
        room = thread_id.strip()
        if not room:
            return
        store = getattr(self._hitl, "store", None)
        records = getattr(store, "_records", None)
        if not isinstance(records, dict):
            return
        for record in list(records.values()):
            bound = str(getattr(record, "thread_id", "") or "")
            resume_thread = str(getattr(record, "resume_thread_id", "") or "")
            if bound != room and resume_thread != room:
                continue
            pending_id = str(getattr(record, "pending_id", "") or "")
            fut = self._hitl_waiters.get(pending_id)
            if fut is None or fut.done():
                continue
            fut.set_exception(TimeoutError("team member approval was cancelled"))

    def _expire_hitl(self, pending_id: str) -> None:
        store = getattr(self._hitl, "store", None)
        mark = getattr(store, "mark_resolved", None)
        if callable(mark):
            mark(pending_id, "expired")

    def _room_hitl_view(
        self, room_thread_id: str, payload: dict[str, Any]
    ) -> tuple[str, int, str, str]:
        getter = getattr(self._thread_registry, "get_thread", None)
        row = getter(room_thread_id) if callable(getter) and room_thread_id else None
        host_id = str(getattr(row, "agent_id", "") or "")
        user_id = int(getattr(row, "user_id", 0) or 0)
        session_key = str(getattr(row, "session_key", "") or "")
        channel = str(getattr(row, "channel_type", "") or "") or "dashboard"
        if user_id <= 0:
            raw_user = payload.get("user")
            if isinstance(raw_user, (int, str)):
                user_id = _octop_user_id(raw_user) or 0
        if not session_key and host_id and user_id > 0:
            session_key = f"{host_id}:{channel}:{user_id}:dm"
        return host_id, user_id, session_key, channel

    async def _open_member_hitl(
        self,
        chunk: dict[str, Any],
        *,
        speaker_id: str,
        member_thread_id: str,
        room_thread_id: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        """Register the room card and arm the waiter before the card is shown."""
        from octop.infra.gateway.hitl.coordinator import HitlStreamContext  # noqa: PLC0415
        from octop.infra.gateway.hitl.format import normalize_hitl_request  # noqa: PLC0415

        coordinator = self._hitl
        if coordinator is None or not hasattr(coordinator, "register_from_request"):
            raise RuntimeError("team member approval has no HITL coordinator")
        host_id, user_id, session_key, channel = self._room_hitl_view(room_thread_id, payload)
        if not host_id or user_id <= 0 or not room_thread_id:
            raise RuntimeError("team member approval is missing its room")
        request = normalize_hitl_request(chunk.get("request"))
        record = coordinator.register_from_request(
            request,
            ctx=HitlStreamContext(
                thread_id=room_thread_id,
                agent_id=host_id,
                user_id=user_id,
                session_key=session_key,
                channel_type=channel,
            ),
            resume_agent_id=speaker_id,
        )
        if not record.action_requests:
            self._expire_hitl(record.pending_id)
            raise RuntimeError("team member paused without an approval request")
        record.resume_agent_id = speaker_id
        record.resume_thread_id = member_thread_id
        loop = asyncio.get_running_loop()
        self._hitl_waiters[record.pending_id] = loop.create_future()
        request = dict(request)
        request["pending_id"] = record.pending_id
        return (
            {**chunk, "request": request, "pending_id": record.pending_id},
            record.pending_id,
        )

    async def _wait_member_hitl(self, pending_id: str) -> list[dict[str, Any]]:
        fut = self._hitl_waiters.get(pending_id)
        if fut is None:
            raise TimeoutError("team member approval is not waiting")
        try:
            return await asyncio.wait_for(fut, _MEMBER_HITL_WAIT_SEC)
        except TimeoutError:
            logger.warning("team member approval timed out pending=%s", pending_id)
            self._expire_hitl(pending_id)
            raise
        finally:
            current = self._hitl_waiters.get(pending_id)
            if current is fut:
                self._hitl_waiters.pop(pending_id, None)

    async def _announce_member_hitl(
        self,
        chunk: dict[str, Any],
        room_thread_id: str,
        speaker_id: str,
    ) -> None:
        request = chunk.get("request")
        if not isinstance(request, dict):
            return
        pending_id = str(chunk.get("pending_id") or request.get("pending_id") or "")
        actions = request.get("action_requests")
        if not pending_id or not isinstance(actions, list) or not actions:
            return
        from octop.infra.gateway.hitl.format import format_hitl_card  # noqa: PLC0415

        _host_id, user_id, _session_key, _channel = self._room_hitl_view(room_thread_id, {})
        card = format_hitl_card(
            actions,
            pending_id=pending_id,
            locale=self._locale_for(user_id or None),
        )
        await self._push_room_to_channels(room_thread_id, speaker_id, card)


__all__ = ["MemberHitlMixin"]
