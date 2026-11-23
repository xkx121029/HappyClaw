"""Workspace path boundary for one plugin.

All file operations resolve against the plugin's own workspace root. A request
that escapes it is denied with a readable message that names both paths; the
path is never truncated or rewritten to fit inside the root, because a silently
adjusted path would make the audit trail lie about what was asked for.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from happyclaw.infra.plugins.sandbox.errors import (
    SandboxConfigError,
    SandboxDeniedError,
    SandboxErrorCode,
    describe_exception,
)

__all__ = ["WorkspaceRoot"]


@dataclass(frozen=True, slots=True)
class WorkspaceRoot:
    """The one directory a plugin may read from and write to."""

    plugin_id: str
    path: Path

    @classmethod
    def create(cls, plugin_id: str, raw: str | Path) -> WorkspaceRoot:
        """Build a root from host configuration.

        Relative roots and strings containing NUL are rejected outright: the
        boundary would otherwise depend on whatever the process cwd happens to
        be, which makes containment unprovable.
        """

        text = str(raw)
        if not plugin_id.strip():
            raise SandboxConfigError("沙箱配置错误：工作区缺少插件 id。")
        if "\x00" in text:
            raise SandboxConfigError(
                f"沙箱配置错误：插件 {plugin_id} 的工作区路径包含非法字符。",
                details={"plugin": plugin_id},
            )
        candidate = Path(text)
        if not text.strip() or not candidate.is_absolute():
            raise SandboxConfigError(
                f"沙箱配置错误：插件 {plugin_id} 的工作区必须是绝对路径，当前为「{text}」。",
                details={"plugin": plugin_id, "workspace_root": text},
            )
        try:
            resolved = candidate.resolve()
        except (OSError, RuntimeError) as exc:
            raise SandboxConfigError(
                f"沙箱配置错误：插件 {plugin_id} 的工作区无法解析（{describe_exception(exc)}）。",
                details={"plugin": plugin_id, "workspace_root": text},
            ) from None
        return cls(plugin_id=plugin_id, path=resolved)

    def require_usable(self) -> None:
        """Deny when the root cannot be judged (missing, a file, unreadable)."""

        try:
            usable = self.path.is_dir()
        except OSError as exc:
            raise SandboxDeniedError(
                SandboxErrorCode.WORKSPACE_UNAVAILABLE,
                f"沙箱拒绝：插件 {self.plugin_id} 的工作区 {self.path} 无法访问（{describe_exception(exc)}）。",
                details={"plugin": self.plugin_id, "workspace_root": str(self.path)},
            ) from None
        if not usable:
            raise SandboxDeniedError(
                SandboxErrorCode.WORKSPACE_UNAVAILABLE,
                f"沙箱拒绝：插件 {self.plugin_id} 的工作区 {self.path} 不存在或不是目录。",
                details={"plugin": self.plugin_id, "workspace_root": str(self.path)},
            )

    def resolve(self, requested: str | Path) -> Path:
        """Resolve a request to an absolute path that is inside this root.

        Relative requests are joined to the root; absolute requests are only
        accepted when they already sit inside it. Symlinks are followed before
        the containment check, so a link inside the workspace that points
        outside is denied rather than used.
        """

        text = str(requested)
        if "\x00" in text:
            raise SandboxDeniedError(
                SandboxErrorCode.PATH_INVALID,
                f"沙箱拒绝：插件 {self.plugin_id} 请求的路径包含非法字符。",
                details={"plugin": self.plugin_id},
            )
        if not text.strip():
            raise SandboxDeniedError(
                SandboxErrorCode.PATH_INVALID,
                f"沙箱拒绝：插件 {self.plugin_id} 请求了空路径。",
                details={"plugin": self.plugin_id},
            )

        candidate = Path(text)
        if not candidate.is_absolute():
            candidate = self.path / candidate
        try:
            resolved = candidate.resolve()
        except (OSError, RuntimeError) as exc:
            raise SandboxDeniedError(
                SandboxErrorCode.PATH_INVALID,
                f"沙箱拒绝：路径 {text} 无法解析（{describe_exception(exc)}）。",
                details={"plugin": self.plugin_id, "requested": text},
            ) from None

        try:
            resolved.relative_to(self.path)
        except ValueError:
            raise SandboxDeniedError(
                SandboxErrorCode.PATH_OUTSIDE_WORKSPACE,
                f"沙箱拒绝：路径 {text} 超出了插件 {self.plugin_id} 的工作区 {self.path}。",
                details={
                    "plugin": self.plugin_id,
                    "requested": text,
                    "resolved": str(resolved),
                    "workspace_root": str(self.path),
                },
            ) from None
        return resolved
