"""Streaming a turn: harness request build, chunk projection and HITL resume."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

from happyclaw_gateway.models import InboundMessage

from happyclaw.infra.agents.teams import is_team_agent
from happyclaw.infra.agents.teams.team_manager import (
    stamp_team_host_chunk as _maybe_stamp_team_host,
)
from happyclaw.infra.gateway.cli.events import message_event_to_cli_chunks
from happyclaw.infra.gateway.hitl.coordinator import (
    HitlAnswerOutcome,
    HitlSlashOutcome,
    iter_with_session_auto_approve,
)
from happyclaw.infra.gateway.hitl.format import normalize_hitl_request
from happyclaw.infra.gateway.media.attachment_hints import (
    content_blocks_need_vision,
    inbound_attachments_from_parts,
)
from happyclaw.infra.gateway.media.tool_media import (
    enrich_tool_result_for_dashboard,
    enrich_tool_result_with_backend,
    iter_dashboard_attachment_frames,
    note_live_tool_call,
)
from happyclaw.infra.gateway.process.agent_resolve import (
    harness_workspace_for_agent,
    media_backend_for_agent,
)
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
from happyclaw.infra.gateway.process.processor_base import GlobalProcessorBase
from happyclaw.infra.gateway.process.processor_message_utils import (
    _elapsed_ms,
    _inbound_thread_id,
    _stream_error,
)
from happyclaw.infra.gateway.process.stream_project import enrich_tool_stream_chunk
from happyclaw.infra.gateway.process.usage_record import UsageTracker
from happyclaw.infra.gateway.slash.catalog import HITL_APPROVAL_COMMANDS
from happyclaw.infra.gateway.slash.parser import parse_slash
from happyclaw.infra.gateway.slash.runner import try_handle_slash
from happyclaw.infra.history.projection import TurnHistoryTracker
from happyclaw.infra.utils.locale import resolve_user_locale
from happyclaw.infra.utils.turn_failure import log_failed_tool_results


class ProcessorTurnStreamMixin(GlobalProcessorBase):
    """回合流式输出：harness 请求构建、chunk 投影与 HITL 恢复流。"""

    async def iter_turn_chunks(self, msg: InboundMessage) -> AsyncIterator[dict[str, Any]]:
        """Run one agent turn and yield harness-native stream chunks.

        For transports that consume the dashboard chunk protocol (``token``,
        ``tool_result``, ``attachment``, ``done``, …) without going through
        happyclaw-gateway :class:`MessageEvent` batching.

        IM channels use :meth:`__call__` → ``project_stream`` → ``MessageEvent``
        (e.g. DingTalk ``BaseChannel.handle_inbound``).
        """
        from happyclaw.infra.metrics import METRICS  # noqa: PLC0415

        METRICS.inc("messages_total")

        agent_id = msg.tenant_id or ""
        if not agent_id:
            yield {"type": "error", "message": "No agent (tenant_id) specified"}
            yield {"type": "done"}
            return

        agent_row = self._agent_repo.get(agent_id)
        team_host = is_team_agent(agent_row)
        traj_on = self._agent_trajectory_enabled(agent_id, agent_row)
        user_id = resolve_user_id_for_message(
            msg,
            agent_owner_id=agent_row.user_id if agent_row is not None else None,
        )
        session_key = session_key_from_message(msg, agent_id=agent_id)
        channel_type = msg.channel_type or "unknown"
        im_meta = session_metadata_from_message(msg)
        meta = msg.metadata or {}
        locale = resolve_user_locale(
            user_repo=self._user_repo,
            user_id=user_id,
            channel_type=channel_type,
            metadata=meta,
        )
        cmd = parse_slash(msg.text)
        if cmd is not None and cmd.name in HITL_APPROVAL_COMMANDS:
            usage_tracker = UsageTracker()
            slash_outcome = HitlSlashOutcome()
            async for ev in self._hitl.iter_slash_resolution(
                cmd,
                self._slash_ctx(
                    agent_id=agent_id,
                    user_id=user_id,
                    channel_type=channel_type,
                    session_key=session_key,
                    metadata=meta,
                ),
                agent_manager=self._agent_manager,
                locale=locale,
                usage_tracker=usage_tracker,
                outcome=slash_outcome,
                history_finalize=self._complete_resumed_history,
                member_hitl=self.teams.deliver_member_hitl,
            ):
                for frame in message_event_to_cli_chunks(ev):
                    yield _maybe_stamp_team_host(frame, agent_id, team_host)
            thread_id = self._thread_registry.get_bound_thread_id(session_key)
            if thread_id is None:
                thread_id = await self._thread_registry.get_or_create_by_key(
                    session_key=session_key,
                    agent_id=agent_id,
                    user_id=user_id,
                    channel_type=channel_type,
                    channel_channel_id=msg.channel_id or None,
                    channel_metadata=im_meta,
                )
            if slash_outcome.completed_turn and thread_id:
                self._touch_thread_after_turn(thread_id, msg.text)
                if usage_tracker.usage:
                    self._record_turn_usage(
                        agent_id=agent_id,
                        user_id=user_id,
                        thread_id=thread_id,
                        usage=usage_tracker.usage,
                    )
            yield _maybe_stamp_team_host(
                self._done_chunk(thread_id) if thread_id else {"type": "done"},
                agent_id,
                team_host,
            )
            return

        if cmd is None and bool(msg.text and msg.text.strip()):
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
                    for frame in message_event_to_cli_chunks(ev):
                        yield _maybe_stamp_team_host(frame, agent_id, team_host)
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
                yield _maybe_stamp_team_host(
                    self._done_chunk(ask_record.thread_id),
                    agent_id,
                    team_host,
                )
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
                    for frame in message_event_to_cli_chunks(ev):
                        yield _maybe_stamp_team_host(frame, agent_id, team_host)
                bound = self._thread_registry.get_bound_thread_id(session_key)
                done = (
                    self._done_chunk(bound)
                    if isinstance(bound, str) and bound.strip()
                    else {"type": "done"}
                )
                yield _maybe_stamp_team_host(done, agent_id, team_host)
                return

        handled, slash_lines, slash_actions = await try_handle_slash(
            msg.text,
            dispatcher=self._dispatcher,
            ctx=self._slash_ctx(
                agent_id=agent_id,
                user_id=user_id,
                channel_type=channel_type,
                session_key=session_key,
                metadata=meta,
            ),
        )
        if handled:
            thread_id = meta.get("thread_id")
            if not isinstance(thread_id, str) or not thread_id.strip():
                thread_id = await self._thread_registry.get_or_create_by_key(
                    session_key=session_key,
                    agent_id=agent_id,
                    user_id=user_id,
                    channel_type=channel_type,
                    channel_channel_id=msg.channel_id or None,
                    channel_metadata=im_meta,
                )
            await self._append_slash_checkpoint(
                agent_id=agent_id,
                thread_id=thread_id,
                command=msg.text,
                response_lines=slash_lines,
                user_id=user_id,
            )
            self._hitl.expire_pending_for_thread(thread_id, agent_id=agent_id, user_id=user_id)
            self.teams.cancel_member_hitl(thread_id)
            self._touch_thread_after_turn(thread_id, msg.text)
            for line in slash_lines:
                yield _maybe_stamp_team_host(
                    {"type": "token", "content": f"{line}\n"},
                    agent_id,
                    team_host,
                )
            for action in slash_actions:
                yield _maybe_stamp_team_host(
                    {"type": "slash_action", **action},
                    agent_id,
                    team_host,
                )
            yield _maybe_stamp_team_host({"type": "done"}, agent_id, team_host)
            return

        thread_id = meta.get("thread_id")
        if not isinstance(thread_id, str) or not thread_id.strip():
            thread_id = await self._thread_registry.get_or_create_by_key(
                session_key=session_key,
                agent_id=agent_id,
                user_id=user_id,
                channel_type=channel_type,
                channel_channel_id=msg.channel_id or None,
                channel_metadata=im_meta,
            )

        self._schedule_auto_thread_title(thread_id, msg.text, user_id=user_id)
        turn_started = time.perf_counter()
        self._hitl.expire_pending_for_thread(thread_id, agent_id=agent_id, user_id=user_id)
        self.teams.cancel_member_hitl(thread_id)
        request = await self._build_dashboard_request(
            msg,
            agent_id=agent_id,
            user_id=user_id,
            session_key=session_key,
            thread_id=thread_id,
            meta=meta,
        )
        history_tracker = TurnHistoryTracker.from_request(request)
        self._observe_trajectory(
            agent_id=agent_id,
            thread_id=thread_id,
            chunk={"type": "user", "content": msg.text or "", "source": channel_type},
            enabled=traj_on,
        )
        await self._observe_turn_start_context(
            agent_id=agent_id,
            thread_id=thread_id,
            request=request,
            meta=meta,
            phase="context",
            trajectory_enabled=traj_on,
        )

        stream_ok = False
        failure_saved = False
        harness_workspace = harness_workspace_for_agent(self._agent_manager, agent_id)
        usage_tracker = UsageTracker()
        # Align with IM stream_project: only push tool_call ids opened this
        # turn, then dedupe intra-turn replays and identical path/URL frames.
        saw_tool_call = False
        live_tool_call_ids: set[str] = set()
        emitted_media_ids: set[str] = set()
        emitted_attachment_keys: set[str] = set()
        emitted_tool_error_ids: set[str] = set()

        try:
            async for chunk in iter_with_session_auto_approve(
                self._agent_manager.stream(agent_id, request),
                thread_id=thread_id,
                policies=self._hitl.session_policies,
                resume=lambda next_decisions: self._agent_manager.resume_hitl(
                    agent_id, thread_id, next_decisions
                ),
            ):
                usage_tracker.observe(chunk)
                history_tracker.observe(chunk)
                self._observe_trajectory(
                    agent_id=agent_id,
                    thread_id=thread_id,
                    chunk=chunk,
                    enabled=traj_on,
                )
                if chunk.get("type") == "hitl_required":
                    request_payload = chunk.get("request")
                    if isinstance(request_payload, dict):
                        from happyclaw.infra.gateway.hitl.coordinator import HitlStreamContext

                        request_payload = normalize_hitl_request(request_payload)
                        record = self._hitl.register_from_request(
                            request_payload,
                            ctx=HitlStreamContext(
                                thread_id=thread_id,
                                agent_id=agent_id,
                                user_id=user_id,
                                session_key=session_key,
                                channel_type=channel_type,
                            ),
                        )
                        request_payload["pending_id"] = record.pending_id
                        chunk = {
                            **chunk,
                            "request": request_payload,
                            "pending_id": record.pending_id,
                        }
                if chunk.get("type") == "tool_call_chunk":
                    saw_tool_call = True
                    note_live_tool_call(chunk, live_tool_call_ids)
                if chunk.get("type") == "tool_result":
                    log_failed_tool_results(
                        chunk,
                        agent_id=agent_id,
                        thread_id=thread_id,
                        seen=emitted_tool_error_ids,
                        live=saw_tool_call,
                    )
                    if harness_workspace is not None:
                        chunk = await enrich_tool_result_with_backend(
                            chunk,
                            agent_id=agent_id,
                            workspace=harness_workspace,
                        )
                        async for att in iter_dashboard_attachment_frames(
                            chunk,
                            agent_id=agent_id,
                            workspace=harness_workspace,
                            live_tool_call_ids=live_tool_call_ids,
                            emitted_media_ids=emitted_media_ids,
                            emitted_attachment_keys=emitted_attachment_keys,
                        ):
                            yield _maybe_stamp_team_host(att, agent_id, team_host)
                    else:
                        chunk = enrich_tool_result_for_dashboard(
                            chunk,
                            agent_id=agent_id,
                        )
                chunk = enrich_tool_stream_chunk(
                    chunk,
                    locale,
                    agent_manager=self._agent_manager,
                    agent_id=agent_id,
                    user_id=user_id,
                )
                yield _maybe_stamp_team_host(chunk, agent_id, team_host)
            stream_ok = True
        except Exception as exc:
            await self._record_stream_error(
                user_id=user_id, agent_id=agent_id, thread_id=thread_id, exc=exc
            )
            message, error_code = _stream_error(exc, locale)
            payload: dict[str, Any] = {"type": "error", "message": message}
            if error_code:
                payload["error_code"] = error_code
            history_tracker.observe(payload)
            await self._persist_incomplete_turn(thread_id, history_tracker, title_source=msg.text)
            failure_saved = True
            yield _maybe_stamp_team_host(payload, agent_id, team_host)
        finally:
            self._finish_trajectory(thread_id=thread_id, usage=usage_tracker.usage, enabled=traj_on)
            if stream_ok:
                history_tracker.note_turn_duration(_elapsed_ms(turn_started))
            if not failure_saved and not stream_ok:
                await self._persist_incomplete_turn(
                    thread_id, history_tracker, title_source=msg.text
                )
        if stream_ok:
            self._touch_thread_after_turn(thread_id, msg.text)
            self._record_turn_usage(
                agent_id=agent_id,
                user_id=user_id,
                thread_id=thread_id,
                usage=usage_tracker.usage,
            )
            await self._record_turn_history(thread_id, history_tracker)
        yield _maybe_stamp_team_host(
            self._done_chunk(
                thread_id,
                duration_ms=_elapsed_ms(turn_started) if stream_ok else None,
            ),
            agent_id,
            team_host,
        )

    async def iter_hitl_resume_chunks(
        self,
        *,
        agent_id: str,
        thread_id: str,
        user_id: int,
        decisions: list[dict[str, Any]],
    ) -> AsyncIterator[dict[str, Any]]:
        """Resume a dashboard HITL turn with the normal history bookkeeping."""
        usage_tracker = UsageTracker()
        history_tracker = TurnHistoryTracker.from_request({})
        turn_started = time.perf_counter()
        completed = False
        failure_saved = False
        traj_on = self._agent_trajectory_enabled(agent_id)
        team_host = is_team_agent(self._agent_manager.get_row(agent_id))
        saw_tool_call = False
        emitted_tool_error_ids: set[str] = set()
        try:
            async for chunk in iter_with_session_auto_approve(
                self._agent_manager.resume_hitl(
                    agent_id,
                    thread_id,
                    decisions,
                ),
                thread_id=thread_id,
                policies=self._hitl.session_policies,
                resume=lambda next_decisions: self._agent_manager.resume_hitl(
                    agent_id, thread_id, next_decisions
                ),
            ):
                usage_tracker.observe(chunk)
                history_tracker.observe(chunk)
                self._observe_trajectory(
                    agent_id=agent_id,
                    thread_id=thread_id,
                    chunk=chunk,
                    enabled=traj_on,
                )
                if chunk.get("type") == "tool_call_chunk":
                    saw_tool_call = True
                if chunk.get("type") == "tool_result":
                    log_failed_tool_results(
                        chunk,
                        agent_id=agent_id,
                        thread_id=thread_id,
                        seen=emitted_tool_error_ids,
                        live=saw_tool_call,
                    )
                yield _maybe_stamp_team_host(chunk, agent_id, team_host)
            completed = True
        except Exception as exc:
            await self._record_stream_error(
                user_id=user_id, agent_id=agent_id, thread_id=thread_id, exc=exc
            )
            locale = resolve_user_locale(
                user_repo=self._user_repo,
                user_id=user_id,
                channel_type="dashboard",
            )
            message, error_code = _stream_error(exc, locale)
            payload: dict[str, Any] = {"type": "error", "message": message}
            if error_code:
                payload["error_code"] = error_code
            history_tracker.observe(payload)
            await self._persist_incomplete_turn(thread_id, history_tracker, title_source=None)
            failure_saved = True
            yield _maybe_stamp_team_host(payload, agent_id, team_host)
        finally:
            self._finish_trajectory(thread_id=thread_id, usage=usage_tracker.usage, enabled=traj_on)
            if completed:
                history_tracker.note_turn_duration(_elapsed_ms(turn_started))
            if not failure_saved and not completed:
                await self._persist_incomplete_turn(thread_id, history_tracker, title_source=None)
            if completed:
                self._touch_thread_after_turn(thread_id, None)
                self._record_turn_usage(
                    agent_id=agent_id,
                    user_id=user_id,
                    thread_id=thread_id,
                    usage=usage_tracker.usage,
                )
                await self._record_turn_history(thread_id, history_tracker)

    async def _build_dashboard_request(
        self,
        msg: InboundMessage,
        *,
        agent_id: str,
        user_id: int,
        session_key: str,
        thread_id: str,
        meta: dict[str, Any],
    ) -> dict[str, Any]:
        from happyclaw.infra.gateway.process.message_keys import COMPOSER_CTX_KEY  # noqa: PLC0415

        media_backend = media_backend_for_agent(self._agent_manager, agent_id)
        source = f"{msg.channel_type}/{msg.channel_id}"
        locale = resolve_user_locale(
            user_repo=self._user_repo,
            user_id=user_id,
            channel_type=msg.channel_type or "unknown",
            metadata=meta,
        )
        content = await build_content_from_message(
            msg,
            media_backend=media_backend,
            locale=locale,
        )
        model_route = self._resolve_harness_model_route(
            agent_id,
            thread_id,
            meta,
            user_id=user_id,
            needs_multimodal=content_blocks_need_vision(content),
        )
        model_ref = model_route.model_ref
        reasoning_overrides = self._resolve_reasoning_overrides(
            user_id=user_id,
            thread_id=thread_id,
            model_ref=model_ref,
            meta=meta,
        )

        message_kwargs: dict[str, Any] = {}
        composer = meta.get(COMPOSER_CTX_KEY)
        if isinstance(composer, dict) and composer:
            message_kwargs[COMPOSER_CTX_KEY] = composer
        attachments = meta.get(INBOUND_ATTACHMENTS_KEY)
        if not isinstance(attachments, list) or not attachments:
            attachments = inbound_attachments_from_parts(msg.content)
        if attachments:
            message_kwargs[INBOUND_ATTACHMENTS_KEY] = attachments

        explicit_mcp = meta.get("mcp_servers")
        # Dashboard always sends mcp_servers (possibly []); trust that list so
        # users can opt out of default_open for a turn. Missing key → IM-style defaults.
        if isinstance(explicit_mcp, list):
            apply_defaults = False
        else:
            explicit_mcp = None
            apply_defaults = True
        resolved_mcp = await self._resolve_turn_mcp_servers(
            agent_id=agent_id,
            user_id=user_id,
            explicit=explicit_mcp,
            apply_defaults=apply_defaults,
        )
        mcp_servers = resolved_mcp.harness if resolved_mcp is not None else None
        shown_mcp = resolved_mcp.shown if resolved_mcp is not None else None
        if mcp_servers:
            # History chips use the viewer's catalog names. The harness request
            # below keeps the names registered on the shared expert.
            shown = shown_mcp if shown_mcp is not None else mcp_servers
            if isinstance(composer, dict) and composer:
                stamped = dict(composer)
                stamped["connectors"] = list(shown)
                message_kwargs[COMPOSER_CTX_KEY] = stamped
            else:
                from happyclaw.infra.gateway.process.message_keys import (  # noqa: PLC0415
                    build_composer_context,
                )

                row = self._agent_repo.get(agent_id)
                default_model = (row.default_model if row is not None else None) or None
                built = build_composer_context(
                    mcp_servers=shown,
                    skills=meta.get("skills") if isinstance(meta.get("skills"), list) else None,
                    target_agent_ids=None,
                    model_ref=model_ref,
                    default_model=default_model,
                )
                if built:
                    message_kwargs[COMPOSER_CTX_KEY] = built

        client_message_id = meta.get("client_message_id")
        request = build_harness_request(
            thread_id=thread_id,
            user_id=user_id,
            agent_id=agent_id,
            session_key=session_key,
            source=source,
            content=content,
            model=model_ref,
            auto_route=model_route.automatic,
            message_kwargs=message_kwargs or None,
            reasoning_overrides=reasoning_overrides,
            message_id=client_message_id if isinstance(client_message_id, str) else None,
        )
        self.teams.stamp_host_runtime(request, agent_id)
        self._attach_turn_knowledge_config(
            request,
            user_id=user_id,
            is_admin=bool(meta.get("user_is_admin")),
            explicit_ids=meta.get("knowledge_base_ids")
            if isinstance(meta.get("knowledge_base_ids"), list)
            else None,
            locale=locale,
            agent_id=agent_id,
        )

        if mcp_servers:
            request["mcp_servers"] = mcp_servers
        if "skills" in meta:
            request["skills"] = meta["skills"]
        self._apply_turn_hitl_policy(thread_id, meta)
        return self._stamp_turn_conversation_mode(
            request,
            agent_id=agent_id,
            thread_id=thread_id,
            meta=meta,
            user_text=msg.text,
            mcp_servers=mcp_servers,
            locale=locale,
        )
