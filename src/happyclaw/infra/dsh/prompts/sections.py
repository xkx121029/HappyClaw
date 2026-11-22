"""Ordered prompt sections, mapped onto Octop's prompt zones.

DSH concatenates sections by ascending ``order`` and breaks ties by section
name (UTF-16 code-unit order in JavaScript; section names are ASCII, so Python
string order is identical). This module keeps that rule and mirrors DSH's
centrally allocated orders so a DSH composition and an Octop composition sort
the same way.

Two deviations are deliberate:

* section text is always a static string. DSH accepts a provider evaluated per
  assembly; accepting one here would let the prompt drift between identical
  requests, which this bridge forbids.
* a section may declare an Octop zone override (used for the synthesized DSH
  skills section) because DSH has no first-party skills section slot.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from happyclaw.infra.dsh.prompts.errors import (
    DuplicateSectionError,
    InvalidSectionError,
    MalformedPromptVariableError,
    MultipleCompleteSectionsError,
    UndefinedPromptVariableError,
    UnknownPromptVariableError,
)

__all__ = [
    "CONTEXT_ZONES",
    "OctopPromptPlan",
    "OctopPromptSection",
    "PromptSection",
    "SECTION_ORDERS",
    "SKILLS_SECTION_ORDER",
    "SYSTEM_ZONES",
    "SectionRegistry",
    "ZONE_ORDERS",
    "interpolate_text",
    "plan_octop_prompt",
    "render_prompt",
]

SECTION_ORDERS: Mapping[str, int] = {
    "HARNESS_IDENTITY": -1000,
    "DEPLOYMENT_PERSONA_PREFIX": 0,
    "PLAN_POLICY": 500,
    "TEAM_POLICY": 600,
    "PTC_ONLY": 800,
    "FILE_REFERENCE": 900,
    "TOOL_BASH": 1000,
    "TOOL_PWSH": 1010,
    "TOOL_READ": 1100,
    "TOOL_WRITE": 1200,
    "TOOL_EDIT": 1300,
    "TOOL_APPLY_PATCH": 1350,
    "TOOL_GLOB": 1400,
    "TOOL_GREP": 1500,
    "TOOL_JOBS": 1600,
    "TOOL_PTY": 1700,
    "TOOL_WEB_SEARCH": 2000,
    "TOOL_WEB_FETCH": 2100,
    "TOOL_LSP": 2200,
    "TOOL_SESSION_QUERY": 2300,
    "TOOL_GOAL": 2400,
    "TOOL_SCHEDULE": 2500,
    "TOOL_WORKFLOW": 2600,
    "TOOL_RALPH": 2700,
    "TOOL_SUBAGENT": 2800,
    "TOOL_REPORT": 2900,
    "TOOL_COMPUTER_USE": 3000,
    "MCP_SERVERS": 3100,
    "TOOLS_SDK": 5000,
    "DELIVERABLE_FILE_REFERENCES": 9000,
    "STRUCTURED_OUTPUT": 9900,
    "HARNESS_SOURCE": 10000,
    "WEB_SURFACE": 10100,
    "DEPLOYMENT_PERSONA_SUFFIX": 10200,
}

# Octop has no numbered section registry; these zones are the stable mapping
# target. 4500 sits between DSH's MCP slot and TOOLS_SDK and is unassigned
# there, so the synthesized skills section cannot collide with a DSH section.
SKILLS_SECTION_ORDER = 4500

ZONE_ORDERS: Mapping[str, int] = {
    "identity": 0,
    "persona": 1000,
    "policy": 2000,
    "workspace": 3000,
    "tools": 4000,
    "skills": 5000,
    "deliverables": 6000,
    "output_schema": 7000,
    "memory_policy": 8000,
    "skill_rules": 8500,
    "persona_suffix": 8800,
    "runtime_context": 9000,
    "extensions": 9500,
}

SYSTEM_ZONES = frozenset(
    {
        "identity",
        "persona",
        "policy",
        "workspace",
        "skills",
        "deliverables",
        "output_schema",
        "memory_policy",
        "skill_rules",
        "persona_suffix",
        "extensions",
    }
)
CONTEXT_ZONES = frozenset({"tools", "runtime_context"})

_EXPLICIT_ZONES: Mapping[str, str] = {
    "harness:identity": "identity",
    "deployment:persona-prefix": "persona",
    # DSH places the persona suffix after runtime context (10200); a dedicated
    # zone keeps that position instead of grouping it with the prefix.
    "deployment:persona-suffix": "persona_suffix",
}

_VARIABLE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_GROUP_AT = re.compile(r"^\{\{([^{}]*)\}\}")


@dataclass(frozen=True, slots=True)
class PromptSection:
    """One registered section with static text."""

    name: str
    order: float
    text: str
    interpolate: bool = True
    complete: bool = False
    zone: str | None = None


class SectionRegistry:
    """Collect sections, then assemble them in DSH's deterministic order."""

    def __init__(self) -> None:
        self._sections: dict[str, PromptSection] = {}

    def register(self, section: PromptSection) -> None:
        if not section.name or section.name != section.name.strip():
            raise InvalidSectionError(
                "提示词 section 名称必须是非空且首尾无空白",
                details={"name": section.name},
            )
        if isinstance(section.order, bool) or not isinstance(section.order, (int, float)):
            raise InvalidSectionError(
                f"提示词 section「{section.name}」的 order 必须是有限数字",
                details={"name": section.name, "order": repr(section.order)},
            )
        if not math.isfinite(section.order):
            raise InvalidSectionError(
                f"提示词 section「{section.name}」的 order 必须是有限数字",
                details={"name": section.name, "order": repr(section.order)},
            )
        if not isinstance(section.text, str):
            raise InvalidSectionError(
                f"提示词 section「{section.name}」只接受静态文本",
                details={"name": section.name},
            )
        if section.name in self._sections:
            raise DuplicateSectionError(
                f"提示词 section 重复注册：{section.name}",
                details={"name": section.name},
            )
        self._sections[section.name] = section

    def assemble(self) -> tuple[PromptSection, ...]:
        return tuple(
            sorted(self._sections.values(), key=lambda section: (section.order, section.name))
        )


