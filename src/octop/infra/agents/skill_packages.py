"""Skill-package mounting, composer defaults, and capability access gating.

Split out of :mod:`octop.infra.agents.manager` so AgentManager keeps a focused
lifecycle/invoke surface. Cross-mixin calls (``get_config``, ``get_agent``,
``resolve_workspace_dir``, ``_backend_spec_for_row``) are declared as stubs on
:class:`AgentManagerBase` and resolved through the MRO.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from octop.infra.agents.manager_base import AgentManagerBase
from octop.infra.agents.settings.profile import (
    dump_id_list,
    dumps_config,
    skill_package_ids_list,
)
from octop.infra.backend.resolver import (
    default_agent_backend_spec,
    resolve_agent_backend_spec,
)
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.skills.skill_package_store import SkillPackageStore


class AgentSkillPackageMixin(AgentManagerBase):
    """Persist skill packages / composer defaults and gate capability access."""

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
        from octop.infra.agents.workspace.dir import is_explicit_host_root  # noqa: PLC0415

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
            raise OctopError(ErrorCode.AGENT_NOT_FOUND, f"agent {agent_id!r} not found")
        normalized_ids = self.validate_skill_package_ids(package_ids)
        if row.user_id is not None:
            self._assert_skill_packages_visible(row.user_id, normalized_ids)
        workspace_dir = self.resolve_workspace_dir(agent_id)
        if normalized_ids and not self._backend_supports_host_skill_packages(
            self._backend_spec_for_row(row),
            workspace_dir=workspace_dir,
        ):
            raise OctopError(
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
        except OctopError:
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
                raise OctopError(
                    ErrorCode.SKILL_PACKAGE_NOT_FOUND,
                    f"skill package {package_id!r} not found",
                )
        return normalized_ids

    def _user_is_admin(self, user_id: int | None) -> bool:
        if user_id is None:
            return False
        user = self._repos.user_repo.get(user_id)
        return user is not None and user.role == "admin"

    def model_ref_allowed_for_user(self, user_id: int, model_ref: str | None) -> bool:
        from octop.infra.users.groups import model_ref_allowed

        return model_ref_allowed(
            self._repos,
            user_id=user_id,
            is_admin=self._user_is_admin(user_id),
            model_ref=model_ref,
        )

    def _assert_model_ref(self, user_id: int, model_ref: str | None) -> None:
        from octop.infra.users.groups import RESOURCE_MODEL, GroupAccess

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
        from octop.infra.backend.resolver import collect_named_storage_backend_refs
        from octop.infra.users.groups import RESOURCE_STORAGE_BACKEND, GroupAccess

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

    def _skill_package_shared_with(self, user_id: int, package: Any) -> bool:
        """Private packages stay with the owner. Groups cannot open them."""
        if self._user_is_admin(user_id):
            return True
        if str(user_id) == str(getattr(package, "created_by", "")):
            return True
        return bool(getattr(package, "shared", False))

    def _skill_package_visible(self, user_id: int, package: Any) -> bool:
        from octop.infra.users.groups import RESOURCE_SKILL_PACKAGE, GroupAccess

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
        from octop.infra.users.groups import RESOURCE_SKILL_PACKAGE, GroupAccess

        access = GroupAccess(self._repos)
        is_admin = self._user_is_admin(user_id)
        for package_id in package_ids:
            package = self._repos.skill_package_repo.get(package_id)
            if package is None:
                continue
            if not self._skill_package_shared_with(user_id, package):
                raise OctopError(ErrorCode.SKILL_PACKAGE_NOT_FOUND, "skill package not found")
            access.assert_allowed(
                user_id=user_id,
                is_admin=is_admin,
                resource_type=RESOURCE_SKILL_PACKAGE,
                resource_key=str(package.id),
                is_owner=str(user_id) == str(package.created_by),
            )

    def persist_knowledge_base_ids(self, agent_id: str, knowledge_base_ids: list[str]) -> None:
        """Persist composer knowledge-base defaults without reloading harness."""
        row = self._repos.agent_repo.get(agent_id)
        if row is None:
            raise OctopError(ErrorCode.AGENT_NOT_FOUND, f"agent {agent_id!r} not found")
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
        from octop.infra.agents.teams import is_team_agent

        row = self._repos.agent_repo.get(agent_id)
        if row is None:
            raise OctopError(ErrorCode.AGENT_NOT_FOUND, f"agent {agent_id!r} not found")
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
            raise OctopError(
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
            raise OctopError(ErrorCode.CONNECTOR_NOT_BOUND, str(exc)) from exc

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
        raise OctopError(
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
