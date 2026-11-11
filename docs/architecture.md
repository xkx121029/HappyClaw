# Architecture

HappyClaw is a single-user, local AI assistant workspace with multiple agents,
delivered as a single Python process.
It glues three reusable libraries — `octop-harness` (LangGraph-based
chat runtime), `octop-gateway` (IM channel pipeline), and a React
+ TypeScript dashboard — into one wheel that ships with a CLI, an
HTTP/WebSocket API, and a web UI.

> Looking for the contributor-facing navigation guide (module boundaries,
> change workflow, hard bans)? See [AGENTS.md](../AGENTS.md) at the repo
> root. This document is the **human-readable** overview; AGENTS.md is
> the **agent-facing** handbook.

## 1. Layering

```
┌──────────────────────────────────────────────────────────────────┐
│  Surface          │  Dashboard (React)   CLI (click)   HTTP API │
├──────────────────────────────────────────────────────────────────┤
│  API layer        │  FastAPI routers       WS / SSE / JSON        │
├──────────────────────────────────────────────────────────────────┤
│  Domain layer     │  AgentManager   Gateway   GlobalProcessor     │
│                   │  CronManager    LocalOwner  SharedServices    │
├──────────────────────────────────────────────────────────────────┤
│  Reusable libs    │  octop-harness   octop-gateway            │
├──────────────────────────────────────────────────────────────────┤
│  Storage          │  SQLite or PostgreSQL control plane + file workspaces│
└──────────────────────────────────────────────────────────────────┘
```

The whole stack is one process. There is no separate worker, no
external queue, no required external services beyond whatever LLM
provider the user configures.

## 2. Process model

`OctopServer.start()` wires the runtime tree in dependency order. The
composition root lives in `src/octop/infra/server.py`; FastAPI/uvicorn
is attached from `src/octop/launch.py` (the only module that may import
both `infra/server` and `api/app`).

```
OctopServer.start()
 ├─ PathLayout.from_env()            (root + DB + secrets dirs)
 ├─ load_config(config.json)        (env overrides on top)
 ├─ open_database()                  (SQLite WAL or PostgreSQL via PostgresPool)
 ├─ run_migrations()                 (infra/db/migrations/*.sql, versioned)
 ├─ SharedServices (repos + factories)
 ├─ LocalOwner                       (resolve-or-create the single owner row)
 ├─ ExpertCatalog  / SubagentCatalog (bundled MD libraries)
 ├─ PluginManager.seed_bundled() then load_installed()  (~/.octop/plugins/*; bundled default off)
 ├─ AgentManager (global registry — one per process)
 │    └─ for each agent row: builds HarnessAgentRuntime on demand
 │       ├─ HarnessAgent (LangGraph)
 │       ├─ GlobalProcessor (slash dispatch + chunk projection)
 │       └─ BackendWorkspace (filesystem or remote storage adapter)
 ├─ Gateway                         (IM channels + WS hub + cron trigger source)
 │    ├─ ChannelManager (one per agent that has a channel row)
 │    └─ WebSocketHub  (dashboard + CLI channel)
 ├─ CronManager (process-wide APScheduler)
 └─ CronManager (process-wide APScheduler)
```

The `AppRuntime` dataclass holds the four live singletons that
`api/routers/*` reach via `server.app_runtime.<thing>`.

### Single local user

HappyClaw binds every request to one `local` owner row created on first boot.
There is no login, JWT verification, role check, or per-user isolation: the
auth middleware injects the owner, and the legacy `user_id` columns stay for
schema compatibility and imported data. All agents belong to that owner, and
the global `AgentManager` registry dispatches to whichever harness runtime
matches the row.

The dashboard always talks to HappyClaw over `/api` HTTP/WebSocket; the
React SPA never imports a Python module and never opens the SQLite
file directly.

## 3. Conversation surfaces

Three surfaces share the same agent runtime:

