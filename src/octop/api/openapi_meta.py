"""OpenAPI metadata for Scalar API docs."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from octop.api.deps import is_jwt_exempt_path

API_DESCRIPTION = """\
**HappyClaw** is a local-first, single-user AI assistant. All routes are served under `/api`.

## Authentication

HappyClaw runs as a single local owner on this machine. There is no login, session,
role, or bearer-token gate: every request is handled as that owner, and
`/api/setup/*` is available while the first-run wizard is still open.

The desktop shell keeps its local credential bound through `/api/auth/device/*`
(`register` records it, `token` exchanges it on cold start).

Multi-user endpoints from earlier releases (invites, roles, SSO/OIDC/OAuth, LDAP,
MFA, passkey) are retired and answer `404` with `SINGLE_USER_UNSUPPORTED`.

## Streaming chat

Dashboard live turns use **WebSocket** at `/api/agents/{agent_id}/chat/ws`. Send
`{"type":"user_turn", ...}` frames; the server replies with JSON chunks matching the
harness stream format, ending with `{"type":"done"}` or
`{"type":"error","message":"..."}`.

Text-type dashboard pushes (cron reminders, proactive care) also emit
`{"type":"dashboard_push", ...}` on `/api/notifications/ws` so the SPA can show a toast
even when the chat socket is not subscribed.

HITL resume still uses `POST /api/agents/{agent_id}/chat/hitl/resume` (SSE).

