"""In-process MCP gateway for Octop-hosted connector adapters.

The public helpers are loaded lazily (PEP 562) so that importing any submodule
under ``happyclaw.infra.connectors.gateway`` — e.g. the lightweight credential
materializer in ``wecom_creds`` — does not drag in the whole LangChain /
harness / cryptography tree at interpreter startup. This matters for cold boot,
where ``langchain_core`` + ``happyclaw_harness`` alone cost ~9s of import time.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "build_gateway_langchain_tools",
    "handle_mcp_request",
    "mcp_tools_for_kind",
    "agently_auth",
]

# module path, attribute name -- resolved on first access
_LAZY = {
    "build_gateway_langchain_tools": (
        "happyclaw.infra.connectors.gateway.langchain",
        "build_gateway_langchain_tools",
    ),
    "handle_mcp_request": (
        "happyclaw.infra.connectors.gateway.protocol",
        "handle_mcp_request",
    ),
    "mcp_tools_for_kind": (
        "happyclaw.infra.connectors.gateway.registry",
        "mcp_tools_for_kind",
    ),
    "agently_auth": (
        "happyclaw.infra.connectors.gateway.agently_auth",
        None,  # module itself (kept for backward compat with `from ... import agently_auth`)
    ),
}


def __getattr__(name: str) -> Any:
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module_path, attr = target
    module = importlib.import_module(module_path)
    value = module if attr is None else getattr(module, attr)
    globals()[name] = value  # cache so subsequent accesses skip __getattr__
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