@dataclass(frozen=True, slots=True)
class OctopPromptSection:
    """A section assigned to one Octop prompt zone."""

    zone: str
    zone_order: int
    name: str
    dsh_order: float
    text: str
    interpolate: bool = True
    complete: bool = False

    def sort_key(self) -> tuple[int, float, str]:
        return (self.zone_order, self.dsh_order, self.name)


@dataclass(frozen=True, slots=True)
class OctopPromptPlan:
    """Sections grouped by Octop zone in a stable, reproducible order."""

    sections: tuple[OctopPromptSection, ...]

    def zone(self, zone: str) -> tuple[OctopPromptSection, ...]:
        return tuple(section for section in self.sections if section.zone == zone)

    def system_sections(self) -> tuple[OctopPromptSection, ...]:
        return tuple(section for section in self.sections if section.zone in SYSTEM_ZONES)

    def context_sections(self) -> tuple[OctopPromptSection, ...]:
        return tuple(section for section in self.sections if section.zone in CONTEXT_ZONES)

    def render_system(self, variables: Mapping[str, str | None] | None = None) -> str:
        return _render(self.system_sections(), variables or {})

    def render_all(self, variables: Mapping[str, str | None] | None = None) -> str:
        return _render(self.sections, variables or {})


def plan_octop_prompt(sections: Iterable[PromptSection]) -> OctopPromptPlan:
    """Map assembled DSH sections onto Octop zones.

    Unknown section names are classified by DSH's order bands, so a newly added
    section still lands in a deterministic place; an unknown explicit zone is a
    configuration error.
    """

    planned: list[OctopPromptSection] = []
    for section in sections:
        zone = section.zone or _zone_for(section)
        zone_order = ZONE_ORDERS.get(zone)
        if zone_order is None:
            raise InvalidSectionError(
                f"提示词 section「{section.name}」使用了未知 zone：{zone}",
                details={"name": section.name, "zone": zone},
            )
        planned.append(
            OctopPromptSection(
                zone=zone,
                zone_order=zone_order,
                name=section.name,
                dsh_order=section.order,
                text=section.text,
                interpolate=section.interpolate,
                complete=section.complete,
            )
        )
    planned.sort(key=OctopPromptSection.sort_key)
    return OctopPromptPlan(tuple(planned))


