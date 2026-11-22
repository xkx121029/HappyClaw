"""Deterministic catalog over DSH skill roots and plugin packages.

Precedence is explicit: lower ``rank`` wins, then earlier root order, then the
skill name. Nothing is cached between calls, so two discoveries over unchanged
files always produce the same order and the same contents.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from happyclaw.infra.dsh.skills.discovery import (
    DshSkillRoot,
    discover_plugin_package,
    discover_skill_root,
)
from happyclaw.infra.dsh.skills.errors import (
    DshSkillDuplicateError,
    DshSkillError,
    DshSkillFrontmatterError,
    DshSkillManifestError,
)
from happyclaw.infra.dsh.skills.frontmatter import parse_skill_text
from happyclaw.infra.dsh.skills.models import DshSkillDefinition, DshSkillSummary
from happyclaw.infra.dsh.skills.paths import resolve_within_root
from happyclaw.infra.skills.skill_packages import (
    ResolvedSkillPackage,
    resolve_workspace_uploads,
)

__all__ = ["DshSkillCatalog"]


@dataclass(frozen=True, slots=True)
class _Candidate:
    summary: DshSkillSummary
    position: int


class DshSkillCatalog:
    """Read DSH skills without owning or mutating Octop's skill catalog."""

    def __init__(
        self,
        roots: Iterable[DshSkillRoot] = (),
        *,
        plugin_packages: Sequence[str | Path] = (),
    ) -> None:
        self._roots = tuple(roots)
        self._plugin_packages = tuple(Path(package) for package in plugin_packages)
        self._last_summaries: tuple[DshSkillSummary, ...] = ()
        self._discovered = False

    def discover(self, *, strict: bool = False) -> tuple[DshSkillSummary, ...]:
        """Return merged summaries sorted by name.

        Read failures are contained per root unless ``strict`` is set. Duplicate
        names keep the highest-priority definition; ``strict`` turns the
        collision into :class:`DshSkillDuplicateError` instead of preferring one.
        """

        candidates: list[_Candidate] = []
        position = 0
        for root in self._roots:
            try:
                found = discover_skill_root(root, strict=strict)
            except DshSkillError:
                if strict:
                    raise
                continue
            for summary in found:
                candidates.append(_Candidate(summary, position))
                position += 1
        for package in self._plugin_packages:
            try:
                found = discover_plugin_package(package, strict=strict)
            except DshSkillError:
                if strict:
                    raise
                continue
            for summary in found:
                candidates.append(_Candidate(summary, position))
                position += 1

        candidates.sort(key=lambda item: (item.summary.rank, item.position))
        merged: dict[str, DshSkillSummary] = {}
        for candidate in candidates:
            name = candidate.summary.name
            if name in merged:
                if strict:
                    raise DshSkillDuplicateError(
                        f"DSH 技能名重复：{name}",
                        details={
                            "name": name,
                            "kept": str(merged[name].path),
                            "ignored": str(candidate.summary.path),
                        },
                    )
                continue
            merged[name] = candidate.summary

        self._last_summaries = tuple(sorted(merged.values(), key=lambda item: item.name))
        self._discovered = True
        return self._last_summaries

    def summaries(self) -> tuple[DshSkillSummary, ...]:
        """Return the last discovery result, running discovery once when needed."""

        if not self._discovered:
            return self.discover()
        return self._last_summaries

    def load(self, name: str) -> DshSkillDefinition:
        """Read one skill body, re-checking its path after discovery."""

        for summary in self.summaries():
            if summary.name == name:
                return self._load_summary(summary)
        raise DshSkillManifestError(
            f"DSH 技能不在清单中：{name}",
            details={"name": name},
        )

    def load_all(self) -> tuple[DshSkillDefinition, ...]:
        return tuple(self._load_summary(summary) for summary in self.summaries())

    def materialize(self, name: str) -> ResolvedSkillPackage:
        """Build Octop's workspace-upload package for one skill.

        Only the manifest and the resources the body actually references are
        copied, so a flat skill next to unrelated files does not drag them in.
        """

        definition = self.load(name)
        uploads: list[tuple[str, bytes]] = [
            (
                f"skills/{definition.name}/SKILL.md",
                definition.render_skill_markdown().encode("utf-8"),
            )
        ]
        for resource in definition.resources:
            resolved = resolve_within_root(definition.root, resource.path)
            if not resolved.is_file():
                raise DshSkillManifestError(
                    f"DSH 技能资源在读取时已不存在：{resource.relative_path}",
                    details={"skill": definition.name, "resource": resource.relative_path},
                )
            uploads.append(
                (f"skills/{definition.name}/{resource.relative_path}", resolved.read_bytes())
            )
        return resolve_workspace_uploads(
            slug=definition.name,
            uploads=uploads,
            source=f"dsh:{definition.source}",
        )

    def _load_summary(self, summary: DshSkillSummary) -> DshSkillDefinition:
        resolved = resolve_within_root(summary.root, summary.path)
        if not resolved.is_file():
            raise DshSkillManifestError(
                f"DSH 技能文件不存在：{resolved}",
                details={"path": str(resolved), "name": summary.name},
            )
        try:
            text = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise DshSkillManifestError(
                f"DSH 技能文件无法读取：{resolved}",
                details={"path": str(resolved), "reason": type(exc).__name__},
            ) from None
        parsed = parse_skill_text(text, path=str(resolved))
        if parsed.name != summary.name:
            raise DshSkillFrontmatterError(
                f"DSH 技能名在读取后发生变化：{summary.name} -> {parsed.name}",
                details={
                    "path": str(resolved),
                    "expected": summary.name,
                    "actual": parsed.name,
                },
            )
        return DshSkillDefinition(
            name=summary.name,
            description=parsed.description,
            path=resolved,
            root=summary.root,
            resource_base=summary.resource_base,
            source=summary.source,
            rank=summary.rank,
            when_to_use=parsed.when_to_use,
            model_invocable=parsed.model_invocable,
            user_invocable=parsed.user_invocable,
            metadata=parsed.metadata,
            resources=summary.resources,
            body=parsed.body,
        )
