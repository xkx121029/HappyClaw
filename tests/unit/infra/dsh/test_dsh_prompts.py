"""Unit tests for DSH prompt sections and incremental skill injection."""

from __future__ import annotations

import pytest

from happyclaw.infra.dsh.prompts import (
    DuplicateSectionError,
    MalformedPromptVariableError,
    MultipleCompleteSectionsError,
    PromptSection,
    SECTION_ORDERS,
    SKILLS_SECTION_ORDER,
    SectionRegistry,
    SkillInjectionCursor,
    SkillPromptEntry,
    SkillPromptSnapshot,
    UnknownPromptVariableError,
    build_dsh_skills_section,
    plan_octop_prompt,
    render_prompt,
)


def _entry(name: str, description: str = "helper", path: str | None = None) -> SkillPromptEntry:
    return SkillPromptEntry(
        name=name,
        description=description,
        path=path or f"/workspace/skills/{name}/SKILL.md",
    )


def test_sections_assemble_in_dsh_order_regardless_of_registration() -> None:
    registry = SectionRegistry()
    registry.register(PromptSection("tool:read", SECTION_ORDERS["TOOL_READ"], "TOOL"))
    registry.register(PromptSection("deployment:persona-prefix", 0, "PERSONA"))
    registry.register(PromptSection("harness:identity", -1000, "IDENTITY"))
    registry.register(PromptSection("policy:plan", SECTION_ORDERS["PLAN_POLICY"], "PLAN"))
    registry.register(PromptSection("policy:any", SECTION_ORDERS["PLAN_POLICY"], "POLICY"))

    assembled = registry.assemble()

    assert [section.name for section in assembled] == [
        "harness:identity",
        "deployment:persona-prefix",
        "policy:any",
        "policy:plan",
        "tool:read",
    ]
    assert [section.name for section in registry.assemble()] == [
        section.name for section in assembled
    ]


def test_plan_maps_zones_and_excludes_context_zones_from_system_prompt() -> None:
    registry = SectionRegistry()
    registry.register(PromptSection("harness:identity", -1000, "IDENTITY"))
    registry.register(PromptSection("deployment:persona-prefix", 0, "PERSONA"))
    registry.register(PromptSection("policy:plan", 500, "PLAN"))
    registry.register(PromptSection("workspace:files", 900, "WORKSPACE"))
    registry.register(PromptSection("tool:read", 1100, "TOOL-READ"))
    registry.register(PromptSection("tool:sdk", 5000, "TOOLS-SDK"))
    registry.register(PromptSection("runtime:harness", 10000, "RUNTIME"))
    registry.register(PromptSection("deployment:persona-suffix", 10200, "SUFFIX"))
    registry.register(
        build_dsh_skills_section(SkillPromptSnapshot.build([_entry("alpha")]))
    )

    plan = plan_octop_prompt(registry.assemble())

    assert [section.zone for section in plan.sections] == [
        "identity",
        "persona",
        "policy",
        "workspace",
        "tools",
        "tools",
        "skills",
        "persona_suffix",
        "runtime_context",
    ]
    assert [section.name for section in plan.zone("persona")] == [
        "deployment:persona-prefix",
    ]
    assert [section.name for section in plan.zone("persona_suffix")] == [
        "deployment:persona-suffix",
    ]
    rendered = plan.render_system()
    assert "IDENTITY" in rendered
    assert "TOOL-READ" not in rendered
    assert "RUNTIME" not in rendered
    assert "## DSH Skills" in rendered
    assert rendered.endswith("SUFFIX")


def test_skill_section_slot_does_not_collide_with_a_dsh_order() -> None:
    assert SKILLS_SECTION_ORDER not in set(SECTION_ORDERS.values())


def test_incremental_injection_only_emits_changed_lines() -> None:
    cursor = SkillInjectionCursor()
    first = SkillPromptSnapshot.build([_entry("alpha"), _entry("beta")])

    text, cursor = cursor.advance(first)
    assert text.startswith("## DSH Skills")
    assert "**alpha**" in text
    assert "**beta**" in text

    unchanged_text, next_cursor = cursor.advance(first)
    assert unchanged_text == ""
    assert next_cursor is not cursor
    assert next_cursor.snapshot.digest() == cursor.snapshot.digest()

    second = SkillPromptSnapshot.build(
        [
            _entry("alpha", description="updated helper"),
            _entry("delta"),
            _entry("gamma"),
        ]
    )
    delta_text, _ = cursor.advance(second)

    assert delta_text.startswith("<dsh_skills_update>")
    assert "Added:" in delta_text
    assert "**delta**" in delta_text
    assert "**gamma**" in delta_text
    assert "Updated:" in delta_text
    assert "updated helper" in delta_text
    assert "Removed: `beta`" in delta_text
    assert "**beta**" not in delta_text


def test_incremental_injection_keeps_unchanged_skills_out() -> None:
    cursor = SkillInjectionCursor(SkillPromptSnapshot.build([_entry("alpha"), _entry("keep")]))
    current = SkillPromptSnapshot.build([_entry("alpha", "changed"), _entry("keep")])

    text, _ = cursor.advance(current)

    assert "**alpha**" in text
    assert "**keep**" not in text


def test_incremental_injection_bounds_update_size() -> None:
    cursor = SkillInjectionCursor(SkillPromptSnapshot.build([_entry("alpha")]))
    current = SkillPromptSnapshot.build([_entry("alpha"), _entry("beta")])

    text, _ = cursor.advance(current, max_chars=10)

    assert "清单已变化" in text
    assert "**beta**" not in text


def test_rendering_interpolates_strictly_and_preserves_literal_sections() -> None:
    sections = [
        PromptSection("a", 0, "Hello {{name}}"),
        PromptSection("b", 1, "Literal {{name}}", interpolate=False),
    ]
    assert render_prompt(sections, {"name": "Octop"}) == "Hello Octop\n\nLiteral {{name}}"

    with pytest.raises(UnknownPromptVariableError):
        render_prompt([PromptSection("a", 0, "Hello {{missing}}")])

    with pytest.raises(MalformedPromptVariableError):
        render_prompt([PromptSection("a", 0, "Hello {{Bad Name}}")])

    assert render_prompt([PromptSection("a", 0, "open {{ braces")]) == "open {{ braces"


def test_registry_rejects_duplicates_and_multiple_complete_sections() -> None:
    registry = SectionRegistry()
    registry.register(PromptSection("a", 0, "A"))
    with pytest.raises(DuplicateSectionError):
        registry.register(PromptSection("a", 1, "A2"))

    sections = [
        PromptSection("complete:1", 0, "ONE", complete=True),
        PromptSection("complete:2", 1, "TWO", complete=True),
    ]
    with pytest.raises(MultipleCompleteSectionsError):
        render_prompt(sections)

    assert render_prompt(
        [
            PromptSection("complete:1", 0, "ONE", complete=True),
            PromptSection("other", 1, "OTHER"),
        ],
        None,
    ) == "ONE"