Frame payloads are published as schemas so clients can type the stream: every
harness chunk (`token`, `tool_call_chunk`, `done`, `error`, `hitl_required`, …) matches
`ChatStreamChunk`, and anything the chat socket can push — chunks plus turn lifecycle,
steer-queue, and control frames — matches `ChatWsServerFrame`. OpenAPI has no
WebSocket operations, so these live in `components/schemas` only.
"""

OPENAPI_TAGS: list[dict[str, str]] = [
    {
        "name": "setup",
        "description": "First-run wizard: create the admin user and optional LLM provider.",
    },
    {"name": "auth", "description": "Sign in, sign out, and manage the current user profile."},
    {"name": "health", "description": "Liveness probe for load balancers and monitoring."},
    {"name": "users", "description": "Admin user management, roles, and user groups."},
    {
        "name": "agents",
        "description": "Create and configure AI agents; start, stop, and inspect runtime status.",
    },
    {
        "name": "chat",
        "description": "Dashboard chat: WebSocket streaming, threads, conversation history, trajectory ledger, and text-push toasts.",
    },
    {
        "name": "slash",
        "description": "Slash command metadata for composer menus and inline help.",
    },
    {
        "name": "connectors",
        "description": "Third-party integrations (Notion, Figma, …) exposed as MCP servers.",
    },
    {
        "name": "bridge",
        "description": "Link this HappyClaw to remote HappyClaw instances (HTTP tunnel + remote chat).",
    },
    {
        "name": "knowledge",
        "description": "Private, shareable document knowledge bases and their indexing capability.",
    },
    {
        "name": "internal-mcp",
        "description": "Internal MCP gateway used by harness agents (no dashboard auth).",
    },
    {
        "name": "agent-mcp",
        "description": "Authenticated MCP gateway for external agents to call HappyClaw experts.",
    },
    {
        "name": "channels",
        "description": "Instant-messaging bridges (WeCom, Feishu, Telegram, …) per agent.",
    },
    {
        "name": "cron",
        "description": "Scheduled prompts that run against an agent on a cron trigger.",
    },
    {
        "name": "settings",
        "description": "Process-level settings (timezone, upload size limit, HITL switch, login captcha).",
    },
    {
        "name": "envs",
        "description": "Global environment variables (~/.octop/env) inherited by every agent.",
    },
    {
        "name": "search",
        "description": "Web-search provider API key probes (Tavily, Brave, DeepSeek, Google, Kimi).",
    },
    {"name": "providers", "description": "LLM provider configuration and active model selection."},
    {"name": "voice", "description": "Speech-to-text and text-to-speech provider configuration."},
    {
        "name": "observability",
        "description": "LLM observability integrations (Langfuse tracing).",
    },
    {
        "name": "tls",
        "description": "Let's Encrypt HTTPS certificate issuance and status.",
    },
    {
        "name": "security",
        "description": "Agent security policy: tool approval (HITL), command guard rules, filesystem rules, PII redaction.",
    },
    {"name": "admin", "description": "Server-wide admin operations (audit log, storage, usage)."},
    {"name": "storage-backends", "description": "User-visible remote storage backend connections."},
    {
        "name": "filesystem",
        "description": "Host filesystem directory browsing for dashboard forms.",
    },
    {"name": "mbti", "description": "MBTI persona presets applied to agent personality."},
    {"name": "experts", "description": "Bundled expert templates for creating specialized agents."},
    {
        "name": "teams",
        "description": "Expert teams: roster, create/edit, and member dispatch.",
    },
    {
        "name": "text-assist",
        "description": (
            "One-shot LLM polish/generate for form copy and chat composer prompts. "
            "Prompts are managed in backend i18n."
        ),
    },
    {"name": "workspace", "description": "Agent workspace file tree: list, read, write, upload."},
    {"name": "agent_files", "description": "Agent-owned configuration files (SOUL.md, skills, …)."},
    {"name": "usage", "description": "Token usage summaries for billing and dashboards."},
    {
        "name": "skill-packages",
        "description": "Instance-global skill package catalog and package skill content.",
    },
    {"name": "skills", "description": "Per-agent skills and Skill Hub marketplace search."},
    {
        "name": "subagents",
        "description": "Per-agent subagent definitions (agents/*.md) and bundled catalog install.",
    },
    {"name": "terminal", "description": "AI-assisted remote terminal sessions."},
    {"name": "update", "description": "In-place server update checks and apply flow."},
    {
        "name": "browser",
        "description": "Remote browser: env/install, harness sessions, live stream, record/replay.",
    },
    {
        "name": "desktop",
        "description": "Remote OS desktop stream and input injection (admin only).",
    },
    {"name": "ollama", "description": "Local Ollama model discovery and download management."},
    {
        "name": "onnx",
        "description": "Local ONNX / fastembed embedding service: enable, catalog, and download.",
    },
    {"name": "i18n", "description": "Locale bundles served to the dashboard."},
    {"name": "device-link", "description": "Paired phone App: pair, connect, command, screenshots, live events."},
    {"name": "plugins", "description": "Plugin catalog, install/uninstall, market sources, and per-agent plugin tools."},
    {"name": "memory", "description": "Agent memory: search, read, save, and portable import/export."},
    {"name": "backup", "description": "Backup archives: create, list, restore, import/export, and schedule."},
    {"name": "proactive-care", "description": "Proactive care messages generated from recent life events."},
    {"name": "cloud", "description": "Cloud provider accounts: authorize, list regions/instances, and run actions."},
]

_BEARER_SCHEME = {
    "type": "http",
    "scheme": "bearer",
    "bearerFormat": "JWT",
    "description": "Legacy bearer scheme kept for schema compatibility; single-user mode does not enforce tokens.",
}


def configure_openapi(app: FastAPI) -> None:
    """Attach tag descriptions, the API intro, and the legacy security scheme."""

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema

        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=API_DESCRIPTION,
            routes=app.routes,
            tags=OPENAPI_TAGS,
        )
        components = schema.setdefault("components", {})
        components.setdefault("securitySchemes", {})["BearerAuth"] = _BEARER_SCHEME
        # Chat payload mirrors hide their fields from FastAPI's serialization
        # pass, and WebSocket/SSE frames have no operation of their own; publish
        # their schemas so generated clients can type chat and its stream.
        from octop.api.routers.chat.events import stream_event_schemas  # noqa: PLC0415
        from octop.api.routers.chat.responses import RESPONSE_MODELS, model_schemas  # noqa: PLC0415

        schemas = components.setdefault("schemas", {})
        schemas.update(model_schemas(RESPONSE_MODELS))
        schemas.update(stream_event_schemas())

        for path, path_item in schema.get("paths", {}).items():
            if not path.startswith("/api/") or is_jwt_exempt_path(path):
                continue
            for operation in path_item.values():
                if isinstance(operation, dict) and "security" not in operation:
                    operation["security"] = [{"BearerAuth": []}]

        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]
