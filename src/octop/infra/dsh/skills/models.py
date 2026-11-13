"""Source-neutral DSH skill records and their Octop projection.

A DSH skill is a directory bundle (``<skill>/SKILL.md``) or a flat
``<name>.md`` file. Both forms are reduced to the same record so callers never
branch on the on-disk shape. ``to_octop_summary`` is the only projection into
Octop's existing skill catalog shape; it does not change that catalog.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["DshSkillDefinition", "DshSkillResource", "DshSkillSummary"]


@dataclass(frozen=True, slots=True)
class DshSkillResource:
    """One file referenced by a skill body, resolved inside its workspace root."""

    relative_path: str
    path: Path
    size: int


@dataclass(frozen=True, slots=True)
class DshSkillSummary:
    """Routing metadata for one discovered DSH skill, without its body."""

    name: str
    description: str
    path: Path
    root: Path
    resource_base: Path
    source: str
    rank: int
    when_to_use: str = ""
    model_invocable: bool = True
    user_invocable: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)
    resources: tuple[DshSkillResource, ...] = ()

    def to_octop_summary(self) -> dict[str, Any]:
        """Project into the row shape returned by Octop's skill catalog.

        ``slug`` is the DSH kebab-case name because Octop addresses a skill by
        its directory slug, and ``kind`` names the source instead of pretending
        the skill is workspace-installed.
        """

        return {
            "slug": self.name,
            "name": self.name,
            "description": self.description,
            "enabled": True,
            "kind": "dsh",
            "path": str(self.path),
            "source": self.source,
            "when_to_use": self.when_to_use,
            "resources": [resource.relative_path for resource in self.resources],
        }

    def to_prompt_entry(self) -> Any:
        """Return the prompt-listing entry for this skill.

        Imported lazily so the discovery module never depends on prompt code.
        """

        from octop.infra.dsh.prompts.skills_injection import SkillPromptEntry  # noqa: PLC0415

        return SkillPromptEntry(
            name=self.name,
            description=self.description,
            path=str(self.path),
            when_to_use=self.when_to_use,
        )


@dataclass(frozen=True, slots=True)
class DshSkillDefinition(DshSkillSummary):
    """A discovered DSH skill plus its instruction body."""

    body: str = ""

    def render_skill_markdown(self) -> str:
        """Render a workspace ``SKILL.md`` that Octop's catalog can also read."""

        lines = [
            "---",
            f"name: {json.dumps(self.name, ensure_ascii=False)}",
            f"description: {json.dumps(self.description, ensure_ascii=False)}",
        ]
        if self.when_to_use:
            lines.append(f"whenToUse: {json.dumps(self.when_to_use, ensure_ascii=False)}")
        lines.extend(["---", "", self.body.strip(), ""])
        return "\n".join(lines)
