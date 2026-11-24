"""Skill packages, skill/tool toggles and skill catalog summaries."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from happyclaw.infra.agents.manager.base import AgentManagerBase
from happyclaw.infra.agents.manager.config import (
    skill_package_ids_list,
    skills_disabled_set,
)
from happyclaw.infra.agents.manager.startup import _fill_missing_subagent_colors
from happyclaw.infra.agents.settings.profile import (
    dump_id_list,
    dumps_config,
)
from happyclaw.infra.backend.resolver import (
    default_agent_backend_spec,
    resolve_agent_backend_spec,
)
from happyclaw.infra.errors import (
    ErrorCode,
    HappyclawError,
)
from happyclaw.infra.skills.presentation import (
    apply_skill_presentation,
    localize_skill_summary,
)
from happyclaw.infra.skills.skill_package_store import SkillPackageStore
from happyclaw.infra.skills.workspace_catalog import (
    list_workspace_skill_summaries,
    repair_workspace_skill_manifests,
)
from happyclaw.infra.utils.locale import Locale

logger = logging.getLogger(__name__)


class SkillsMixin(AgentManagerBase):
    """Skill packages, skill/tool toggles and skill catalog summaries."""

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
        from happyclaw.infra.agents.settings.tool_catalog import normalize_tools_disabled

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

    def _skill_package_store(self) -> SkillPackageStore:
        return SkillPackageStore(
            repo=self._repos.skill_package_repo,
            root=self._paths.skill_packages_dir,
            database=self._config.database,
        )

    def _resolve_skill_package_dirs(self, agent_id: str) -> list[str]:
        """Resolve persisted package ids to existing absolute package skill directories."""
        store = self._skill_package_store()
        row = self._repos.agent_repo.get(agent_id)
        owner_id = row.user_id if row is not None else None
        roots: list[str] = []
        for package_id in skill_package_ids_list(self.get_config(agent_id)):
            package = self._repos.skill_package_repo.get(package_id)
            if package is None:
                continue
            if owner_id is not None and not self._skill_package_visible(owner_id, package):
                continue
            roots.append(str(store.package_skills_dir(package_id).resolve()))
        return roots

    @staticmethod
    def _normalize_skills_dir_config(value: Any) -> list[str]:
        if isinstance(value, str | bytes):
            text = str(value).strip()
            return [text] if text else []
        if isinstance(value, Sequence):
            out: list[str] = []
            for item in value:
                text = str(item).strip()
                if text:
                    out.append(text)
            return out
        return []

    @staticmethod
    def _backend_supports_host_skill_packages(
        spec: Any,
        *,
        workspace_dir: Path | None = None,
    ) -> bool:
        """Local backends that can mount global package host paths via skills_dir.

        POSIX defaults use ``root_dir='/'``. Windows defaults scope the backend to
        the agent workspace (``root_dir='/'`` is unsafe across drives) — both are
        local host backends and may attach absolute ``skills_dir`` package roots.
        """
        if not isinstance(spec, dict):
            return False
        kind = str(spec.get("type") or "").lower()
        if kind not in {"local_shell", "filesystem"}:
            return False
        root_dir = str(spec.get("root_dir") or "").strip()
        if not root_dir:
            return False
        from happyclaw.infra.agents.workspace.dir import is_explicit_host_root  # noqa: PLC0415

        # ``/`` on POSIX, or a drive root (``C:/``) on Windows. Both can see the
        # host path of a global skill package.
        if is_explicit_host_root(root_dir):
            return True
        if workspace_dir is None:
            return False
        try:
            return Path(root_dir).resolve() == Path(workspace_dir).resolve()
        except OSError:
            return False

    @staticmethod
    def _backend_blocks_acp_outbound(
        spec: Any,
        *,
        workspace_dir: Path | None = None,
    ) -> bool:
        """True when a scoped directory sandbox is active for this backend.

        Used by the dashboard ACP page (via the mirrored TS helper) to lock
        runner enable/edit while viewing a jailed agent. Host-rooted local
        backends (``/``, ``\\``, or empty) and the agent workspace root are
        not treated as a jail. Non-local backends count as blocked for that
        UI. Inbound ``octop acp`` and the per-agent ``acp_runner`` tool toggle
        are unaffected.
        """
        if not isinstance(spec, dict):
            return True
        kind = str(spec.get("type") or "").lower()
        if kind not in {"local_shell", "filesystem"}:
            return True
        root_dir = str(spec.get("root_dir") or "").strip()
        if root_dir in {"", "/", "\\"}:
            return False
        if workspace_dir is not None:
            try:
                if Path(root_dir).resolve() == Path(workspace_dir).resolve():
                    return False
            except OSError:
                pass
        return True

    async def persist_skill_package_ids(self, agent_id: str, package_ids: list[str]) -> None:
        """Persist package ids after validation and hot-sync a running agent.

        Unlike :meth:`update_config_json`, this does not schedule a harness rebuild.
        Mounting packages only needs ``skills_dir`` updated so list/enable keep working.
        """
        row = self._repos.agent_repo.get(agent_id)
        if row is None:
            raise HappyclawError(ErrorCode.AGENT_NOT_FOUND, f"agent {agent_id!r} not found")
        normalized_ids = self.validate_skill_package_ids(package_ids)
        if row.user_id is not None:
            self._assert_skill_packages_visible(row.user_id, normalized_ids)
        workspace_dir = self.resolve_workspace_dir(agent_id)
        if normalized_ids and not self._backend_supports_host_skill_packages(
            self._backend_spec_for_row(row),
            workspace_dir=workspace_dir,
        ):
            raise HappyclawError(
                ErrorCode.SKILL_PACKAGE_BACKEND_UNSUPPORTED,
                "skill packages currently support only local_shell/filesystem backends "
                "with host root '/' or the agent workspace root",
            )
        cfg = self.get_config(agent_id)
        self._repos.agent_repo.update_config(
            agent_id,
            skill_package_ids=dump_id_list(normalized_ids),
            config_json=dumps_config(cfg),
        )
        self.sync_skill_package_dirs(agent_id)

    def sync_skill_package_dirs(self, agent_id: str) -> None:
        """Hot-update ``skills_dir`` on the running harness agent (no rebuild)."""
        try:
            agent = self.get_agent(agent_id)
        except HappyclawError:
            return
        row = self._repos.agent_repo.get(agent_id)
        if row is None:
            return
        cfg = self.get_config(agent_id)
        backend = self._backend_spec_for_row(row)
        workspace_dir = self.resolve_workspace_dir(agent_id)
        supports_packages = self._backend_supports_host_skill_packages(
            backend,
            workspace_dir=workspace_dir,
        )
        configured = self._normalize_skills_dir_config(cfg.get("skills"))
        package_dirs = self._resolve_skill_package_dirs(agent_id) if supports_packages else []
        skill_dirs = configured + package_dirs
        config = getattr(agent, "config", None)
        if config is None:
            config = getattr(agent, "_config", None)
        if config is not None and hasattr(config, "skills_dir"):
            config.skills_dir = skill_dirs or None
        reload = getattr(agent, "reload_subagents", None)
        if callable(reload):
            reload()
        else:
            init_graph = getattr(agent, "_init_graph", None)
            if callable(init_graph):
                init_graph()

    def validate_skill_package_ids(self, package_ids: list[str]) -> list[str]:
        """Normalize package ids and ensure each package still exists."""
        normalized_ids = skill_package_ids_list({"skill_package_ids": package_ids})
        for package_id in normalized_ids:
            if self._repos.skill_package_repo.get(package_id) is None:
                raise HappyclawError(
                    ErrorCode.SKILL_PACKAGE_NOT_FOUND,
                    f"skill package {package_id!r} not found",
                )
        return normalized_ids

    def _skill_package_shared_with(self, user_id: int, package: Any) -> bool:
        """Private packages stay with the owner. Groups cannot open them."""
        if self._user_is_admin(user_id):
            return True
        if str(user_id) == str(getattr(package, "created_by", "")):
            return True
        return bool(getattr(package, "shared", False))

    def _skill_package_visible(self, user_id: int, package: Any) -> bool:
        from happyclaw.infra.users.groups import RESOURCE_SKILL_PACKAGE, GroupAccess

        if not self._skill_package_shared_with(user_id, package):
            return False
        return GroupAccess(self._repos).allows(
            user_id=user_id,
            is_admin=self._user_is_admin(user_id),
            resource_type=RESOURCE_SKILL_PACKAGE,
            resource_key=str(package.id),
            is_owner=str(user_id) == str(package.created_by),
        )

    def _assert_skill_packages_visible(self, user_id: int, package_ids: list[str]) -> None:
        from happyclaw.infra.users.groups import RESOURCE_SKILL_PACKAGE, GroupAccess

        access = GroupAccess(self._repos)
        is_admin = self._user_is_admin(user_id)
        for package_id in package_ids:
            package = self._repos.skill_package_repo.get(package_id)
            if package is None:
                continue
            if not self._skill_package_shared_with(user_id, package):
                raise HappyclawError(ErrorCode.SKILL_PACKAGE_NOT_FOUND, "skill package not found")
            access.assert_allowed(
                user_id=user_id,
                is_admin=is_admin,
                resource_type=RESOURCE_SKILL_PACKAGE,
                resource_key=str(package.id),
                is_owner=str(user_id) == str(package.created_by),
            )

    def assert_backend_supports_skill_packages(
        self,
        backend_spec: Any | None,
        *,
        workspace_dir: Path | None = None,
    ) -> None:
        """Raise when *backend_spec* cannot mount host skill-package paths."""
        resolved_workspace = workspace_dir or self._paths.agent_workspace("_probe")
        if backend_spec is None:
            resolved = default_agent_backend_spec(resolved_workspace)
        else:
            resolved = resolve_agent_backend_spec(
                backend_spec,
                repo=self._repos.storage_backend_repo,
            )
        if self._backend_supports_host_skill_packages(
            resolved,
            workspace_dir=resolved_workspace,
        ):
            return
        raise HappyclawError(
            ErrorCode.SKILL_PACKAGE_BACKEND_UNSUPPORTED,
            "skill packages currently support only local_shell/filesystem backends "
            "with host root '/' or the agent workspace root",
        )

    async def refresh_agents_for_package(self, package_id: str) -> None:
        """Hot-sync running agents that mount a changed package."""
        for row in self._repos.agent_repo.list_all(include_disabled=False):
            if package_id not in skill_package_ids_list(self.get_config(row.agent_id)):
                continue
            self.sync_skill_package_dirs(row.agent_id)

    async def strip_skill_package_id(self, package_id: str) -> None:
        """Remove a deleted package id from every agent and hot-sync running agents."""
        for row in self._repos.agent_repo.list_all():
            cfg = self.get_config(row.agent_id)
            package_ids = skill_package_ids_list(cfg)
            if package_id not in package_ids:
                continue
            remaining = [item for item in package_ids if item != package_id]
            self._repos.agent_repo.update_config(
                row.agent_id,
                skill_package_ids=dump_id_list(remaining),
                config_json=dumps_config(cfg),
            )
            self.sync_skill_package_dirs(row.agent_id)

    async def list_skill_summaries(
        self,
        agent_id: str,
        *,
        locale: Locale | None = None,
    ) -> list[dict[str, Any]]:
        """Installed skills for *agent_id* (harness catalog + package ``kind`` labels).

        Harness lists builtin / workspace / ``skills_dir`` entries (all non-builtin as
        ``kind="workspace"``). Octop relabels mounted skill-package slugs to
        ``kind="package"`` unless the agent workspace has its own copy.
        """
        from happyclaw.infra.utils.frontmatter import parse_frontmatter

        agent = self.get_agent(agent_id)
        cfg = self.get_config(agent_id)
        workspace_dir = self.resolve_workspace_dir(agent_id)
        repaired = repair_workspace_skill_manifests(workspace_dir)
        if repaired:
            logger.warning(
                "repaired invalid UTF-8 skill manifests for agent %s: %s",
                agent_id,
                ", ".join(repaired),
            )

        try:
            harness_rows = list(await agent.list_skill_summaries())
        except (OSError, PermissionError, UnicodeDecodeError, UnicodeError) as exc:
            logger.warning(
                "harness list_skill_summaries failed for agent %s; using workspace fallback: %s",
                agent_id,
                exc,
            )
            harness_rows = list_workspace_skill_summaries(
                workspace_dir,
                skills_disabled=skills_disabled_set(cfg),
            )
        except ExceptionGroup as exc:
            # Starlette/anyio may wrap a single UnicodeDecodeError in a group.
            if not any(
                isinstance(inner, OSError | PermissionError | UnicodeDecodeError | UnicodeError)
                for inner in exc.exceptions
            ):
                raise
            logger.warning(
                "harness list_skill_summaries failed for agent %s; using workspace fallback: %s",
                agent_id,
                exc,
            )
            harness_rows = list_workspace_skill_summaries(
                workspace_dir,
                skills_disabled=skills_disabled_set(cfg),
            )
        # Surface unrepairable manifests that harness silently skipped.
        present = {
            str(row.get("slug") or "").strip()
            for row in harness_rows
            if str(row.get("slug") or "").strip()
        }
        for row in list_workspace_skill_summaries(
            workspace_dir,
            skills_disabled=skills_disabled_set(cfg),
            include_corrupt=True,
        ):
            if not row.get("corrupt"):
                continue
            slug = str(row.get("slug") or "").strip()
            if not slug or slug in present:
                continue
            harness_rows.append(row)
            logger.warning(
                "agent %s skill %s skipped: %s",
                agent_id,
                slug,
                row.get("error") or "corrupt",
            )
        from happyclaw_harness.skills import catalog as harness_skill_catalog  # noqa: PLC0415

        if getattr(harness_skill_catalog, "SKILL_PRESENTATION_METADATA_VERSION", 0) < 1:
            workspace = getattr(agent, "workspace", None)
            aread = getattr(workspace, "aread_text", None)
            if callable(aread):
                for index, row in enumerate(harness_rows):
                    if row.get("label") or row.get("display_name"):
                        continue
                    slug = str(row.get("slug") or "").strip()
                    if not slug:
                        continue
                    root = "_builtin_skills" if row.get("kind") == "builtin" else "skills"
                    manifest = await aread(f"{root}/{slug}/SKILL.md")
                    if manifest is None:
                        continue
                    meta, _body = parse_frontmatter(manifest)
                    harness_rows[index] = apply_skill_presentation(row, meta)
        package_ids = skill_package_ids_list(cfg)
        if not package_ids:
            if locale is not None:
                return [localize_skill_summary(row, locale) for row in harness_rows]
            return harness_rows

        disabled = skills_disabled_set(cfg)
        store = self._skill_package_store()
        package_by_slug: dict[str, dict[str, Any]] = {}
        for package_id in package_ids:
            if self._repos.skill_package_repo.get(package_id) is None:
                continue
            for summary in store.list_skill_summaries(package_id):
                slug = str(summary.get("slug") or "").strip()
                if not slug:
                    continue
                name = str(summary.get("name") or slug)
                package_by_slug[slug] = {
                    **summary,
                    "kind": "package",
                    "package_id": package_id,
                    "enabled": slug not in disabled and name not in disabled,
                }

        merged: dict[str, dict[str, Any]] = {}
        for row in harness_rows:
            slug = str(row.get("slug") or "").strip()
            if slug:
                merged[slug] = dict(row)

        workspace = getattr(agent, "workspace", None)
        for slug, package_row in package_by_slug.items():
            has_workspace = False
            if workspace is not None:
                aread = getattr(workspace, "aread_text", None)
                if callable(aread):
                    manifest = await aread(f"skills/{slug}/SKILL.md")
                    if manifest is not None:
                        meta, _body = parse_frontmatter(manifest)
                        has_workspace = not bool(meta.get("removed"))
            if has_workspace:
                if slug in merged:
                    merged[slug]["kind"] = "workspace"
                continue
            merged[slug] = package_row

        kind_order = {"builtin": 0, "package": 1, "workspace": 2}
        rows = sorted(
            merged.values(),
            key=lambda row: (
                kind_order.get(str(row.get("kind")), 99),
                str(row.get("slug", "")),
            ),
        )
        if locale is not None:
            return [localize_skill_summary(row, locale) for row in rows]
        return rows

    async def list_subagent_summaries(self, agent_id: str) -> list[dict[str, Any]]:
        """Installed subagents for *agent_id* (delegates to happyclaw-harness catalog)."""
        agent = self.get_agent(agent_id)
        rows = [dict(row) for row in await agent.list_subagent_summaries()]
        await _fill_missing_subagent_colors(agent, rows)
        return rows

    def sync_skills_disabled(self, agent_id: str, disabled: set[str]) -> None:
        """Push ``skills_disabled`` to the running harness agent (hot update)."""
        self.get_agent(agent_id).set_skills_disabled(disabled)

    def sync_tools_disabled(self, agent_id: str, disabled: set[str]) -> None:
        """Push ``tools_disabled`` to the running harness agent (hot update).

        No-op when the agent is not loaded — persisted config still applies on
        the next start via ``_build_harness_config``.
        """
        try:
            agent = self.get_agent(agent_id)
        except HappyclawError:
            return
        setter = getattr(agent, "set_tools_disabled", None)
        if callable(setter):
            setter(disabled)

    def strip_team_host_runtime_tools(self, agent_id: str) -> None:
        """Drop leftover MCP / connector tools on a running team host."""
        from happyclaw.infra.agents.teams import is_team_agent

        if not is_team_agent(self.get_row(agent_id)):
            return
        try:
            agent = self.get_agent(agent_id)
        except HappyclawError:
            return
        configs = getattr(agent.config, "mcp_server_configs", None)
        mcp_tools = getattr(agent, "_mcp_tools", None)
        if configs:
            agent.config.mcp_server_configs = {}
        if mcp_tools:
            replace = getattr(agent, "replace_mcp_tools", None)
            if callable(replace):
                replace([])
        self.sync_effective_tools_disabled(agent_id)

    def sync_effective_tools_disabled(self, agent_id: str) -> None:
        """Hot-sync builtin + plugin denylist derived from current agent config."""
        from happyclaw_harness.plugins import PluginRegistry

        from happyclaw.infra.agents.settings.tool_catalog import effective_tools_disabled
        from happyclaw.infra.agents.teams import host_tools_disabled, is_team_agent

        cfg = self.get_config(agent_id)
        global_plugins = (
            self._plugin_manager.global_enabled_map() if self._plugin_manager is not None else {}
        )
        registered = [(reg.plugin_id, reg.name) for reg in PluginRegistry().all_tools()]
        disabled = effective_tools_disabled(
            cfg,
            registered_plugin_tools=registered,
            global_plugins=global_plugins,
        )
        if is_team_agent(self.get_row(agent_id)):
            disabled = set(host_tools_disabled(disabled))
        self.sync_tools_disabled(agent_id, disabled)
