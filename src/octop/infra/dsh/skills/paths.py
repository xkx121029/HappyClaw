"""Workspace containment for DSH skill files.

DSH keeps skill bodies and their resources on the host filesystem. A manifest
may therefore point at ``../somewhere`` or a symlink that leaves the skill root.
Those requests are refused outright instead of being clipped to a path that
happens to fit inside the root: a silently rewritten path would make the audit
trail claim the skill read a file it never asked for.

The check itself is reused from the plugin sandbox so one containment rule
covers both runtimes.
"""

from __future__ import annotations

from pathlib import Path

from octop.infra.dsh.skills.errors import DshSkillPathError
from octop.infra.plugins.sandbox.errors import SandboxError
from octop.infra.plugins.sandbox.paths import WorkspaceRoot

__all__ = ["resolve_within_root"]

_BOUNDARY_OWNER = "dsh-skill"


def resolve_within_root(root: Path, requested: str | Path) -> Path:
    """Resolve ``requested`` inside ``root`` or raise :class:`DshSkillPathError`.

    Relative requests are joined to ``root``; absolute requests are accepted
    only when they already sit inside it. Symlinks are followed before the
    containment check, so a link that escapes the root is rejected.
    """

    try:
        boundary = WorkspaceRoot.create(_BOUNDARY_OWNER, root)
        return boundary.resolve(requested)
    except SandboxError as exc:
        details = {
            "requested": str(requested),
            "workspace_root": str(root),
            **exc.details,
        }
        raise DshSkillPathError(
            f"DSH 技能路径越界：{requested} 不在工作区 {root} 内，已拒绝读取。",
            details=details,
        ) from None
