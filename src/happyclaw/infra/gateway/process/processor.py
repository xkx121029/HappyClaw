"""GlobalProcessor — happyclaw-gateway MessageProcessor; team room lives on TeamManager."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import (
    TYPE_CHECKING,
    Any,
)

from happyclaw_gateway.models import (
    InboundMessage,
    MessageEvent,
    MessageEventType,
    TextContent,
)
from happyclaw_harness.slash import SlashSink

from happyclaw.infra.agents.teams.team_manager import TeamManager
from happyclaw.infra.gateway.hitl.coordinator import (
    HitlAnswerOutcome,
    HitlChannelCoordinator,
    HitlStreamContext,
)
from happyclaw.infra.gateway.hitl.stream_compat import install_harness_hitl_compat
from happyclaw.infra.gateway.media.attachment_hints import (
    content_blocks_need_vision,
    inbound_attachments_from_parts,
)
from happyclaw.infra.gateway.process.agent_resolve import media_backend_for_agent
from happyclaw.infra.gateway.process.harness_request import (
    build_content_from_message,
    build_harness_request,
)
from happyclaw.infra.gateway.process.message_keys import (
    INBOUND_ATTACHMENTS_KEY,
    resolve_user_id_for_message,
    session_key_from_message,
    session_metadata_from_message,
)
from happyclaw.infra.gateway.process.processor_base import (
    _ResolvedModelRoute as _ResolvedModelRoute,
)
from happyclaw.infra.gateway.process.processor_base import (
    _ResolvedTurnMcp as _ResolvedTurnMcp,
)
from happyclaw.infra.gateway.process.processor_history import ProcessorHistoryMixin
from happyclaw.infra.gateway.process.processor_message_utils import (
    _elapsed_ms as _elapsed_ms,
)
from happyclaw.infra.gateway.process.processor_message_utils import (
    _inbound_thread_id as _inbound_thread_id,
)
from happyclaw.infra.gateway.process.processor_message_utils import (
    _overwrite_last_user_text as _overwrite_last_user_text,
)
from happyclaw.infra.gateway.process.processor_message_utils import (
    _stream_error as _stream_error,
)
from happyclaw.infra.gateway.process.processor_model_routes import ProcessorModelRouteMixin
from happyclaw.infra.gateway.process.processor_slash import ProcessorSlashMixin
from happyclaw.infra.gateway.process.processor_trajectory import ProcessorTrajectoryMixin
from happyclaw.infra.gateway.process.processor_turn_config import ProcessorTurnConfigMixin
from happyclaw.infra.gateway.process.processor_turn_stream import ProcessorTurnStreamMixin
from happyclaw.infra.gateway.process.stream_project import (
    StreamProjectionState,
    project_stream,
)
from happyclaw.infra.gateway.process.usage_record import UsageTracker
from happyclaw.infra.gateway.slash.catalog import HITL_APPROVAL_COMMANDS
from happyclaw.infra.gateway.slash.parser import parse_slash
from happyclaw.infra.history.projection import TurnHistoryTracker
from happyclaw.infra.utils.locale import resolve_user_locale
from happyclaw.infra.utils.turn_failure import log_turn_failure

if TYPE_CHECKING:
    from happyclaw.infra.agents.manager import AgentManager
    from happyclaw.infra.db.repos.agents import AgentRepo
    from happyclaw.infra.db.repos.audit import AuditRepo
    from happyclaw.infra.db.repos.connectors import ConnectorRepo
    from happyclaw.infra.db.repos.users import UserRepo
    from happyclaw.infra.gateway.slash.dispatcher import SlashDispatcher
    from happyclaw.infra.gateway.threads import ThreadRegistry

install_harness_hitl_compat()


class _MessageEventSink(SlashSink):
    def __init__(self) -> None:
        self.events: list[MessageEvent] = []

    async def text(self, line: str) -> None:
        self.events.append(
            MessageEvent(type=MessageEventType.MESSAGE, content=[TextContent(text=line)])
        )

    async def complete(self) -> None:
        pass


class GlobalProcessor(
    ProcessorTrajectoryMixin,
    ProcessorSlashMixin,
    ProcessorModelRouteMixin,
    ProcessorTurnStreamMixin,
    ProcessorTurnConfigMixin,
    ProcessorHistoryMixin,
):
    """Routes InboundMessages by ``tenant_id`` to the correct HarnessAgent."""

    def __init__(
        self,
        *,
        agent_manager: AgentManager,
        thread_registry: ThreadRegistry,
        audit_repo: AuditRepo,
        agent_repo: AgentRepo,
        user_repo: UserRepo,
        connector_repo: ConnectorRepo,
        knowledge_repo: Any | None = None,
        settings_repo: Any | None = None,
        provider_repo: Any | None = None,
        dispatcher: SlashDispatcher,
        usage_repo: Any | None = None,
        thread_message_repo: Any | None = None,
        gateway: Any | None = None,
        hitl: HitlChannelCoordinator | None = None,
        trajectory_service: Any | None = None,
    ) -> None:
        self._agent_manager = agent_manager
        self._thread_registry = thread_registry
        self._audit_repo = audit_repo
        self._agent_repo = agent_repo
        self._user_repo = user_repo
        self._connector_repo = connector_repo
        self._knowledge_services = (
            SimpleNamespace(
                knowledge_repo=knowledge_repo,
                settings_repo=settings_repo,
                provider_repo=provider_repo,
            )
            if knowledge_repo is not None and settings_repo is not None
            else None
        )
        self._dispatcher = dispatcher
        self._usage_repo = usage_repo
        self._thread_message_repo = thread_message_repo
        self._gateway = gateway
        self._hitl = hitl or HitlChannelCoordinator()
        self._trajectory_service = trajectory_service
        self._title_inflight: set[str] = set()
        self._pending_system_prompt: set[str] = set()
        self.teams = TeamManager(
            agent_manager=agent_manager,
            thread_registry=thread_registry,
            user_repo=user_repo,
            thread_message_repo=thread_message_repo,
            gateway=gateway,
            hitl_coordinator=self._hitl,
        )

    async def _complete_resumed_history(
        self, thread_id: str, tracker: TurnHistoryTracker, *, completed: bool
    ) -> None:
        if completed:
            await self._record_turn_history(thread_id, tracker)

    @property
    def hitl_coordinator(self) -> HitlChannelCoordinator:
        return self._hitl

    def replace_thread_message_repo(self, repo: Any) -> None:
        """Rebind projection writes after a control-plane restore."""
        self._thread_message_repo = repo
        self.teams.replace_thread_message_repo(repo)

    async def __call__(self, msg: InboundMessage) -> AsyncIterator[MessageEvent]:
        from happyclaw.infra.metrics import METRICS  # noqa: PLC0415

        METRICS.inc("messages_total")

        agent_id = msg.tenant_id or ""
        if not agent_id:
            yield MessageEvent.error_event("No agent (tenant_id) specified")
            yield MessageEvent.completed()
            return

        agent_row = self._agent_repo.get(agent_id)
        user_id = resolve_user_id_for_message(
            msg,
            agent_owner_id=agent_row.user_id if agent_row is not None else None,
        )
        session_key = session_key_from_message(msg, agent_id=agent_id)
        channel_type = msg.channel_type or "unknown"
        im_meta = session_metadata_from_message(msg)

        cmd = parse_slash(msg.text)
        locale = resolve_user_locale(
            user_repo=self._user_repo,
            user_id=user_id,
            channel_type=channel_type,
            metadata=msg.metadata,
        )
        if cmd is not None and cmd.name in HITL_APPROVAL_COMMANDS:
            async for ev in self._relay_im_approval(
                msg,
                agent_id=agent_id,
                user_id=user_id,
                channel_type=channel_type,
                session_key=session_key,
                locale=locale,
                command=cmd,
            ):
                yield ev
            yield MessageEvent.completed()
            return

        # An open ``ask_user_question`` pause turns the user's next message into
        # the answer for that paused turn instead of starting a new one.
        if cmd is None and msg.text.strip():
            ask_record = self._hitl.resolve_ask_pending(
                session_key,
                agent_id=agent_id,
                user_id=user_id,
                thread_id=_inbound_thread_id(msg),
            )
            if ask_record is not None:
                usage_tracker = UsageTracker()
                history_tracker = TurnHistoryTracker.from_request({})
                answer_outcome = HitlAnswerOutcome()
                async for ev in self._hitl.iter_answer_resolution(
                    ask_record,
                    msg.text,
                    agent_manager=self._agent_manager,
                    locale=locale,
                    usage_tracker=usage_tracker,
                    history_tracker=history_tracker,
                    outcome=answer_outcome,
                    member_hitl=self.teams.deliver_member_hitl,
                ):
                    yield ev
                if answer_outcome.completed_turn:
                    self._touch_thread_after_turn(ask_record.thread_id, msg.text)
                    if usage_tracker.usage:
                        self._record_turn_usage(
                            agent_id=agent_id,
                            user_id=user_id,
                            thread_id=ask_record.thread_id,
                            usage=usage_tracker.usage,
                        )
                    await self._record_turn_history(ask_record.thread_id, history_tracker)
                yield MessageEvent.completed()
                return

            phrase = self._phrase_to_apply(
                msg.text,
                session_key=session_key,
                agent_id=agent_id,
                user_id=user_id,
            )
            if phrase is not None:
                async for ev in self._iter_applied_phrase(
                    msg,
                    phrase=phrase,
                    agent_id=agent_id,
                    user_id=user_id,
                    channel_type=channel_type,
                    session_key=session_key,
                    locale=locale,
                ):
                    yield ev
                yield MessageEvent.completed()
                return

        if cmd is not None:
            sink = _MessageEventSink()
            handled = await self._dispatcher.handle(
                cmd,
                self._slash_ctx(
                    agent_id=agent_id,
                    user_id=user_id,
                    channel_type=channel_type,
                    session_key=session_key,
                    metadata=msg.metadata,
                ),
                sink,
            )
            for ev in sink.events:
                yield ev
            if handled:
                yield MessageEvent.completed()
                return

        thread_id = await self._thread_registry.get_or_create_by_key(
            session_key=session_key,
            agent_id=agent_id,
            user_id=user_id,
            channel_type=channel_type,
            channel_channel_id=msg.channel_id or None,
            channel_metadata=im_meta,
        )
        self._schedule_auto_thread_title(thread_id, msg.text, user_id=user_id)

        media_backend = media_backend_for_agent(self._agent_manager, agent_id)
        content = await build_content_from_message(
            msg,
            media_backend=media_backend,
            locale=locale,
        )
        model_route = self._resolve_harness_model_route(
            agent_id,
            thread_id,
            None,
            user_id=user_id,
            needs_multimodal=content_blocks_need_vision(content),
        )
        model_ref = model_route.model_ref
        reasoning_overrides = self._resolve_reasoning_overrides(
            user_id=user_id,
            thread_id=thread_id,
            model_ref=model_ref,
            meta=None,
        )
        resolved_mcp = await self._resolve_turn_mcp_servers(
            agent_id=agent_id,
            user_id=user_id,
            explicit=None,
            apply_defaults=True,
            raise_on_failure=False,
        )
        mcp_servers = resolved_mcp.harness if resolved_mcp is not None else None
        shown_mcp = resolved_mcp.shown if resolved_mcp is not None else None
        message_kwargs: dict[str, Any] = {}
        attachments = inbound_attachments_from_parts(msg.content)
        if attachments:
            message_kwargs[INBOUND_ATTACHMENTS_KEY] = attachments
        if mcp_servers:
            from happyclaw.infra.gateway.process.message_keys import (  # noqa: PLC0415
                COMPOSER_CTX_KEY,
                build_composer_context,
            )

            row = self._agent_repo.get(agent_id)
            default_model = (row.default_model if row is not None else None) or None
            composer = build_composer_context(
                mcp_servers=shown_mcp,
                skills=None,
                target_agent_ids=None,
                model_ref=model_ref,
                default_model=default_model,
            )
            if composer:
                message_kwargs[COMPOSER_CTX_KEY] = composer
        request = build_harness_request(
            thread_id=thread_id,
            user_id=user_id,
            agent_id=agent_id,
            session_key=session_key,
            source=f"{msg.channel_type}/{msg.channel_id}",
            content=content,
            model=model_ref,
            auto_route=model_route.automatic,
            message_kwargs=message_kwargs or None,
            reasoning_overrides=reasoning_overrides,
        )
        self.teams.stamp_host_runtime(request, agent_id)
        self._attach_turn_knowledge_config(
            request,
            user_id=user_id,
            is_admin=False,
            explicit_ids=None,
            locale=locale,
            agent_id=agent_id,
        )
        request = self._stamp_turn_conversation_mode(
            request,
            agent_id=agent_id,
            thread_id=thread_id,
            meta=None,
            user_text=msg.text,
            mcp_servers=mcp_servers,
            locale=locale,
        )

        yield MessageEvent.typing()
        turn_started = time.perf_counter()
        stream_ok = False
        hitl_paused = False
        failure_saved = False
        usage_tracker = UsageTracker()
        history_tracker = TurnHistoryTracker.from_request(request)
        projection_state = StreamProjectionState()
        try:
            async for ev in project_stream(
                self._agent_manager,
                agent_id,
                request,
                media_backend=media_backend,
                usage_tracker=usage_tracker,
                history_tracker=history_tracker,
                locale=locale,
                projection_state=projection_state,
                hitl_coordinator=self._hitl,
                hitl_ctx=HitlStreamContext(
                    thread_id=thread_id,
                    agent_id=agent_id,
                    user_id=user_id,
                    session_key=session_key,
                    channel_type=channel_type,
                ),
            ):
                yield ev
            stream_ok = True
            hitl_paused = projection_state.hitl_paused
        except Exception as exc:
            await self._record_stream_error(
                user_id=user_id, agent_id=agent_id, thread_id=thread_id, exc=exc
            )
            message, error_code = _stream_error(exc, locale)
            if error_code:
                message = f"[{error_code}] {message}"
            history_tracker.observe(
                {
                    "type": "error",
                    "message": message,
                    **({"error_code": error_code} if error_code else {}),
                }
            )
            await self._persist_incomplete_turn(thread_id, history_tracker, title_source=msg.text)
            failure_saved = True
            yield MessageEvent.error_event(message)
        else:
            if stream_ok and not hitl_paused:
                history_tracker.note_turn_duration(_elapsed_ms(turn_started))
                self._touch_thread_after_turn(thread_id, msg.text)
                self._record_turn_usage(
                    agent_id=agent_id,
                    user_id=user_id,
                    thread_id=thread_id,
                    usage=usage_tracker.usage,
                )
                await self._record_turn_history(thread_id, history_tracker)
                hint = self._plan_ready_hint(thread_id, locale)
                if hint:
                    yield MessageEvent(
                        type=MessageEventType.MESSAGE,
                        content=[TextContent(text=hint)],
                    )
        finally:
            if not failure_saved and (not stream_ok and not hitl_paused):
                await self._persist_incomplete_turn(
                    thread_id, history_tracker, title_source=msg.text
                )
        yield MessageEvent.completed()

    def cancel_agent_stream(self, agent_id: str, thread_id: str) -> None:
        """Signal the harness to stop the active stream (mid-turn steer preemption).

        The stream iterator ends cleanly (no error chunk); state stays at the
        last completed superstep checkpoint.
        """
        if self._agent_manager is not None:
            self._agent_manager.cancel_stream(agent_id, thread_id)

    # -- Raw harness-chunk stream (Dashboard WS, etc.) -------------------------
    # IM channels (DingTalk, Feishu, …) stream via __call__ → MessageEvent instead.

    def _done_chunk(self, thread_id: str, *, duration_ms: int | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": "done"}
        if duration_ms is not None and duration_ms >= 0:
            payload["duration_ms"] = duration_ms
        thread = self._thread_registry.get_thread(thread_id)
        if thread is None:
            return payload
        if thread.conversation_mode:
            payload["conversation_mode"] = thread.conversation_mode
        if thread.pending_plan_path:
            payload["pending_plan_path"] = thread.pending_plan_path
        return payload

    def _plan_ready_hint(self, thread_id: str, locale: str) -> str:
        from happyclaw.i18n import tr
        from happyclaw.infra.agents.conversation_mode import parse_conversation_mode

        thread = self._thread_registry.get_thread(thread_id)
        if thread is None:
            return ""
        if parse_conversation_mode(thread.conversation_mode) != "plan":
            return ""
        path = (thread.pending_plan_path or "").strip()
        if not path:
            return ""
        return tr("conversation_mode.plan_ready", locale, path=path)

    async def _record_stream_error(
        self,
        *,
        user_id: int,
        agent_id: str,
        exc: Exception,
        thread_id: str = "",
    ) -> None:
        from happyclaw.infra.metrics import METRICS as _M  # noqa: PLC0415

        _M.inc("stream_errors_total")
        log_turn_failure(
            "stream",
            detail=str(exc),
            agent_id=agent_id,
            thread_id=thread_id,
            exc=exc,
            level=logging.ERROR,
        )
        user_row = self._user_repo.get(user_id)
        actor = user_row.username if user_row else str(user_id)
        self._audit_repo.write(
            actor=actor,
            action="agent.stream.error",
            target=agent_id,
            payload=str(exc),
        )
