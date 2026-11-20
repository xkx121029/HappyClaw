"""联网搜索来源选择：HappySearch / 原生 searchfree / 两者结合。

持久化在 ``settings`` KV 表（键 ``search.source``），环境变量
``OCTOP_SEARCH_SOURCE`` 优先覆盖。仅依赖标准库；商业 provider 的
环境变量表按需从 harness 惰性导入。
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

SEARCH_SOURCE_KEY = "search.source"
DEFAULT_SOURCE = "happysearch"
SOURCE_ENV = "OCTOP_SEARCH_SOURCE"
VALID_SOURCES = ("happysearch", "searchfree", "both")

Origin = Literal["env", "settings", "default"]

_ALIASES = {
    "happy": "happysearch",
    "happy_search": "happysearch",
    "native": "searchfree",
    "native_search": "searchfree",
    "combined": "both",
    "mix": "both",
}

_TOOL_BY_PROVIDER = {
    "tavily": "tavily_search",
    "brave": "brave_search",
    "deepseek": "deepseek_search",
    "google": "google_search",
    "kimi": "kimi_search",
    "yuanbao": "yuanbao_search",
    "you": "you_search",
}


@dataclass(frozen=True)
class SourceState:
    effective: str
    stored: str | None
    env: str | None
    origin: Origin


def parse_source(value: object) -> str | None:
    """Normalize a stored/env/request value; return ``None`` when invalid."""
    if not isinstance(value, str):
        return None
    raw = value.strip().lower()
    if not raw:
        return None
    raw = _ALIASES.get(raw, raw)
    return raw if raw in VALID_SOURCES else None


def _legacy_happy_disabled() -> bool:
    """``OCTOP_HAPPYSEARCH_TOOL=0`` used to mean "do not mount HappySearch"."""
    raw = os.getenv("OCTOP_HAPPYSEARCH_TOOL")
    if raw is None:
        return False
    return raw.strip().lower() not in ("1", "true", "yes", "on")


def load_source(settings_repo: Any) -> SourceState:
    """Resolve the effective source. Never raises on malformed stored data."""
    stored = None
    if settings_repo is not None:
        stored = parse_source(settings_repo.get(SEARCH_SOURCE_KEY))

    env_value = parse_source(os.getenv(SOURCE_ENV))
    if env_value is not None:
        return SourceState(env_value, stored, env_value, "env")
    if stored is not None:
        return SourceState(stored, stored, None, "settings")
    if _legacy_happy_disabled():
        return SourceState("searchfree", stored, None, "env")
    return SourceState(DEFAULT_SOURCE, stored, None, "default")


def save_source(settings_repo: Any, value: str) -> SourceState:
    parsed = parse_source(value)
    if parsed is None:
        raise ValueError(f"invalid search source: {value!r}; expected one of {VALID_SOURCES}")
    settings_repo.set(SEARCH_SOURCE_KEY, parsed)
    return load_source(settings_repo)


def _provider_requirements() -> dict[str, tuple[str, ...]]:
    from octop_harness.builtin.tools.web_search._registry import (  # noqa: PLC0415
        _AUTO_REQUIRED_ENV,
        WEB_SEARCH_PROVIDERS,
    )

    requirements: dict[str, tuple[str, ...]] = {}
    for name, (env_vars, _loader) in WEB_SEARCH_PROVIDERS.items():
        if name == "searchfree":
            continue
        requirements[name] = tuple(env_vars) + tuple(_AUTO_REQUIRED_ENV.get(name, ()))
    return requirements


def commercial_providers() -> list[str]:
    """Configured third-party providers. These are additive, never a replacement."""
    return [
        name
        for name, env_vars in _provider_requirements().items()
        if all(os.getenv(item) for item in env_vars)
    ]


def harness_policy(state: SourceState, *, agent_cfg: Mapping[str, Any]) -> bool | list[str]:
    """Value for ``HarnessAgentConfig.web_search_tools``.

    ``searchfree`` is always excluded: the free source is mounted by Octop
    itself so the model never sees two competing free-search tools.
    """
    if agent_cfg.get("web_search_tools") is False:
        return False
    providers = commercial_providers()
    return providers or False


def visible_tool_names(state: SourceState, *, agent_cfg: Mapping[str, Any]) -> list[str]:
    """Tool names the model is expected to see for this configuration."""
    if agent_cfg.get("web_search_tools") is False:
        return []
    names = [_TOOL_BY_PROVIDER.get(name, f"{name}_search") for name in commercial_providers()]
    if state.effective in ("happysearch", "both"):
        names.append("happysearch_search")
    else:
        names.append("searchfree_search")
    return names


__all__ = [
    "DEFAULT_SOURCE",
    "SEARCH_SOURCE_KEY",
    "SOURCE_ENV",
    "VALID_SOURCES",
    "SourceState",
    "commercial_providers",
    "harness_policy",
    "load_source",
    "parse_source",
    "save_source",
    "visible_tool_names",
]
