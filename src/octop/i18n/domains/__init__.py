"""Per-namespace i18n helpers (each maps to a top-level JSON key).

Exports are resolved lazily via PEP 562.  Historically this module eagerly
imported every domain — including ``domains.stream``, whose top level imports
``langchain_core``.  That pulled the whole LangChain import tree into any CLI
or error-handling path merely doing ``from octop.infra.errors import OctopError``.

Importing ``octop.i18n.domains`` (or any *other* submodule) now stays cheap.
Code that targets a specific submodule directly
(``from octop.i18n.domains.stream import ...``) is unaffected, and every public
name below still resolves on attribute access.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

# symbol -> submodule that defines it.  Values with a ":" suffix are an
# alias: "public_name: module_attr" (slash_tr is imported as `tr` upstream).
_SYMBOL_TO_MODULE: dict[str, str] = {
    "MODEL_REF_UNAVAILABLE": "agents",
    "NO_MODELS_CONFIGURED": "agents",
    "agent_error_message": "agents",
    "agent_state_label": "agents",
    "classify_agent_start_error_message": "agents",
    "format_agent_start_error": "agents",
    "attachment_empty_image": "attachment",
    "attachment_empty_message": "attachment",
    "attachment_extracted_body": "attachment",
    "attachment_image_unavailable": "attachment",
    "attachment_path_hint": "attachment",
    "channel_tool_hint_end": "channel",
    "channel_tool_hint_start": "channel",
    "error_message": "errors",
    "field_label": "slash",
    "localized_rows": "slash",
    "slash_tr": "slash:tr",
    "classify_stream_error_message": "stream",
    "format_stream_error": "stream",
    "stream_error_message": "stream",
    "HITL_TOOL_EXCLUDE": "tools",
    "HitlToolCatalogEntry": "tools",
    "all_tool_labels": "tools",
    "hitl_tool_catalog": "tools",
    "tool_display_name": "tools",
}

__all__ = list(_SYMBOL_TO_MODULE)


def __getattr__(name: str) -> Any:
    target = _SYMBOL_TO_MODULE.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if ":" in target:
        module_name, attr_name = target.split(":", 1)
    else:
        module_name, attr_name = target, name
    module = import_module(f"{__name__}.{module_name}")
    value = getattr(module, attr_name)
    globals()[name] = value  # cache so subsequent access is a plain dict hit
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
