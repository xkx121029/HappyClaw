"""DSH prompt assembly and skill injection, projected onto Octop.

Public surface:

* :class:`SectionRegistry` collects static sections and assembles them in DSH
  order.
* :func:`plan_octop_prompt` maps those sections into Octop's prompt zones.
* :class:`SkillInjectionCursor` emits only changed skill listings per turn.

Text is always static; provider callables from DSH are intentionally not
accepted, so two identical requests assemble identical prompts.
"""

from __future__ import annotations

from happyclaw.infra.dsh.prompts.errors import (
    DshPromptError,
    DshPromptErrorCode,
    DuplicateSectionError,
    InvalidSectionError,
    MalformedPromptVariableError,
    MultipleCompleteSectionsError,
    UndefinedPromptVariableError,
    UnknownPromptVariableError,
)
from happyclaw.infra.dsh.prompts.sections import (
    CONTEXT_ZONES,
    SECTION_ORDERS,
    SKILLS_SECTION_ORDER,
    SYSTEM_ZONES,
    ZONE_ORDERS,
    OctopPromptPlan,
    OctopPromptSection,
    PromptSection,
    SectionRegistry,
    interpolate_text,
    plan_octop_prompt,
    render_prompt,
)
from happyclaw.infra.dsh.prompts.skills_injection import (
    SkillInjectionCursor,
    SkillPromptDelta,
    SkillPromptEntry,
    SkillPromptSnapshot,
    build_dsh_skills_section,
    snapshot_from_summaries,
)

__all__ = [
    "CONTEXT_ZONES",
    "SECTION_ORDERS",
    "SKILLS_SECTION_ORDER",
    "SYSTEM_ZONES",
    "ZONE_ORDERS",
    "DshPromptError",
    "DshPromptErrorCode",
    "DuplicateSectionError",
    "InvalidSectionError",
    "MalformedPromptVariableError",
    "MultipleCompleteSectionsError",
    "OctopPromptPlan",
    "OctopPromptSection",
    "PromptSection",
    "SectionRegistry",
    "SkillInjectionCursor",
    "SkillPromptDelta",
    "SkillPromptEntry",
    "SkillPromptSnapshot",
    "UndefinedPromptVariableError",
    "UnknownPromptVariableError",
    "build_dsh_skills_section",
    "interpolate_text",
    "plan_octop_prompt",
    "render_prompt",
    "snapshot_from_summaries",
]
