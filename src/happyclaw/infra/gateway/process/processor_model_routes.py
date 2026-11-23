"""Model route and reasoning overrides resolved from agent metadata."""

from __future__ import annotations

from typing import Any

from happyclaw.infra.agents.providers.reasoning import reasoning_request_parameters
from happyclaw.infra.gateway.process.processor_base import (
    GlobalProcessorBase,
    _ResolvedModelRoute,
)
from happyclaw.infra.users.preferences import (
    get_model_reasoning_from_json,
    get_preferred_model_from_json,
)


class ProcessorModelRouteMixin(GlobalProcessorBase):
    """按智能体元数据解析模型路由与推理档位覆盖。"""

    @staticmethod
    def _model_ref_from_meta(
        thread_model: str | None,
        meta: dict[str, Any] | None,
        sticky_model: str | None = None,
    ) -> str | None:
        meta_model = (meta or {}).get("model")
        # Explicit composer choice wins, followed by its persisted conversation
        # value. The legacy /model override remains supported at lower priority.
        model_ref = meta_model or sticky_model or thread_model
        if isinstance(model_ref, str):
            stripped = model_ref.strip()
            return stripped or None
        return None

    def _resolve_harness_model(
        self,
        agent_id: str,
        thread_id: str,
        meta: dict[str, Any] | None,
        *,
        needs_multimodal: bool,
        user_id: int = 0,
    ) -> str | None:
        return self._resolve_harness_model_route(
            agent_id,
            thread_id,
            meta,
            needs_multimodal=needs_multimodal,
            user_id=user_id,
        ).model_ref

    def _resolve_harness_model_route(
        self,
        agent_id: str,
        thread_id: str,
        meta: dict[str, Any] | None,
        *,
        needs_multimodal: bool,
        user_id: int = 0,
    ) -> _ResolvedModelRoute:
        """Per-turn ``model`` for harness requests.

        - Expert AUTO (no ``default_model`` on row): omit ``model`` → harness routes.
        - Expert default set: pass default (or slash/thread / dashboard override).
        - Stale overrides (deleted / disabled catalog refs) are dropped so routing
          falls through to a usable expert default or harness AUTO.
        - When a model is passed and the turn needs vision, upgrade to a vision ref.
        """
        providers = self._agent_manager.providers
        thread_model = self._agent_manager.get_thread_model(agent_id, thread_id)
        thread_row = self._thread_registry.get_thread(thread_id)
        model_ref = self._model_ref_from_meta(
            thread_model,
            meta,
            thread_row.model_ref if thread_row is not None else None,
        )
        automatic = False
        if model_ref and not providers.is_model_ref_usable(model_ref):
            model_ref = None
        if model_ref and not self._agent_manager.model_ref_allowed_for_user(user_id, model_ref):
            model_ref = None
        if not model_ref:
            row = self._agent_repo.get(agent_id)
            if row is not None:
                model_ref = providers.resolve_explicit_default_model(
                    row,
                    self._agent_manager.get_config(agent_id),
                )
                if model_ref and not self._agent_manager.model_ref_allowed_for_user(
                    user_id,
                    model_ref,
                ):
                    model_ref = None
        if not model_ref:
            user_row = self._user_repo.get(user_id)
            preferred = get_preferred_model_from_json(
                user_row.preferences_json if user_row is not None else None
            )
            if (
                preferred
                and self._agent_manager.is_auto_route_model_available(preferred)
                and self._agent_manager.model_ref_allowed_for_user(user_id, preferred)
            ):
                model_ref = preferred
                automatic = True
        if not model_ref:
            fallback = self._agent_manager.resolve_fallback_model_ref()
            candidate = fallback.strip() if isinstance(fallback, str) and fallback.strip() else None
            if candidate and self._agent_manager.model_ref_allowed_for_user(user_id, candidate):
                model_ref = candidate
                automatic = True
        if not model_ref:
            return _ResolvedModelRoute(None, automatic=True)
        resolved = providers.resolve_model_for_multimodal_turn(
            model_ref,
            needs_multimodal=needs_multimodal,
        )
        if resolved != model_ref:
            automatic = True
        return _ResolvedModelRoute(resolved, automatic=automatic)

    def _resolve_reasoning_overrides(
        self,
        *,
        user_id: int,
        thread_id: str,
        model_ref: str | None,
        meta: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not model_ref:
            return {}
        capability = self._agent_manager.providers.get_model_reasoning_capability(model_ref)
        if capability is None:
            return {}
        thread = self._thread_registry.get_thread(thread_id)
        user_row = self._user_repo.get(user_id)
        user_prefs = get_model_reasoning_from_json(
            user_row.preferences_json if user_row is not None else None
        )
        user_pref = user_prefs.get(model_ref)
        raw_mode = (meta or {}).get("reasoning_mode")
        raw_effort = (meta or {}).get("reasoning_effort")
        mode = (
            str(raw_mode)
            if raw_mode in ("auto", "enabled", "disabled")
            else thread.reasoning_mode
            if thread is not None and thread.reasoning_mode
            else user_pref.mode
            if user_pref is not None
            else None
        )
        effort = (
            str(raw_effort).strip().lower()
            if isinstance(raw_effort, str) and raw_effort.strip()
            else thread.reasoning_effort
            if thread is not None and thread.reasoning_effort
            else user_pref.effort
            if user_pref is not None
            else None
        )
        return reasoning_request_parameters(capability, mode=mode, effort=effort)

    # -- IM channel entry (MessageEvent stream) --------------------------------
