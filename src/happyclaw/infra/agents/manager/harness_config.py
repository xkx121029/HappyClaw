"""Harness config assembly, peer manifest metadata and stream request preparation."""

from __future__ import annotations

import json
import logging
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
)

from happyclaw_harness import HarnessAgentConfig
from happyclaw_harness.registry import AgentEntry
from happyclaw_harness.security.models import SecurityPolicy

from happyclaw.infra.agents.manager.base import AgentManagerBase
from happyclaw.infra.agents.manager.config import skills_disabled_set
from happyclaw.infra.agents.manager.constants import _HARNESS_AGENT_CONFIG_FIELDS
from happyclaw.infra.agents.manager.memory import (
    _memory_extract_settings,
    _memory_namespace,
    _resolve_memory_backend_kwargs,
)
from happyclaw.infra.agents.security.hitl_session import apply_session_bypass
from happyclaw.infra.agents.settings.runtime_limits import apply_agent_runtime_to_stream_request
from happyclaw.infra.connectors.builder import build_mcp_server_configs_for_user
from happyclaw.infra.dsh.integration import (
    compose_system_prompt,
    dsh_skills_prompts_enabled,
    workspace_skill_snapshot,
)
from happyclaw.infra.dsh.switches import stage_enabled as dsh_stage_enabled
from happyclaw.infra.utils.locale import resolve_user_locale

if TYPE_CHECKING:
    from happyclaw.infra.db.repos.agents import AgentRow

logger = logging.getLogger(__name__)

