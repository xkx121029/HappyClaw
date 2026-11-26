"""Agent CRUD — create, update, delete, and related validation helpers.

Split out of :mod:`octop.infra.agents.manager` so AgentManager keeps lifecycle,
runtime, and settings concerns. Cross-mixin calls are declared as stubs on
:class:`AgentManagerBase` and resolved through the MRO.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from octop.infra.agents.manager_base import AgentManagerBase
from octop.infra.agents.settings.profile import (
    dump_id_list,
    dumps_config,
    extract_profile_from_config,
    parse_config_json,
    strip_profile_config,
)
from octop.infra.agents.settings.runtime_limits import (
    AGENT_RUNTIME_CONFIG_KEYS,
    merge_agent_runtime_values,
)
from octop.infra.db.repos.audit import ACTOR_SYSTEM
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.utils.ulid import new_short_id

if TYPE_CHECKING:
    from octop.infra.agents.manager import AgentCreateSpec
    from octop.infra.db.repos.agents import AgentRow

logger = logging.getLogger(__name__)


def _stored_id_list(value: Any) -> list[str]:
    """Normalize a persisted id list, whether it is already a list or JSON text."""
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item).strip()]
    return []


# Custom agent ids become workspace directory names (~/.octop/agents/<id>/),
# so restrict to a conservative slug charset — no separators, dots, or
# unicode — to keep every downstream path/URL usage safe.
_CUSTOM_AGENT_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{1,62}[a-zA-Z0-9]$")


def validate_custom_agent_id(agent_id: str) -> str:
    """Validate a user-supplied agent id; raise ``OctopError`` when invalid."""
    if not _CUSTOM_AGENT_ID_RE.fullmatch(agent_id):
        raise OctopError(
            ErrorCode.AGENT_ID_INVALID,
            "agent id must be 3-64 chars of letters/digits/underscore/hyphen, "
            "starting and ending with a letter or digit",
        )
    lowered = agent_id.lower()
    if lowered in _RESERVED_AGENT_IDS:
        raise OctopError(ErrorCode.AGENT_ID_INVALID, f"agent id {agent_id!r} is reserved")
    return agent_id


# Lowercase names that would collide with workspace-adjacent directories or
# well-known URL/route segments.
_RESERVED_AGENT_IDS = frozenset({"api", "admin", "agents", "experts"})


class AgentCrudMixin(AgentManagerBase):
    """Persist agent rows and keep the harness runtime in sync."""

    # ------------------------------------------------------------------
    # CRUD — persist agent rows and sync harness runtime
    # ------------------------------------------------------------------

    async def create(
        self,
        spec: AgentCreateSpec,
        *,
        defer_bootstrap: bool = False,
        workspace_initializer: Callable[[AgentRow, Any], Awaitable[None]] | None = None,
    ) -> AgentRow:
        """Create a new agent, persist to DB, and register with harness."""
        async with self._lock:
            self._assert_agent_name_available(spec.user_id, spec.name)
            if spec.agent_id:
                validate_custom_agent_id(spec.agent_id)
                if self._repos.agent_repo.get(spec.agent_id) is not None:
                    raise OctopError(
                        ErrorCode.AGENT_ID_TAKEN,
                        f"agent_id {spec.agent_id!r} already exists",
                    )
                agent_id = spec.agent_id
            else:
                for _ in range(16):
                    agent_id = new_short_id()
                    if self._repos.agent_repo.get(agent_id) is None:
                        break
                else:
                    raise RuntimeError("failed to allocate unique agent_id")
            config = merge_agent_runtime_values(
                spec.config,
                spec.runtime_config,
            )
            if spec.persona_mbti:
                config["persona"] = spec.persona_mbti.upper()
            from octop.infra.agents.workspace.dir import (  # noqa: PLC0415
                DEFAULT_SYSTEM_FILES_PATH,
                seed_workspace_dir_on_create,
            )
            from octop.infra.users.resource_policy import (
                apply_workspace_root_to_config,
                assert_agent_quota_available,
                raise_if_backend_outside_user_root,
                raise_if_workspace_dir_outside_user_root,
            )

            if spec.user_id is not None:
                kind = spec.kind if spec.kind in {"expert", "team"} else "expert"
                if kind == "expert":
                    assert_agent_quota_available(
                        self._repos.user_policy_repo,
                        self._repos.agent_repo,
                        spec.user_id,
                    )
                apply_workspace_root_to_config(
                    self._repos.user_policy_repo,
                    spec.user_id,
                    config,
                    fill_missing=True,
                )
                raise_if_backend_outside_user_root(
                    self._repos.user_policy_repo,
                    spec.user_id,
                    config.get("backend"),
                )
                raise_if_workspace_dir_outside_user_root(
                    self._repos.user_policy_repo,
                    spec.user_id,
                    config,
                )
                self._assert_named_storage_backends(spec.user_id, config.get("backend"))
                self._assert_model_ref(spec.user_id, spec.default_model)

            # Create-time: user-assigned workspace_dir wins; otherwise default+encode.
            # After insert, resolve_workspace_dir reads the DB value as source of truth.
            seed_workspace_dir_on_create(config, paths=self._paths, agent_id=agent_id)
            # ``system_files_path`` is an internal layout control and must not
            # be user-configurable. New agents always use the default prefix.
            config.pop("system_files_path", None)
            config["system_files_path"] = DEFAULT_SYSTEM_FILES_PATH
            if spec.is_shared and spec.kind == "team":
                raise OctopError(
                    ErrorCode.TEAM_NOT_SHAREABLE,
                    "teams cannot be shared",
                )
            profile = extract_profile_from_config(config)
            config = strip_profile_config(config)
            package_ids_json = (
                dump_id_list(spec.skill_package_ids)
                if spec.skill_package_ids is not None
                else profile.get("skill_package_ids")
            )
            knowledge_ids_json = (
                dump_id_list(spec.knowledge_base_ids)
                if spec.knowledge_base_ids is not None
                else profile.get("knowledge_base_ids")
            )
            if spec.kind == "team":
                mcp_servers_json: str | None = dump_id_list([])
            elif spec.mcp_servers is not None:
                mcp_servers_json = dump_id_list(spec.mcp_servers)
            else:
                raw_mcp = profile.get("mcp_servers")
                mcp_servers_json = raw_mcp if isinstance(raw_mcp, str) else None
            if spec.user_id is not None:
                self._assert_skill_packages_visible(
                    spec.user_id,
                    _stored_id_list(package_ids_json),
                )
                self.validate_knowledge_base_ids(
                    spec.user_id,
                    _stored_id_list(knowledge_ids_json),
                )
            self._repos.agent_repo.create(
                agent_id=agent_id,
                user_id=spec.user_id,
                name=spec.name,
                description=spec.description,
                persona_mbti=spec.persona_mbti,
                default_model=spec.default_model,
                system_prompt=spec.system_prompt,
                config_json=json.dumps(config) if config else None,
                icon=spec.icon,
                template_name=spec.template_name or profile.get("template_name"),
                color=spec.color or profile.get("color"),
                icon_name=spec.icon_name or profile.get("icon_name"),
                icon_url=spec.icon_url or profile.get("icon_url"),
                skill_package_ids=package_ids_json,
                published_expert_id=spec.published_expert_id or profile.get("published_expert_id"),
                welcome_message=(
                    spec.welcome_message
                    if spec.welcome_message is not None
                    else profile.get("welcome_message")
                ),
                knowledge_base_ids=knowledge_ids_json,
                mcp_servers=mcp_servers_json,
                kind=spec.kind if spec.kind in {"expert", "team"} else "expert",
            )
            row = self._repos.agent_repo.get(agent_id)
            assert row is not None
            if spec.is_shared:
                self._repos.agent_repo.set_shared(agent_id, True)
                row = self._repos.agent_repo.get(agent_id)
                assert row is not None
            if spec.kind == "team":
                from octop.infra.agents.teams.service import seed_team_template

                try:
                    workspace = self._backend_workspace_for_row(row)
                    await seed_team_template(
                        workspace,
                        member_ids=list(spec.member_ids or []),
                    )
                except Exception:
                    await self._abort_incomplete_create(agent_id)
                    raise
            elif spec.template_name:
                await self._seed_expert_template(row, spec.template_name)
            if workspace_initializer is not None:
                try:
                    workspace = self._backend_workspace_for_row(row)
                    await workspace_initializer(row, workspace)
                    row = self._repos.agent_repo.get(agent_id)
                    assert row is not None
                except Exception:
                    await self._abort_incomplete_create(agent_id)
                    raise
            if defer_bootstrap:
                self._repos.agent_repo.set_state(agent_id, "starting")
                row = self._repos.agent_repo.get(agent_id)
                assert row is not None
                asyncio.create_task(
                    self._complete_create_bootstrap(row),
                    name=f"bootstrap-agent-{agent_id}",
                )
            else:
                try:
                    agent = await self._start_agent(row, init_workspace=True)
                except Exception:
                    if spec.kind == "team":
                        await self._abort_incomplete_create(agent_id)
                    raise
                if agent is not None and spec.kind == "team":
                    if self._spec_is_opensandbox(self._backend_spec_for_row(row)):
                        from octop.infra.agents.teams.service import seed_team_template

                        workspace = self._backend_workspace_for_row(row)
                        await seed_team_template(
                            workspace,
                            member_ids=list(spec.member_ids or []),
                        )
                elif agent is not None and spec.template_name:
                    if self._spec_is_opensandbox(self._backend_spec_for_row(row)):
                        await self._seed_expert_template(row, spec.template_name)
                    reload = getattr(agent, "reload_subagents", None)
                    if callable(reload):
                        await asyncio.to_thread(reload)
            self._repos.audit_repo.write(
                actor=ACTOR_SYSTEM, action="agent.create", target=agent_id, payload=spec.name
            )
            if self._proactive_scheduler is not None:
                self._proactive_scheduler.ensure_scheduled(agent_id)
            return row

    async def _abort_incomplete_create(self, agent_id: str) -> None:
        """Best-effort rollback after a failed create. Caller holds ``_lock``."""
        try:
            if self._harness_manager is not None:
                await self._harness_manager.aremove_agent(agent_id)
        except Exception:
            logger.exception("abort team create: harness remove failed for %s", agent_id)
        try:
            row = self._repos.agent_repo.get(agent_id)
            workspace_dir = self.resolve_workspace_dir(agent_id, persist_if_missing=False)
            if row is not None:
                from octop.infra.agents.memory.thread_cleanup import (  # noqa: PLC0415
                    agent_config_from_row,
                    delete_agent_memory_and_checkpoints,
                )

                cfg = agent_config_from_row(row)
                await asyncio.to_thread(
                    delete_agent_memory_and_checkpoints,
                    agent_id=agent_id,
                    thread_ids=self._repos.thread_repo.list_ids_for_agent(agent_id),
                    cfg=cfg,
                    octop_config=self._config,
                    workspace_dir=workspace_dir,
                    paths=self._paths,
                )
                from octop.infra.agents.workspace.dir import remove_agent_host_dirs  # noqa: PLC0415

                await asyncio.to_thread(
                    remove_agent_host_dirs, cfg, paths=self._paths, agent_id=agent_id
                )
            elif await asyncio.to_thread(workspace_dir.exists):
                await asyncio.to_thread(shutil.rmtree, workspace_dir)
        except OSError:
            logger.exception("abort team create: rmtree failed for %s", agent_id)
        except Exception:
            logger.exception("abort team create: memory purge failed for %s", agent_id)
        try:
            self._repos.agent_repo.delete(agent_id)
        except Exception:
            logger.exception("abort team create: db delete failed for %s", agent_id)

    def _preserve_internal_layout(
        self,
        agent_id: str,
        cfg: dict[str, Any],
        *,
        pin_workspace_dir: bool = False,
    ) -> dict[str, Any]:
        """Keep the internal layout keys that user-facing config updates must not rewrite.

        ``system_files_path`` stays exactly as stored: a legacy agent without it keeps the root
        layout, so a value a client invents is dropped.

        ``pin_workspace_dir`` additionally pins ``workspace_dir`` to the stored value. User-facing
        updates need it — rewriting the directory relocates the agent's workspace, so a scoped or
        container agent would resolve to the classic layout and lose sight of its skills, sessions
        and generated files. The directory is chosen at create and stays fixed. Internal persists
        do not pin: the resolver and the create path must still be able to write it.
        """
        out = dict(cfg)
        row = self._repos.agent_repo.get(agent_id)
        current_raw = parse_config_json(row.config_json) if row and row.config_json else {}
        if "system_files_path" in current_raw:
            out["system_files_path"] = current_raw["system_files_path"]
        else:
            out.pop("system_files_path", None)
        if pin_workspace_dir and "workspace_dir" in current_raw:
            out["workspace_dir"] = current_raw["workspace_dir"]
        return out

    async def update(self, agent_id: str, **kwargs: Any) -> AgentRow:
        """Update agent config in DB and reload harness agent in the background."""
        runtime_updates = {
            key: kwargs.pop(key) for key in AGENT_RUNTIME_CONFIG_KEYS if key in kwargs
        }
        if runtime_updates:
            raw_config = kwargs.get("config_json")
            if raw_config is None:
                current_row = self._repos.agent_repo.get(agent_id)
                if current_row is None:
                    raise OctopError(ErrorCode.AGENT_NOT_FOUND, f"agent {agent_id!r} not found")
                raw_config = current_row.config_json
            try:
                parsed_config = json.loads(raw_config or "{}")
            except (json.JSONDecodeError, TypeError):
                parsed_config = {}
            if not isinstance(parsed_config, dict):
                parsed_config = {}
            kwargs["config_json"] = json.dumps(
                merge_agent_runtime_values(parsed_config, runtime_updates),
            )
        if "config_json" in kwargs:
            parsed_profile_cfg = parse_config_json(
                kwargs["config_json"] if isinstance(kwargs["config_json"], str) else None
            )
            parsed_profile_cfg = self._preserve_internal_layout(
                agent_id, parsed_profile_cfg, pin_workspace_dir=True
            )
            owner_row = self._repos.agent_repo.get(agent_id)
            if owner_row is not None and owner_row.user_id is not None:
                from octop.infra.users.resource_policy import (
                    POLICY_WORKSPACE_ROOT_DIR,
                    apply_workspace_root_to_config,
                    effective_workspace_root_dir,
                    persisted_workspace_within_root,
                    raise_if_backend_outside_user_root,
                )

                allowed_root = effective_workspace_root_dir(
                    self._repos.user_policy_repo.get(owner_row.user_id, POLICY_WORKSPACE_ROOT_DIR)
                )
                workspace_in_jail = persisted_workspace_within_root(
                    parsed_profile_cfg, allowed_root
                )
                if workspace_in_jail:
                    apply_workspace_root_to_config(
                        self._repos.user_policy_repo,
                        owner_row.user_id,
                        parsed_profile_cfg,
                        fill_missing=False,
                    )
                raise_if_backend_outside_user_root(
                    self._repos.user_policy_repo,
                    owner_row.user_id,
                    parsed_profile_cfg.get("backend"),
                    reject_host_root=bool(allowed_root) and not workspace_in_jail,
                )
                self._assert_named_storage_backends(
                    owner_row.user_id,
                    parsed_profile_cfg.get("backend"),
                )
            lifted = extract_profile_from_config(parsed_profile_cfg)
            kwargs["config_json"] = dumps_config(parsed_profile_cfg)
            for key, value in lifted.items():
                kwargs.setdefault(key, value)
        if "default_model" in kwargs:
            model_owner = self._repos.agent_repo.get(agent_id)
            if model_owner is not None and model_owner.user_id is not None:
                self._assert_model_ref(model_owner.user_id, kwargs.get("default_model"))
        new_name = kwargs.get("name")
        if isinstance(new_name, str):
            row = self._repos.agent_repo.get(agent_id)
            if row is None:
                raise OctopError(ErrorCode.AGENT_NOT_FOUND, f"agent {agent_id!r} not found")
            if new_name != row.name:
                self._assert_agent_name_available(
                    row.user_id,
                    new_name,
                    exclude_agent_id=agent_id,
                )
        self._repos.agent_repo.update_config(agent_id, **kwargs)
        row = self._repos.agent_repo.get(agent_id)
        if row is None:
            raise OctopError(ErrorCode.AGENT_NOT_FOUND, f"agent {agent_id!r} not found")
        self._schedule_reload(agent_id)
        return row

    async def set_shared(self, agent_id: str, shared: bool) -> AgentRow:
        """Persist whether other users may access this agent."""
        existing = self._repos.agent_repo.get(agent_id)
        if existing is None:
            raise OctopError(ErrorCode.AGENT_NOT_FOUND, f"agent {agent_id!r} not found")
        from octop.infra.agents.teams import is_team_agent

        if shared and is_team_agent(existing):
            raise OctopError(ErrorCode.TEAM_NOT_SHAREABLE, "teams cannot be shared")
        self._repos.agent_repo.set_shared(agent_id, shared)
        row = self._repos.agent_repo.get(agent_id)
        if row is None:
            raise OctopError(ErrorCode.AGENT_NOT_FOUND, f"agent {agent_id!r} not found")
        return row

    def set_icon_url(self, agent_id: str, icon_url: str | None) -> AgentRow:
        """Persist display avatar URL without reloading the harness agent."""
        row = self._repos.agent_repo.get(agent_id)
        if row is None:
            raise OctopError(ErrorCode.AGENT_NOT_FOUND, f"agent {agent_id!r} not found")
        self._repos.agent_repo.update_config(agent_id, icon_url=icon_url)
        updated = self._repos.agent_repo.get(agent_id)
        if updated is None:
            raise OctopError(ErrorCode.AGENT_NOT_FOUND, f"agent {agent_id!r} not found")
        return updated

    async def delete(self, agent_id: str) -> None:
        """Remove agent from DB, harness runtime, workspace, memory, and checkpoints.

        Checkpoint rows and Postgres memory namespaces are not foreign keys
        of ``agents``. They are deleted before the agent row. If that purge
        fails, the row stays so the delete can be retried.
        """
        row = self._repos.agent_repo.get(agent_id)
        if row is None:
            raise OctopError(ErrorCode.AGENT_NOT_FOUND, f"agent {agent_id!r} not found")
        self._teams.assert_can_delete_agent(agent_id)
        from octop.infra.agents.memory.thread_cleanup import (  # noqa: PLC0415
            agent_config_from_row,
            delete_agent_memory_and_checkpoints,
        )
        from octop.infra.agents.teams import is_team_agent

        affected_teams: list[str] = []
        thread_ids = self._repos.thread_repo.list_ids_for_agent(agent_id)
        workspace_dir = self.resolve_workspace_dir(agent_id, persist_if_missing=False)
        async with self._lock:
            if not is_team_agent(row):
                try:
                    affected_teams = self._teams.drop_member(agent_id)
                except Exception:
                    logger.exception("failed to drop deleted expert %s from team rosters", agent_id)
            await asyncio.to_thread(self._quiesce_octop_memory, agent_id)
            await self._release_pool_for_agent(agent_id)
            await self._harness_manager.aremove_agent(agent_id)  # type: ignore[union-attr]
        self._bootstrap_known.pop(agent_id, None)
        self._plugin_tool_labels.pop(agent_id, None)
        # Agent deleted: drop every DSH session cursor and its snapshot.
        self._dsh().discard_agent(agent_id)
        cfg = agent_config_from_row(row)
        await asyncio.to_thread(
            delete_agent_memory_and_checkpoints,
            agent_id=agent_id,
            thread_ids=thread_ids,
            cfg=cfg,
            octop_config=self._config,
            workspace_dir=workspace_dir,
            paths=self._paths,
        )
        try:
            from octop.infra.agents.workspace.dir import remove_agent_host_dirs  # noqa: PLC0415

            await asyncio.to_thread(
                remove_agent_host_dirs, cfg, paths=self._paths, agent_id=agent_id
            )
        except OSError:
            logger.exception("rmtree failed for %s; agent removed from DB anyway", workspace_dir)
        self._repos.agent_repo.delete(agent_id)
        from octop.infra.users.groups import RESOURCE_EXPERT, GroupAccess  # noqa: PLC0415

        GroupAccess(self._repos).clear(RESOURCE_EXPERT, agent_id)
        if self._proactive_scheduler is not None:
            self._proactive_scheduler.cancel(agent_id)
        self._repos.audit_repo.write(actor=ACTOR_SYSTEM, action="agent.delete", target=agent_id)
        for team_id in affected_teams:
            try:
                await self.reload(team_id)
            except Exception:
                logger.exception("failed to reload team %s after dropping %s", team_id, agent_id)


__all__ = ["AgentCrudMixin", "validate_custom_agent_id"]
