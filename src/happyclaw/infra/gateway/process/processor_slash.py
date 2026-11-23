"""Slash commands, IM approvals and peer room turns handled before the model call."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

from happyclaw_gateway.models import (
    InboundMessage,
    MessageEvent,
)
from happyclaw_harness.slash import SlashCommand
from happyclaw_harness.teams.inbox import InboxMessage
from happyclaw_harness.teams.processor import ReplyEvent
from happyclaw_harness.teams.util import (
    PeerCall,
    PeerSession,
)

from happyclaw.infra.gateway.hitl.coordinator import HitlSlashOutcome
from happyclaw.infra.gateway.hitl.phrases import (
    ApprovalUtterance,
    match_approval_utterance,
)
from happyclaw.infra.gateway.process.message_keys import session_metadata_from_message
from happyclaw.infra.gateway.process.processor_base import GlobalProcessorBase
from happyclaw.infra.gateway.process.processor_message_utils import _elapsed_ms
from happyclaw.infra.gateway.process.usage_record import UsageTracker
from happyclaw.infra.gateway.slash.ctx import (
    SlashCtx,
    build_slash_ctx,
)
from happyclaw.infra.history.projection import TurnHistoryTracker


class ProcessorSlashMixin(GlobalProcessorBase):
    """模型调用前的斜杠命令、IM 审批与 peer 房间回合。"""

    async def prepare_peer_session(self, call: PeerCall) -> PeerSession | None:
        return await self.teams.prepare_peer_session(call)

    async def record_peer_turn(
        self,
        call: PeerCall,
        thread_id: str,
        result: dict[str, Any],
    ) -> None:
        await self.teams.record_peer_turn(call, thread_id, result)

    def compose_followup(
        self,
        msg: InboxMessage,
        *,
        result_text: str | None,
        error_text: str | None,
    ) -> str:
        return self.teams.compose_followup(msg, result_text=result_text, error_text=error_text)

    async def on_reply(self, event: ReplyEvent) -> None:
        await self.teams.on_reply(event)

    def _slash_ctx(
        self,
        *,
        agent_id: str,
        user_id: int,
        channel_type: str,
        session_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> SlashCtx:
        return build_slash_ctx(
            gateway=self._gateway,
            thread_registry=self._thread_registry,
            agent_repo=self._agent_repo,
            connector_repo=self._connector_repo,
            user_repo=self._user_repo,
            agent_manager=self._agent_manager,
            usage_repo=self._usage_repo,
            agent_id=agent_id,
            user_id=user_id,
            channel_type=channel_type,
            session_key=session_key,
            metadata=metadata,
            paths=self._agent_manager.paths,
            default_timezone=self._agent_manager.octop_config.default_timezone,
        )

    async def _relay_im_approval(
        self,
        msg: InboundMessage,
        *,
        agent_id: str,
        user_id: int,
        channel_type: str,
        session_key: str,
        locale: str,
        command: SlashCommand | None = None,
        utterance: ApprovalUtterance | None = None,
    ) -> AsyncIterator[MessageEvent]:
        """Run an IM approval and bookkeep the resumed turn."""
        usage_tracker = UsageTracker()
        slash_outcome = HitlSlashOutcome()
        turn_started = time.perf_counter()

        async def _finalize(
            thread_id: str, tracker: TurnHistoryTracker, *, completed: bool
        ) -> None:
            if completed:
                tracker.note_turn_duration(_elapsed_ms(turn_started))
            await self._complete_resumed_history(thread_id, tracker, completed=completed)

        ctx = self._slash_ctx(
            agent_id=agent_id,
            user_id=user_id,
            channel_type=channel_type,
            session_key=session_key,
            metadata=msg.metadata,
        )
        if command is not None:
            stream = self._hitl.iter_slash_resolution(
                command,
                ctx,
                agent_manager=self._agent_manager,
                locale=locale,
                usage_tracker=usage_tracker,
                outcome=slash_outcome,
                history_finalize=_finalize,
                member_hitl=self.teams.deliver_member_hitl,
            )
        else:
            assert utterance is not None
            stream = self._hitl.iter_utterance_resolution(
                utterance,
                ctx,
                agent_manager=self._agent_manager,
                locale=locale,
                usage_tracker=usage_tracker,
                outcome=slash_outcome,
                history_finalize=_finalize,
                member_hitl=self.teams.deliver_member_hitl,
            )
        async for ev in stream:
            yield ev
        if not slash_outcome.completed_turn:
            return
        thread_id = self._thread_registry.get_bound_thread_id(session_key)
        if thread_id is None:
            thread_id = await self._thread_registry.get_or_create_by_key(
                session_key=session_key,
                agent_id=agent_id,
                user_id=user_id,
                channel_type=channel_type,
                channel_channel_id=msg.channel_id or None,
                channel_metadata=session_metadata_from_message(msg),
            )
        if thread_id:
            self._touch_thread_after_turn(thread_id, msg.text)
            if usage_tracker.usage:
                self._record_turn_usage(
                    agent_id=agent_id,
                    user_id=user_id,
                    thread_id=thread_id,
                    usage=usage_tracker.usage,
                )

    def _phrase_to_apply(
        self,
        text: str | None,
        *,
        session_key: str,
        agent_id: str,
        user_id: int,
    ) -> ApprovalUtterance | None:
        """Whole-message approval reply, or a reset while a bypass is active."""
        utterance = match_approval_utterance(text)
        if utterance is None:
            return None
        pending = self._hitl.owned_tool_approval(
            session_key,
            agent_id=agent_id,
            user_id=user_id,
        )
        if utterance.kind == "reset":
            if pending is not None:
                return utterance
            bound = self._thread_registry.get_bound_thread_id(session_key)
            if not isinstance(bound, str) or not bound.strip():
                return None
            if self._hitl.session_policies.get(bound).mode == "ask":
                return None
            return utterance
        if pending is None:
            return None
        return utterance

    def _reset_thread_ids(
        self,
        *,
        session_key: str,
        agent_id: str,
        user_id: int,
    ) -> tuple[list[str], bool]:
        record = self._hitl.owned_tool_approval(
            session_key,
            agent_id=agent_id,
            user_id=user_id,
        )
        thread_ids: list[str] = []
        if record is not None:
            for thread_id in (record.thread_id, record.resume_thread_id):
                if isinstance(thread_id, str) and thread_id.strip() and thread_id not in thread_ids:
                    thread_ids.append(thread_id.strip())
        bound = self._thread_registry.get_bound_thread_id(session_key)
        if isinstance(bound, str) and bound.strip() and bound not in thread_ids:
            thread_ids.append(bound.strip())
        return thread_ids, record is not None

    async def _iter_applied_phrase(
        self,
        msg: InboundMessage,
        *,
        phrase: ApprovalUtterance,
        agent_id: str,
        user_id: int,
        channel_type: str,
        session_key: str,
        locale: str,
    ) -> AsyncIterator[MessageEvent]:
        if phrase.kind == "reset":
            thread_ids, pending = self._reset_thread_ids(
                session_key=session_key,
                agent_id=agent_id,
                user_id=user_id,
            )
            self._hitl.clear_bypass(thread_ids)
            async for ev in self._hitl.iter_reset_notice(locale=locale, pending=pending):
                yield ev
            return
        async for ev in self._relay_im_approval(
            msg,
            agent_id=agent_id,
            user_id=user_id,
            channel_type=channel_type,
            session_key=session_key,
            locale=locale,
            utterance=phrase,
        ):
            yield ev
