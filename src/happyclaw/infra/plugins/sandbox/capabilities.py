"""Capability declarations for plugins and tools.

A tool only gets what it explicitly declares. Nothing is inferred from the
tool name, the plugin metadata, or a previous call: an unknown or missing
declaration is a denial, never a default grant (fail-closed).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from happyclaw.infra.plugins.sandbox.errors import SandboxConfigError, SandboxErrorCode

__all__ = [
    "CAPABILITY_LABELS",
    "CapabilityDeclaration",
    "SandboxCapability",
    "capability_labels",
    "parse_capabilities",
    "parse_capability",
]


class SandboxCapability(StrEnum):
    """What a tool is allowed to do outside its own in-memory state."""

    FS_READ = "fs.read"
    FS_WRITE = "fs.write"
    EXEC = "exec"
    NETWORK = "network"


CAPABILITY_LABELS: Mapping[SandboxCapability, str] = {
    SandboxCapability.FS_READ: "读文件",
    SandboxCapability.FS_WRITE: "写文件",
    SandboxCapability.EXEC: "执行命令",
    SandboxCapability.NETWORK: "网络访问",
}

FILE_CAPABILITIES: frozenset[SandboxCapability] = frozenset(
    {SandboxCapability.FS_READ, SandboxCapability.FS_WRITE}
)


def parse_capability(raw: object) -> SandboxCapability:
    """Parse one capability name, refusing anything the sandbox does not know."""

    if isinstance(raw, SandboxCapability):
        return raw
    text = str(raw).strip() if isinstance(raw, str) else ""
    try:
        return SandboxCapability(text)
    except ValueError:
        valid = "、".join(capability.value for capability in SandboxCapability)
        raise SandboxConfigError(
            f"沙箱配置错误：无法识别的能力「{raw}」，可用值为 {valid}。",
            details={
                "capability": str(raw),
                "valid": sorted(cap.value for cap in SandboxCapability),
            },
        ) from None


def parse_capabilities(raw: object) -> frozenset[SandboxCapability]:
    """Parse a declared capability list.

    ``None`` means "declared nothing" and yields the empty set; every operation
    then denies. A bare string is accepted as exactly one capability because the
    intent is unambiguous; a comma-joined string is not split, so it fails loud
    rather than being guessed.
    """

    if raw is None:
        return frozenset()
    if isinstance(raw, str) or isinstance(raw, SandboxCapability):
        return frozenset({parse_capability(raw)})
    if not isinstance(raw, Iterable) or isinstance(raw, (bytes, bytearray, Mapping)):
        raise SandboxConfigError(
            "沙箱配置错误：能力声明必须是名称列表。",
            details={"value": repr(raw)},
        )
    return frozenset(parse_capability(item) for item in raw)


def capability_labels(capabilities: Iterable[SandboxCapability]) -> str:
    """Render capabilities as readable Chinese for denial messages."""

    ordered = [cap for cap in SandboxCapability if cap in set(capabilities)]
    if not ordered:
        return "（无）"
    return "、".join(CAPABILITY_LABELS[cap] for cap in ordered)


@dataclass(frozen=True, slots=True)
class CapabilityDeclaration:
    """What one tool of one plugin says it needs."""

    plugin_id: str
    tool_name: str
    capabilities: frozenset[SandboxCapability]

    def __post_init__(self) -> None:
        if not self.plugin_id.strip():
            raise SandboxConfigError(
                "沙箱配置错误：能力声明缺少插件 id。",
                details={"code": SandboxErrorCode.DECLARATION_INVALID.value},
            )
        if not self.tool_name.strip():
            raise SandboxConfigError(
                f"沙箱配置错误：插件 {self.plugin_id} 的能力声明缺少工具名。",
                details={"plugin": self.plugin_id},
            )
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))

    def declares(self, capability: SandboxCapability) -> bool:
        return capability in self.capabilities

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "tool_name": self.tool_name,
            "capabilities": sorted(cap.value for cap in self.capabilities),
        }
