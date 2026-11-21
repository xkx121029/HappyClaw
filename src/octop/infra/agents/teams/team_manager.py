"""Team room: dispatch members, relay live chunks, project history.

A team host is a wrapped expert. Members stay regular experts and are
reached with ``ask_agent``. This class owns the room side of that call:

- member tokens stay off the room wall while the host turn is still streaming
- a member tool approval pauses that job until the user answers; it is not
  a finished member turn
- history for the team page is a ``thread_messages`` row (not the host checkpoint)
- the member page uses the member's own thread / checkpoint"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from octop_harness.teams.util import (
    PeerCall,
    PeerSession,
    derive_peer_thread_id,
)

if TYPE_CHECKING:
    from octop.infra.agents.manager import AgentManager
    from octop.infra.db.repos.users import UserRepo
    from octop.infra.gateway.threads import ThreadRegistry

from octop.infra.agents.teams.room.base import TeamRoomBase
from octop.infra.agents.teams.room.channels import ChannelPushMixin
from octop.infra.agents.teams.room.hitl import MemberHitlMixin
from octop.infra.agents.teams.room.live_wall import LiveWallMixin
from octop.infra.agents.teams.room.member_dispatch import MemberDispatchMixin
from octop.infra.agents.teams.room.projection import (
    _make_peer_session,
    _octop_user_id,
    stamp_stream_speaker,
    stamp_team_host_chunk,
)
from octop.infra.agents.teams.room.turns import RoomTurnMixin
from octop.infra.agents.teams.room.wiring import (
    host_system_prompt,
    subscribe_with_member_catchup,
    wire_host_dispatch,
    wire_shared_member_peers,
)

logger = logging.getLogger(__name__)


class TeamManager(
    MemberDispatchMixin,
    LiveWallMixin,
    MemberHitlMixin,
    ChannelPushMixin,
    RoomTurnMixin,
    TeamRoomBase,
):
    """Octop-side team room. Harness still owns ``ask_agent`` / inbox."""

    def __init__(
        self,
        *,
        agent_manager: AgentManager,
        thread_registry: ThreadRegistry,
        user_repo: UserRepo,
        thread_message_repo: Any | None = None,
        gateway: Any | None = None,
        hitl_coordinator: Any | None = None,
    ) -> None:
        self._agent_manager = agent_manager
        self._thread_registry = thread_registry
        self._user_repo = user_repo
        self._thread_message_repo = thread_message_repo
        self._gateway = gateway
        self._hitl = hitl_coordinator
        self._hitl_waiters: dict[str, asyncio.Future[list[dict[str, Any]]]] = {}
        self._peer_prompts: dict[tuple[str, str], tuple[str, str]] = {}
        self._live_host_replies: set[str] = set()
        # Room text a member has already pushed and not yet persisted.
        # A refresh mid-answer has no history row; the new subscriber gets this.
        self._live_member_text: dict[str, dict[str, str]] = {}
        self._live_member_turn: dict[str, str] = {}
        self._member_wall_lock = asyncio.Lock()

    def replace_thread_message_repo(self, repo: Any) -> None:
        self._thread_message_repo = repo

    async def prepare_peer_session(self, call: PeerCall) -> PeerSession | None:
        """Open the member thread and stash the host's rewritten assignment."""
        thread_id = (
            derive_peer_thread_id(call.source_thread_id, call.to_agent_id)
            if call.source_thread_id
            else None
        )
        session_key = None
        uid = _octop_user_id(call.user_id)
        group = self._is_group_dispatch(call)
        extra = self._member_runtime(call)
        question = ""
        dispatch_message = None
        if group:
            question = await self._assignment_text(call)
            dispatch_message = await self._dispatch_message(call, uid)
            if thread_id and (question or dispatch_message):
                self.stash_peer_prompt(
                    call.to_agent_id,
                    thread_id,
                    question=question or str(dispatch_message or ""),
                    dispatch=dispatch_message or question,
                )
        # Expert-to-expert sync ask_agent also uses peer:{room} so it does not
        # reuse the callee's 1:1 DM. Existing DM peer history will not follow.
        if call.source_session_key:
            if call.source_thread_id:
                session_key = self._thread_registry.peer_room_session_key(
                    call.source_session_key,
                    call.to_agent_id,
                    room_thread_id=call.source_thread_id,
                    group=group,
                )
            else:
                session_key = self._thread_registry.peer_session_key(
                    call.source_session_key, call.to_agent_id
                )
        self._track_job(call, begin=True)
        if group and call.source_thread_id:
            await self._notify_channel_dispatched(
                str(call.source_thread_id),
                call.to_agent_id,
                uid,
            )
        if thread_id and session_key and uid is not None:
            parts = session_key.split(":", 3)
            channel_type = parts[1] if len(parts) >= 2 else "dashboard"
            self._thread_registry.ensure_thread(
                thread_id=thread_id,
                agent_id=call.to_agent_id,
                user_id=uid,
                channel_type=channel_type,
                session_key=session_key,
            )
            self._title_member_thread(call, thread_id, uid)
            if group:
                self._seed_member_user_question(
                    thread_id,
                    question or str(call.message or ""),
                    turn_id=getattr(call, "job_id", None),
                )
        return _make_peer_session(
            thread_id=thread_id,
            session_key=session_key,
            configurable=extra,
            message=question or dispatch_message,
        )


__all__ = [
    "TeamManager",
    "host_system_prompt",
    "stamp_stream_speaker",
    "stamp_team_host_chunk",
    "subscribe_with_member_catchup",
    "wire_host_dispatch",
    "wire_shared_member_peers",
]
