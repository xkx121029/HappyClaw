"""Shared state and collaborator surface of :class:`GlobalProcessor`.

``GlobalProcessor`` is assembled from the responsibility mixins beside this module
(trajectory capture, slash and IM approvals, model routes, streaming turns, turn
configuration, history and titles). Each mixin reaches the processor's own state and
the collaborators it calls through this protocol, so every module type-checks on its
own under ``mypy --strict``.
"""

from __future__ import annotations

import logging
from collections.abc import (
    AsyncIterator,
    Sequence,
)
from dataclasses import dataclass
from types import SimpleNamespace
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    NamedTuple,
    Protocol,
)

from happyclaw_gateway.models import (
    InboundMessage,
    MessageEvent,
)
from happyclaw_harness.slash import SlashCommand

from happyclaw.infra.agents.teams.team_manager import TeamManager
from happyclaw.infra.gateway.hitl.coordinator import HitlChannelCoordinator
from happyclaw.infra.gateway.hitl.phrases import ApprovalUtterance
from happyclaw.infra.gateway.slash.ctx import SlashCtx
from happyclaw.infra.history.projection import TurnHistoryTracker

if TYPE_CHECKING:
    from happyclaw.infra.agents.manager import AgentManager
    from happyclaw.infra.db.repos.agents import AgentRepo
    from happyclaw.infra.db.repos.audit import AuditRepo
    from happyclaw.infra.db.repos.connectors import ConnectorRepo
    from happyclaw.infra.db.repos.thread_messages import ThreadMessageInput
    from happyclaw.infra.db.repos.users import UserRepo
    from happyclaw.infra.gateway.slash.dispatcher import SlashDispatcher
    from happyclaw.infra.gateway.threads import ThreadRegistry

# One logger for the whole GlobalProcessor family; kept under the historical name so
# existing log filters and tests keep matching.
logger = logging.getLogger("happyclaw.infra.gateway.process.processor")


@dataclass(frozen=True)
class _ResolvedModelRoute:
    model_ref: str | None
    automatic: bool


class _ResolvedTurnMcp(NamedTuple):
    """Harness names go to the model; shown names go on history chips."""

    harness: list[str]
    shown: list[str]


