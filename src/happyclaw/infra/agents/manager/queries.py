"""Read-only row, config and workspace queries."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
)

from happyclaw.infra.agents.manager.base import AgentManagerBase
from happyclaw.infra.agents.settings.profile import (
    dumps_config,
    extract_profile_from_config,
)
from happyclaw.infra.agents.settings.runtime_limits import (
    resolve_context_max_tokens as config_context_max_tokens,
)
from happyclaw.infra.errors import HappyclawError

if TYPE_CHECKING:
    from happyclaw.infra.db.repos.agents import AgentRow

logger = logging.getLogger(__name__)

class QueriesMixin(AgentManagerBase):
    """Read-only row, config and workspace queries."""


    def get_row(self, agent_id: str) -> AgentRow | None:
        """Look up an agent row by its public agent_id (ULID). Returns None if absent."""
        return self._repos.agent_repo.get(agent_id)


    def workspace_for_agent(self, agent_id: str) -> Any | None:
        """Return the agent's :class:`BackendWorkspace`.

        Reuses the live harness agent's workspace when the agent is running;
        only falls back to building a fresh backend from the row's spec when
        no live handle exists (agent stopped, failed, or harness not booted).
        """
        row = self.get_row(agent_id)
        if row is None:
            return None
        if self._harness_manager is not None:
            try:
                return self._harness_manager.get_agent(agent_id).agent.workspace
            except KeyError:
                pass
        return self._backend_workspace_for_row(row)


    def list_agents(self, user_id: int) -> list[AgentRow]:
        return self._repos.agent_repo.list_by_user(user_id, include_disabled=False)


    def list_rows(self) -> list[AgentRow]:
        """Return all enabled agent rows (all users), sorted by creation time."""
        return self._repos.agent_repo.list_all(include_disabled=False)


    def resolve_user_agent(self, user_id: int, query: str) -> AgentRow | None:
        """Match an agent owned by *user_id* by id suffix, full id, or name."""
        q = query.strip()
        if not q:
            return None
        rows = self.list_agents(user_id)
        ql = q.lower()
        for row in rows:
            if row.agent_id == q or row.agent_id.endswith(q):
                return row
        for row in rows:
            if row.name.lower() == ql:
                return row
        partial = [r for r in rows if ql in r.name.lower()]
        return partial[0] if len(partial) == 1 else None


    def get_config(self, agent_id: str) -> dict[str, Any]:
        """Return harness config for agent_id, overlaying column skill_package_ids."""
        row = self._repos.agent_repo.get(agent_id)
        if row is None:
            return {}
        return self._agent_config_dict(row)


    def persist_harness_config(self, agent_id: str, cfg: dict[str, Any], **extra: Any) -> None:
        """Write harness keys to ``config_json`` and lift leftover profile fields.

        ``dumps_config`` strips profile keys (including ``skill_package_ids``). If those
        still only live in the dict, copy them onto empty columns so a later overlay
        does not drop mounts.
        """
        cfg = self._preserve_internal_layout(agent_id, cfg)
        lifted = extract_profile_from_config(cfg)
        row = self._repos.agent_repo.get(agent_id)
        kwargs: dict[str, Any] = {"config_json": dumps_config(cfg)}
        if row is not None:
            for key, value in lifted.items():
                current = getattr(row, key, None)
                if current is None or (isinstance(current, str) and not str(current).strip()):
                    kwargs[key] = value
        kwargs.update(extra)
        self._repos.agent_repo.update_config(agent_id, **kwargs)


    def resolve_workspace_dir(self, agent_id: str, *, persist_if_missing: bool = True) -> Path:
        """On-disk workspace for Octop host FS ops (delete, memory path, …).

        May map agent-facing ``/.octop/workspaces/…`` onto scoped ``root_dir``.
        ``_build_harness_config`` parses the persisted string directly from
        config — do not route harness through this host join.
        """
        from happyclaw.infra.agents.workspace.dir import (  # noqa: PLC0415
            neutralize_unwritable_local_root,
            resolve_workspace_host_path,
            workspace_dir_from_config,
        )

        cfg = self.get_config(agent_id)
        raw = cfg.get("workspace_dir")
        if isinstance(raw, str) and raw.strip():
            out = workspace_dir_from_config(cfg, paths=self._paths, agent_id=agent_id)
            try:
                intended = resolve_workspace_host_path(raw, cfg)
            except ValueError:
                intended = out
            if persist_if_missing and out.resolve() != intended.resolve():
                logger.warning(
                    "Agent %s: workspace %s is not writable; remapping to %s",
                    agent_id,
                    intended,
                    out,
                )
                new_cfg = neutralize_unwritable_local_root(dict(cfg))
                new_cfg["workspace_dir"] = str(out.resolve())
                if self._repos.agent_repo.get(agent_id) is not None:
                    self.persist_harness_config(agent_id, new_cfg)
            return out

        # Legacy / incomplete row: classic Octop layout only (not scoped create default).
        out = self._paths.ensure_agent_workspace(agent_id)
        if persist_if_missing and self._repos.agent_repo.get(agent_id) is not None:
            new_cfg = dict(cfg)
            new_cfg["workspace_dir"] = str(out.resolve())
            self.persist_harness_config(agent_id, new_cfg)
        return out


    def is_bootstrapped(self, agent_id: str) -> bool:
        """Whether onboarding has completed for a running agent."""
        from happyclaw.infra.agents.teams import is_team_agent  # noqa: PLC0415

        # Team hosts skip BOOTSTRAP.md; they are ready as soon as the row exists.
        if is_team_agent(self.get_row(agent_id)):
            return True
        try:
            agent = self.get_agent(agent_id)
        except HappyclawError:
            return False
        if self._bootstrap_known.get(agent_id) is True:
            return True
        try:
            known = agent.is_bootstrapped()
        except HappyclawError:
            return False
        except Exception:
            logger.warning(
                "bootstrap check failed for agent %s; assuming bootstrapped",
                agent_id,
                exc_info=True,
            )
            return True
        if known:
            self._bootstrap_known[agent_id] = True
        return known


    def find_agents_using_provider(self, provider_name: str) -> list[dict[str, str]]:
        """Return agents referencing *provider_name* in config or default_model."""
        return self._providers.find_agents_using_provider(
            agent_repo=self._repos.agent_repo,
            get_config=self.get_config,
            provider_name=provider_name,
        )


    def find_agents_using_storage_backend(self, backend_name: str) -> list[dict[str, str]]:
        """Return agents whose ``config.backend`` references a storage backend by name."""
        from happyclaw.infra.backend.resolver import (
            find_agents_using_storage_backend,  # noqa: PLC0415
        )

        return find_agents_using_storage_backend(
            agent_repo=self._repos.agent_repo,
            get_config=self.get_config,
            backend_name=backend_name,
        )


    def assert_agents_deletable(self, agent_ids: Sequence[str]) -> None:
        """Raise when any owned agent has an in-flight team job."""
        for agent_id in agent_ids:
            self._teams.assert_can_delete_agent(agent_id)


    def resolve_context_max_tokens(self, agent_id: str, *, fallback: int = 128_000) -> int:
        """Return the configured context cap for *agent_id* (``max_input_length``)."""
        return config_context_max_tokens(self.get_config(agent_id), fallback=fallback)
