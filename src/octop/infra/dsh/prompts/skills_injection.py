"""Incremental injection of DSH skill listings into the system prompt.

A long conversation must not re-inject the full skill catalog on every turn.
The cursor below holds an immutable snapshot; ``advance`` returns only the
lines that changed since the previous snapshot and a new cursor. The caller owns
the cursor per thread, so two requests never share implicit state.

Rendering of a single skill mirrors ``deepagents`` (the middleware Octop already
uses for workspace skills), so both catalogs read the same way to the model.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol

from octop.infra.dsh.prompts.sections import SKILLS_SECTION_ORDER, PromptSection

__all__ = [
    "SkillInjectionCursor",
    "SkillPromptDelta",
    "SkillPromptEntry",
    "SkillPromptSnapshot",
    "build_dsh_skills_section",
    "snapshot_from_summaries",
]

DEFAULT_HEADING = "## DSH Skills"
_HEADING_INTRO = (
    "The following DSH skills are available. Read a skill's SKILL.md before "
    "following its instructions."
)
_UPDATE_OPEN = "<dsh_skills_update>"
_UPDATE_CLOSE = "</dsh_skills_update>"


@dataclass(frozen=True, slots=True)
class SkillPromptEntry:
    """One skill's model-facing listing line."""

    name: str
    description: str
    path: str
    when_to_use: str = ""
    allowed_tools: tuple[str, ...] = ()

    def render(self) -> str:
        lines = [f"- **{self.name}**: {self.description}"]
        if self.allowed_tools:
            lines.append(f"  -> Allowed tools: {', '.join(self.allowed_tools)}")
        lines.append(f"  -> Read `{self.path}` for full instructions")
        return "\n".join(lines)

    def payload(self) -> tuple[object, ...]:
        """Everything that changes the rendered line or its routing meaning."""

        return (
            self.name,
            self.description,
            self.path,
            self.when_to_use,
            self.allowed_tools,
        )


class _PromptEntryRecord(Protocol):
    """A discovered record that can project itself into a prompt entry."""

    def to_prompt_entry(self) -> SkillPromptEntry: ...


@dataclass(frozen=True, slots=True)
class SkillPromptSnapshot:
    """Sorted, de-duplicated skill listing at one point in time."""

    entries: tuple[SkillPromptEntry, ...] = ()

    @classmethod
    def build(cls, entries: Iterable[SkillPromptEntry]) -> SkillPromptSnapshot:
        """Build a snapshot; the last entry for a name wins, then names sort."""

        by_name: dict[str, SkillPromptEntry] = {}
        for entry in entries:
            by_name[entry.name] = entry
        return cls(tuple(sorted(by_name.values(), key=lambda entry: entry.name)))

    def index(self) -> dict[str, SkillPromptEntry]:
        return {entry.name: entry for entry in self.entries}

    def digest(self) -> str:
        """Stable hash of the current listing, independent of insertion order."""

        digest = hashlib.sha256()
        for entry in self.entries:
            digest.update(entry.render().encode("utf-8"))
            digest.update(b"\x00")
        return digest.hexdigest()

    def render(self) -> str:
        return "\n".join(entry.render() for entry in self.entries)

    def diff(self, current: SkillPromptSnapshot) -> SkillPromptDelta:
        previous_index = self.index()
        current_index = current.index()

        added = tuple(
            current_index[name] for name in sorted(current_index) if name not in previous_index
        )
        removed = tuple(name for name in sorted(previous_index) if name not in current_index)
        updated = tuple(
            current_index[name]
            for name in sorted(current_index)
            if name in previous_index
            and current_index[name].payload() != previous_index[name].payload()
        )
        unchanged = sum(
            1
            for name in previous_index
            if name in current_index
            and current_index[name].payload() == previous_index[name].payload()
        )
        return SkillPromptDelta(
            added=added,
            updated=updated,
            removed=removed,
            unchanged=unchanged,
            previous=self,
            current=current,
        )


