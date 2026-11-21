"""Live member wall: streamed text that has not been persisted yet."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from octop.infra.agents.teams.room.base import TeamRoomBase
from octop.infra.agents.teams.room.projection import (
    _with_room_turn_id,
    stamp_stream_speaker,
)

logger = logging.getLogger(__name__)


class LiveWallMixin(TeamRoomBase):
    """Live member wall: streamed text that has not been persisted yet."""

    def _append_live_member(
        self,
        room_thread_id: str,
        speaker_id: str,
        piece: str,
        turn_id: str = "",
    ) -> None:
        room = room_thread_id.strip()
        speaker = speaker_id.strip()
        if not room or not speaker or not piece:
            return
        bucket = self._live_member_text.setdefault(room, {})
        bucket[speaker] = bucket.get(speaker, "") + piece
        if turn_id:
            self._live_member_turn[room] = turn_id

    async def _clear_live_member(self, room_thread_id: str, speaker_id: str) -> None:
        room = room_thread_id.strip()
        speaker = speaker_id.strip()
        if not room or not speaker:
            return
        async with self._member_wall_lock:
            bucket = self._live_member_text.get(room)
            if not bucket:
                return
            bucket.pop(speaker, None)
            if not bucket:
                self._live_member_text.pop(room, None)
                self._live_member_turn.pop(room, None)

    def _live_member_frames(self, room_thread_id: str) -> list[dict[str, Any]]:
        room = room_thread_id.strip()
        bucket = self._live_member_text.get(room) or {}
        frames: list[dict[str, Any]] = []
        for speaker, text in bucket.items():
            if not speaker or not text:
                continue
            frame = {
                "type": "token",
                "content": text,
                "agent_id": speaker,
                "agent": speaker,
                "team_snapshot": True,
                "team_live": True,
                "thread_id": room,
            }
            stamped = _with_room_turn_id(frame, self._live_member_turn.get(room, ""))
            frames.append(stamped)
        return frames

    async def deliver_live_member_catchup(
        self,
        room_thread_id: str,
        *,
        subscribe: Callable[[], None],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        """Subscribe, then replay member text that is on the wall but not in history.

        The lock covers subscribe and the replay so a token cannot land twice:
        once inside the snapshot and again as a live delta.
        """
        async with self._member_wall_lock:
            subscribe()
            for frame in self._live_member_frames(room_thread_id):
                await send(frame)

    async def _relay_chunk(
        self,
        chunk: dict[str, Any],
        *,
        room_thread_id: str,
        member_thread_id: str,
        speaker_id: str,
        include_room: bool = True,
        turn_id: str = "",
    ) -> None:
        hub = getattr(self._gateway, "ws_hub", None) if self._gateway is not None else None
        if hub is None:
            return
        stamped = _with_room_turn_id(
            stamp_stream_speaker(chunk, speaker_id, include_done=True),
            turn_id,
        )
        member_frame = _with_room_turn_id(chunk, turn_id)
        piece = str(chunk.get("content") or "") if str(chunk.get("type") or "") == "token" else ""
        try:
            if include_room and room_thread_id:
                async with self._member_wall_lock:
                    await hub.push_to_thread(room_thread_id, stamped)
                    if piece:
                        self._append_live_member(room_thread_id, speaker_id, piece, turn_id)
            if member_thread_id and member_thread_id != room_thread_id:
                await hub.push_to_thread(member_thread_id, member_frame)
        except Exception:
            logger.warning(
                "failed to relay team peer chunk speaker=%s room=%s",
                speaker_id,
                room_thread_id,
                exc_info=True,
            )

    async def _push_room_frame(
        self,
        chunk: dict[str, Any],
        room_thread_id: str,
        speaker_id: str,
        turn_id: str = "",
    ) -> None:
        """Push one already-delivered member frame onto the room wall."""
        hub = getattr(self._gateway, "ws_hub", None) if self._gateway is not None else None
        if hub is None or not room_thread_id:
            return
        stamped = _with_room_turn_id(
            stamp_stream_speaker(chunk, speaker_id, include_done=True),
            turn_id,
        )
        piece = str(chunk.get("content") or "") if str(chunk.get("type") or "") == "token" else ""
        try:
            async with self._member_wall_lock:
                await hub.push_to_thread(room_thread_id, stamped)
                if piece:
                    self._append_live_member(room_thread_id, speaker_id, piece, turn_id)
        except Exception:
            logger.warning(
                "failed to flush team room frame speaker=%s room=%s",
                speaker_id,
                room_thread_id,
                exc_info=True,
            )


__all__ = ["LiveWallMixin"]