class GlobalProcessorBase(Protocol):
    """State and collaborators shared by ``GlobalProcessor`` and its mixins."""

    _agent_manager: AgentManager
    _thread_registry: ThreadRegistry
    _audit_repo: AuditRepo
    _agent_repo: AgentRepo
    _user_repo: UserRepo
    _connector_repo: ConnectorRepo
    _knowledge_services: SimpleNamespace | None
    _dispatcher: SlashDispatcher
    _usage_repo: Any | None
    _thread_message_repo: Any | None
    _gateway: Any | None
    _hitl: HitlChannelCoordinator
    _trajectory_service: Any | None
    _title_inflight: set[str]
    _pending_system_prompt: set[str]
    teams: TeamManager

    async def _complete_resumed_history(
        self, thread_id: str, tracker: TurnHistoryTracker, *, completed: bool
    ) -> None: ...

    @property
    def hitl_coordinator(self) -> HitlChannelCoordinator: ...

    def replace_thread_message_repo(self, repo: Any) -> None: ...

    def _done_chunk(self, thread_id: str, *, duration_ms: int | None = None) -> dict[str, Any]: ...

    def _plan_ready_hint(self, thread_id: str, locale: str) -> str: ...

    async def _record_stream_error(
        self,
        *,
        user_id: int,
        agent_id: str,
        exc: Exception,
        thread_id: str = "",
    ) -> None: ...

    def cancel_agent_stream(self, agent_id: str, thread_id: str) -> None: ...

    def _agent_trajectory_enabled(self, agent_id: str, row: Any | None = None) -> bool: ...

    def _observe_trajectory(
        self,
        *,
        agent_id: str,
        thread_id: str,
        chunk: dict[str, Any],
        enabled: bool | None = None,
    ) -> None: ...

    def _finish_trajectory(
        self,
        *,
        thread_id: str,
        usage: dict[str, Any] | None = None,
        enabled: bool | None = None,
    ) -> None: ...

    async def _observe_turn_start_context(
        self,
        *,
        agent_id: str,
        thread_id: str,
        request: dict[str, Any],
        meta: dict[str, Any],
        phase: Literal["system", "context"] = "context",
        trajectory_enabled: bool | None = None,
    ) -> None: ...

    def _trajectory_system_prompt(self, agent_id: str) -> str | None: ...

    async def _trajectory_enabled_skill_names(
        self, agent_id: str
    ) -> list[dict[str, str]] | None: ...

    def _captures_model_system_prompt(self, agent_id: str) -> bool: ...

    async def _trajectory_workspace_files(self, agent_id: str) -> list[str]: ...

    def _clear_captured_system_prompt(self, agent_id: str, thread_id: str) -> None: ...

    def _sync_memory_prompt_trajectory(self, agent_id: str, thread_id: str) -> None: ...

    def _slash_ctx(
        self,
        *,
        agent_id: str,
        user_id: int,
        channel_type: str,
        session_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> SlashCtx: ...

    def _relay_im_approval(
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
    ) -> AsyncIterator[MessageEvent]: ...

    def _phrase_to_apply(
        self,
        text: str | None,
        *,
        session_key: str,
        agent_id: str,
        user_id: int,
    ) -> ApprovalUtterance | None: ...

    def _reset_thread_ids(
        self,
        *,
        session_key: str,
        agent_id: str,
        user_id: int,
    ) -> tuple[list[str], bool]: ...

    def _iter_applied_phrase(
        self,
        msg: InboundMessage,
        *,
        phrase: ApprovalUtterance,
        agent_id: str,
        user_id: int,
        channel_type: str,
        session_key: str,
        locale: str,
    ) -> AsyncIterator[MessageEvent]: ...

    @staticmethod
    def _model_ref_from_meta(
        thread_model: str | None,
        meta: dict[str, Any] | None,
        sticky_model: str | None = None,
    ) -> str | None: ...

    def _resolve_harness_model(
        self,
        agent_id: str,
        thread_id: str,
        meta: dict[str, Any] | None,
        *,
        needs_multimodal: bool,
        user_id: int = 0,
    ) -> str | None: ...

    def _resolve_harness_model_route(
        self,
        agent_id: str,
        thread_id: str,
        meta: dict[str, Any] | None,
        *,
        needs_multimodal: bool,
        user_id: int = 0,
    ) -> _ResolvedModelRoute: ...

    def _resolve_reasoning_overrides(
        self,
        *,
        user_id: int,
        thread_id: str,
        model_ref: str | None,
        meta: dict[str, Any] | None,
    ) -> dict[str, Any]: ...

    def _apply_turn_hitl_policy(self, thread_id: str, meta: dict[str, Any] | None) -> None: ...

    def _sync_and_resolve_conversation_mode(
        self,
        agent_id: str,
        thread_id: str,
        *,
        meta: dict[str, Any] | None,
        user_text: str,
    ) -> tuple[Any, str | None]: ...

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
    ) -> dict[str, Any]: ...

    def _attach_conversation_mode(self, request: dict[str, Any], mode: Any) -> None: ...

    def _attach_turn_knowledge_config(
        self,
        request: dict[str, Any],
        *,
        user_id: int,
        is_admin: bool,
        explicit_ids: list[str] | None,
        locale: str,
        agent_id: str | None = None,
    ) -> None: ...

    async def _resolve_turn_mcp_servers(
        self,
        *,
        agent_id: str,
        user_id: int,
        explicit: list[str] | None,
        apply_defaults: bool | None = None,
        raise_on_failure: bool = True,
    ) -> _ResolvedTurnMcp | None: ...

    def _touch_thread_after_turn(self, thread_id: str, title_source: str | None) -> None: ...

    def _plain_title(self, thread_id: str) -> str | None: ...

    def _schedule_auto_thread_title(
        self, thread_id: str, source: str | None, *, user_id: int
    ) -> None: ...

    async def _generate_thread_title(
        self, thread_id: str, source: str, *, user_id: int
    ) -> None: ...

    def _thread_agent_id(self, thread_id: str) -> str: ...

    async def _push_thread_title(self, thread_id: str, title: str) -> None: ...

    def _record_turn_usage(
        self,
        *,
        agent_id: str,
        user_id: int,
        thread_id: str,
        usage: dict[str, Any] | None,
    ) -> None: ...

    async def _persist_incomplete_turn(
        self,
        thread_id: str,
        tracker: TurnHistoryTracker,
        *,
        title_source: str | None,
    ) -> None: ...

    async def _record_turn_history(self, thread_id: str, tracker: TurnHistoryTracker) -> None: ...

    async def _append_slash_checkpoint(
        self,
        *,
        agent_id: str,
        thread_id: str,
        command: str,
        response_lines: list[str],
        user_id: int = 0,
    ) -> None: ...

    @staticmethod
    def _write_shadow_history(thread_id: str, items: Sequence[ThreadMessageInput]) -> None: ...

    async def _build_dashboard_request(
        self,
        msg: InboundMessage,
        *,
        agent_id: str,
        user_id: int,
        session_key: str,
        thread_id: str,
        meta: dict[str, Any],
    ) -> dict[str, Any]: ...

    def iter_turn_chunks(self, msg: InboundMessage) -> AsyncIterator[dict[str, Any]]: ...
