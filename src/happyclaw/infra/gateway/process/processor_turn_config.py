"""Turn request configuration: HITL policy, conversation mode, knowledge and MCP."""

from __future__ import annotations

from typing import Any

from happyclaw.infra.agents.teams import is_team_agent
from happyclaw.infra.errors import HappyclawError
from happyclaw.infra.gateway.process.processor_base import (
    GlobalProcessorBase,
    _ResolvedTurnMcp,
    logger,
)
from happyclaw.infra.gateway.process.processor_message_utils import _overwrite_last_user_text
from happyclaw.infra.knowledge.default_open import stamp_turn_knowledge_config


class ProcessorTurnConfigMixin(GlobalProcessorBase):
    """回合请求配置：HITL 策略、会话模式、知识库与 MCP 服务。"""

    def _apply_turn_hitl_policy(self, thread_id: str, meta: dict[str, Any] | None) -> None:
        raw = (meta or {}).get("hitl_policy")
        if raw is None:
            return
        self._hitl.session_policies.set(thread_id, raw)

    def _sync_and_resolve_conversation_mode(
        self,
        agent_id: str,
        thread_id: str,
        *,
        meta: dict[str, Any] | None,
        user_text: str,
    ) -> tuple[Any, str | None]:
        from happyclaw.infra.agents.conversation_mode import (
            is_plan_execute_utterance,
            parse_conversation_mode,
            resolve_conversation_mode,
        )

        thread = self._thread_registry.get_thread(thread_id)
        thread_mode = thread.conversation_mode if thread is not None else None
        pending = (thread.pending_plan_path if thread is not None else None) or ""
        explicit = (meta or {}).get("conversation_mode")
        sticky = parse_conversation_mode(thread_mode)
        if pending and sticky == "plan" and is_plan_execute_utterance(user_text):
            self._thread_registry.update_composer(
                thread_id,
                conversation_mode="craft",
                pending_plan_path=None,
            )
            return "craft", pending
        mode = resolve_conversation_mode(
            explicit=explicit,
            thread_mode=thread_mode,
            default_mode=self._agent_manager.get_config(agent_id).get("conversation_mode"),
        )
        if isinstance(explicit, str) and explicit in ("ask", "plan", "craft"):
            self._thread_registry.update_composer(
                thread_id,
                conversation_mode=explicit,
            )
        return mode, None

    def _stamp_turn_conversation_mode(
        self,
        request: dict[str, Any],
        *,
        agent_id: str,
        thread_id: str,
        meta: dict[str, Any] | None,
        user_text: str,
        mcp_servers: list[str] | None,
        locale: str,
    ) -> dict[str, Any]:
        from happyclaw.infra.agents.conversation_mode import execute_user_message

        mode, execute_path = self._sync_and_resolve_conversation_mode(
            agent_id, thread_id, meta=meta, user_text=user_text
        )
        if execute_path:
            _overwrite_last_user_text(request, execute_user_message(execute_path, locale))
        self._attach_conversation_mode(request, mode)
        if mode in ("ask", "plan"):
            request.pop("mcp_servers", None)
            request["skills"] = []
        elif mcp_servers:
            request["mcp_servers"] = mcp_servers
        return request

    def _attach_conversation_mode(self, request: dict[str, Any], mode: Any) -> None:
        from happyclaw.infra.agents.conversation_mode import stamp_conversation_mode

        stamp_conversation_mode(request, mode)

    def _attach_turn_knowledge_config(
        self,
        request: dict[str, Any],
        *,
        user_id: int,
        is_admin: bool,
        explicit_ids: list[str] | None,
        locale: str,
        agent_id: str | None = None,
    ) -> None:
        """Expose selected knowledge-base ids for the search_knowledge tool."""
        if self._knowledge_services is None:
            return
        bases = (
            self._knowledge_services.knowledge_repo.list_all()
            if is_admin
            else self._knowledge_services.knowledge_repo.list_visible(user_id)
        )
        extra_ids = self._agent_manager.default_knowledge_base_ids(agent_id) if agent_id else None
        stamp_turn_knowledge_config(
            request,
            visible_bases=bases,
            explicit_ids=explicit_ids,
            owner_user_id=user_id,
            extra_ids=extra_ids,
            is_admin=is_admin,
            locale=locale,
        )

    async def _resolve_turn_mcp_servers(
        self,
        *,
        agent_id: str,
        user_id: int,
        explicit: list[str] | None,
        apply_defaults: bool | None = None,
        raise_on_failure: bool = True,
    ) -> _ResolvedTurnMcp | None:
        """Merge turn picks with default_open and ensure tools are loaded.

        Dashboard / HTTP paths should keep ``raise_on_failure=True`` so the
        client sees a clear MCP load error. IM ingress uses ``False`` so a
        flaky connector does not abort the whole message turn.
        """
        from happyclaw.infra.errors import ErrorCode  # noqa: PLC0415

        # Team hosts only dispatch — never attach MCP tools.
        row = self._agent_manager.get_row(agent_id)
        if is_team_agent(row):
            return None
        owner_raw = getattr(row, "user_id", None) if row is not None else None
        owner_id = owner_raw if isinstance(owner_raw, int) else None

        extra_defaults = self._agent_manager.default_mcp_servers(agent_id)
        merged = self._agent_manager.merge_turn_mcp_servers(
            user_id,
            explicit,
            apply_defaults=apply_defaults,
            extra_defaults=extra_defaults,
            agent_owner_id=owner_id,
        )
        if not merged:
            return None
        harness = list(merged)
        shown = list(merged)
        if owner_id is not None and owner_id != user_id:
            harness = self._agent_manager.align_mcp_names_to_harness(owner_id, user_id, merged)
            shown = self._agent_manager.mcp_names_for_chips(owner_id, user_id, merged, harness)
        failed = await self._agent_manager.prepare_chat_mcp(
            agent_id,
            merged,
            connector_user_id=user_id,
        )
        if failed:
            detail = f"mcp load failed: {', '.join(failed)}"
            if raise_on_failure:
                raise HappyclawError(ErrorCode.CONNECTOR_MCP_LOAD_FAILED, detail)
            logger.warning(
                "skipping turn MCP for agent=%s user=%s (%s)",
                agent_id,
                user_id,
                detail,
            )
            return None
        return _ResolvedTurnMcp(harness=harness, shown=shown)
