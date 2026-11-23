"""Global settings stores and per-agent configuration persistence."""

from __future__ import annotations

import logging
from typing import (
    TYPE_CHECKING,
    Any,
)

from happyclaw_harness.security.models import SecurityPolicy

from happyclaw.infra.agents.manager.base import AgentManagerBase
from happyclaw.infra.agents.settings.decision import DecisionSettings
from happyclaw.infra.agents.settings.langfuse import LangfuseSettings
from happyclaw.infra.agents.settings.media_generation import (
    MediaGenerationSettings,
    MediaProviderUpdate,
)
from happyclaw.infra.agents.settings.profile import (
    dump_id_list,
    dumps_config,
    extract_profile_from_config,
    parse_config_json,
)
from happyclaw.infra.errors import (
    ErrorCode,
    HappyclawError,
)

if TYPE_CHECKING:
    from happyclaw.infra.db.repos.agents import AgentRow

logger = logging.getLogger(__name__)

def skills_disabled_set(cfg: dict[str, Any]) -> set[str]:
    """Return the set of disabled skill slugs from agent config."""
    raw = cfg.get("skills_disabled")
    if isinstance(raw, list):
        return {str(x) for x in raw}
    return set()


def tools_disabled_set(cfg: dict[str, Any]) -> set[str]:
    """Return disabled built-in tool names from agent config (critical stripped)."""
    from happyclaw.infra.agents.settings.tool_catalog import (
        tools_disabled_set as _tools_disabled_set,
    )

    return _tools_disabled_set(cfg)


def skill_package_ids_list(cfg: dict[str, Any]) -> list[str]:
    """Return non-empty skill package ids from agent config."""
    raw = cfg.get("skill_package_ids")
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item).strip()]


class ConfigMixin(AgentManagerBase):
    """Global settings stores and per-agent configuration persistence."""


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


    async def apply_persona_mbti(self, agent_id: str, code: str) -> AgentRow:
        """Persist MBTI persona on the agent row and reload harness runtime."""
        norm = code.upper()
        row = self._repos.agent_repo.get(agent_id)
        if row is None:
            raise HappyclawError(ErrorCode.AGENT_NOT_FOUND, f"agent {agent_id!r} not found")

        from happyclaw.infra.agents.persona import PersonaLoader  # noqa: PLC0415

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
            raise HappyclawError(ErrorCode.AGENT_NOT_FOUND, f"agent {agent_id!r} not found")
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
            raise HappyclawError(ErrorCode.AGENT_NOT_FOUND, f"agent {agent_id!r} not found")
        self._schedule_reload(agent_id)
        return row


    def persist_knowledge_base_ids(self, agent_id: str, knowledge_base_ids: list[str]) -> None:
        """Persist composer knowledge-base defaults without reloading harness."""
        row = self._repos.agent_repo.get(agent_id)
        if row is None:
            raise HappyclawError(ErrorCode.AGENT_NOT_FOUND, f"agent {agent_id!r} not found")
        normalized = (
            self.validate_knowledge_base_ids(row.user_id, knowledge_base_ids)
            if row.user_id is not None
            else skill_package_ids_list({"skill_package_ids": knowledge_base_ids})
        )
        self._repos.agent_repo.update_config(
            agent_id,
            knowledge_base_ids=dump_id_list(normalized),
        )


    def persist_mcp_servers(self, agent_id: str, mcp_servers: list[str]) -> None:
        """Persist composer connector defaults without reloading harness."""
        from happyclaw.infra.agents.teams import is_team_agent

        row = self._repos.agent_repo.get(agent_id)
        if row is None:
            raise HappyclawError(ErrorCode.AGENT_NOT_FOUND, f"agent {agent_id!r} not found")
        if is_team_agent(row):
            self._repos.agent_repo.update_config(agent_id, mcp_servers=dump_id_list([]))
            return
        normalized = (
            self.validate_mcp_servers(row.user_id, mcp_servers)
            if row.user_id is not None
            else skill_package_ids_list({"skill_package_ids": mcp_servers})
        )
        self._repos.agent_repo.update_config(
            agent_id,
            mcp_servers=dump_id_list(normalized),
        )


    def validate_knowledge_base_ids(self, user_id: int, knowledge_base_ids: list[str]) -> list[str]:
        """Normalize ids and ensure each knowledge base is visible to *user_id*."""
        normalized = skill_package_ids_list({"skill_package_ids": knowledge_base_ids})
        if not normalized:
            return []
        visible = {base.id for base in self._repos.knowledge_repo.list_visible(user_id)}
        unknown = [kb_id for kb_id in normalized if kb_id not in visible]
        if unknown:
            raise HappyclawError(
                ErrorCode.KNOWLEDGE_NOT_FOUND,
                f"knowledge base(s) not found: {', '.join(unknown)}",
            )
        return normalized


    def validate_mcp_servers(self, user_id: int, mcp_servers: list[str]) -> list[str]:
        """Normalize MCP server names and ensure they are available to *user_id*."""
        normalized = skill_package_ids_list({"skill_package_ids": mcp_servers})
        if not normalized:
            return []
        try:
            return list(self._connector_svc.validate_mcp_servers_for_user(user_id, normalized))
        except ValueError as exc:
            raise HappyclawError(ErrorCode.CONNECTOR_NOT_BOUND, str(exc)) from exc


    def _user_is_admin(self, user_id: int | None) -> bool:
        if user_id is None:
            return False
        user = self._repos.user_repo.get(user_id)
        return user is not None and user.role == "admin"


    def model_ref_allowed_for_user(self, user_id: int, model_ref: str | None) -> bool:
        from happyclaw.infra.users.groups import model_ref_allowed

        return model_ref_allowed(
            self._repos,
            user_id=user_id,
            is_admin=self._user_is_admin(user_id),
            model_ref=model_ref,
        )


    def _assert_model_ref(self, user_id: int, model_ref: str | None) -> None:
        from happyclaw.infra.users.groups import RESOURCE_MODEL, GroupAccess

        ref = (model_ref or "").strip()
        if not ref or ref.lower() == "auto" or "/" not in ref:
            return
        GroupAccess(self._repos).assert_allowed(
            user_id=user_id,
            is_admin=self._user_is_admin(user_id),
            resource_type=RESOURCE_MODEL,
            resource_key=ref,
            is_owner=False,
        )


    def _assert_named_storage_backends(self, user_id: int, backend: Any) -> None:
        from happyclaw.infra.backend.resolver import collect_named_storage_backend_refs
        from happyclaw.infra.users.groups import RESOURCE_STORAGE_BACKEND, GroupAccess

        refs = collect_named_storage_backend_refs(backend)
        if not refs:
            return
        access = GroupAccess(self._repos)
        is_admin = self._user_is_admin(user_id)
        for name in refs:
            access.assert_allowed(
                user_id=user_id,
                is_admin=is_admin,
                resource_type=RESOURCE_STORAGE_BACKEND,
                resource_key=str(name),
                is_owner=False,
            )
