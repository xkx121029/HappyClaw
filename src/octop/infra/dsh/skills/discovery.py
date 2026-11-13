"""Discover DSH skills from filesystem roots and plugin manifests.

Two declaration shapes are supported, matching DSH itself:

* a skill root holding directory bundles (``<skill>/SKILL.md``) or flat
  ``<name>.md`` files;
* a plugin package whose ``package.json`` advertises a ``skills/`` directory
  (``files`` / ``exports``) or lists explicit ``dsh.skills`` paths.

Nothing here imports a DSH package or evaluates ``!!js``; only declarations and
Markdown bodies are read. A declared path that leaves its root is refused, not
clipped, and a declared file that is missing is an error rather than a skipped
entry, so a broken package cannot silently advertise a smaller catalog.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from octop.infra.dsh.skills.errors import (
    DshSkillDeclarationError,
    DshSkillFrontmatterError,
    DshSkillManifestError,
    DshSkillResourceError,
    DshSkillRootError,
)
from octop.infra.dsh.skills.frontmatter import parse_skill_text
from octop.infra.dsh.skills.models import DshSkillResource, DshSkillSummary
from octop.infra.dsh.skills.paths import resolve_within_root

__all__ = [
    "DshSkillRoot",
    "PROJECT_AGENTS_RANK",
    "PROJECT_DSH_RANK",
    "PLUGIN_RANK",
    "CUSTOM_RANK",
    "USER_DSH_RANK",
    "USER_AGENTS_RANK",
    "BUNDLED_RANK",
    "default_skill_roots",
    "discover_plugin_package",
    "discover_skill_root",
    "read_skill_summary",
]

# Rank values mirror @deepseek-ai/dsh-skill-filesystem so a catalog merged from
# both readers resolves collisions the same way.
PROJECT_DSH_RANK = 100
PROJECT_AGENTS_RANK = 200
PLUGIN_RANK = 250
CUSTOM_RANK = 300
USER_DSH_RANK = 400
USER_AGENTS_RANK = 500
BUNDLED_RANK = 600

_RESOURCE_RE = re.compile(r"`([^`\n]+)`")
_RESOURCE_PREFIXES = ("references/", "templates/", "assets/", "scripts/", "examples/")
_RESOURCE_IGNORED_CHARS = frozenset("*?[]{}<>$|")


@dataclass(frozen=True, slots=True)
class DshSkillRoot:
    """One directory scanned for DSH skills plus its precedence metadata."""

    path: Path
    source: str
    rank: int


def default_skill_roots(
    workspace: str | Path,
    *,
    dsh_home: str | Path | None = None,
    agents_home: str | Path | None = None,
    bundled_dir: str | Path | None = None,
    custom_dirs: Sequence[str | Path] = (),
    include_defaults: bool = True,
) -> tuple[DshSkillRoot, ...]:
    """Build the DSH root list for a workspace.

    ``include_defaults`` adds project and user roots; custom roots are always
    kept. Environment variables are read only when the matching argument is
    omitted, and the result is de-duplicated by resolved path with the first
    (highest-priority) root winning.
    """

    base = _absolute_dir(workspace, label="工作区")
    roots: list[DshSkillRoot] = []
    if include_defaults:
        roots.extend(
            (
                DshSkillRoot(base / ".dsh" / "skills", "project-dsh", PROJECT_DSH_RANK),
                DshSkillRoot(base / ".agents" / "skills", "project-agents", PROJECT_AGENTS_RANK),
            )
        )
    roots.extend(
        DshSkillRoot(_absolute_dir(raw, label="自定义技能目录"), "custom", CUSTOM_RANK)
        for raw in custom_dirs
    )
    if include_defaults:
        resolved_dsh_home = _optional_abs(dsh_home, env="DSH_HOME") or (Path.home() / ".dsh")
        resolved_agents_home = _optional_abs(agents_home, env="DSH_AGENTS_HOME") or (
            Path.home() / ".agents"
        )
        roots.extend(
            (
                DshSkillRoot(resolved_dsh_home / "skills", "user-dsh", USER_DSH_RANK),
                DshSkillRoot(resolved_agents_home / "skills", "user-agents", USER_AGENTS_RANK),
            )
        )
        resolved_bundled = _optional_abs(bundled_dir, env="DSH_BUNDLED_SKILL_DIR")
        if resolved_bundled is not None:
            roots.append(DshSkillRoot(resolved_bundled, "bundled", BUNDLED_RANK))

    deduped: list[DshSkillRoot] = []
    seen: set[Path] = set()
    for root in roots:
        try:
            key = root.path.resolve()
        except (OSError, RuntimeError):
            key = root.path
        if key in seen:
            continue
        seen.add(key)
        deduped.append(root)
    return tuple(deduped)


def discover_skill_root(
    root: DshSkillRoot,
    *,
    strict: bool = False,
) -> tuple[DshSkillSummary, ...]:
    """Read every skill in one root, sorted by name.

    An absent root yields an empty tuple: DSH treats a missing project or user
    root as "no skills". Files without usable frontmatter, or skills whose
    referenced resources are missing, are skipped, matching DSH's tolerance for
    incomplete packages; ``strict`` turns those skips into errors. Path escapes
    always raise, even when not strict.
    """

    root_path = root.path.resolve()
    if not root_path.is_dir():
        return ()

    summaries: list[DshSkillSummary] = []
    for entry in sorted(root_path.iterdir(), key=lambda item: item.name):
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            manifest = entry / "SKILL.md"
            if not manifest.is_file():
                continue
            try:
                summaries.append(
                    read_skill_summary(
                        manifest,
                        root=root_path,
                        resource_base=entry,
                        source=root.source,
                        rank=root.rank,
                    )
                )
            except (DshSkillFrontmatterError, DshSkillResourceError):
                if strict:
                    raise
                continue
        elif entry.is_file() and entry.suffix.lower() == ".md":
            try:
                summaries.append(
                    read_skill_summary(
                        entry,
                        root=root_path,
                        resource_base=root_path,
                        source=root.source,
                        rank=root.rank,
                    )
                )
            except (DshSkillFrontmatterError, DshSkillResourceError):
                if strict:
                    raise
                continue
    return tuple(sorted(summaries, key=lambda item: item.name))


def discover_plugin_package(
    package_dir: str | Path,
    *,
    rank: int = PLUGIN_RANK,
    strict: bool = False,
) -> tuple[DshSkillSummary, ...]:
    """Read the skills a DSH plugin package declares.

    Explicit ``dsh.skills`` entries are always strict: every entry must exist,
    stay inside the package, and parse. Without that field, the conventional
    ``skills/`` directory is scanned with the same rules as a filesystem root.
    Package ``exports``/``files`` are not treated as declarations because DSH
    packages also export non-skill Markdown documents there.
    """

    base = _absolute_dir(package_dir, label="DSH 插件目录")
    manifest_path = base / "package.json"
    if not manifest_path.is_file():
        raise DshSkillManifestError(
            f"DSH 插件缺少 package.json：{base}",
            details={"package_dir": str(base)},
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DshSkillDeclarationError(
            f"DSH 插件 package.json 无法解析：{manifest_path}",
            details={"path": str(manifest_path), "reason": type(exc).__name__},
        ) from None
    if not isinstance(manifest, dict):
        raise DshSkillDeclarationError(
            f"DSH 插件 package.json 必须是对象：{manifest_path}",
            details={"path": str(manifest_path)},
        )

    package_name = str(manifest.get("name") or base.name)
    source = f"plugin:{package_name}"
    declared = _declared_skill_paths(manifest)
    if declared is not None:
        return _discover_declared_paths(
            base,
            declared,
            source=source,
            rank=rank,
        )

    skills_dir = base / "skills"
    if not skills_dir.is_dir():
        return ()
    return discover_skill_root(
        DshSkillRoot(skills_dir, source, rank),
        strict=strict,
    )


def read_skill_summary(
    path: str | Path,
    *,
    root: Path,
    resource_base: Path,
    source: str,
    rank: int,
) -> DshSkillSummary:
    """Read and validate one skill file, including its referenced resources."""

    resolved = resolve_within_root(root, path)
    if not resolved.is_file():
        raise DshSkillManifestError(
            f"DSH 技能文件不存在：{resolved}",
            details={"path": str(resolved), "workspace_root": str(root)},
        )
    try:
        text = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise DshSkillManifestError(
            f"DSH 技能文件无法读取：{resolved}",
            details={"path": str(resolved), "reason": type(exc).__name__},
        ) from None

    parsed = parse_skill_text(text, path=str(resolved))
    resources = _resolve_resources(
        parsed.body,
        root=root,
        resource_base=resource_base,
        skill=parsed.name,
    )
    return DshSkillSummary(
        name=parsed.name,
        description=parsed.description,
        path=resolved,
        root=root,
        resource_base=resource_base,
        source=source,
        rank=rank,
        when_to_use=parsed.when_to_use,
        model_invocable=parsed.model_invocable,
        user_invocable=parsed.user_invocable,
        metadata=parsed.metadata,
        resources=resources,
    )


def _discover_declared_paths(
    base: Path,
    declared: Sequence[Any],
    *,
    source: str,
    rank: int,
) -> tuple[DshSkillSummary, ...]:
    summaries: list[DshSkillSummary] = []
    for raw in declared:
        if not isinstance(raw, str) or not raw.strip():
            raise DshSkillDeclarationError(
                "DSH 插件的 dsh.skills 只能包含非空字符串路径",
                details={"package_dir": str(base)},
            )
        requested = raw.strip()
        resolved = resolve_within_root(base, requested)
        if resolved.is_dir():
            manifest = resolved / "SKILL.md"
            if not manifest.is_file():
                raise DshSkillManifestError(
                    f"DSH 插件声明的技能目录缺少 SKILL.md：{resolved}",
                    details={"package_dir": str(base), "declared": requested},
                )
            summaries.append(
                read_skill_summary(
                    manifest,
                    root=base,
                    resource_base=resolved,
                    source=source,
                    rank=rank,
                )
            )
            continue
        if not resolved.is_file():
            raise DshSkillManifestError(
                f"DSH 插件声明的技能文件不存在：{requested}",
                details={"package_dir": str(base), "declared": requested},
            )
        if resolved.suffix.lower() != ".md":
            raise DshSkillDeclarationError(
                f"DSH 插件声明的技能必须是 Markdown：{requested}",
                details={"package_dir": str(base), "declared": requested},
            )
        summaries.append(
            read_skill_summary(
                resolved,
                root=base,
                resource_base=base,
                source=source,
                rank=rank,
            )
        )
    return tuple(sorted(summaries, key=lambda item: item.name))


def _declared_skill_paths(manifest: Mapping[str, Any]) -> tuple[Any, ...] | None:
    dsh = manifest.get("dsh")
    if not isinstance(dsh, Mapping):
        return None
    declared = dsh.get("skills")
    if declared is None:
        return None
    if not isinstance(declared, list):
        raise DshSkillDeclarationError(
            "DSH 插件的 dsh.skills 必须是列表",
            details={"field": "dsh.skills"},
        )
    return tuple(declared)


def _resolve_resources(
    body: str,
    *,
    root: Path,
    resource_base: Path,
    skill: str,
) -> tuple[DshSkillResource, ...]:
    resources: list[DshSkillResource] = []
    seen: set[str] = set()
    for match in _RESOURCE_RE.finditer(body):
        reference = match.group(1).strip().removeprefix("./")
        if not reference or reference.endswith("/"):
            continue
        if any(char in reference for char in _RESOURCE_IGNORED_CHARS):
            continue
        if not reference.startswith(_RESOURCE_PREFIXES):
            continue
        reference = reference.split("#", 1)[0]
        if not reference or reference in seen:
            continue
        seen.add(reference)

        resolved = resolve_within_root(resource_base, reference)
        if resolved.is_file():
            resources.append(
                DshSkillResource(
                    relative_path=reference,
                    path=resolved,
                    size=resolved.stat().st_size,
                )
            )
            continue
        if resolved.is_dir():
            # A prose mention of a resource directory is not a file dependency.
            continue
        if "." in resolved.name:
            raise DshSkillResourceError(
                f"DSH 技能 {skill} 引用的资源不存在：{reference}",
                details={"skill": skill, "resource": reference, "root": str(root)},
            )
    return tuple(resources)


def _absolute_dir(raw: str | Path, *, label: str) -> Path:
    candidate = Path(raw)
    if not str(raw).strip() or not candidate.is_absolute():
        raise DshSkillRootError(
            f"{label}必须是绝对路径，当前为「{raw}」。",
            details={"path": str(raw)},
        )
    try:
        return candidate.resolve()
    except (OSError, RuntimeError) as exc:
        raise DshSkillRootError(
            f"{label}无法解析：{raw}（{type(exc).__name__}）",
            details={"path": str(raw)},
        ) from None


def _optional_abs(raw: str | Path | None, *, env: str) -> Path | None:
    value: str | Path | None = raw
    if value is None:
        value = os.environ.get(env) or None
    if value is None:
        return None
    return _absolute_dir(value, label=env)