| Surface | Wire | Session key (default) | Notes |
|---------|------|-----------------------|-------|
| Web UI | WebSocket `/api/agents/{aid}/chat/ws` | `<aid>:dashboard:local:dm` | Dashboard turn endpoint |
| CLI | Embedded `OctopServer` (REPL) or WebSocket | `<aid>:cli:local:dm` | `octop chats send` / `chats repl` |
| IM channel | gateway `ChannelManager` | `<aid>:<channel_kind>:<platform_session>:<dm\|group>` | See `infra/gateway/process/message_keys.py` |
| Cron job | APScheduler trigger → `Gateway.push_text_from_session` | row's `session_key` (defaults to `dashboard_key` of the owner) | `task_type=text\|agent` chooses direct-push vs run-AI-then-push |

`thread_id` itself encodes no origin; origin is a column on
`chat_sessions` / `threads`. Thread reuse / archival is a row update —
see `infra/gateway/threads.py` for the full state machine.

> **Streaming chat is now WebSocket.** Legacy SSE on
> `POST /api/agents/{aid}/chat/stream` has been replaced by a
> bidirectional WS endpoint that lets the dashboard also send
> slash/`/compact` mid-turn. `POST /api/agents/{aid}/chat/hitl/resume`
> is the one route that still uses SSE — it streams the resumed turn
> back to the client.

## 4. Storage

The **control plane** (local owner, agents, providers, channels, cron,
sessions, audit) lives in either:

* SQLite — default file under `~/.octop/` (legacy `octop.db` or
  `config.json` → `database.sqlite_path`), or
* PostgreSQL — `config.json` / `OCTOP_DATABASE_*` / first-boot database config.

Migrations: `src/octop/infra/db/migrations/NNN_*.sql` (SQLite) and
`NNN_*.pg.sql` (PostgreSQL). Connection PRAGMAs live on the SQLite pool;
PostgreSQL extensions (e.g. `vector`) are docker/ops init, not app
migrations. Agent memory DDL is owned by octop-memory. See
[ADR 002](./adr/002-database-backends.md).

The wheel ships the built dashboard SPA, so the entire stack is one
`pip install`.

Per-agent workspace files (Markdown, skills, expert templates) are
read and written through the agent's `BackendWorkspace`
(`octop.infra.backend` → `octop_harness.backends`). The default
backend is a `filesystem` adapter rooted at
`~/.octop/agents/<agent_id>/`; remote backends (S3, COS) are mounted
on top of the same root_dir and the HappyClaw service never reads
content files via `Path.write_text` / `read_text` (see
[agent-backend-file-io.md](./agent-backend-file-io.md) for the full
rules). Checkpointing, langgraph state, and the
`sessions/*.jsonl` fallbacks stay on the local workspace dir because
they are harness-managed.

## 5. Internationalization (i18n)

Server-owned strings (slash replies, IM status, API error messages,
tool display names, CLI output) come from the bundles in
`src/octop/i18n/{en,zh}.json` and helpers under
`src/octop/i18n/domains/`. Locale resolution lives in
`infra/utils/locale.py`: local owner preference → `Accept-Language`
header → channel-type hint. The dashboard mirrors the codes under
`dashboard/src/locales/{en,zh}.json → apiErrors.*` and may hydrate
tool labels from `GET /api/i18n/tools`.

## 6. Multi-agent interactions (harness teams)

`@Agent` and `ask_agent` flow through the harness `TeamManager`
(InboxManager + GlobalProcessor) — see
[agent-interop-mailbox.md](./agent-interop-mailbox.md) for the queue
contract and [agent-call-agent.md](./agent-call-agent.md) /
[agent-delegation.md](./agent-delegation.md) for the two user-facing
entry points. HappyClaw's `GlobalProcessor` implements the
`TeamProcessor` protocol so replies land back in the parent thread
checkpoint and are pushed to the dashboard / IM channel by
`on_reply`.

## See also

- [AGENTS.md](../AGENTS.md) — module boundaries, hard bans, change workflow
- [Architecture Decision Records](./adr/) — single-process, no queue (ADR 001)
- [Configuration](configuration.md) — `~/.octop/` layout + env vars
- [API reference](api.md) — every route, body, and error
- [CLI reference](cli.md) — every subcommand
- [Personas](personas.md) — MBTI templates and the mbti_profiles data module
- [ACP integration](acp.md) — in/out ACP server and runner tool
- [Agent interop](agent-interop-mailbox.md),
  [agent call](agent-call-agent.md),
  [agent delegation](agent-delegation.md)
- [Agent backend file I/O](agent-backend-file-io.md) — content file rules
