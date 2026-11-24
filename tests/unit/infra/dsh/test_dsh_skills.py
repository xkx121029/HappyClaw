"""Unit tests for reading DSH skill declarations without a DSH runtime."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from happyclaw.infra.dsh.skills import (
    DshSkillCatalog,
    DshSkillErrorCode,
    DshSkillFrontmatterError,
    DshSkillManifestError,
    DshSkillPathError,
    DshSkillRoot,
    DshSkillRootError,
    default_skill_roots,
    discover_plugin_package,
    discover_skill_root,
)

_ALPHA = """---
name: alpha
description: Alpha helper for fixture work.
whenToUse: When the fixture needs alpha behaviour.
---
# Alpha

Read `references/notes.md` before answering.
"""

_BETA = """---
name: beta
description: Beta helper shipped as a flat markdown file.
---
# Beta
"""


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _package(tmp_path: Path, manifest: dict[str, object]) -> Path:
    package = tmp_path / "pkg"
    _write(package / "package.json", json.dumps(manifest))
    return package


def test_discover_directory_bundle_and_flat_skill(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write(root / "alpha" / "SKILL.md", _ALPHA)
    _write(root / "alpha" / "references" / "notes.md", "fixture notes\n")
    _write(root / "beta.md", _BETA)

    summaries = discover_skill_root(DshSkillRoot(root, "project-dsh", 100))

    assert [summary.name for summary in summaries] == ["alpha", "beta"]
    alpha = summaries[0]
    assert alpha.description == "Alpha helper for fixture work."
    assert alpha.when_to_use == "When the fixture needs alpha behaviour."
    assert [resource.relative_path for resource in alpha.resources] == ["references/notes.md"]
    assert alpha.resource_base == root / "alpha"
    assert summaries[1].resource_base == root

    octop_row = alpha.to_octop_summary()
    assert octop_row["slug"] == "alpha"
    assert octop_row["kind"] == "dsh"
    assert octop_row["source"] == "project-dsh"
    assert octop_row["resources"] == ["references/notes.md"]


def test_skill_resource_path_escape_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write(
        root / "alpha" / "SKILL.md",
        _ALPHA.replace("references/notes.md", "references/../../outside.md"),
    )

    with pytest.raises(DshSkillPathError):
        discover_skill_root(DshSkillRoot(root, "project-dsh", 100))


def test_default_roots_keep_dsh_priority_order(tmp_path: Path) -> None:
    roots = default_skill_roots(
        tmp_path / "workspace",
        dsh_home=tmp_path / "dsh-home",
        agents_home=tmp_path / "agents-home",
        bundled_dir=tmp_path / "bundled",
        custom_dirs=(tmp_path / "custom",),
    )

    assert [(root.source, root.rank) for root in roots] == [
        ("project-dsh", 100),
        ("project-agents", 200),
        ("custom", 300),
        ("user-dsh", 400),
        ("user-agents", 500),
        ("bundled", 600),
    ]


def test_default_roots_reject_relative_paths(tmp_path: Path) -> None:
    with pytest.raises(DshSkillRootError):
        default_skill_roots(Path("relative-workspace"))


def test_discover_absent_root_is_empty(tmp_path: Path) -> None:
    assert discover_skill_root(DshSkillRoot(tmp_path / "missing", "user-dsh", 400)) == ()


def test_plugin_convention_skills_directory(tmp_path: Path) -> None:
    package = _package(tmp_path, {"name": "@demo/plugin", "files": ["skills"]})
    _write(package / "skills" / "alpha" / "SKILL.md", _ALPHA)
    _write(package / "skills" / "alpha" / "references" / "notes.md", "fixture notes\n")

    summaries = discover_plugin_package(package)

    assert [summary.name for summary in summaries] == ["alpha"]
    assert summaries[0].source == "plugin:@demo/plugin"


def test_declared_skill_file_missing_is_an_error(tmp_path: Path) -> None:
    package = _package(tmp_path, {"name": "demo", "dsh": {"skills": ["skills/ghost.md"]}})

    with pytest.raises(DshSkillManifestError) as caught:
        discover_plugin_package(package)

    assert caught.value.code is DshSkillErrorCode.MANIFEST_MISSING
    assert "不存在" in caught.value.message


def test_declared_skill_path_escape_is_rejected_not_truncated(tmp_path: Path) -> None:
    outside = _write(tmp_path / "outside.md", _BETA)
    package = _package(tmp_path, {"name": "demo", "dsh": {"skills": ["../outside.md"]}})

    with pytest.raises(DshSkillPathError) as caught:
        discover_plugin_package(package)

    assert caught.value.code is DshSkillErrorCode.PATH_OUTSIDE_ROOT
    assert "越界" in caught.value.message
    assert caught.value.details["requested"] == "../outside.md"
    assert outside.exists()


def test_plugin_exports_alone_do_not_declare_skills(tmp_path: Path) -> None:
    package = _package(tmp_path, {"name": "demo", "exports": {"./skills/*.md": "./skills/*.md"}})

    assert discover_plugin_package(package) == ()


def test_root_skips_malformed_frontmatter_unless_strict(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write(root / "beta.md", _BETA)
    _write(root / "broken.md", "# no frontmatter\n")

    assert [
        summary.name for summary in discover_skill_root(DshSkillRoot(root, "user-dsh", 400))
    ] == ["beta"]

    with pytest.raises(DshSkillFrontmatterError):
        discover_skill_root(DshSkillRoot(root, "user-dsh", 400), strict=True)


def test_declared_bundle_missing_manifest_is_an_error(tmp_path: Path) -> None:
    package = _package(tmp_path, {"name": "demo", "dsh": {"skills": ["skills/empty"]}})
    (package / "skills" / "empty").mkdir(parents=True)

    with pytest.raises(DshSkillManifestError):
        discover_plugin_package(package)


def test_catalog_prefers_lower_rank_and_materializes_workspace_uploads(
    tmp_path: Path,
) -> None:
    high = tmp_path / "high"
    low = tmp_path / "low"
    _write(high / "alpha" / "SKILL.md", _ALPHA)
    _write(high / "alpha" / "references" / "notes.md", "high notes\n")
    _write(
        low / "alpha" / "SKILL.md",
        _ALPHA.replace("Alpha helper for fixture work.", "Low priority alpha."),
    )
    _write(low / "alpha" / "references" / "notes.md", "low notes\n")

    catalog = DshSkillCatalog(
        (
            DshSkillRoot(high, "project-dsh", 100),
            DshSkillRoot(low, "user-dsh", 400),
        )
    )
    summaries = catalog.discover()

    assert [summary.name for summary in summaries] == ["alpha"]
    assert summaries[0].description == "Alpha helper for fixture work."

    definition = catalog.load("alpha")
    assert "references/notes.md" in definition.body

    package = catalog.materialize("alpha")
    assert package.slug == "alpha"
    assert {path for path, _ in package.files} == {
        "SKILL.md",
        "references/notes.md",
    }
    assert [path for path, _ in package.workspace_uploads()] == [
        "skills/alpha/SKILL.md",
        "skills/alpha/references/notes.md",
    ]
