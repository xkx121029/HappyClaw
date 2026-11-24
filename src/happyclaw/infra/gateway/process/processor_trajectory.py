"""Turn trajectory capture: start context, system prompt, workspace files and skills."""

from __future__ import annotations

from typing import (
    Any,
    Literal,
)

from happyclaw.infra.agents.settings.profile import parse_config_json
from happyclaw.infra.gateway.process.agent_resolve import harness_workspace_for_agent
from happyclaw.infra.gateway.process.processor_base import GlobalProcessorBase, logger
from happyclaw.infra.history.trajectory.settings import agent_trajectory_enabled


def _mcp_server_names(raw: Any) -> list[str] | None:
    if isinstance(raw, list):
        names = [str(item).strip() for item in raw if str(item).strip()]
        return names or None
    if isinstance(raw, dict):
        names = [str(key).strip() for key in raw if str(key).strip()]
        return names or None
    return None


class ProcessorTrajectoryMixin(GlobalProcessorBase):
    """回合轨迹观测：起始上下文、系统提示、工作区文件与技能名单。"""

    def _agent_trajectory_enabled(self, agent_id: str, row: Any | None = None) -> bool:
        if self._trajectory_service is None:
            return False
        agent_row = row if row is not None else self._agent_repo.get(agent_id)
        if agent_row is None:
            return False
        return agent_trajectory_enabled(parse_config_json(getattr(agent_row, "config_json", None)))

    def _observe_trajectory(
        self,
        *,
        agent_id: str,
        thread_id: str,
        chunk: dict[str, Any],
        enabled: bool | None = None,
    ) -> None:
        if enabled is False:
            return
        if enabled is None and not self._agent_trajectory_enabled(agent_id):
            return
        service = self._trajectory_service
        if service is None:
            return
        # Capture before this chunk is stored. A user chunk advances the turn,
        # and a context row finalizes any open assistant message — doing this
        # after the chunk would pin the previous prompt on the new turn and
        # split the reply that is still streaming.
        self._sync_memory_prompt_trajectory(agent_id, thread_id)
        try:
            service.observe_chunk(agent_id, thread_id, chunk)
        except Exception:
            logger.exception(
                "trajectory observe_chunk failed agent=%s thread=%s",
                agent_id,
                thread_id,
            )

    def _finish_trajectory(
        self,
        *,
        thread_id: str,
        usage: dict[str, Any] | None = None,
        enabled: bool | None = None,
    ) -> None:
        if enabled is False:
            return
        service = self._trajectory_service
        if service is None:
            return
        try:
            service.finish_turn(thread_id, usage)
        except Exception:
            record_failure = getattr(service, "record_failure", None)
            if callable(record_failure):
                record_failure(thread_id)
            logger.exception("trajectory finish_turn failed thread=%s", thread_id)

    async def _observe_turn_start_context(
        self,
        *,
        agent_id: str,
        thread_id: str,
        request: dict[str, Any],
        meta: dict[str, Any],
        phase: Literal["system", "context"] = "context",
        trajectory_enabled: bool | None = None,
    ) -> None:
        """Emit SYSTEM / CONTEXT from harness injection sources of truth."""
        if trajectory_enabled is False:
            return
        if trajectory_enabled is None and not self._agent_trajectory_enabled(agent_id):
            return
        service = self._trajectory_service
        if service is None:
            return
        try:
            from happyclaw.infra.history.trajectory.turn_context import (  # noqa: PLC0415
                build_turn_start_chunks,
                filter_turn_skill_names,
            )

            include_system = phase == "system" and not bool(service.has_kind(thread_id, "system"))
            system_prompt = self._trajectory_system_prompt(agent_id) if phase == "system" else None
            skills: list[str] | None = None
            skills_filter_present = False
            mcp_names: list[str] | None = None
            workspace_files: list[tuple[str, str]] = []
            captures_model_system = False
            if phase == "context":
                skills_filter_present = "skills" in request or "skills" in meta
                turn_skills: list[str] | None = None
                if "skills" in request and isinstance(request.get("skills"), list):
                    turn_skills = [str(x) for x in request["skills"]]
                elif "skills" in meta and isinstance(meta.get("skills"), list):
                    turn_skills = [str(x) for x in meta["skills"]]
                enabled = await self._trajectory_enabled_skill_names(agent_id)
                if enabled is not None:
                    skills = filter_turn_skill_names(
                        enabled,
                        turn_skills=turn_skills,
                        skills_filter_present=skills_filter_present,
                    )
                mcp_names = _mcp_server_names(request.get("mcp_servers"))
                captures_model_system = self._captures_model_system_prompt(agent_id)
                if not captures_model_system:
                    workspace_files = [
                        (name, "") for name in await self._trajectory_workspace_files(agent_id)
                    ]
            for chunk in build_turn_start_chunks(
                include_system=include_system,
                system_prompt=system_prompt,
                workspace_files=workspace_files,
                skills=skills,
                mcp_servers=mcp_names,
                skills_filter_present=skills_filter_present,
            ):
                self._observe_trajectory(
                    agent_id=agent_id,
                    thread_id=thread_id,
                    chunk=chunk,
                    enabled=True,
                )
            if phase == "context" and captures_model_system:
                self._clear_captured_system_prompt(agent_id, thread_id)
                self._pending_system_prompt.add(thread_id)
        except Exception:
            logger.exception(
                "trajectory turn-start context failed agent=%s thread=%s",
                agent_id,
                thread_id,
            )

    def _trajectory_system_prompt(self, agent_id: str) -> str | None:
        """Live harness config prompt — same string the graph was compiled with."""
        try:
            agent = self._agent_manager.get_agent(agent_id)
            prompt = getattr(getattr(agent, "_config", None), "system_prompt", None)
            if isinstance(prompt, str) and prompt.strip():
                return prompt
        except Exception:
            logger.debug(
                "trajectory live system_prompt unavailable agent=%s",
                agent_id,
                exc_info=True,
            )
        row = self._agent_repo.get(agent_id)
        if row is not None and isinstance(row.system_prompt, str) and row.system_prompt.strip():
            return row.system_prompt
        return None

    async def _trajectory_enabled_skill_names(self, agent_id: str) -> list[dict[str, str]] | None:
        """Enabled skills from harness catalog (SoT for prompt skill section)."""
        try:
            agent = self._agent_manager.get_agent(agent_id)
            summaries = await agent.list_skill_summaries()
        except Exception:
            logger.debug(
                "trajectory skill catalog unavailable agent=%s",
                agent_id,
                exc_info=True,
            )
            return None
        rows: list[dict[str, str]] = []
        seen: set[str] = set()
        for row in summaries:
            if not isinstance(row, dict) or not row.get("enabled", True):
                continue
            name = str(row.get("name") or row.get("slug") or "").strip()
            slug = str(row.get("slug") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            item = {"name": name}
            if slug:
                item["slug"] = slug
            rows.append(item)
        return rows

    def _captures_model_system_prompt(self, agent_id: str) -> bool:
        """True when this harness build records the system message it sent."""
        try:
            agent = self._agent_manager.get_agent(agent_id)
        except Exception:
            return False
        return callable(getattr(agent, "model_system_prompt", None))

    async def _trajectory_workspace_files(self, agent_id: str) -> list[str]:
        """Existing memory paths, for harness builds that do not capture the prompt."""
        from happyclaw.infra.history.trajectory.turn_context import (
            memory_file_order,  # noqa: PLC0415
        )

        workspace = harness_workspace_for_agent(self._agent_manager, agent_id)
        if workspace is None:
            return []
        out: list[str] = []
        for name in memory_file_order():
            try:
                exists = await workspace.aexists(name)
            except Exception:
                logger.debug(
                    "trajectory workspace exists failed agent=%s path=%s",
                    agent_id,
                    name,
                    exc_info=True,
                )
                continue
            if not exists:
                continue
            out.append(name)
        return out

    def _clear_captured_system_prompt(self, agent_id: str, thread_id: str) -> None:
        """Drop the previous turn's captured system message before this turn runs."""
        try:
            agent = self._agent_manager.get_agent(agent_id)
        except Exception:
            logger.debug(
                "trajectory system prompt clear skipped agent=%s",
                agent_id,
                exc_info=True,
            )
            return
        clear = getattr(agent, "clear_model_system_prompt", None)
        if callable(clear):
            clear(thread_id)

    def _sync_memory_prompt_trajectory(self, agent_id: str, thread_id: str) -> None:
        """Store the system message from this turn's model request."""
        if thread_id not in self._pending_system_prompt:
            return
        service = self._trajectory_service
        if service is None:
            return
        try:
            agent = self._agent_manager.get_agent(agent_id)
        except Exception:
            logger.debug(
                "trajectory system prompt agent unavailable agent=%s",
                agent_id,
                exc_info=True,
            )
            return
        reader = getattr(agent, "model_system_prompt", None)
        if not callable(reader):
            return
        text = reader(thread_id)
        if not isinstance(text, str) or not text.strip():
            return
        try:
            recorded = service.record_model_system_prompt(agent_id, thread_id, text)
        except Exception:
            logger.exception(
                "trajectory system prompt sync failed agent=%s thread=%s",
                agent_id,
                thread_id,
            )
            return
        if recorded:
            self._pending_system_prompt.discard(thread_id)
            self._clear_captured_system_prompt(agent_id, thread_id)

    # -- TeamProcessor (delegates to TeamManager) ------------------------------