@dataclass(frozen=True, slots=True)
class SkillPromptDelta:
    """Only the catalog lines that changed between two snapshots."""

    added: tuple[SkillPromptEntry, ...] = ()
    updated: tuple[SkillPromptEntry, ...] = ()
    removed: tuple[str, ...] = ()
    unchanged: int = 0
    previous: SkillPromptSnapshot = field(default_factory=SkillPromptSnapshot)
    current: SkillPromptSnapshot = field(default_factory=SkillPromptSnapshot)

    @property
    def changed(self) -> bool:
        return bool(self.added or self.updated or self.removed)

    def counts(self) -> dict[str, int]:
        return {
            "added": len(self.added),
            "updated": len(self.updated),
            "removed": len(self.removed),
            "unchanged": self.unchanged,
        }

    def render(self, *, initial: bool = False, max_chars: int = 4000) -> str:
        """Render the delta; empty string means "inject nothing this turn".

        ``initial`` renders the full catalog instead of an update block, which
        is what the first turn of a thread needs.
        """

        if initial:
            return build_skill_section(self.current)
        if not self.changed:
            return ""

        blocks: list[str] = [_UPDATE_OPEN]
        if self.added:
            blocks.append("Added:")
            blocks.extend(entry.render() for entry in self.added)
        if self.updated:
            blocks.append("Updated:")
            blocks.extend(entry.render() for entry in self.updated)
        if self.removed:
            blocks.append("Removed: " + ", ".join(f"`{name}`" for name in self.removed))
        blocks.append(_UPDATE_CLOSE)
        text = "\n".join(blocks)
        if len(text) <= max_chars:
            return text

        counts = self.counts()
        return "\n".join(
            [
                _UPDATE_OPEN,
                "DSH 技能清单已变化："
                f"新增 {counts['added']}、更新 {counts['updated']}、移除 {counts['removed']}。"
                "完整清单以技能目录为准。",
                _UPDATE_CLOSE,
            ]
        )


@dataclass(frozen=True, slots=True)
class SkillInjectionCursor:
    """Per-thread incremental injector; holding no global state."""

    snapshot: SkillPromptSnapshot = field(default_factory=SkillPromptSnapshot)

    def advance(
        self,
        current: SkillPromptSnapshot,
        *,
        max_chars: int = 4000,
    ) -> tuple[str, SkillInjectionCursor]:
        """Return this turn's prompt text (possibly empty) and the next cursor."""

        delta = self.snapshot.diff(current)
        text = delta.render(initial=not self.snapshot.entries, max_chars=max_chars)
        return text, SkillInjectionCursor(current)


def build_skill_section(
    snapshot: SkillPromptSnapshot,
    *,
    heading: str = DEFAULT_HEADING,
) -> str:
    """Render a complete DSH skills section, or ``""`` when there are none."""

    if not snapshot.entries:
        return ""
    return f"{heading}\n\n{_HEADING_INTRO}\n\n{snapshot.render()}"


def build_dsh_skills_section(
    snapshot: SkillPromptSnapshot,
    *,
    heading: str = DEFAULT_HEADING,
) -> PromptSection:
    """Wrap a snapshot as an Octop prompt section in the ``skills`` zone.

    ``SKILLS_SECTION_ORDER`` is unassigned in DSH's order table, so this slot is
    stable and cannot collide with a DSH-owned section.
    """

    return PromptSection(
        name="octop:dsh-skills",
        order=SKILLS_SECTION_ORDER,
        text=build_skill_section(snapshot, heading=heading),
        zone="skills",
    )


def snapshot_from_summaries(summaries: Iterable[_PromptEntryRecord]) -> SkillPromptSnapshot:
    """Build a snapshot from records exposing ``to_prompt_entry``."""

    return SkillPromptSnapshot.build(summary.to_prompt_entry() for summary in summaries)
