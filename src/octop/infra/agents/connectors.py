"""Connector / MCP orchestration for one :class:`AgentManager`.

Owns everything that used to be a block of methods on the agent manager:
per-user MCP tool caching, pre-chat tool loading, connector credential refresh
and the name mapping between a viewer's catalogue and the harness registry.

The manager keeps thin forwarding methods so existing callers and tests do not
change.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from octop_harness import HarnessAgent

from octop.infra.agents.plugins.mcp_bind import bind_custom_mcp_tools
from octop.infra.agents.security.hitl_session import apply_session_bypass
from octop.infra.agents.settings.profile import id_list_from_row
from octop.infra.agents.teams import is_team_agent
from octop.infra.connectors.builder import (
    gateway_mcp_server_names,
    inject_missing_gateway_tools,
)

if TYPE_CHECKING:
    from octop.infra.agents.manager import AgentManager

logger = logging.getLogger(__name__)

__all__ = ["ConnectorCoordinator", "attach_connector_coordinator"]


def attach_connector_coordinator(manager: AgentManager) -> ConnectorCoordinator:
    """Return the manager's MCP coordinator, creating it on first use.

    ``__init__`` attaches it eagerly, but partial constructions (tests that use
    ``object.__new__``) must not crash.
    """
    existing = getattr(manager, "connectors", None)
    if isinstance(existing, ConnectorCoordinator):
        return existing
    coordinator = ConnectorCoordinator(manager)
    manager.connectors = coordinator  # type: ignore[attr-defined]
    return coordinator


class ConnectorCoordinator:
    """User-scoped MCP tool cache and pre-chat connector preparation."""

    def __init__(self, manager: AgentManager) -> None:
        self._manager = manager
        # User-scoped custom MCP tools: (user_id, server_name, fingerprint) -> tools
        self._tool_cache: dict[tuple[int, str, str], list[Any]] = {}
        self._tool_cache_locks: dict[tuple[int, str], Any] = {}
        self._tool_cache_guard: Any = None

    # -- cache ------------------------------------------------------------

    def _locks(self) -> dict[tuple[int, str], Any]:
        return self._tool_cache_locks

    def invalidate(self, user_id: int | None = None) -> None:
        """Drop cached custom MCP tools (one user, or all users when ``None``)."""
        if user_id is None:
            self._tool_cache.clear()
            self._tool_cache_locks.clear()
            return
        for cache_key in [k for k in self._tool_cache if k[0] == user_id]:
            del self._tool_cache[cache_key]
        for lock_key in [k for k in self._tool_cache_locks if k[0] == user_id]:
            del self._tool_cache_locks[lock_key]

    # -- labels -----------------------------------------------------------

    def server_labels_for_user(self, user_id: int) -> dict[str, str]:
        labels: dict[str, str] = {}
        for inst in self._manager._connector_svc.list_instances_for_api(user_id):
            name = str(inst["mcp_server_name"])
            display_name = str(inst.get("display_name") or name)
            labels[name] = display_name.strip() or name
        return labels

    def tool_display_name(
        self,
        *,
        agent_id: str,
        user_id: int | None,
        tool_name: str,
        locale: str,
    ) -> str:
        from octop.i18n.domains.tools import resolve_tool_display_name

        uid = user_id
        if uid is None:
            row = self._manager.get_row(agent_id)
            uid = self._manager._connector_uid_for(row) if row is not None else None
        mcp_labels = self.server_labels_for_user(uid) if uid is not None else {}
        return resolve_tool_display_name(
            tool_name,
            locale,
            mcp_server_labels=mcp_labels,
            plugin_labels=self._manager._plugin_tool_labels.get(agent_id, {}),
        )

    # -- defaults ---------------------------------------------------------

    def default_servers(self, agent_id: str) -> list[str]:
        """Composer MCP servers selected on the expert for new sessions."""
        row = self._manager._repos.agent_repo.get(agent_id)
        if row is None or is_team_agent(row):
            return []
        return id_list_from_row(row, "mcp_servers")

    # -- passthrough to ConnectorService ---------------------------------

    def merge_turn_servers(
        self,
        user_id: int,
        explicit: list[str] | None,
        *,
        apply_defaults: bool | None = None,
        extra_defaults: list[str] | None = None,
        agent_owner_id: int | None = None,
    ) -> list[str] | None:
        """Resolve turn MCP servers vs default_open plus optional expert defaults."""
        return self._manager._connector_svc.merge_turn_mcp_servers(
            user_id,
            explicit,
            apply_defaults=apply_defaults,
            extra_defaults=extra_defaults,
            agent_owner_id=agent_owner_id,
        )

    def present_names_for_viewer(
        self, owner_user_id: int, viewer_user_id: int, names: list[str]
    ) -> list[str]:
        return self._manager._connector_svc.present_mcp_names_for_viewer(
            owner_user_id=owner_user_id,
            viewer_user_id=viewer_user_id,
            names=names,
        )

    def align_names_to_harness(
        self, owner_user_id: int, viewer_user_id: int, names: list[str]
    ) -> list[str]:
        return self._manager._connector_svc.align_mcp_names_to_harness(
            owner_user_id=owner_user_id,
            viewer_user_id=viewer_user_id,
            names=names,
        )

    def names_for_chips(
        self,
        owner_user_id: int,
        viewer_user_id: int,
        requested: list[str],
        harness_names: list[str],
    ) -> list[str]:
        return self._manager._connector_svc.mcp_names_for_chips(
            owner_user_id=owner_user_id,
            viewer_user_id=viewer_user_id,
            requested=requested,
            harness_names=harness_names,
        )

    # -- reload -----------------------------------------------------------

    async def reload(self, agent_id: str, *, connector_user_id: int | None = None) -> None:
        """Refresh connector OAuth tokens and reload harness MCP registrations."""
        manager = self._manager
        row = manager.get_row(agent_id)
        if row is None or is_team_agent(row):
            return
        uid = manager._connector_uid_for(row, connector_user_id=connector_user_id)
        if uid is None:
            logger.warning(
                "agent %s: skip connector reload — agent.user_id is NULL and no connector_user_id",
                agent_id,
            )
            return
        manager._connector_user_override[agent_id] = uid
        try:
            svc = manager._connector_svc
            for inst in manager._repos.connector_repo.list_visible(uid):
                if inst.status != "active":
                    continue
                await svc.ensure_fresh_credentials(inst.instance_id, inst.kind)
            await manager._reload_agent(agent_id)
        finally:
            manager._connector_user_override.pop(agent_id, None)

    async def reload_for_user(self, user_id: int) -> None:
        manager = self._manager
        self.invalidate(user_id)
        reloaded: set[str] = set()
        for row in manager._repos.agent_repo.list_by_user(user_id, include_disabled=False):
            await self.reload(row.agent_id, connector_user_id=user_id)
            reloaded.add(row.agent_id)
        # Shared agents (user_id IS NULL) still need this user's connector MCP configs.
        for row in manager._repos.agent_repo.list_all(include_disabled=False):
            if row.user_id is not None or row.agent_id in reloaded:
                continue
            await self.reload(row.agent_id, connector_user_id=user_id)

    # -- lazy tool loading ------------------------------------------------

    async def server_lock(self, user_id: int, server_name: str) -> Any:
        """Per-(user, server) lock shared by every agent loading that server."""
        import asyncio

        key = (user_id, server_name)
        if self._tool_cache_guard is None:
            self._tool_cache_guard = asyncio.Lock()
        async with self._tool_cache_guard:
            lock = self._tool_cache_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._tool_cache_locks[key] = lock
            return lock

    async def get_or_load_tools(
        self, user_id: int, server_name: str, spec: dict[str, Any]
    ) -> list[Any]:
        """Load custom MCP tools once per user/server/fingerprint; share across agents."""
        from octop_harness.mcp import aload_mcp_tools

        from octop.infra.connectors.mcp_tool_cache import (
            fingerprint_mcp_spec,
            wrap_tools_for_shared_use,
        )

        fp = fingerprint_mcp_spec(spec)
        cache_key = (user_id, server_name, fp)
        cached = self._tool_cache.get(cache_key)
        if cached is not None:
            return cached

        if self._tool_cache_guard is None:
            import asyncio

            self._tool_cache_guard = asyncio.Lock()
        async with self._tool_cache_guard:
            cached = self._tool_cache.get(cache_key)
            if cached is not None:
                return cached
            load_lock = self._tool_cache_locks.get((user_id, server_name))
            if load_lock is None:
                import asyncio

                load_lock = asyncio.Lock()
                self._tool_cache_locks[(user_id, server_name)] = load_lock

        async with load_lock:
            cached = self._tool_cache.get(cache_key)
            if cached is not None:
                return cached
            from octop.infra.utils.env_file import (
                env_file_path,
                load_env_file,
                overlay_stdio_spec_env,
            )

            global_env = load_env_file(env_file_path(self._manager._paths.root))
            load_spec = overlay_stdio_spec_env(spec, global_env)
            raw = await aload_mcp_tools({server_name: load_spec})
            from octop.infra.agents.plugins.plugin_tool_names import sanitize_plugin_tool_names

            sanitize_plugin_tool_names(raw)
            server_lock = await self.server_lock(user_id, server_name)
            wrapped = wrap_tools_for_shared_use(raw, server_lock)
            self._tool_cache[cache_key] = wrapped
            stale = [
                key
                for key in self._tool_cache
                if key[0] == user_id and key[1] == server_name and key[2] != fp
            ]
            for key in stale:
                del self._tool_cache[key]
            logger.info(
                "mcp tool cache store user=%s server=%s fingerprint=%s tools=%d",
                user_id,
                server_name,
                fp,
                len(wrapped),
            )
            return wrapped

    # -- pre-chat preparation ---------------------------------------------

    async def prepare_chat(
        self,
        agent_id: str,
        names: list[str] | None,
        *,
        connector_user_id: int | None = None,
    ) -> list[str]:
        """Ensure requested MCP servers are configured and tools loaded before chat.

        Returns server names that still have no loaded tools after reload/retry.
        """
        manager = self._manager
        if not names:
            return []
        if is_team_agent(manager.get_row(agent_id)):
            return []
        agent = manager.get_agent(agent_id)
        row = manager.get_row(agent_id)
        uid = manager._connector_uid_for(row, connector_user_id=connector_user_id) if row else None
        if uid is None and connector_user_id is not None:
            uid = connector_user_id
        owner_raw = getattr(row, "user_id", None) if row is not None else None
        owner_id = owner_raw if isinstance(owner_raw, int) else None
        requested = list(names)
        aliases: dict[str, str] = {}
        if owner_id is not None and uid is not None and owner_id != uid:
            aliases = manager._connector_svc.shared_custom_harness_aliases(owner_id)
            names = []
            for name in requested:
                mapped = aliases.get(name, name)
                if mapped not in names:
                    names.append(mapped)

        custom_configs: dict[str, Any] = {}
        load_user: dict[str, int] = {}
        if uid is not None:
            custom_configs = manager._connector_svc.custom_harness_configs(uid)
            load_user = dict.fromkeys(custom_configs, uid)
        if aliases and uid is not None and owner_id is not None:
            # Load the owner's spec when the turn asked for the shared server.
            viewer_own = set(manager._connector_svc.get_custom_servers(uid))
            owner_backed = {
                short
                for long_name, short in aliases.items()
                if long_name in requested or (short in requested and short not in viewer_own)
            }
            if owner_backed:
                owner_configs = manager._connector_svc.custom_harness_configs(owner_id)
                for name in owner_backed:
                    spec = owner_configs.get(name)
                    if isinstance(spec, dict):
                        custom_configs[name] = spec
                        load_user[name] = owner_id

        tool_set: frozenset[str] = getattr(agent, "_mcp_tool_name_set", frozenset())
        attached_raw = getattr(agent, "_mcp_attached_user", None)
        attached: dict[str, int] = attached_raw if isinstance(attached_raw, dict) else {}
        missing_tools: list[str] = []
        for name in names:
            has_tools = any(tool_name.startswith(f"{name}_") for tool_name in tool_set)
            expected = load_user.get(name)
            if has_tools and (expected is None or attached.get(name) == expected):
                continue
            missing_tools.append(name)
        logger.info(
            "prepare_chat_mcp agent=%s connector_user_id=%s requested=%s tool_count=%d missing=%s",
            agent_id,
            connector_user_id,
            names,
            len(tool_set),
            missing_tools,
        )
        if not missing_tools:
            matched = sorted(t for t in tool_set if any(t.startswith(f"{n}_") for n in names))
            logger.info(
                "prepare_chat_mcp agent=%s: MCP already ready, matching_tools=%s",
                agent_id,
                matched,
            )
            return []

        custom_missing = [n for n in missing_tools if n in custom_configs]
        builtin_missing = [n for n in missing_tools if n not in custom_configs]

        if custom_missing and uid is not None:
            for name in custom_missing:
                spec = custom_configs[name]
                if not isinstance(spec, dict) or not spec.get("transport"):
                    continue
                try:
                    tools = await self._manager._get_or_load_mcp_tools(
                        load_user.get(name, uid), name, spec
                    )
                except Exception:
                    logger.exception(
                        "prepare_chat_mcp agent=%s: failed loading custom MCP %s",
                        agent_id,
                        name,
                    )
                    continue
                if tools:
                    try:
                        bound_user = load_user.get(name, uid)
                        bind_custom_mcp_tools(
                            agent,
                            name,
                            tools,
                            user_id=bound_user if isinstance(bound_user, int) else None,
                        )
                    except Exception:
                        logger.exception(
                            "prepare_chat_mcp agent=%s: append_mcp_tools failed for %s",
                            agent_id,
                            name,
                        )
                        continue
                agent.config.mcp_server_configs[name] = dict(spec)

        gateway_missing: list[str] = []
        if builtin_missing and uid is not None:
            gateway_names = gateway_mcp_server_names(
                connector_repo=manager._repos.connector_repo,
                user_id=uid,
            )
            gateway_missing = [n for n in builtin_missing if n in gateway_names]
            builtin_missing = [n for n in builtin_missing if n not in gateway_names]

        if gateway_missing and uid is not None:
            await self.attach_gateway_tools(
                agent,
                agent_id=agent_id,
                user_id=uid,
                server_names=gateway_missing,
            )

        if builtin_missing:
            logger.info(
                "Reloading agent %s MCP tools (builtin_missing=%s)",
                agent_id,
                builtin_missing,
            )
            await self._manager.reload_connectors(agent_id, connector_user_id=connector_user_id)
            agent = manager.get_agent(agent_id)
            tool_set = getattr(agent, "_mcp_tool_name_set", frozenset())
            still_builtin = [
                n
                for n in builtin_missing
                if n in agent.config.mcp_server_configs
                and not any(t.startswith(f"{n}_") for t in tool_set)
            ]
            still_builtin.extend(
                n for n in builtin_missing if n not in agent.config.mcp_server_configs
            )
            still_builtin = sorted(set(still_builtin))
            if still_builtin:
                from octop_harness.mcp import aload_mcp_tools

                from octop.infra.utils.env_file import (
                    env_file_path,
                    load_env_file,
                    overlay_stdio_mcp_configs,
                )

                subset = {
                    n: agent.config.mcp_server_configs[n]
                    for n in still_builtin
                    if isinstance(agent.config.mcp_server_configs.get(n), dict)
                    and agent.config.mcp_server_configs[n].get("transport")
                }
                if subset:
                    logger.info(
                        "prepare_chat_mcp agent=%s: targeted MCP reload for %s",
                        agent_id,
                        sorted(subset),
                    )
                    global_env = load_env_file(env_file_path(manager._paths.root))
                    extra = await aload_mcp_tools(overlay_stdio_mcp_configs(subset, global_env))
                    if extra:
                        from octop.infra.agents.plugins.plugin_tool_names import (
                            sanitize_plugin_tool_names,
                        )

                        sanitize_plugin_tool_names(extra)
                        agent.append_mcp_tools(extra)

            # Full reload drops previously appended custom tools — re-inject from cache.
            if custom_configs and uid is not None:
                agent = manager.get_agent(agent_id)
                tool_set = getattr(agent, "_mcp_tool_name_set", frozenset())
                for name in names:
                    if name not in custom_configs:
                        continue
                    if any(t.startswith(f"{name}_") for t in tool_set):
                        continue
                    spec = custom_configs[name]
                    if not isinstance(spec, dict) or not spec.get("transport"):
                        continue
                    try:
                        tools = await self._manager._get_or_load_mcp_tools(
                            load_user.get(name, uid), name, spec
                        )
                    except Exception:
                        logger.exception(
                            "prepare_chat_mcp agent=%s: re-inject custom MCP %s failed",
                            agent_id,
                            name,
                        )
                        continue
                    if tools:
                        bound_user = load_user.get(name, uid)
                        bind_custom_mcp_tools(
                            agent,
                            name,
                            tools,
                            user_id=bound_user if isinstance(bound_user, int) else None,
                        )
                        agent.config.mcp_server_configs[name] = dict(spec)
                    tool_set = getattr(agent, "_mcp_tool_name_set", frozenset())

        agent = manager.get_agent(agent_id)
        tool_set = getattr(agent, "_mcp_tool_name_set", frozenset())
        still_missing = sorted(n for n in names if not any(t.startswith(f"{n}_") for t in tool_set))
        if still_missing:
            logger.warning(
                "prepare_chat_mcp agent=%s: tools still missing for %s",
                agent_id,
                still_missing,
            )
        if aliases:
            short_to_long = {short: long for long, short in aliases.items()}
            still_missing = [
                short_to_long[name]
                if name in short_to_long and short_to_long[name] in requested
                else name
                for name in still_missing
            ]
        return still_missing

    async def attach_gateway_tools(
        self,
        agent: HarnessAgent,
        *,
        agent_id: str,
        user_id: int,
        server_names: list[str],
    ) -> None:
        """Add gateway connector tools to the running agent without rebuilding it."""
        manager = self._manager
        repo = manager._repos.connector_repo
        if not repo.connector_feature_allows(user_id):
            return
        for inst in repo.list_visible(user_id):
            if inst.status != "active" or inst.mcp_server_name not in server_names:
                continue
            try:
                await manager._connector_svc.ensure_fresh_credentials(inst.instance_id, inst.kind)
            except Exception:
                logger.exception(
                    "prepare_chat_mcp agent=%s: credential refresh failed for %s",
                    agent_id,
                    inst.mcp_server_name,
                )
        for name in server_names:
            agent.config.mcp_server_configs.setdefault(name, {})
        extra = manager._agently_write_interrupts(user_id)
        if extra:
            current = {**(getattr(agent.config, "interrupt_on", None) or {}), **extra}
            store = getattr(manager, "_hitl_session_store", None)
            if store is not None:
                current = apply_session_bypass(current, store) or current
            agent.config.interrupt_on = current
        inject_missing_gateway_tools(
            agent,
            svc=manager._connector_svc,
            connector_repo=repo,
            user_id=user_id,
            agent_id=agent_id,
            mcp_server_configs=agent.config.mcp_server_configs,
        )
