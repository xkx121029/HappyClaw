"""Settings persistence and agent config mutations.

Split out of :mod:`octop.infra.agents.manager` so AgentManager keeps lifecycle,
CRUD, and runtime concerns. Cross-mixin calls are declared as stubs on
:class:`AgentManagerBase` and resolved through the MRO.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from octop_harness.security.models import SecurityPolicy

from octop.infra.agents.manager_base import AgentManagerBase
from octop.infra.agents.settings.decision import DecisionSettings
from octop.infra.agents.settings.langfuse import LangfuseSettings
from octop.infra.agents.settings.media_generation import (
    MediaGenerationSettings,
    MediaProviderUpdate,
)
from octop.infra.agents.settings.profile import (
    dumps_config,
    extract_profile_from_config,
    parse_config_json,
)
from octop.infra.agents.settings.runtime_limits import (
    resolve_context_max_tokens as config_context_max_tokens,
)
from octop.infra.errors import ErrorCode, OctopError

if TYPE_CHECKING:
    from octop.infra.db.repos.agents import AgentRow

logger = logging.getLogger(__name__)


class AgentSettingsMixin(AgentManagerBase):
    """Persist global policy / per-agent config and push it into the harness."""

    # ------------------------------------------------------------------
    # Settings persistence — push global policy into harness runtime
    # ------------------------------------------------------------------

    def save_langfuse(
        self,
        *,
        enabled: bool,
        public_key: str,
        host: str,
        secret_key: str | None = None,
    ) -> LangfuseSettings:
        """Persist Langfuse settings and push them into the harness runtime."""
        view = self._langfuse.save(
            enabled=enabled,
            public_key=public_key,
            host=host,
            secret_key=secret_key,
        )
        if self._harness_manager is not None:
            self._harness_manager.set_langfuse(self._langfuse.harness_config())
        return view

    async def save_decision(
        self,
        *,
        enabled: bool,
        provider: str,
        endpoint: str,
        model: str,
        skills: bool,
        tools: bool,
        team: bool,
        threshold: float,
        tool_min_count: int,
        api_key: str | None = None,
        services: list[dict[str, object]] | None = None,
    ) -> DecisionSettings:
        """Persist the decision switch and rebuild agents so the middleware mounts or not."""
        view = self._decision.save(
            enabled=enabled,
            provider=provider,
            endpoint=endpoint,
            model=model,
            skills=skills,
            tools=tools,
            team=team,
            threshold=threshold,
            tool_min_count=tool_min_count,
            api_key=api_key,
            services=services,
        )
        await self.reload_all()
        return view

    async def probe_decision(
        self,
        *,
        endpoint: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        provider: str | None = None,
    ) -> dict[str, Any]:
        return await self._decision.probe(
            endpoint=endpoint,
            api_key=api_key,
            model=model,
            provider=provider,
        )

    async def save_media_generation(
        self,
        *,
        enabled: bool,
        providers: list[MediaProviderUpdate],
        default_image_provider: str | None,
        default_video_provider: str | None,
    ) -> MediaGenerationSettings:
        """Persist media settings and rebuild running harness agents."""
        view = self._media_generation.save(
            enabled=enabled,
            providers=providers,
            default_image_provider=default_image_provider,
            default_video_provider=default_video_provider,
        )
        await self.reload_all()
        return view

    def save_security(self, policy: SecurityPolicy | dict[str, Any]) -> SecurityPolicy:
        """Persist security policy and push it into harness agents."""
        resolved = self._security.save(policy)
        if self._harness_manager is not None:
            try:
                self._harness_manager.set_security_policy(self._security.harness_policy())
            except Exception:
                logger.exception("failed to apply security policy to running harness agents")
        return resolved

    # ------------------------------------------------------------------
    # Agent config mutations — persona, skills, config_json patches
    # ------------------------------------------------------------------

    async def apply_persona_mbti(self, agent_id: str, code: str) -> AgentRow:
        """Persist MBTI persona on the agent row and reload harness runtime."""
        norm = code.upper()
        row = self._repos.agent_repo.get(agent_id)
        if row is None:
            raise OctopError(ErrorCode.AGENT_NOT_FOUND, f"agent {agent_id!r} not found")

        from octop.infra.agents.persona import PersonaLoader  # noqa: PLC0415

        loader = PersonaLoader()
        persona_text = loader.render(
            mbti=norm,
            agent_name=row.name,
            user_display="User",
            custom=None,
        )

        cfg = self.get_config(agent_id)
        cfg["persona"] = norm
        self.persist_harness_config(
            agent_id,
            cfg,
            persona_mbti=norm,
            system_prompt=persona_text,
        )
        row = self._repos.agent_repo.get(agent_id)
        if row is None:
            raise OctopError(ErrorCode.AGENT_NOT_FOUND, f"agent {agent_id!r} not found")
        self._schedule_reload(agent_id)
        return row

    async def update_config_json(self, agent_id: str, config_json: str) -> AgentRow:
        """Patch ``config_json`` and reload the harness runtime in the background."""
        parsed = self._preserve_internal_layout(
            agent_id, parse_config_json(config_json), pin_workspace_dir=True
        )
        lifted = extract_profile_from_config(parsed)
        self._repos.agent_repo.update_config(
            agent_id,
            config_json=dumps_config(parsed),
            **lifted,
        )
        row = self._repos.agent_repo.get(agent_id)
        if row is None:
            raise OctopError(ErrorCode.AGENT_NOT_FOUND, f"agent {agent_id!r} not found")
        self._schedule_reload(agent_id)
        return row

    async def persist_skills_disabled(self, agent_id: str, disabled: set[str]) -> None:
        """Persist ``skills_disabled`` and hot-sync the running agent (no rebuild).

        Unlike :meth:`update_config_json`, this does not schedule a harness reload.
        Skill enable/disable and marketplace install only need the filter set updated.
        """
        cfg = self.get_config(agent_id)
        cfg["skills_disabled"] = sorted(disabled)
        self.persist_harness_config(agent_id, cfg)
        self.sync_skills_disabled(agent_id, disabled)

    async def persist_tools_disabled(self, agent_id: str, disabled: set[str]) -> None:
        """Persist builtin ``tools_disabled`` and hot-sync the effective denylist."""
        from octop.infra.agents.settings.tool_catalog import normalize_tools_disabled

        cfg = self.get_config(agent_id)
        cleaned = normalize_tools_disabled(sorted(disabled))
        cfg["tools_disabled"] = cleaned
        self.persist_harness_config(agent_id, cfg)
        self.sync_effective_tools_disabled(agent_id)

    async def persist_plugin_tools_config(
        self,
        agent_id: str,
        plugins: dict[str, Any],
    ) -> None:
        """Persist ``config.plugins`` and hot-sync tool denylist (no harness reload)."""
        cfg = self.get_config(agent_id)
        cfg["plugins"] = plugins
        self.persist_harness_config(agent_id, cfg)
        self.sync_effective_tools_disabled(agent_id)

    def resolve_context_max_tokens(self, agent_id: str, *, fallback: int = 128_000) -> int:
        """Return the configured context cap for *agent_id* (``max_input_length``)."""
        return config_context_max_tokens(self.get_config(agent_id), fallback=fallback)


__all__ = ["AgentSettingsMixin"]
