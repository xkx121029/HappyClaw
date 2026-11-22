"""Stable failure codes for reading DSH skill declarations.

Every failure is raised while reading a manifest or a skill body, never while
executing DSH code. Messages are safe to show to the local owner: they name the
offending path but never include a traceback.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

__all__ = [
    "DshSkillDeclarationError",
    "DshSkillDuplicateError",
    "DshSkillError",
    "DshSkillErrorCode",
    "DshSkillFrontmatterError",
    "DshSkillManifestError",
    "DshSkillPathError",
    "DshSkillResourceError",
    "DshSkillRootError",
]


class DshSkillErrorCode(StrEnum):
    """Machine-readable DSH skill failure codes."""

    ROOT_INVALID = "DSH_SKILL_ROOT_INVALID"
    DECLARATION_INVALID = "DSH_SKILL_DECLARATION_INVALID"
    MANIFEST_MISSING = "DSH_SKILL_MANIFEST_MISSING"
    FRONTMATTER_INVALID = "DSH_SKILL_FRONTMATTER_INVALID"
    PATH_OUTSIDE_ROOT = "DSH_SKILL_PATH_OUTSIDE_ROOT"
    RESOURCE_MISSING = "DSH_SKILL_RESOURCE_MISSING"
    DUPLICATE_NAME = "DSH_SKILL_DUPLICATE_NAME"


class DshSkillError(Exception):
    """Base DSH skill failure carrying a stable code plus structured details."""

    code: DshSkillErrorCode = DshSkillErrorCode.DECLARATION_INVALID

    def __init__(
        self,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "details": dict(self.details),
        }

    def __str__(self) -> str:
        return self.message


class DshSkillRootError(DshSkillError):
    """A configured skill root cannot be used as a workspace boundary."""

    code = DshSkillErrorCode.ROOT_INVALID


class DshSkillDeclarationError(DshSkillError):
    """A plugin manifest declares skills in a shape this reader cannot follow."""

    code = DshSkillErrorCode.DECLARATION_INVALID


class DshSkillManifestError(DshSkillError):
    """A declared skill file or directory does not exist."""

    code = DshSkillErrorCode.MANIFEST_MISSING


class DshSkillFrontmatterError(DshSkillError):
    """A skill file has no usable YAML frontmatter."""

    code = DshSkillErrorCode.FRONTMATTER_INVALID


class DshSkillPathError(DshSkillError):
    """A declared path resolves outside its workspace root and is refused."""

    code = DshSkillErrorCode.PATH_OUTSIDE_ROOT


class DshSkillResourceError(DshSkillError):
    """A resource referenced by a skill body is missing or unusable."""

    code = DshSkillErrorCode.RESOURCE_MISSING


class DshSkillDuplicateError(DshSkillError):
    """Two skills claim the same name inside one root, or strict mode saw a duplicate."""

    code = DshSkillErrorCode.DUPLICATE_NAME
