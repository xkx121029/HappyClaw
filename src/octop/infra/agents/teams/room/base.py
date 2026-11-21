"""Attribute contract shared by every team-room mixin."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from octop.infra.agents.manager import AgentManager
    from octop.infra.db.repos.users import UserRepo
    from octop.infra.gateway.threads import ThreadRegistry


class TeamRoomBase:
    """Declares the state :class:`TeamManager` owns; mixins only read it."""

    _agent_manager: AgentManager
    _thread_registry: ThreadRegistry
    _user_repo: UserRepo
    _thread_message_repo: Any | None
    _gateway: Any
    _hitl: Any
    _hitl_waiters: dict[str, asyncio.Future[list[dict[str, Any]]]]
    _peer_prompts: dict[tuple[str, str], tuple[str, str]]
    _live_host_replies: set[str]
    _live_member_text: dict[str, dict[str, str]]
    _live_member_turn: dict[str, str]
    _member_wall_lock: asyncio.Lock

    # Cross-mixin calls: the concrete implementation lives on a sibling mixin
    # of the composed TeamManager, so the contract is declared here.
    def _persist_room_assistant(
        self,
        thread_id: str,
        speaker_id: str,
        text: str,
        *,
        wrapup: bool = False,
        error: bool = False,
        decision: dict[str, Any] | None = None,
    ) -> None: ...

    async def _push_room_to_channels(
        self,
        thread_id: str,
        speaker_id: str,
        text: str,
        *,
        prefix_speaker: bool = True,
        wrapup: bool = False,
    ) -> None: ...

    async def _publish_room_text(
        self, thread_id: str, speaker_id: str, text: str, *, error: bool = False
    ) -> None: ...

    async def _push_room_snapshot(
        self,
        thread_id: str,
        speaker_id: str,
        text: str,
        *,
        wrapup: bool = False,
        error: bool = False,
    ) -> None: ...

    def _thread_is_watched(self, thread_id: str) -> bool:
        raise NotImplementedError

    async def _deliver_text(
        self,
        session: Any,
        session_key: str,
        text: str,
        *,
        speaker_id: str | None = None,
        error: bool = False,
    ) -> None: ...

    def _expire_hitl(self, pending_id: str) -> None: ...

    async def _open_member_hitl(
        self,
        chunk: dict[str, Any],
        *,
        speaker_id: str,
        member_thread_id: str,
        room_thread_id: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        raise NotImplementedError

    async def _wait_member_hitl(self, pending_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def _announce_member_hitl(
        self,
        chunk: dict[str, Any],
        room_thread_id: str,
        speaker_id: str,
    ) -> None: ...

    async def _clear_live_member(self, room_thread_id: str, speaker_id: str) -> None: ...

    async def _relay_chunk(
        self,
        chunk: dict[str, Any],
        *,
        room_thread_id: str,
        member_thread_id: str,
        speaker_id: str,
        include_room: bool = True,
        turn_id: str = "",
    ) -> None: ...

    async def _push_room_frame(
        self,
        chunk: dict[str, Any],
        room_thread_id: str,
        speaker_id: str,
        turn_id: str = "",
    ) -> None: ...

    def _defer_member_wall(self, speaker_id: str, member_tid: str, room_thread_id: str) -> bool:
        raise NotImplementedError

    def _room_agent_id(self, room_thread_id: str) -> str:
        raise NotImplementedError

    def _end_job_from_reply(self, event: Any) -> None: ...

    def _ensure_projection(self, thread_id: str) -> None: ...

    def _locale_for(self, user_id: int | None) -> str:
        raise NotImplementedError

    async def _history(self, agent_id: str, thread_id: str | None) -> list[Any]:
        raise NotImplementedError

    def _channel_line(self, locale: str, name: str, text: str) -> str:
        raise NotImplementedError

    def _display_name(self, agent_id: str) -> str:
        raise NotImplementedError

    def _room_followup_turn_id(self, room_thread_id: str) -> str:
        raise NotImplementedError


__all__ = ["TeamRoomBase"]
