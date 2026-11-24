"""``octop selfcheck`` — prove the runtime can build an agent before shipping.

A PyInstaller bundle can import fine and still be missing a *lazy* dependency
that only surfaces on the first chat turn (that is exactly how ``numpy`` went
missing: ``langchain_aws.embeddings.bedrock`` is imported during agent graph
construction, not at boot). This command walks the same import surface and
compiles a throwaway LangGraph, so ``scripts/packaging/verify_backend.py`` can
fail the build instead of letting a user discover it.

It never touches the network and never needs database rows.
"""

from __future__ import annotations

import json
import sys
from typing import Any, TypedDict

import click

# Imported by the first chat turn / agent graph construction. Keep in sync with
# the provider integrations under ``octop/infra/agents/providers``.
_IMPORTS: tuple[tuple[str, str], ...] = (
    ("happyclaw.api.app", "happyclaw.api.app"),
    ("happyclaw.infra.server", "happyclaw.infra.server"),
    ("happyclaw.infra.agents.manager", "happyclaw.infra.agents.manager"),
    ("happyclaw_harness", "happyclaw_harness"),
    ("langchain_core", "langchain_core"),
    ("langchain", "langchain"),
    ("langchain_aws", "langchain_aws"),
    ("langchain_aws.embeddings.bedrock", "langchain_aws.embeddings.bedrock"),
    ("langchain_openai", "langchain_openai"),
    ("langchain_anthropic", "langchain_anthropic"),
    ("langchain_google_genai", "langchain_google_genai"),
    ("langchain_community", "langchain_community"),
    ("langchain_mcp_adapters", "langchain_mcp_adapters"),
    ("tiktoken", "tiktoken"),
    ("tiktoken_ext.openai_public", "tiktoken_ext.openai_public"),
    ("tqdm", "tqdm"),
    ("numpy", "numpy"),
    # The bundle prunes googleapiclient's offline discovery corpus. These two
    # are the only consumers; importing them proves the modules (not the data)
    # survive the prune.
    ("googleapiclient.discovery", "googleapiclient.discovery"),
    ("langchain_community.document_loaders.googledrive", "langchain_community.document_loaders.googledrive"),
    ("langchain_community.agent_toolkits.gmail.toolkit", "langchain_community.agent_toolkits.gmail.toolkit"),
)


class _GraphState(TypedDict):
    messages: list[Any]


@click.command("selfcheck")
def selfcheck() -> None:
    """Import the agent stack and compile one throwaway graph."""
    imports: list[str] = []
    failures: list[dict[str, str]] = []

    # Must run before googleapiclient.discovery is imported, so the finder can
    # wrap build() and turn a missing offline document into a network fetch.
    from happyclaw.infra.utils.google_discovery import install_google_discovery_fallback

    install_google_discovery_fallback()

    for label, module in _IMPORTS:
        try:
            __import__(module)
        except Exception as exc:  # noqa: BLE001 - report, don't crash
            failures.append({"module": module, "error": f"{type(exc).__name__}: {exc}"})
        else:
            imports.append(label)

    google_info: dict[str, object] | None = None
    try:
        from happyclaw.infra.utils.google_discovery import (
            missing_documents_hint,
            offline_documents_present,
            patch_installed,
        )

        google_info = {
            "offline_documents": offline_documents_present(),
            "network_fallback": patch_installed(),
            "hint_zh": missing_documents_hint(),
        }
        if not google_info["network_fallback"]:
            failures.append(
                {
                    "module": "google-discovery-fallback",
                    "error": "googleapiclient.discovery.build 没有被联网回退包装",
                }
            )
    except Exception as exc:  # noqa: BLE001
        failures.append({"module": "google-discovery", "error": f"{type(exc).__name__}: {exc}"})

    graph_info: dict[str, object] | None = None
    try:
        from langchain_core.messages import HumanMessage
        from langgraph.graph import END, START, StateGraph

        def _agent_node(state: _GraphState) -> dict[str, list[Any]]:
            return {"messages": [*state.get("messages", []), HumanMessage(content="ping")]}

        builder = StateGraph(_GraphState)
        builder.add_node("agent", _agent_node)
        builder.add_edge(START, "agent")
        builder.add_edge("agent", END)
        compiled = builder.compile()
        final = compiled.invoke({"messages": []})
        graph_info = {"nodes": 1, "messages": len(final.get("messages", []))}
    except Exception as exc:  # noqa: BLE001
        failures.append({"module": "agent-graph", "error": f"{type(exc).__name__}: {exc}"})

    # The bundle embeds the dashboard; verify the stamp written at packaging
    # time still matches the entry file that actually shipped.
    dashboard_info: dict[str, object] | None = None
    try:
        import hashlib

        from happyclaw.infra.utils.build_info import dashboard_build_info, dashboard_dir

        stamp = dashboard_build_info() or {}
        root = dashboard_dir()
        index = root / "index.html" if root is not None else None
        actual = (
            hashlib.sha256(index.read_bytes()).hexdigest() if index and index.is_file() else None
        )
        expected = stamp.get("index_sha256")
        dashboard_info = {
            "built_at": stamp.get("dashboard_built_at"),
            "git_commit": (stamp.get("git_commit") or "")[:12],
            "index_sha256": actual,
            "stamp_sha256": expected,
            "match": bool(expected) and actual == expected,
        }
        if not dashboard_info["match"]:
            failures.append(
                {
                    "module": "dashboard-index",
                    "error": "产物内 dashboard/index.html 的 sha256 与打包时写入的 version.json 不一致"
                    "（前端未重建或拷贝了旧产物）",
                }
            )
    except Exception as exc:  # noqa: BLE001
        failures.append({"module": "dashboard-index", "error": f"{type(exc).__name__}: {exc}"})

    ok = not failures
    click.echo(
        json.dumps(
            {
                "ok": ok,
                "imports": imports,
                "failures": failures,
                "graph": graph_info,
                "google_discovery": google_info,
                "dashboard": dashboard_info,
            },
            ensure_ascii=False,
        )
    )
    if not ok:
        sys.exit(1)
