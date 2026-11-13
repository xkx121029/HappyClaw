"""Read-only bridge from DSH skill declarations into Octop.

Public surface:

* :class:`DshSkillCatalog` merges roots and plugin packages deterministically.
* :func:`discover_skill_root` / :func:`discover_plugin_package` read a single
  source.
* :class:`DshSkillSummary` / :class:`DshSkillDefinition` are the neutral records.

Nothing in this package executes DSH code, downloads plugins, or mutates
Octop's existing skill catalog.
"""

from __future__ import annotations

from octop.infra.dsh.skills.catalog import DshSkillCatalog
from octop.infra.dsh.skills.discovery import (
    BUNDLED_RANK,
    CUSTOM_RANK,
    PLUGIN_RANK,
    PROJECT_AGENTS_RANK,
    PROJECT_DSH_RANK,
    USER_AGENTS_RANK,
    USER_DSH_RANK,
    DshSkillRoot,
    default_skill_roots,
    discover_plugin_package,
    discover_skill_root,
    read_skill_summary,
)
from octop.infra.dsh.skills.errors import (
    DshSkillDeclarationError,
    DshSkillDuplicateError,
    DshSkillError,
    DshSkillErrorCode,
    DshSkillFrontmatterError,
    DshSkillManifestError,
    DshSkillPathError,
    DshSkillResourceError,
    DshSkillRootError,
)
from octop.infra.dsh.skills.models import (
    DshSkillDefinition,
    DshSkillResource,
    DshSkillSummary,
)

__all__ = [
    "BUNDLED_RANK",
    "CUSTOM_RANK",
    "PLUGIN_RANK",
    "PROJECT_AGENTS_RANK",
    "PROJECT_DSH_RANK",
    "USER_AGENTS_RANK",
    "USER_DSH_RANK",
    "DshSkillCatalog",
    "DshSkillDeclarationError",
    "DshSkillDefinition",
    "DshSkillDuplicateError",
    "DshSkillError",
    "DshSkillErrorCode",
    "DshSkillFrontmatterError",
    "DshSkillManifestError",
    "DshSkillPathError",
    "DshSkillResource",
    "DshSkillResourceError",
    "DshSkillRoot",
    "DshSkillRootError",
    "DshSkillSummary",
    "default_skill_roots",
    "discover_plugin_package",
    "discover_skill_root",
    "read_skill_summary",
]
