"""Minimal reader for the YAML frontmatter DSH writes into skill files.

DSH requires ``name`` and ``description``; ``whenToUse`` and ``metadata`` are
optional, and invocation is controlled by ``disable-model-invocation`` and
``user-invocable``. Unknown keys are preserved in ``metadata`` rather than
interpreted, because this reader must not execute or extend DSH behaviour.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import yaml

from octop.infra.dsh.skills.errors import DshSkillFrontmatterError

__all__ = ["ParsedSkillFrontmatter", "SKILL_NAME_RE", "parse_skill_text"]

# Mirrors ``isSkillName`` in @deepseek-ai/dsh-skill.
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

_TRUE = frozenset({"true", "yes", "on", "1"})
_FALSE = frozenset({"false", "no", "off", "0"})


@dataclass(frozen=True, slots=True)
class ParsedSkillFrontmatter:
    """One skill file split into routing metadata and instruction body."""

    name: str
    description: str
    body: str
    when_to_use: str = ""
    model_invocable: bool = True
    user_invocable: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)


def parse_skill_text(text: str, *, path: str) -> ParsedSkillFrontmatter:
    """Parse one ``SKILL.md`` or flat ``<name>.md`` file.

    A leading UTF-8 BOM is tolerated. The closing fence is the first line that
    is exactly ``---`` after the opening fence; a file without both fences is
    rejected instead of being treated as a body-only skill.
    """

    raw = text.lstrip("\ufeff")
    lines = raw.splitlines(keepends=True)
    if not lines or lines[0].lstrip("\ufeff").rstrip("\r\n") != "---":
        raise DshSkillFrontmatterError(
            f"DSH 技能文件缺少 frontmatter：{path}",
            details={"path": path},
        )

    closing_index = -1
    for index in range(1, len(lines)):
        if lines[index].rstrip("\r\n") == "---":
            closing_index = index
            break
    if closing_index == -1:
        raise DshSkillFrontmatterError(
            f"DSH 技能 frontmatter 未闭合：{path}",
            details={"path": path},
        )

    yaml_text = "".join(lines[1:closing_index])
    body = "".join(lines[closing_index + 1 :]).strip()
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise DshSkillFrontmatterError(
            f"DSH 技能 frontmatter 不是合法 YAML：{path}",
            details={"path": path, "reason": type(exc).__name__},
        ) from None
    if not isinstance(data, dict):
        raise DshSkillFrontmatterError(
            f"DSH 技能 frontmatter 必须是对象：{path}",
            details={"path": path},
        )

    name = str(data.get("name") or "").strip()
    description = str(data.get("description") or "").strip()
    if not name or not description:
        raise DshSkillFrontmatterError(
            f"DSH 技能 frontmatter 缺少 name 或 description：{path}",
            details={"path": path},
        )
    if not SKILL_NAME_RE.match(name):
        raise DshSkillFrontmatterError(
            f"DSH 技能名不是 kebab-case：{name}（{path}）",
            details={"path": path, "name": name},
        )

    when_to_use = str(data.get("whenToUse") or "").strip()
    metadata = data.get("metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}

    return ParsedSkillFrontmatter(
        name=name,
        description=description,
        body=body,
        when_to_use=when_to_use,
        model_invocable=_frontmatter_bool(data, "disable-model-invocation", path=path) is not True,
        user_invocable=_frontmatter_bool(data, "user-invocable", path=path) is not False,
        metadata=dict(metadata),
    )


def _frontmatter_bool(data: Mapping[str, Any], key: str, *, path: str) -> bool | None:
    if key not in data:
        return None
    value = data[key]
    if isinstance(value, bool):
        return value
    if value == 1 or value == "1":
        return True
    if value == 0 or value == "0":
        return False
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE:
            return True
        if normalized in _FALSE:
            return False
    raise DshSkillFrontmatterError(
        f"DSH 技能 frontmatter 字段 {key} 必须是布尔值：{path}",
        details={"path": path, "field": key},
    )
