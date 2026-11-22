"""Harness agent config assembly (model, middleware, tools, workspace).

Split out of :mod:`octop.infra.agents.manager` so AgentManager keeps a focused
lifecycle/invoke surface. Cross-mixin calls are declared as stubs on
:class:`AgentManagerBase` and resolved through the MRO.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import fields, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from octop_harness import HarnessAgentConfig
from octop_harness.builtin.tools.ask_user import ASK_USER_TOOL_NAME
from octop_harness.security.models import SecurityPolicy

from octop.infra.agents.manager_base import AgentManagerBase
from octop.infra.agents.memory.backend import memory_backend_from_agent_config
from octop.infra.agents.memory.client import memory_namespace
from octop.infra.agents.security.hitl_session import apply_session_bypass
from octop.infra.connectors.builder import build_mcp_server_configs_for_user
from octop.infra.dsh.compat.switch import compat_enabled
from octop.infra.dsh.switches import skills_prompts_enabled as dsh_skills_prompts_enabled
from octop.infra.dsh.switches import stage_enabled as dsh_stage_enabled
from octop.infra.utils.locale import resolve_user_locale

if TYPE_CHECKING:
    from octop.infra.db.repos.agents import AgentRow

logger = logging.getLogger(__name__)


_LOCAL_BACKEND_KINDS = frozenset({"local_shell", "filesystem"})


def _scope_local_backend_to_workspace(spec: Any, workspace_dir: Path) -> Any:
    """Point local backend roots at the conversation workspace.

    Pooled runtimes are built from the expert's persisted backend, whose
    ``root_dir`` is the expert home. Project/session directories live outside
    that root, so every file tool call is rejected as "outside root directory".
    Remote backends are left untouched: their paths are container-relative.
    """
    if not isinstance(spec, dict):
        return spec
    scoped = str(workspace_dir.resolve())
    kind = spec.get("type")
    if kind in _LOCAL_BACKEND_KINDS:
        return {**spec, "root_dir": scoped}
    default = spec.get("default")
    if (
        kind == "composite"
        and isinstance(default, dict)
        and default.get("type") in _LOCAL_BACKEND_KINDS
    ):
        return {**spec, "default": {**default, "root_dir": scoped}}
    return spec


_HARNESS_AGENT_CONFIG_FIELDS = frozenset(item.name for item in fields(HarnessAgentConfig))


def skills_disabled_set(cfg: dict[str, Any]) -> set[str]:
    """Return the set of disabled skill slugs from agent config."""
    raw = cfg.get("skills_disabled")
    if isinstance(raw, list):
        return {str(x) for x in raw}
    return set()


def _memory_aux_model_settings(
    mem: dict[str, Any],
    supported_fields: frozenset[str],
    is_ref_usable: Callable[[str], bool] | None,
) -> dict[str, Any]:
    """Map the ``memory.aux_model`` ref onto both harness extraction tiers.

    A stale ref (provider deleted / model disabled since it was saved) is
    dropped with a warning so extraction falls back to the default model
    instead of failing at call time.
    """
    aux_model = mem.get("aux_model")
    if (
        not isinstance(aux_model, str)
        or not aux_model.strip()
        or "memory_aux_light_model" not in supported_fields
        or "memory_aux_heavy_model" not in supported_fields
    ):
        return {}
    ref = aux_model.strip()
    if is_ref_usable is not None and not is_ref_usable(ref):
        logger.warning(
            "memory aux_model %r no longer usable; falling back to the default model",
            ref,
        )
        return {}
    # One user-chosen model drives both extraction tiers.
    return {"memory_aux_light_model": ref, "memory_aux_heavy_model": ref}


def _memory_extract_settings(
    cfg: dict[str, Any],
    *,
    supported_fields: frozenset[str] = _HARNESS_AGENT_CONFIG_FIELDS,
    is_ref_usable: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    """Extract the ``memory`` config section into HarnessAgentConfig kwargs.

    Mirrors the shape written by the dashboard's ``PUT .../memory/extract-config``
    endpoint. Only recognized keys are forwarded; anything missing falls through
    to HarnessAgentConfig's own defaults, so an agent with no ``memory`` section
    behaves exactly as before.
    """
    mem = cfg.get("memory")
    if not isinstance(mem, dict):
        return {}
    out: dict[str, Any] = _memory_aux_model_settings(mem, supported_fields, is_ref_usable)
    for key in ("memory_enabled", "memory_capture_enabled", "memory_recall_inject_enabled"):
        if key in supported_fields and isinstance(mem.get(key), bool):
            out[key] = mem[key]
    if "memory_extract_on_session_end" in supported_fields and isinstance(
        mem.get("extract_on_session_end"), bool
    ):
        out["memory_extract_on_session_end"] = mem["extract_on_session_end"]
    mode = mem.get("extract_trigger_mode")
    if mode in ("idle", "interval") and "memory_extract_trigger_mode" in supported_fields:
        out["memory_extract_trigger_mode"] = mode
    for src, dst in (
        ("extract_idle_seconds", "memory_extract_idle_seconds"),
        ("extract_interval_seconds", "memory_extract_interval_seconds"),
    ):
        val = mem.get(src)
        if (
            dst in supported_fields
            and isinstance(val, int | float)
            and not isinstance(val, bool)
            and val > 0
        ):
            out[dst] = float(val)

    # Aux-call options (#1360): read timeouts per tier, an extraction output
    # budget, and vendor request extras for the aux LLM. Forward-compat: only
    # forwarded when the installed octop-harness knows the field.
    for src, dst in (
        ("extract_light_timeout_s", "memory_aux_light_timeout_s"),
        ("extract_heavy_timeout_s", "memory_aux_heavy_timeout_s"),
    ):
        val = mem.get(src)
        if (
            dst in supported_fields
            and isinstance(val, int | float)
            and not isinstance(val, bool)
            and val > 0
        ):
            # Older API versions accepted timeouts beyond harness limits.
            out[dst] = max(30.0, min(3600.0, float(val)))
    max_tokens = mem.get("extract_max_tokens")
    if (
        "memory_extract_max_tokens" in supported_fields
        and isinstance(max_tokens, int)
        and not isinstance(max_tokens, bool)
        and max_tokens > 0
    ):
        out["memory_extract_max_tokens"] = max(128, min(65536, max_tokens))
    thinking = mem.get("extract_thinking")
    if thinking in ("auto", "off", "on") and "memory_aux_thinking" in supported_fields:
        out["memory_aux_thinking"] = thinking
    for src, dst in (
        ("extract_max_retries", "memory_aux_max_retries"),
        ("extract_retry_backoff_s", "memory_aux_retry_backoff_s"),
    ):
        value = mem.get(src)
        if (
            dst in supported_fields
            and isinstance(value, int | float)
            and not isinstance(value, bool)
        ):
            out[dst] = value
    extra_body = mem.get("extract_extra_body")
    aux_model = mem.get("aux_model")
    has_aux_override = isinstance(aux_model, str) and bool(aux_model.strip())
    if (
        "memory_aux_extra_body" in supported_fields
        and isinstance(extra_body, dict)
        and extra_body
        and (not has_aux_override or "memory_aux_light_model" in out)
    ):
        out["memory_aux_extra_body"] = dict(extra_body)

    # octop-harness 0.9.5 predates the interval trigger fields. Keep
    # hot reload working against that release and approximate interval mode
    # with its per-session idle watchdog until a newer harness is installed.
    if (
        mode == "interval"
        and "memory_extract_trigger_mode" not in supported_fields
        and "memory_extract_idle_seconds" in supported_fields
    ):
        interval = mem.get("extract_interval_seconds")
        if isinstance(interval, int | float) and not isinstance(interval, bool) and interval > 0:
            out["memory_extract_idle_seconds"] = float(interval)
        logger.warning(
            "Installed octop-harness lacks interval memory extraction; "
            "falling back to the idle watchdog for this agent"
        )
    return out


def _resolve_memory_backend_kwargs(
    cfg: dict[str, Any],
    *,
    workspace_dir: Any,
    config: Any,
) -> dict[str, Any]:
    return memory_backend_from_agent_config(cfg, octop_config=config, workspace_dir=workspace_dir)


def _search_tools(settings_repo: Any, agent_cfg: dict[str, Any]) -> list[Any]:
    """按持久化搜索来源挂载**恰好一个**免费搜索工具。

    ``happysearch`` -> ``happysearch_search``；``searchfree`` ->
    ``searchfree_search``；``both`` -> 一个内部融合两路的
    ``happysearch_search``。绝不同时挂载两个免费工具。
    """
    from octop.infra.search.source import load_source  # noqa: PLC0415

    if agent_cfg.get("web_search_tools") is False:
        return []
    state = load_source(settings_repo)
    if state.effective == "searchfree":
        from octop.infra.search.native_tool import searchfree_search  # noqa: PLC0415

        return [searchfree_search]
    from octop.infra.search.happy_tool import build_happysearch_tool  # noqa: PLC0415

    mode = "both" if state.effective == "both" else "happysearch"
    return [build_happysearch_tool(mode=mode)]


class AgentHarnessConfigMixin(AgentManagerBase):
    """Translate an AgentRow into a HarnessAgentConfig."""

    def _build_harness_config(
        self, row: AgentRow, *, workspace_override: Path | None = None
    ) -> HarnessAgentConfig:
        """Convert an AgentRow into a HarnessAgentConfig.

        ``workspace_override`` builds a pooled instance for a project directory
        owned by this expert; expert-level state (memory) stays in the private
        ``agents/<id>`` directory.
        """
        from octop_harness.middleware.bootstrap import bootstrap_marker_exists  # noqa: PLC0415

        from octop.infra.agents.workspace.dir import (  # noqa: PLC0415
            harness_workspace_path,
            resolve_workspace_host_path,
            system_files_path_from_config,
        )

        cfg = self._agent_config_dict(row)
        raw = cfg.get("workspace_dir")
        stored = self._repos.agent_repo.get(row.agent_id) is not None
        if workspace_override is not None:
            workspace_dir = workspace_override
            harness_workspace = workspace_override
            cfg = dict(cfg)
            cfg["workspace_dir"] = str(workspace_override)
            workspace_dir.mkdir(parents=True, exist_ok=True)
        elif isinstance(raw, str) and raw.strip() and stored:
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
        if workspace_override is not None:
            backend = _scope_local_backend_to_workspace(backend, workspace_override)
            # The workspace facade must resolve virtual absolute paths against
            # the same root as the harness backend, or ``/report.html`` would
            # still land in the expert home instead of the conversation.
            cfg = dict(cfg)
            cfg["backend"] = backend
        ws = self._backend_workspace_for_row(
            row,
            cfg=cfg,
            workspace_dir=workspace_dir,
            allow_ephemeral_remote=self._spec_is_opensandbox(backend),
        )

        from octop.infra.agents.teams import is_team_agent  # noqa: PLC0415

        team_host = is_team_agent(row)

        cron_tools: list[Any] | None = None
        if not team_host and self._cron_manager is not None:
            from octop.infra.cron.tools import build_cronjob_tools  # noqa: PLC0415

            cron_tools = build_cronjob_tools(self._cron_manager)

        from octop.infra.knowledge.tools import (  # noqa: PLC0415
            KnowledgeToolServices,
            build_knowledge_tools,
        )

        knowledge_tools: list[Any] = []
        if not team_host:
            knowledge_tools = build_knowledge_tools(KnowledgeToolServices(self))

        # 设备链路（HappyClaw ↔ 手机 App）：仅已配对时挂载；离线时由
        # DeviceLinkToolGateMiddleware 把工具从模型可见列表中剔除。
        device_tools: list[Any] = []
        if not team_host:
            try:
                from octop.infra.control.device_link.agent_tools import (  # noqa: PLC0415
                    build_device_link_tools,
                )
                from octop.infra.control.device_link.manager import (  # noqa: PLC0415
                    get_device_link_manager,
                )

                if get_device_link_manager().is_paired():
                    device_tools = build_device_link_tools(
                        self._config,
                        user_repo=self._repos.user_repo,
                        cron_manager=self._cron_manager,
                    )
            except Exception:  # noqa: BLE001
                logger.warning("device link agent tools unavailable", exc_info=True)
                device_tools = []

        # 本机 adb 通道：与设备直连并列，直接调用主机 adb 操作模拟器/USB 调试手机。
        # 主机没有 adb 时不挂载，避免给模型一堆必然失败的工具。
        adb_tools: list[Any] = []
        if not team_host:
            try:
                from octop.infra.control.adb.runner import adb_available  # noqa: PLC0415
                from octop.infra.control.adb.tools import build_adb_tools  # noqa: PLC0415

                if adb_available():
                    adb_tools = build_adb_tools(user_repo=self._repos.user_repo)
            except Exception:  # noqa: BLE001
                logger.warning("adb agent tools unavailable", exc_info=True)
                adb_tools = []

        from octop_harness.plugins import PluginRegistry, build_plugin_tools  # noqa: PLC0415

        from octop.infra.agents.plugins.plugin_tool_defaults import (  # noqa: PLC0415
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
        from octop.infra.agents.plugins.plugin_tool_names import (  # noqa: PLC0415
            extract_original_plugin_label,
            sanitize_plugin_tool_names,
        )

        sanitize_plugin_tool_names(
            plugin_tools,
            reserved={
                str(getattr(t, "name", ""))
                for t in [*(cron_tools or []), *knowledge_tools, *device_tools, *adb_tools]
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

        from octop.infra.agents.middleware.binary_read_guard import BinaryReadGuardMiddleware
        from octop.infra.agents.middleware.browser_profile import BrowserProfileMiddleware
        from octop.infra.agents.middleware.conversation_context import (
            ConversationContextMiddleware,
        )
        from octop.infra.agents.middleware.mcp_output_schema import (
            McpOutputSchemaMiddleware,
            harness_handles_mcp_tool_errors,
        )
        from octop.infra.agents.middleware.octop_ui_offload import OctopUiOffloadMiddleware
        from octop.infra.agents.middleware.reasoning import ReasoningRequestMiddleware
        from octop.infra.agents.middleware.thread_artifacts import ThreadArtifactsMiddleware
        from octop.infra.agents.middleware.token_quota import TokenQuotaMiddleware
        from octop.infra.agents.middleware.workspace_image import (
            WorkspaceImageMaterializeMiddleware,
        )
        from octop.infra.knowledge.hint import KnowledgeSearchHintMiddleware

        # FilesystemGuard + ModelSettings live in octop-harness (auto-mounted).
        # BinaryReadGuard stays Octop-specific (inbound/attachment product policy).
        # ThreadArtifacts writes workspace paths onto threads after successful tools.
        # WorkspaceImageMaterialize expands path-only vision refs at model-call time.
        # OctopUiOffload stays innermost so every outer middleware observes the
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
            ConversationContextMiddleware(
                thread_repo=self._repos.thread_repo,
                project_repo=self._repos.project_repo,
                paths=self._paths,
                agent_id=row.agent_id,
                agent_name=row.name,
                workspace_dir=workspace_dir,
                default_timezone=self._config.default_timezone,
                cron_manager=self._cron_manager,
            ),
            BrowserProfileMiddleware(),
            BinaryReadGuardMiddleware(),
            *(() if harness_handles_mcp_tool_errors() else (McpOutputSchemaMiddleware(),)),
            WorkspaceImageMaterializeMiddleware(workspace=ws),
            ThreadArtifactsMiddleware(
                thread_repo=self._repos.thread_repo,
                workspace_dir=harness_workspace,
                agent_id=row.agent_id,
            ),
            OctopUiOffloadMiddleware(),
        ]
        if workspace_override is None:
            # Only the base agent serves conversations that have no workspace
            # yet; pooled instances already run inside a resolved directory.
            from octop.infra.agents.middleware.session_workspace import (  # noqa: PLC0415
                SessionWorkspaceMiddleware,
            )

            session_mw = SessionWorkspaceMiddleware(
                thread_repo=self._repos.thread_repo,
                workspace_dir=workspace_dir,
                root_dir=Path(str(backend.get("root_dir")))
                if isinstance(backend, dict) and backend.get("root_dir")
                else None,
            )
            self._session_workspace_mw[row.agent_id] = session_mw
            agent_middleware.append(session_mw)
        # Quick chats have no workspace: hide file/shell tools on every runtime
        # (base and pooled), and refuse them again at tool-call time.
        from octop.infra.agents.middleware.quick_chat_guard import (  # noqa: PLC0415
            QuickChatGuardMiddleware,
        )

        agent_middleware.append(QuickChatGuardMiddleware(thread_repo=self._repos.thread_repo))
        if device_tools:
            from octop.infra.agents.middleware.device_link_gate import (  # noqa: PLC0415
                DeviceLinkToolGateMiddleware,
            )

            agent_middleware.append(DeviceLinkToolGateMiddleware())
            # 设备副作用动作的审批必须独立于全局 HITL 开关与 onboarding 状态：
            # 自己挂一个 HumanInTheLoopMiddleware，避免 cfg.interrupt_on 在
            # 未 bootstrap / hitl 关闭时被 harness 静默丢弃。
            from langchain.agents.middleware import HumanInTheLoopMiddleware  # noqa: PLC0415

            from octop.infra.control.device_link.agent_tools import (  # noqa: PLC0415
                device_link_interrupt_on,
            )

            agent_middleware.append(
                HumanInTheLoopMiddleware(interrupt_on=device_link_interrupt_on())
            )
        if adb_tools:
            # adb 的副作用动作同样逐次审批；只读（列设备/截屏）不打断。
            from langchain.agents.middleware import HumanInTheLoopMiddleware  # noqa: PLC0415

            from octop.infra.control.adb.tools import (  # noqa: PLC0415
                adb_interrupt_on,
            )

            agent_middleware.append(HumanInTheLoopMiddleware(interrupt_on=adb_interrupt_on()))
        if dsh_skills_prompts_enabled():
            # Only mounts when the opt-in flag is on, so the flag-off middleware
            # chain is byte-identical to before this integration existed.
            from octop.infra.agents.middleware.dsh_skills_prompt import (
                DshSkillPromptMiddleware,
            )

            agent_middleware.append(DshSkillPromptMiddleware())

        merged_tools: list[Any] = []
        if cron_tools:
            merged_tools.extend(cron_tools)
        merged_tools.extend(knowledge_tools)
        if not team_host:
            from octop.infra.agents.workspace.present_file import (  # noqa: PLC0415
                build_present_file_tool,
            )

            merged_tools.append(build_present_file_tool(ws))
        merged_tools.extend(device_tools)
        merged_tools.extend(adb_tools)
        merged_tools.extend(plugin_tools)
        merged_tools.extend(_search_tools(self._repos.settings_repo, cfg))
        # dsh:stage-tools — the only S2 insertion point. When the switch is off
        # this block neither imports the tools package nor touches the list.
        if dsh_stage_enabled("tools"):
            merged_tools.extend(self._dsh_plugin_tools(row, reserved=merged_tools))
        # dsh:compat-tools — independent of the DSH tool stage. Only active when
        # OCTOP_DSH_COMPAT is on; a bundle that failed to mount contributes nothing.
        if compat_enabled():
            from octop.infra.dsh.compat.tools import compat_structured_tools  # noqa: PLC0415

            merged_tools.extend(compat_structured_tools(reserved=merged_tools))
        # agent_list / ask_agent: PeerAgentMiddleware (team_enabled=True), not config.tools.

        acp_section = cfg.get("acp")
        acp_raw: dict[str, Any] = acp_section if isinstance(acp_section, dict) else {}
        from octop_harness.acp.models import ACPConfig

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
        if workspace_override is not None:
            # Pooled runtimes (project / session conversations) act for an
            # expert already onboarded in its private workspace. The bootstrap
            # marker lives there, not in the conversation directory, so checking
            # the override path would blank the persona prompt and memory files
            # and turn the turn into a bare model request. Never run onboarding
            # inside a project or session directory either.
            bootstrap_enabled = False
        elif not team_host and not bootstrap_marker_exists(ws):
            system_prompt = None
            memory = ()
            bootstrap_enabled = True
        else:
            bootstrap_enabled = not team_host

        if dsh_skills_prompts_enabled() and not team_host and system_prompt:
            # Opt-in: fold the deterministic DSH skills section into the graph
            # prompt. Flag off keeps the exact previous string and reads nothing.
            from octop.infra.dsh.integration import (  # noqa: PLC0415
                compose_system_prompt,
                workspace_skill_snapshot,
            )

            snapshot = workspace_skill_snapshot(workspace_dir, agent_id=row.agent_id)
            self._dsh().snapshots[row.agent_id] = snapshot
            system_prompt = compose_system_prompt(system_prompt, snapshot)

        if compat_enabled() and not team_host and system_prompt:
            # DSH bundles that publish memory/system-prompt context (for example
            # auto-memory) fold their rendered sections in here. Failures are
            # swallowed inside the bridge; they never reach the chat path.
            from octop.infra.dsh.compat.prompt import compat_prompt_block  # noqa: PLC0415

            compat_block = compat_prompt_block()
            if compat_block:
                system_prompt = f"{system_prompt}\n\n{compat_block}"

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

            from octop.infra.utils.env_file import (  # noqa: PLC0415
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

        from octop.infra.agents.workspace.execute_env import (
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
        from octop.infra.backend.compat import (  # noqa: PLC0415
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
        if "web_search_tools" in _HARNESS_AGENT_CONFIG_FIELDS:
            # 始终显式传值，避免 harness 默认 "auto" 无条件带上 searchfree。
            # 这里只放已配置的商业 provider；免费来源由 Octop 自己挂载。
            from octop.infra.search.source import harness_policy, load_source  # noqa: PLC0415

            harness_fields["web_search_tools"] = harness_policy(
                load_source(self._repos.settings_repo),
                agent_cfg=cfg,
            )

        harness_cfg = HarnessAgentConfig(
            name=memory_namespace(row.agent_id),
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
            bootstrap_enabled=bootstrap_enabled,
            acp_runners=acp_config.runners,
            acp_delegate_enabled=bool(acp_raw.get("tool_enabled", False)),
            skills_disabled=frozenset(skills_disabled_set(cfg) | plugin_skills_disabled),
            skills_dir=skill_dirs or None,
            default_timezone=self._config.default_timezone,
            media_generation=self._media_generation.harness_config(),
            **harness_fields,
            **_memory_extract_settings(cfg, is_ref_usable=self._providers.is_model_ref_usable),
            **_resolve_memory_backend_kwargs(
                cfg,
                workspace_dir=(
                    self._paths.agent_workspace(row.agent_id)
                    if workspace_override is not None
                    else workspace_dir
                ),
                config=self._config,
            ),
        )
        if "tools_disabled" in _HARNESS_AGENT_CONFIG_FIELDS:
            from octop.infra.agents.settings.tool_catalog import effective_tools_disabled
            from octop.infra.agents.teams import host_tools_disabled

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
        # ``ask_user_question`` is a collaboration pause, not an approval gate:
        # the harness only interrupts while its own default flag happens to stay
        # on, and a turn that misses it runs the tool body and answers the model
        # with "No interactive user is available" (the question never reaches
        # the conversation). Pin the pause per turn so a project/session runtime
        # can never degrade that way. A user who removed the tool from the
        # agent's tool list keeps it off; nothing is re-enabled behind their back.
        ask_disabled = ASK_USER_TOOL_NAME in getattr(applied, "tools_disabled", frozenset())
        ask_rule = {
            "allowed_decisions": ["respond"],
            "description": "The agent is asking you to decide.",
        }
        if not ask_disabled and "ask_user_enabled" in _HARNESS_AGENT_CONFIG_FIELDS:
            applied = replace(applied, ask_user_enabled=True)
        if not ask_disabled and "interrupt_on" in _HARNESS_AGENT_CONFIG_FIELDS:
            applied = replace(
                applied,
                interrupt_on={**(applied.interrupt_on or {}), ASK_USER_TOOL_NAME: dict(ask_rule)},
            )
        if not ask_disabled and applied.middleware:
            # Device actions carry their own ``HumanInTheLoopMiddleware`` (it must
            # survive ``hitl.enabled=False`` and the onboarding window). deepagents
            # merges caller middleware by ``.name``, and that class name is shared
            # with the harness instance — ours therefore *replaces* it, silently
            # dropping the pause pinned above, and the tool body runs instead
            # (the "No interactive user is available" reply). Mirror the rule onto
            # the instance that actually reaches the graph.
            from langchain.agents.middleware import HumanInTheLoopMiddleware  # noqa: PLC0415

            for middleware in applied.middleware:
                if not isinstance(middleware, HumanInTheLoopMiddleware):
                    continue
                current = dict(middleware.interrupt_on or {})
                if ASK_USER_TOOL_NAME not in current:
                    middleware.interrupt_on = {**current, ASK_USER_TOOL_NAME: dict(ask_rule)}
        if applied.model_retry_enabled:
            factory = (
                self._harness_manager.shared_factory if self._harness_manager is not None else None
            )
            get_chat_model = getattr(factory, "get_chat_model", None)
            if callable(get_chat_model):
                from octop.infra.agents.middleware.model_failover import (
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
