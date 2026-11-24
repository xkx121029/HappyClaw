"""Agent start-up, backend spec resolution and workspace seeding."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
)

from happyclaw_harness import (
    HarnessAgent,
    HarnessAgentConfig,
)

from happyclaw.i18n.domains.agents import format_agent_start_error
from happyclaw.infra.agents.manager.base import AgentManagerBase
from happyclaw.infra.agents.manager.mcp import _sanitize_bound_mcp_tools
from happyclaw.infra.agents.settings.profile import (
    overlay_skill_package_ids,
    parse_config_json,
)
from happyclaw.infra.backend.docker_spec import (
    enrich_docker_backend_spec,
    inject_docker_global_environment,
)
from happyclaw.infra.backend.resolver import (
    default_agent_backend_spec,
    resolve_agent_backend_spec,
    windows_neutralize_host_root,
)
from happyclaw.infra.connectors.builder import inject_missing_gateway_tools
from happyclaw.infra.errors import (
    ErrorCode,
    HappyclawError,
)

if TYPE_CHECKING:
    from happyclaw.infra.db.repos.agents import AgentRow

logger = logging.getLogger(__name__)


async def _fill_missing_subagent_colors(agent: Any, rows: list[dict[str, Any]]) -> None:
    """Copy ``color`` from workspace frontmatter when harness omitted it."""
    missing = [row for row in rows if not str(row.get("color") or "").strip() and row.get("path")]
    if not missing:
        return
    workspace = getattr(agent, "workspace", None)
    aread = getattr(workspace, "aread_text", None)
    if not callable(aread):
        return
    from happyclaw.infra.utils.frontmatter import parse_frontmatter

    for row in missing:
        path = str(row.get("path") or "")
        try:
            text = await aread(path)
        except (OSError, TypeError, ValueError):
            continue
        if not isinstance(text, str) or not text:
            continue
        meta, _body = parse_frontmatter(text)
        color = str(meta.get("color") or "").strip()
        if color:
            row["color"] = color


class StartupMixin(AgentManagerBase):
    """Agent start-up, backend spec resolution and workspace seeding."""

    async def _complete_create_bootstrap(self, row: AgentRow) -> None:
        """Start harness runtime after create (expert files are already seeded on disk)."""
        try:
            fresh = self._repos.agent_repo.get(row.agent_id)
            if fresh is None:
                return
            agent = await self._start_agent(fresh, init_workspace=True)
            if agent is not None and fresh.template_name:
                reload = getattr(agent, "reload_subagents", None)
                if callable(reload):
                    await asyncio.to_thread(reload)
        except Exception:
            logger.exception("Deferred bootstrap failed for agent %s", row.agent_id)

    def _repair_persisted_backend_root(self, row: AgentRow) -> None:
        """Persist a workspace-scoped backend root for agents stored on the wrong drive.

        Older builds wrote the *home drive* (``C:/``) into the default expert's
        ``config.backend.root_dir`` even when ``HAPPYCLAW_HOME`` lived on another
        drive. Resolving already neutralizes that in memory; rewriting the stored
        value keeps the settings UI honest and stops the warning from repeating.
        The original value is logged first.
        """
        if os.name != "nt":
            return
        cfg = self._agent_config_dict(row)
        backend = cfg.get("backend")
        if not isinstance(backend, dict):
            return
        workspace_dir = self.resolve_workspace_dir(row.agent_id)
        fixed = windows_neutralize_host_root(
            backend, workspace_dir=workspace_dir, agent_id=row.agent_id
        )
        if not isinstance(fixed, dict) or fixed == backend:
            return
        cfg["backend"] = fixed
        self.persist_harness_config(row.agent_id, cfg)

    async def _start_agent(
        self, row: AgentRow, *, init_workspace: bool = True
    ) -> HarnessAgent | None:
        assert self._harness_manager is not None, "_start_agent called before boot()"
        self._repair_persisted_backend_root(row)
        if self._harness_manager.shared_factory is None:
            # Single-user mode: no model configured yet is a normal first-run
            # state, not an internal failure. Keep the expert reloadable by the
            # existing "needs model reload" path.
            self._repos.agent_repo.set_state(row.agent_id, "created", error=None)
            logger.info(
                "agent %s not started: no model configured (single-user first run)",
                row.agent_id,
            )
            return None
        async with self._lifecycle_lock_for(row.agent_id):
            existing = self._happyclaw_harness_or_none(row.agent_id)
            if existing is not None:
                # Idempotent: a concurrent reload/boot may have already registered.
                self._repos.agent_repo.set_state(row.agent_id, "running", error=None)
                logger.info(
                    "Agent %s (%s) already in harness registry — skip create",
                    row.agent_id,
                    row.name,
                )
                return existing
            self._bootstrap_known.pop(row.agent_id, None)
            try:
                from happyclaw.infra.agents.teams import is_team_agent  # noqa: PLC0415

                cfg, metadata, tags, user_display = self._agent_runtime_bundle(row)
                # Team hosts already have AGENTS/SOUL/MEMORY from seed_team_template.
                # Never let harness copy builtin skills just to strip them later.
                seed_workspace = init_workspace and not is_team_agent(row)
                from happyclaw.infra.utils import startup_timing as _timing  # noqa: PLC0415

                with _timing.segment("agent.create", agent_id=row.agent_id):
                    entry = await self._harness_manager.acreate_agent(
                        cfg,
                        agent_id=row.agent_id,
                        metadata=metadata,
                        tags=tags,
                        init_workspace=seed_workspace,
                    )
                with _timing.segment("agent.post_start", agent_id=row.agent_id):
                    await self._post_start_agent(row, entry.agent, cfg, user_display=user_display)
                self._repos.agent_repo.set_state(row.agent_id, "running", error=None)
                logger.info("Agent %s (%s) started", row.agent_id, row.name)
                return entry.agent
            except Exception as exc:
                recovered = self._happyclaw_harness_or_none(row.agent_id)
                if recovered is not None and self._is_already_registered_error(exc):
                    self._repos.agent_repo.set_state(row.agent_id, "running", error=None)
                    logger.warning(
                        "Agent %s create raced with another loader; using existing registry entry",
                        row.agent_id,
                    )
                    return recovered
                logger.exception("Failed to start agent %s", row.agent_id)
                self._repos.agent_repo.set_state(
                    row.agent_id,
                    "failed",
                    error=format_agent_start_error(exc),
                )
                return None

    async def _post_start_agent(
        self,
        row: AgentRow,
        agent: HarnessAgent,
        cfg: HarnessAgentConfig,
        *,
        user_display: str = "User",
    ) -> None:
        from happyclaw.infra.agents.teams import is_team_agent  # noqa: PLC0415

        team_host = is_team_agent(row)
        uid = self._connector_uid_for(row)
        if uid is not None and not team_host:
            inject_missing_gateway_tools(
                agent,
                svc=self._connector_svc,
                connector_repo=self._repos.connector_repo,
                user_id=uid,
                agent_id=row.agent_id,
                mcp_server_configs=cfg.mcp_server_configs,
            )
        if not team_host:
            _sanitize_bound_mcp_tools(agent)
        if team_host:
            self.strip_team_host_runtime_tools(row.agent_id)
        tool_set: frozenset[str] = getattr(agent, "_mcp_tool_name_set", frozenset())
        logger.info(
            "Agent %s started with mcp_servers=%s mcp_tool_count=%d tools_sample=%s",
            row.agent_id,
            sorted(agent.config.mcp_server_configs.keys()),
            len(tool_set),
            sorted(tool_set)[:8],
        )
        if not team_host:
            ws = agent.workspace
            try:
                from happyclaw.infra.agents.builtin_skills import (  # noqa: PLC0415
                    sync_octop_builtin_skills,
                )

                synced_skills = await sync_octop_builtin_skills(ws)
                logger.info(
                    "Agent %s: synced HappyClaw built-in skills=%s",
                    row.agent_id,
                    synced_skills,
                )
            except Exception:
                logger.warning(
                    "Agent %s: failed to sync HappyClaw built-in skills",
                    row.agent_id,
                    exc_info=True,
                )
            if self._plugin_manager is not None:
                agent_plugins = self.get_config(row.agent_id).get("plugins")
                await asyncio.to_thread(
                    self._plugin_manager.sync_skills_to_workspace,
                    ws,
                    agent_plugins=agent_plugins,
                )

        # Patch config when bootstrap finishes, but defer graph recompile until
        # the in-flight turn has fully drained (sync _init_graph mid-stream segfaults).
        if not team_host and not agent.is_bootstrapped():
            agent_id = row.agent_id

            def _on_bootstrap_complete() -> None:
                self._bootstrap_known[agent_id] = True
                self._mark_bootstrap_graph_refresh_pending(agent_id, agent)

            agent.on_bootstrap_complete = _on_bootstrap_complete

    def _mark_bootstrap_graph_refresh_pending(self, agent_id: str, agent: HarnessAgent) -> None:
        """Record DB-backed config updates; graph rebuild runs on the next turn."""
        row = self._repos.agent_repo.get(agent_id)
        if row is None:
            return
        agent._config.system_prompt = row.system_prompt
        if agent._config.memory == ():
            agent._config.memory = None
        self._bootstrap_graph_refresh_pending.add(agent_id)
        logger.info(
            "Bootstrap complete for agent %s — graph refresh deferred to next turn",
            agent_id,
        )

    def _apply_pending_bootstrap_graph_refresh(self, agent_id: str) -> None:
        """Recompile harness graph after bootstrap once no stream is in progress."""
        if agent_id not in self._bootstrap_graph_refresh_pending:
            return
        if self._harness_manager is None:
            return
        try:
            entry = self._harness_manager.get_agent(agent_id)
        except KeyError:
            return
        self._bootstrap_graph_refresh_pending.discard(agent_id)
        try:
            entry.agent._init_graph()
            logger.info("Bootstrap graph refresh applied for agent %s", agent_id)
        except Exception:
            logger.exception("Bootstrap graph refresh failed for agent %s", agent_id)
            self._bootstrap_graph_refresh_pending.add(agent_id)

    def _agent_config_dict(self, row: AgentRow) -> dict[str, Any]:
        cfg = parse_config_json(row.config_json)
        return overlay_skill_package_ids(cfg, row)

    def _backend_spec_for_row(
        self,
        row: AgentRow,
        *,
        cfg: dict[str, Any] | None = None,
        workspace_dir: Path | None = None,
    ) -> Any:
        if cfg is None:
            cfg = self._agent_config_dict(row)
        backend_spec = cfg.get("backend")
        if workspace_dir is None:
            workspace_dir = self.resolve_workspace_dir(row.agent_id)
        if row.user_id is not None:
            from happyclaw.infra.users.resource_policy import (
                POLICY_WORKSPACE_ROOT_DIR,
                clamp_backend_to_workspace_root,
                effective_workspace_root_dir,
                persisted_workspace_within_root,
            )

            allowed = effective_workspace_root_dir(
                self._repos.user_policy_repo.get(row.user_id, POLICY_WORKSPACE_ROOT_DIR)
            )
            # Only rewrite a root the files already live under. Creating an
            # expert persists the snapped backend before the workspace exists;
            # startup must not jail a host workspace that was seeded earlier.
            if allowed and persisted_workspace_within_root(cfg, allowed):
                try:
                    backend_spec = clamp_backend_to_workspace_root(backend_spec, allowed)
                except ValueError as exc:
                    raise HappyclawError(ErrorCode.WORKSPACE_ROOT_RESTRICTED, str(exc)) from exc
        if backend_spec is None:
            return default_agent_backend_spec(workspace_dir)
        resolved = resolve_agent_backend_spec(
            backend_spec,
            repo=self._repos.storage_backend_repo,
        )
        # Windows: the dashboard defaults local backends to root_dir "/", and
        # older builds persisted the home drive ("C:/") even when HAPPYCLAW_HOME
        # lives elsewhere. Either root resolves to a different drive than the
        # workspace and breaks path checks.
        return windows_neutralize_host_root(
            resolved, workspace_dir=workspace_dir, agent_id=row.agent_id
        )

    def resolved_backend_spec(self, agent_id: str) -> Any:
        """Backend spec for *agent_id* with Octop docker enrichments applied."""
        row = self._repos.agent_repo.get(agent_id)
        if row is None:
            return None
        return self._prepare_docker_backend(self._backend_spec_for_row(row), row)

    def _owner_username(self, row: AgentRow) -> str | None:
        if row.user_id is None:
            return None
        owner = self._repos.user_repo.get(row.user_id)
        if owner is None:
            return None
        return owner.username or None

    @staticmethod
    def _spec_is_opensandbox(spec: Any) -> bool:
        return isinstance(spec, dict) and str(spec.get("type") or "").lower() == "opensandbox"

    def _prepare_docker_backend(self, backend: Any, row: AgentRow) -> Any:
        """Inject Octop docker defaults (prefix / agent_id / username) without overwrite."""
        if not isinstance(backend, dict) or backend.get("type") != "docker":
            return backend
        from happyclaw.infra.utils.env_file import env_file_path  # noqa: PLC0415

        enriched = enrich_docker_backend_spec(
            backend,
            agent_id=row.agent_id,
            username=self._owner_username(row),
        )
        return inject_docker_global_environment(enriched, env_file_path(self._paths.root))

    def _backend_workspace_for_row(
        self,
        row: AgentRow,
        *,
        cfg: dict[str, Any] | None = None,
        workspace_dir: Path | None = None,
        allow_ephemeral_remote: bool = False,
    ) -> Any:
        """Resolve :class:`BackendWorkspace` for *row* without a running harness agent."""
        from happyclaw_harness.backends.workspace import BackendWorkspace  # noqa: PLC0415

        from happyclaw.infra.agents.workspace.dir import (
            system_files_path_from_config,  # noqa: PLC0415
        )
        from happyclaw.infra.backend.opensandbox_deps import (
            ensure_opensandbox_deps,  # noqa: PLC0415
        )
        from happyclaw.infra.backend.resolve_backend import resolve_octop_backend  # noqa: PLC0415

        if cfg is None:
            cfg = self._agent_config_dict(row)
        if workspace_dir is None:
            workspace_dir = self.resolve_workspace_dir(row.agent_id)
        backend = self._prepare_docker_backend(
            self._backend_spec_for_row(row, cfg=cfg, workspace_dir=workspace_dir),
            row,
        )
        if self._spec_is_opensandbox(backend) and not allow_ephemeral_remote:
            # Stopped-agent / seed fallback: do not create a throwaway remote sandbox.
            backend = {
                "type": "filesystem",
                "root_dir": str(workspace_dir),
                "virtual_mode": True,
            }
        elif self._spec_is_opensandbox(backend):
            ensure_opensandbox_deps(allow_install=True)
        from happyclaw.infra.backend.compat import adapt_backend_protocol  # noqa: PLC0415

        return BackendWorkspace(
            adapt_backend_protocol(resolve_octop_backend(backend, workspace_dir=workspace_dir)),
            workspace_dir,
            system_files_path=system_files_path_from_config(cfg),
        )

    async def _seed_expert_template(self, row: AgentRow, template_name: str) -> None:
        """Copy bundled expert files into the agent workspace before harness start."""
        if self._expert_catalog is None:
            logger.warning(
                "Agent %s: template_name=%r set but no expert_catalog configured; skipping",
                row.agent_id,
                template_name,
            )
            return

        expert = self._expert_catalog.get(template_name)
        if expert is None:
            logger.warning(
                "Agent %s: expert %r not found in catalog; skipping template copy",
                row.agent_id,
                template_name,
            )
            return

        from happyclaw.infra.agents.experts.catalog import (  # noqa: PLC0415
            MANIFEST_FILENAME,
            seed_expert_directory,
        )

        expert_dir = self._expert_catalog.expert_dir(template_name)
        if not expert.files and not (expert_dir / MANIFEST_FILENAME).is_file():
            return

        if self._spec_is_opensandbox(self._backend_spec_for_row(row)):
            if self._harness_manager is None:
                logger.info(
                    "Agent %s: skip expert template seed until runtime (ephemeral OpenSandbox)",
                    row.agent_id,
                )
                return
            try:
                workspace = self._harness_manager.get_agent(row.agent_id).agent.workspace
            except KeyError:
                logger.info(
                    "Agent %s: skip expert template seed until runtime (ephemeral OpenSandbox)",
                    row.agent_id,
                )
                return
        else:
            workspace = self._backend_workspace_for_row(row)
        try:
            count = await seed_expert_directory(
                expert_dir=expert_dir,
                workspace=workspace,
                seed_paths=expert.files,
            )
        except Exception as exc:
            logger.warning(
                "Agent %s: expert template %r seed failed: %s",
                row.agent_id,
                template_name,
                exc,
            )
            return
        logger.info(
            "Agent %s: seeded expert template %r (%d files)",
            row.agent_id,
            template_name,
            count,
        )