def render_prompt(
    sections: Iterable[PromptSection],
    variables: Mapping[str, str | None] | None = None,
) -> str:
    """Render sections exactly like DSH: interpolate, drop empty, join blank lines."""

    return _render(tuple(sections), variables or {})


def interpolate_text(
    text: str,
    variables: Mapping[str, str | None],
    *,
    kind: str = "section",
    name: str = "",
) -> str:
    """Apply DSH's strict ``{{variable}}`` rules.

    ``{{`` without any later ``}}`` is literal prose; a malformed group, an
    unregistered name, or a registered name without a value raises. Substituted
    values are not scanned again.
    """

    result: list[str] = []
    last = 0
    open_index = text.find("{{")
    while open_index >= 0:
        group = _GROUP_AT.match(text[open_index:])
        if group is None:
            if text.find("}}", open_index + 2) >= 0:
                snippet = text[open_index : open_index + 16]
                raise MalformedPromptVariableError(
                    f"{kind}「{name}」的变量引用格式错误：{snippet}…",
                    details={"kind": kind, "name": name, "snippet": snippet},
                )
            result.append(text[last : open_index + 2])
            last = open_index + 2
            open_index = text.find("{{", last)
            continue

        variable = group.group(1)
        if not _VARIABLE_NAME.match(variable):
            raise MalformedPromptVariableError(
                f"{kind}「{name}」的变量名不合法：{{{{{variable}}}}}",
                details={"kind": kind, "name": name, "variable": variable},
            )
        if variable not in variables:
            raise UnknownPromptVariableError(
                f"{kind}「{name}」引用了未注册的变量：{{{{{variable}}}}}",
                details={"kind": kind, "name": name, "variable": variable},
            )
        value = variables[variable]
        if value is None:
            raise UndefinedPromptVariableError(
                f"{kind}「{name}」的变量没有取值：{{{{{variable}}}}}",
                details={"kind": kind, "name": name, "variable": variable},
            )
        result.append(text[last:open_index])
        result.append(value)
        last = open_index + len(group.group(0))
        open_index = text.find("{{", last)
    result.append(text[last:])
    return "".join(result)


def _render(
    sections: Iterable[PromptSection | OctopPromptSection],
    variables: Mapping[str, str | None],
) -> str:
    ordered = sorted(sections, key=_render_sort_key)
    complete = [section for section in ordered if section.complete]
    if len(complete) > 1:
        raise MultipleCompleteSectionsError(
            "同时存在多个完整提示词 section："
            + "、".join(section.name for section in complete),
            details={"sections": [section.name for section in complete]},
        )
    selected = complete or ordered
    rendered: list[str] = []
    for section in selected:
        text = (
            section.text
            if section.interpolate is False
            else interpolate_text(section.text, variables, name=section.name)
        )
        if text:
            rendered.append(text)
    return "\n\n".join(rendered)


def _render_sort_key(section: PromptSection | OctopPromptSection) -> tuple[float, float, str]:
    if isinstance(section, OctopPromptSection):
        return (float(section.zone_order), float(section.dsh_order), section.name)
    return (0.0, float(section.order), section.name)


def _zone_for(section: PromptSection) -> str:
    explicit = _EXPLICIT_ZONES.get(section.name)
    if explicit is not None:
        return explicit

    order = section.order
    if order <= SECTION_ORDERS["HARNESS_IDENTITY"]:
        return "identity"
    if order < SECTION_ORDERS["PLAN_POLICY"]:
        return "persona"
    if order < SECTION_ORDERS["FILE_REFERENCE"]:
        return "policy"
    if order == SECTION_ORDERS["FILE_REFERENCE"]:
        return "workspace"
    if order < SECTION_ORDERS["TOOLS_SDK"]:
        return "tools"
    if order < SECTION_ORDERS["DELIVERABLE_FILE_REFERENCES"]:
        return "tools"
    if order < SECTION_ORDERS["STRUCTURED_OUTPUT"]:
        return "deliverables"
    if order < SECTION_ORDERS["HARNESS_SOURCE"]:
        return "output_schema"
    if order < SECTION_ORDERS["DEPLOYMENT_PERSONA_SUFFIX"]:
        return "runtime_context"
    if order == SECTION_ORDERS["DEPLOYMENT_PERSONA_SUFFIX"]:
        return "persona_suffix"
    return "extensions"
