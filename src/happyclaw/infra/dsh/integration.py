"""Wire DSH skills and prompt sections into Octop's agent runtime (opt-in).

The integration is disabled unless ``OCTOP_DSH_SKILLS_PROMPTS`` is truthy, so the
default prompt path stays byte-identical and performs no extra file I/O. When it
is enabled:

* the stable listing is folded into ``HarnessAgentConfig.system_prompt`` by
  :func:`compose_system_prompt` at graph-build time;
* per-turn changes are diffed by a session-scoped
  :class:`DshPromptSessionStore` and handed to the model through the request's
  ``configurable`` + ``DshSkillPromptMiddleware``.

No module-level mutable state is used: cursors live on the owning
``AgentManager`` instance, keyed by ``(agent_id, thread_id)``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field, replace
from pathlib import Path

from happyclaw.infra.dsh.prompts.sections import (
    SECTION_ORDERS,
    PromptSection,
    plan_octop_prompt,
)
from happyclaw.infra.dsh.prompts.skills_injection import (
    SkillInjectionCursor,
    SkillPromptSnapshot,
    build_dsh_skills_section,
    snapshot_from_summaries,
)
from happyclaw.infra.dsh.skills import DshSkillError, DshSkillRoot, discover_skill_root

__all__ = [
    "DSH_SKILLS_PROMPTS_ENV",
    "DSH_SKILLS_STRICT_ENV",
    "WORKSPACE_SKILLS_RANK",
    "DshPromptSession",
    "DshPromptSessionStore",
    "compose_system_prompt",
    "dsh_skills_prompts_enabled",
    "dsh_skills_strict_enabled",
    "workspace_skill_snapshot",
]

logger = logging.getLogger(__name__)

DSH_SKILLS_PROMPTS_ENV = "OCTOP_DSH_SKILLS_PROMPTS"
DSH_SKILLS_STRICT_ENV = "OCTOP_DSH_SKILLS_STRICT"

# Custom rank: the workspace tree is a project-level source in DSH terms.
WORKSPACE_SKILLS_RANK = 300

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def dsh_skills_prompts_enabled() -> bool:
    """Return whether the opt-in DSH prompt integration is on (default: off)."""

    raw = os.environ.get(DSH_SKILLS_PROMPTS_ENV, "")
    return raw.strip().lower() in _TRUTHY


def dsh_skills_strict_enabled() -> bool:
    """Return whether a skill parse error must fail the turn (default: degrade)."""

    raw = os.environ.get(DSH_SKILLS_STRICT_ENV, "")
    return raw.strip().lower() in _TRUTHY


@dataclass(frozen=True, slots=True)
class DshPromptSession:
    """Injection state for one ``(agent_id, thread_id)`` conversation."""

    cursor: SkillInjectionCursor = field(default_factory=SkillInjectionCursor)


class DshPromptSessionStore:
    """Session-scoped cursors owned by ``AgentManager`` (never process-global).

    Keyed by ``(agent_id, thread_id)``; an empty ``thread_id`` is its own key.
    Concurrency: single-user, single event loop, sequential turns. ``stream`` /
    ``call`` already serialize a thread through ``_thread_execution_lock``, so
    the same key is not touched concurrently. A caller that needs cross-thread
    access must add its own lock.
    """

    def __init__(self) -> None:
        self._sessions: dict[tuple[str, str], DshPromptSession] = {}

    def advance(
        self,
        agent_id: str,
        thread_id: str,
        snapshot: SkillPromptSnapshot,
        *,
        max_chars: int = 4000,
    ) -> str:
        """Return this turn's incremental text (``""`` when nothing changed).

        The first turn of a session seeds the cursor with the current snapshot
        and emits nothing: the stable listing is already in the graph's system
        prompt, so re-injecting it would duplicate the catalog.
        """

        key = (agent_id, thread_id)
        session = self._sessions.get(key)
        if session is None:
            self._sessions[key] = DshPromptSession(cursor=SkillInjectionCursor(snapshot))
            return ""
        text, next_cursor = session.cursor.advance(snapshot, max_chars=max_chars)
        self._sessions[key] = DshPromptSession(cursor=next_cursor)
        return text

    def discard(self, agent_id: str, thread_id: str) -> None:
        """Drop one session's cursor (thread deleted or session ended)."""

        self._sessions.pop((agent_id, thread_id), None)

    def discard_agent(self, agent_id: str) -> None:
        """Drop every cursor for an agent (agent stopped/deleted)."""

        for key in [key for key in self._sessions if key[0] == agent_id]:
            self._sessions.pop(key, None)

    def session_count(self) -> int:
        return len(self._sessions)


def workspace_skill_snapshot(
    workspace_dir: Path,
    *,
    agent_id: str = "",
    strict: bool | None = None,
) -> SkillPromptSnapshot:
    """Read ``<workspace>/skills`` into a prompt snapshot.

    A missing directory means "no skills" (DSH treats absent roots the same
    way). Malformed declarations are skipped like DSH does. A path that escapes
    the skills root (or any other parse error) does **not** break the turn by
    default: it is logged as a warning and this build injects no skills, so a
    single bad package cannot take the conversation down. Set
    ``OCTOP_DSH_SKILLS_STRICT=1`` (or pass ``strict=True``) to raise instead.
    """

    root = workspace_dir / "skills"
    if not root.is_dir():
        return SkillPromptSnapshot()
    try:
        summaries = discover_skill_root(
            DshSkillRoot(path=root, source="workspace", rank=WORKSPACE_SKILLS_RANK)
        )
    except DshSkillError as exc:
        effective_strict = strict if strict is not None else dsh_skills_strict_enabled()
        if effective_strict:
            raise
        logger.warning(
            "DSH skill discovery failed; skipping skill injection for this build "
            "(agent=%s root=%s code=%s): %s",
            agent_id or "<unknown>",
            root,
            exc.code.value,
            exc,
        )
        return SkillPromptSnapshot()
    return snapshot_from_summaries(summaries)


def compose_system_prompt(
    base_prompt: str | None,
    snapshot: SkillPromptSnapshot,
) -> str | None:
    """Fold the DSH skills section into ``base_prompt`` deterministically.

    Pure: same inputs render the same bytes. An empty snapshot returns the base
    prompt untouched, so enabling the flag without skills changes nothing.
    """

    if not snapshot.entries:
        return base_prompt

    sections: list[PromptSection] = []
    if base_prompt:
        sections.append(
            PromptSection(
                name="octop:persona",
                order=SECTION_ORDERS["DEPLOYMENT_PERSONA_PREFIX"],
                text=base_prompt,
                interpolate=False,
                zone="persona",
            )
        )
    sections.append(replace(build_dsh_skills_section(snapshot), interpolate=False))
    return plan_octop_prompt(sections).render_system()