class HarnessConfigMixin(AgentManagerBase):
    """Harness config assembly, peer manifest metadata and stream request preparation."""


    def _agent_runtime_bundle(
        self, row: AgentRow
    ) -> tuple[HarnessAgentConfig, dict[str, Any], list[str], str]:
        from happyclaw.infra.utils.browser_media import (  # noqa: PLC0415
            agent_outbound_screenshots_dir,
            configure_browser_profiles_dir,
            configure_browser_screenshots_dir,
            octop_browser_profiles_dir,
        )

        configure_browser_screenshots_dir(
            agent_outbound_screenshots_dir(self.resolve_workspace_dir(row.agent_id)),
        )
        # Shared across agents — not under a single agent workspace.
        configure_browser_profiles_dir(octop_browser_profiles_dir(self._paths))
        user_display = "User"
        if row.user_id is not None:
            owner = self._repos.user_repo.get(row.user_id)
            if owner is not None:
                user_display = owner.display_name or owner.username or user_display
        cfg = self._build_harness_config(row)
        metadata: dict[str, Any] = {
            "user_id": row.user_id,
            "description": row.description,
            "display_name": row.name,
            "icon": row.icon,
            "template_name": row.template_name,
        }
        self._apply_peer_profile_metadata(metadata, row.agent_id, row.description)
        tags: list[str] = []
        if getattr(row, "kind", None) == "team":
            tags.append("team")
        if row.template_name:
            tags.append(row.template_name)
        return cfg, metadata, tags, user_display


    def _refresh_peer_entry(self, entry: AgentEntry) -> None:
        """Re-read description / guidance cards into a running registry entry."""
        row = self._repos.agent_repo.get(entry.agent_id)
        row_desc = row.description if row is not None else None
        if row is not None and str(row.name or "").strip():
            entry.metadata["display_name"] = row.name
        self._apply_peer_profile_metadata(entry.metadata, entry.agent_id, row_desc)


    def _apply_peer_profile_metadata(
        self,
        metadata: dict[str, Any],
        agent_id: str,
        row_description: str | None,
    ) -> None:
        extra = self._peer_manifest_metadata(agent_id, row_description)
        if row_description and str(row_description).strip():
            metadata["description"] = row_description
        elif extra.get("description"):
            metadata["description"] = extra["description"]
        if "quick_prompts" not in extra:
            return
        prompts = extra["quick_prompts"]
        if isinstance(prompts, list) and prompts:
            metadata["quick_prompts"] = prompts
        else:
            metadata.pop("quick_prompts", None)


    def _peer_manifest_metadata(
        self,
        agent_id: str,
        row_description: str | None,
    ) -> dict[str, Any]:
        """Guidance cards (and fallback description) from workspace ``manifest.json``."""
        extra: dict[str, Any] = {}
        try:
            host = self.resolve_workspace_dir(agent_id, persist_if_missing=False)
        except Exception:
            return extra
        for rel in (Path(".octop") / "manifest.json", Path("manifest.json")):
            path = host / rel
            if not path.is_file():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                break
            if not isinstance(data, dict):
                break
            prompts = data.get("quick_prompts")
            extra["quick_prompts"] = prompts if isinstance(prompts, list) else []
            if not (row_description or "").strip():
                desc = data.get("description")
                if isinstance(desc, str | dict) and desc:
                    extra["description"] = desc
            break
        return extra


    def _connector_uid_for(
        self,
        row: AgentRow,
        *,
        connector_user_id: int | None = None,
    ) -> int | None:
        override = self._connector_user_override.get(row.agent_id)
        if override is not None:
            return override
        if connector_user_id is not None:
            return connector_user_id
        return row.user_id


    def _prepare_stream_request(self, agent_id: str, request: dict[str, Any]) -> dict[str, Any]:
        from happyclaw_harness.plugins import collect_plugin_tool_configs  # noqa: PLC0415

        req = dict(request)
        if req.get("agent_id") is None:
            req["agent_id"] = agent_id
        agent_cfg = self.get_config(agent_id)
        plugins_cfg = agent_cfg.get("plugins")
        tool_configs = collect_plugin_tool_configs(
            plugins_cfg if isinstance(plugins_cfg, dict) else None
        )
        if tool_configs:
            configurable = dict(req.get("configurable") or {})
            configurable["plugin_tool_configs"] = tool_configs
            req["configurable"] = configurable
        req = apply_agent_runtime_to_stream_request(req, agent_cfg)
        if dsh_skills_prompts_enabled():
            req = self._apply_dsh_skill_delta(agent_id, req)
        return req


    def _apply_dsh_skill_delta(self, agent_id: str, req: dict[str, Any]) -> dict[str, Any]:
        """Attach this turn's incremental DSH skill text, if the set changed.

        Pure bookkeeping over the per-agent snapshot cached at graph build time:
        no filesystem read happens per turn.
        """

        snapshot = self._dsh_skill_snapshots.get(agent_id)
        if snapshot is None:
            return req
        thread_id = str(req.get("thread_id") or "")
        text = self._dsh_prompt_sessions.advance(agent_id, thread_id, snapshot)
        if not text:
            return req
        configurable = dict(req.get("configurable") or {})
        configurable["dsh_skills_delta"] = text
        req["configurable"] = configurable
        return req


    def _stream_model_label(self, agent_id: str, request: dict[str, Any], thread_id: str) -> str:
        raw = request.get("model")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        cfg = request.get("configurable")
        if isinstance(cfg, dict):
            nested = cfg.get("model")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
        if thread_id:
            with suppress(Exception):
                override = self.get_thread_model(agent_id, thread_id)
                if override:
                    return override
        with suppress(Exception):
            row = self.get_row(agent_id)
            if row is not None and (row.default_model or "").strip():
                return str(row.default_model).strip()
        return ""


    def _build_harness_config(self, row: AgentRow) -> HarnessAgentConfig:
        """Convert an AgentRow into a HarnessAgentConfig."""
        from happyclaw_harness.middleware.bootstrap import bootstrap_marker_exists  # noqa: PLC0415

        from happyclaw.infra.agents.workspace.dir import (  # noqa: PLC0415
            harness_workspace_path,
            resolve_workspace_host_path,
            system_files_path_from_config,
        )

        cfg = self._agent_config_dict(row)
        raw = cfg.get("workspace_dir")
        stored = self._repos.agent_repo.get(row.agent_id) is not None
        if isinstance(raw, str) and raw.strip() and stored:
            # Host mkdir may remap an unwritable leftover (e.g. /root/.octop/…)
            # and persist the new path; re-read so harness gets that string.
            workspace_dir = self.resolve_workspace_dir(row.agent_id)
            persisted = self.get_config(row.agent_id)
            if persisted:
                cfg = persisted
            raw = cfg.get("workspace_dir")
            if isinstance(raw, str) and raw.strip():
                harness_workspace = harness_workspace_path(raw, cfg)
            else:
                harness_workspace = workspace_dir
        elif isinstance(raw, str) and raw.strip():
            # Unit tests pass an in-memory row that is not in the repo.
            harness_workspace = harness_workspace_path(raw, cfg)
            workspace_dir = resolve_workspace_host_path(raw, cfg)
            workspace_dir.mkdir(parents=True, exist_ok=True)
        else:
            # Legacy / incomplete row: backfill classic host workspace (also
            # lifts profile keys such as skill_package_ids into columns).
            workspace_dir = self.resolve_workspace_dir(row.agent_id)
            harness_workspace = workspace_dir
            persisted = self.get_config(row.agent_id)
            if persisted:
                cfg = persisted

        backend = self._backend_spec_for_row(row, cfg=cfg, workspace_dir=workspace_dir)
        ws = self._backend_workspace_for_row(
            row,
            cfg=cfg,
            workspace_dir=workspace_dir,
            allow_ephemeral_remote=self._spec_is_opensandbox(backend),
        )

        from happyclaw.infra.agents.teams import is_team_agent  # noqa: PLC0415

        team_host = is_team_agent(row)

        cron_tools: list[Any] | None = None
        if not team_host and self._cron_manager is not None:
            from happyclaw.infra.cron.tools import build_cronjob_tools  # noqa: PLC0415

            cron_tools = build_cronjob_tools(self._cron_manager)

        from happyclaw.infra.knowledge.tools import (  # noqa: PLC0415
            KnowledgeToolServices,
            build_knowledge_tools,
        )

        knowledge_tools: list[Any] = []
        if not team_host:
            knowledge_tools = build_knowledge_tools(KnowledgeToolServices(self))

        mobile_tools: list[Any] = []
        if not team_host and self._config.capabilities.mobile.enabled:
            from happyclaw.infra.control.mobile.tools import build_mobile_tools  # noqa: PLC0415

            def _mobile_workspace_for(agent_id: str) -> Any:
                # Prefer the running agent's workspace — authoritative for
                # docker / ephemeral remote sandboxes; ws is the start-time
                # fallback for the agent being configured here.
                if self._harness_manager is not None:
                    with suppress(Exception):
                        return self._harness_manager.get_agent(agent_id).agent.workspace
                return ws if agent_id == row.agent_id else None

            mobile_tools = build_mobile_tools(
                self._config,
                user_repo=self._repos.user_repo,
                workspace_for=_mobile_workspace_for,
            )

        from happyclaw_harness.plugins import PluginRegistry, build_plugin_tools  # noqa: PLC0415

        from happyclaw.infra.agents.plugins.plugin_tool_defaults import (  # noqa: PLC0415
            agent_plugin_enabled,
            expand_plugin_tools_default_on,
        )

        global_plugins = (
            self._plugin_manager.global_enabled_map() if self._plugin_manager is not None else {}
        )
        registered = [(reg.plugin_id, reg.name) for reg in PluginRegistry().all_tools()]
        agent_plugins = cfg.get("plugins")
        agent_plugins_map = agent_plugins if isinstance(agent_plugins, dict) else {}
        effective_plugins = dict(global_plugins)
        plugin_tools: list[Any] = []
        if not team_host:
            for plugin in PluginRegistry().list_plugins():
                if not agent_plugin_enabled(agent_plugins_map, plugin.manifest.id):
                    effective_plugins[plugin.manifest.id] = False
            mount_plugins = expand_plugin_tools_default_on(
                agent_plugins_map,
                registered_tools=registered,
                global_plugins=effective_plugins,
            )
            plugin_tools = build_plugin_tools(
                agent_plugins=mount_plugins,
                global_plugins=effective_plugins,
            )
        else:
            for plugin in PluginRegistry().list_plugins():
                effective_plugins[plugin.manifest.id] = False
        # Plugin authors may register tools with non-ASCII (e.g. Chinese) names,
        # which strict LLM tool-name APIs reject. Rewrite them to legal names
        # before binding, keeping the original in the description. Config keys
        # and the plugin-side closures still use the original names.
        from happyclaw.infra.agents.plugins.plugin_tool_names import (  # noqa: PLC0415
            extract_original_plugin_label,
            sanitize_plugin_tool_names,
        )

        sanitize_plugin_tool_names(
            plugin_tools,
            reserved={
                str(getattr(t, "name", ""))
                for t in [*(cron_tools or []), *knowledge_tools, *mobile_tools]
            },
        )
        self._plugin_tool_labels[row.agent_id] = {
            str(getattr(tool, "name", "")): label
            for tool in plugin_tools
            if (label := extract_original_plugin_label(str(getattr(tool, "description", "") or "")))
        }
        plugin_middleware = PluginRegistry().build_middleware_chain(
            global_enabled=effective_plugins
        )
        global_policy = self._security.harness_policy()
        agent_override = cfg.get("security") if isinstance(cfg.get("security"), dict) else None
        policy = SecurityPolicy.merge(global_policy, agent_override)

        from happyclaw.infra.agents.middleware.binary_read_guard import BinaryReadGuardMiddleware
        from happyclaw.infra.agents.middleware.browser_profile import BrowserProfileMiddleware
        from happyclaw.infra.agents.middleware.mcp_output_schema import (
            McpOutputSchemaMiddleware,
            harness_handles_mcp_tool_errors,
        )
        from happyclaw.infra.agents.middleware.octop_ui_offload import HappyclawUiOffloadMiddleware
        from happyclaw.infra.agents.middleware.reasoning import ReasoningRequestMiddleware
        from happyclaw.infra.agents.middleware.thread_artifacts import ThreadArtifactsMiddleware
        from happyclaw.infra.agents.middleware.token_quota import TokenQuotaMiddleware
        from happyclaw.infra.agents.middleware.workspace_image import (
            WorkspaceImageMaterializeMiddleware,
        )
        from happyclaw.infra.knowledge.hint import KnowledgeSearchHintMiddleware

        # FilesystemGuard + ModelSettings live in happyclaw-harness (auto-mounted).
        # BinaryReadGuard stays Octop-specific (inbound/attachment product policy).
        # ThreadArtifacts writes workspace paths onto threads after successful tools.
        # WorkspaceImageMaterialize expands path-only vision refs at model-call time.
        # HappyclawUiOffload stays innermost so every outer middleware observes the
        # slimmed content consistently; it only touches octop_ui plugin envelopes,
        # disjoint from the file-tool results ThreadArtifacts cares about.
        agent_middleware: list[Any] = [
            *plugin_middleware,
            TokenQuotaMiddleware(
                policy_repo=self._repos.user_policy_repo,
                usage_repo=self._repos.usage_repo,
            ),
            ReasoningRequestMiddleware(),
            KnowledgeSearchHintMiddleware(),
            BrowserProfileMiddleware(),
            BinaryReadGuardMiddleware(),
            *(() if harness_handles_mcp_tool_errors() else (McpOutputSchemaMiddleware(),)),
            WorkspaceImageMaterializeMiddleware(workspace=ws),
            ThreadArtifactsMiddleware(
                thread_repo=self._repos.thread_repo,
                workspace_dir=harness_workspace,
                agent_id=row.agent_id,
            ),
            HappyclawUiOffloadMiddleware(),
        ]
        if dsh_skills_prompts_enabled():
            # Only mounts when the opt-in flag is on, so the flag-off middleware
            # chain is byte-identical to before this integration existed.
            from happyclaw.infra.agents.middleware.dsh_skills_prompt import (
                DshSkillPromptMiddleware,
            )

            agent_middleware.append(DshSkillPromptMiddleware())

        merged_tools: list[Any] = []
        if cron_tools:
            merged_tools.extend(cron_tools)
        merged_tools.extend(knowledge_tools)
        merged_tools.extend(mobile_tools)
        merged_tools.extend(plugin_tools)
        # dsh:stage-tools — the only S2 insertion point. When the switch is off
        # this block neither imports the tools package nor touches the list.
        if dsh_stage_enabled("tools"):
            merged_tools.extend(self._dsh_plugin_tools(row, reserved=merged_tools))
        # agent_list / ask_agent: PeerAgentMiddleware (team_enabled=True), not config.tools.

        acp_section = cfg.get("acp")
        acp_raw: dict[str, Any] = acp_section if isinstance(acp_section, dict) else {}
        from happyclaw_harness.acp.models import ACPConfig

        if team_host:
            acp_raw = {}
            acp_config = ACPConfig.from_dict({"runners": {}})
        else:
            acp_user_id = row.user_id
            if acp_user_id is None:
                acp_user_id = self._connector_user_override.get(row.agent_id)
            runners_dict = (
                self._acp_settings.load_runners(acp_user_id) if acp_user_id is not None else {}
            )
            acp_config = ACPConfig.from_dict({"runners": runners_dict})

        system_prompt = row.system_prompt
        memory: tuple[str, ...] | None = None
        if not team_host and not bootstrap_marker_exists(ws):
            system_prompt = None
            memory = ()

        if dsh_skills_prompts_enabled() and not team_host and system_prompt:
            # Opt-in: fold the deterministic DSH skills section into the graph
            # prompt. Flag off keeps the exact previous string and reads nothing.
            snapshot = workspace_skill_snapshot(workspace_dir, agent_id=row.agent_id)
            self._dsh_skill_snapshots[row.agent_id] = snapshot
            system_prompt = compose_system_prompt(system_prompt, snapshot)

        mcp_server_configs: dict[str, Any] = {}
        if not team_host:
            uid = self._connector_uid_for(row)
            if uid is not None:
                mcp_server_configs = build_mcp_server_configs_for_user(
                    svc=self._connector_svc,
                    connector_repo=self._repos.connector_repo,
                    user_id=uid,
                    agent_id=row.agent_id,
                    agent_user_id=row.user_id,
                    config=self._config,
                )
            elif row.user_id is None:
                logger.warning(
                    "_build_harness_config agent=%s agent.user_id=NULL and no "
                    "connector_user_override — mcp_server_configs will be empty "
                    "(shared agent needs chat user id)",
                    row.agent_id,
                )

            from happyclaw.infra.utils.env_file import (  # noqa: PLC0415
                env_file_path,
                load_env_file,
                overlay_stdio_mcp_configs,
            )

            mcp_server_configs = overlay_stdio_mcp_configs(
                mcp_server_configs,
                load_env_file(env_file_path(self._paths.root)),
            )

        skill_dirs: list[str] = []
        plugin_skills_disabled: set[str] = set()
        if not team_host:
            configured_skill_dirs = self._normalize_skills_dir_config(cfg.get("skills"))
            package_skill_dirs = (
                self._resolve_skill_package_dirs(row.agent_id)
                if self._backend_supports_host_skill_packages(
                    backend,
                    workspace_dir=workspace_dir,
                )
                else []
            )
            skill_dirs = configured_skill_dirs + package_skill_dirs
            if self._plugin_manager is not None:
                for plugin_item in self._plugin_manager.list_installed():
                    plugin_id = str(plugin_item.get("id") or "")
                    if plugin_id and (
                        plugin_item.get("enabled", True) is False
                        or not agent_plugin_enabled(agent_plugins_map, plugin_id)
                    ):
                        plugin_skills_disabled.update(
                            self._plugin_manager.plugin_skill_names(plugin_id)
                        )

        from happyclaw.infra.agents.workspace.execute_env import (
            inject_agent_execute_env,  # noqa: PLC0415
        )

        backend = inject_agent_execute_env(
            self._prepare_docker_backend(backend, row),
            paths=self._paths,
            row=row,
            workspace_dir=workspace_dir,
            cfg=cfg,
        )
        # OpenSandbox.create is not idempotent — reuse the instance already
        # wrapped by ``ws`` so start does not spawn a second remote sandbox.
        # The same reuse applies when the workspace wrap adapted an older
        # read/ls surface (S3 / Postgres / COS / …) to ReadResult/LsResult.
        from happyclaw.infra.backend.compat import (  # noqa: PLC0415
            is_adapted_backend,
            is_remote_backend_spec,
        )

        harness_backend: Any = (
            ws.backend
            if (
                self._spec_is_opensandbox(backend)
                or is_adapted_backend(ws.backend)
                or is_remote_backend_spec(backend)
            )
            else backend
        )

        harness_fields: dict[str, Any] = {}
        if "decision" in _HARNESS_AGENT_CONFIG_FIELDS:
            harness_fields["decision"] = self._decision.harness_config()

        harness_cfg = HarnessAgentConfig(
            name=_memory_namespace(row.agent_id),
            workspace_dir=harness_workspace,
            system_files_path=system_files_path_from_config(cfg),
            # Owner's stored locale only. Per-message language would change
            # the cached system prefix on every switch.
            language=resolve_user_locale(
                user_repo=self._repos.user_repo,
                user_id=row.user_id or 0,
            ),
            # Memory aux LLM (extraction / promotion) needs a concrete ref; fall
            # back to the same resolution AUTO chat routing uses (active model
            # first, else first usable) — so promotion works whenever chat does.
            # Per-turn AUTO routing is unaffected: the gateway resolves models via
            # ``resolve_explicit_default_model`` directly.
            default_model=(
                self._providers.resolve_explicit_default_model(row, cfg)
                or self._resolve_configured_fallback_model_ref()
            ),
            system_prompt=system_prompt,
            memory=memory,
            backend=harness_backend,  # spec, or live OpenSandbox instance
            mcp_server_configs=mcp_server_configs,
            tools=merged_tools or None,
            middleware=agent_middleware or None,
            bootstrap_enabled=not team_host,
            acp_runners=acp_config.runners,
            acp_delegate_enabled=bool(acp_raw.get("tool_enabled", False)),
            skills_disabled=frozenset(skills_disabled_set(cfg) | plugin_skills_disabled),
            skills_dir=skill_dirs or None,
            default_timezone=self._config.default_timezone,
            media_generation=self._media_generation.harness_config(),
            **harness_fields,
            **_memory_extract_settings(cfg, is_ref_usable=self._providers.is_model_ref_usable),
            **_resolve_memory_backend_kwargs(cfg, workspace_dir=workspace_dir, config=self._config),
        )
        if "tools_disabled" in _HARNESS_AGENT_CONFIG_FIELDS:
            from happyclaw.infra.agents.settings.tool_catalog import effective_tools_disabled
            from happyclaw.infra.agents.teams import host_tools_disabled

            disabled = effective_tools_disabled(
                cfg,
                registered_plugin_tools=registered,
                global_plugins=global_plugins,
            )
            if team_host:
                disabled = set(host_tools_disabled(disabled))
            harness_cfg.tools_disabled = frozenset(disabled)
        applied = policy.apply_to_config(harness_cfg)
        applied = self._apply_team_host_config(applied, row)
        applied = self._merge_agently_write_interrupts(
            applied, self._connector_uid_for(row) if not team_host else None
        )
        interrupt_on = apply_session_bypass(applied.interrupt_on, self._hitl_session_store)
        if interrupt_on is not applied.interrupt_on:
            applied = replace(applied, interrupt_on=interrupt_on)
        if applied.model_retry_enabled:
            factory = (
                self._harness_manager.shared_factory if self._harness_manager is not None else None
            )
            get_chat_model = getattr(factory, "get_chat_model", None)
            if callable(get_chat_model):
                from happyclaw.infra.agents.middleware.model_failover import (
                    SafeModelFailoverMiddleware,
                )

                retry_middleware: Any = SafeModelFailoverMiddleware(
                    health=self._model_health,
                    candidates=lambda _current_ref, needs_multimodal: (
                        self._providers.list_auto_route_candidates(
                            needs_multimodal=needs_multimodal
                        )
                    ),
                    model_for_ref=get_chat_model,
                    max_retries=applied.model_retry_max_retries,
                    initial_delay=applied.model_retry_initial_delay,
                    max_delay=applied.model_retry_max_delay,
                    on_failure="error",
                )
            else:
                from langchain.agents.middleware import ModelRetryMiddleware

                retry_middleware = ModelRetryMiddleware(
                    max_retries=applied.model_retry_max_retries,
                    initial_delay=applied.model_retry_initial_delay,
                    max_delay=applied.model_retry_max_delay,
                    on_failure="error",
                )

            applied = replace(
                applied,
                model_retry_enabled=False,
                middleware=[
                    retry_middleware,
                    *(applied.middleware or []),
                ],
            )
        self._tool_guard_rules.ensure_seeded()
        return replace(
            applied,
            tool_guard_rules_dir=str(self._tool_guard_rules.rules_dir),
        )


    def _install_team_host_dispatch(self) -> None:
        """Team hosts always enqueue inbox work, even on harness 1.0.8 (default sync)."""
        from happyclaw.infra.agents.teams import is_team_agent
        from happyclaw.infra.agents.teams.team_manager import wire_host_dispatch

        team = getattr(self._harness_manager, "team", None)
        if team is None:
            return
        proc = self._team_processor
        room = getattr(proc, "teams", proc)
        installer = getattr(room, "install_host_dispatch", None)
        if callable(installer):
            installer(team)
            return
        wire_host_dispatch(
            team,
            is_team=lambda agent_id: is_team_agent(self.get_row(agent_id)),
            stream_peer=getattr(room, "stream_peer_to_room", None)
            or getattr(proc, "stream_team_peer_to_room", None),
            stream_host=getattr(room, "stream_host_followup_to_room", None),
            take_prompt=getattr(room, "take_peer_prompt", None)
            or getattr(proc, "take_team_peer_prompt", None),
        )


    def _agently_write_interrupts(self, user_id: int | None) -> dict[str, Any]:
        from happyclaw.infra.connectors.gateway.adapters.agently_cli import write_interrupt_on

        if user_id is None:
            return {}
        if not self._repos.connector_repo.connector_feature_allows(user_id):
            return {}
        return write_interrupt_on(
            [
                inst.mcp_server_name
                for inst in self._repos.connector_repo.list_visible(user_id)
                if inst.kind == "agently-cli" and inst.status == "active"
            ]
        )


    def _merge_agently_write_interrupts(
        self, cfg: HarnessAgentConfig, user_id: int | None
    ) -> HarnessAgentConfig:
        extra = self._agently_write_interrupts(user_id)
        if not extra:
            return cfg
        return replace(cfg, interrupt_on={**(cfg.interrupt_on or {}), **extra})


    def _apply_team_host_config(self, cfg: HarnessAgentConfig, row: Any) -> HarnessAgentConfig:
        from happyclaw.infra.agents.teams import (
            host_system_prompt,
            host_tools_disabled,
            is_team_agent,
        )

        if not is_team_agent(row):
            if "peer_invoke_mode" in _HARNESS_AGENT_CONFIG_FIELDS:
                return replace(cfg, peer_invoke_mode="sync")
            return cfg
        updates: dict[str, Any] = {}
        if "tools_disabled" in _HARNESS_AGENT_CONFIG_FIELDS:
            updates["tools_disabled"] = host_tools_disabled(
                frozenset(getattr(cfg, "tools_disabled", ()) or ())
            )
        if "team_peers" in _HARNESS_AGENT_CONFIG_FIELDS:
            updates["team_peers"] = tuple(self._teams.member_ids(row.agent_id))
        if "peer_invoke_mode" in _HARNESS_AGENT_CONFIG_FIELDS:
            updates["peer_invoke_mode"] = "async"
        if "mcp_server_configs" in _HARNESS_AGENT_CONFIG_FIELDS:
            updates["mcp_server_configs"] = {}
        if "skills_dir" in _HARNESS_AGENT_CONFIG_FIELDS:
            updates["skills_dir"] = None
        if "tools" in _HARNESS_AGENT_CONFIG_FIELDS:
            updates["tools"] = None
        if "subagents_auto_load" in _HARNESS_AGENT_CONFIG_FIELDS:
            updates["subagents_auto_load"] = False
        if "bootstrap_enabled" in _HARNESS_AGENT_CONFIG_FIELDS:
            updates["bootstrap_enabled"] = False
        if "system_prompt" in _HARNESS_AGENT_CONFIG_FIELDS:
            updates["system_prompt"] = host_system_prompt(row, self._repos.user_repo)
        return replace(cfg, **updates) if updates else cfg
