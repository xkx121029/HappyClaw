<p align="center">
  <img src="docs/assets/readme-banner.png" alt="HappyClaw Banner" width="600" />
</p>

<p align="center">
  <strong>A single-person AI workbench on your own machine — one process, one you.</strong>
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img alt="Python 3.12+" src="https://img.shields.io/badge/python-3.12%2B-blue?logo=python&logoColor=white" /></a>
  <a href="https://github.com/xkx121029/HappyClaw/blob/main/LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-green" /></a>
  <img alt="Version 1.0.3b5" src="https://img.shields.io/badge/version-1.0.3b5-orange" />
  <a href="https://github.com/astral-sh/ruff"><img alt="Code Style: Ruff" src="https://img.shields.io/badge/code%20style-ruff-000000?logo=ruff&logoColor=white" /></a>
</p>

<p align="center">
  <a href="#-quick-start">Quick Start</a> ·
  <a href="#-what-you-get">What You Get</a> ·
  <a href="#-install">Install</a> ·
  <a href="#️-configure-models">Configure Models</a> ·
  <a href="#-data-directory--backups">Data & Backups</a> ·
  <a href="#-faq">FAQ</a>
</p>

<p align="center">
  <b>English</b> · <a href="README_CN.md">中文</a>
</p>

---

**HappyClaw** is a local AI workbench for one person. There is no account system, no login page, and no member accounts or permission setup: install it, start it, open the browser, and you are working as the local user.

One process serves the web console, the CLI, IM channels, and scheduled jobs. Everything stays on your machine under `~/.octop/`. You can create multiple experts, each with its own model, workspace, skills, and channels — chat in the browser, or connect Feishu, DingTalk, QQ, WeChat, WeCom, Telegram, and Discord.

## 🚀 Quick Start

> Windows-first walkthrough in 5 minutes: [docs/quickstart.md](docs/quickstart.md).

**Windows (PowerShell)**

```powershell
irm https://download.octop.cloud/octop/scripts/install.ps1 | iex
octop run
```

**macOS / Linux**

```bash
curl -fsSL https://download.octop.cloud/octop/scripts/install.sh | bash
octop run
```

Open **http://127.0.0.1:8088**. The first boot creates the local user automatically — no registration and no password prompt. You land in the console and can configure a model under **Settings → Models** right away.

## 🧭 What You Get

| | Capability | Description |
|---|------------|-------------|
| 💬 | **Local chat** | Real-time conversation in the web console, with attachments and tool calls |
| 🎭 | **Multiple experts** | Each expert has its own workspace, model, skills, and cron jobs; bundled expert library and 16 MBTI persona templates |
| 🎯 | **AgentTeams** *(Beta)* | A coordinator schedules several experts for multi-step work — [details](docs/expert-teams.md) |
| 🔌 | **Connectors** | Tencent Docs, Tencent Meeting, Notion, TickTick, Feishu CLI, WeCom CLI and more via OAuth / MCP — [catalog](docs/connectors.md) |
| 📚 | **Knowledge base** | RAG over your own documents |
| 🧩 | **Plugins & skills** | Install third-party plugins and enable skills per expert |
| ↔️ | **ACP in both directions** | `octop acp` for IDEs; delegate to OpenCode / CodeBuddy / Claude Code / Codex |
| 💻 | **Terminal AI+** | Interactive shell in the browser with AI-assisted commands |
| 🌐 | **Browser AI+** | Chromium sessions for web automation, screenshots, and remote browsing |
| 🖥️ | **Remote desktop** | Live screen and input from the console on Linux, Windows, and macOS |
| ⏰ | **Scheduled jobs** | Natural-language or cron triggers |
| 🏠 | **Fully local** | Config, chats, workspaces, and credentials stay in `~/.octop/` |

## 🧠 Core Technology

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12+ |
| Web framework | FastAPI + uvicorn |
| Agent runtime | `octop-harness` (installed with the `[all]` extra) |
| Memory & retrieval | `octop-memory` |
| IM bridge | `octop-gateway` |
| Browser host | `octop-browser` + Playwright |
| Control-plane DB | SQLite (WAL, default) or PostgreSQL (optional) |
| Frontend | React 18 + TypeScript + Vite + Ant Design |
| Scheduling | APScheduler |
| ACP | stdio JSON-RPC — inbound server (`octop acp`) and outbound `acp_runner` tool |
| Build / quality | hatchling · ruff · mypy · pytest |

Single process: the web UI, IM channels, and cron all go through one in-process `HarnessProcessor`. No external queue or broker; state is rebuilt from the control-plane database on restart.

## 📦 Install

| Method | Platform | Command |
|--------|----------|---------|
| One-liner | macOS / Linux | `curl -fsSL https://download.octop.cloud/octop/scripts/install.sh \| bash` |
| One-liner | Windows | `irm https://download.octop.cloud/octop/scripts/install.ps1 \| iex` |
| Repo script | macOS / Linux | `bash scripts/install.sh` |
| Repo script | Windows | `powershell -ExecutionPolicy Bypass -File scripts/install.ps1` |
| PyPI | Any | `pip install octop` (latest stable; `--pre` for the 1.0.3 beta line) |
| Docker | Any | `docker compose -f docker/docker-compose.yml up -d --build` |

Installers provision an isolated environment at `~/.octop/venv` and a command wrapper at `~/.octop/bin/octop`. System Python is untouched. Open a new terminal afterwards so `octop` is on your PATH.

Optional extras:

```bash
# Playwright Chromium for browser automation (skipped if system Chrome/Chromium exists)
bash scripts/install.sh --extras browser
```

Install flags (`--version`, `--from-source`; `--mirror` is Unix-only): [scripts/README.md](scripts/README.md).

### Docker

```bash
docker compose -f docker/docker-compose.yml up -d --build
# open http://localhost:8088
```

Single-user Docker needs no preset administrator password. The container initializes the database on first boot and binds the local user automatically; data still lives in `/data/.octop`. See [docker/README.md](docker/README.md).

### Upgrade

```bash
octop update
```

`octop update` replaces the program only; the database, workspaces, secrets, and `config.json` under `~/.octop/` are preserved. Schema migrations run on the next boot. Back up first:

```bash
octop backup create
```

## ⚙️ Configure Models

Models are configured per expert, or centrally under **Settings → Models**.

```bash
octop models              # provider presets and model resolution
octop provider list       # configured providers
octop provider --help     # add / edit / remove providers
```

Supported providers include OpenAI-compatible APIs, Anthropic, AWS Bedrock, DashScope (Qwen), and local Ollama. Add a provider with its Base URL and API key, select models, then run **Test connection** before saving. Ollama connects to the local daemon and needs no API key.

### Common commands

```bash
octop agent list                 # experts
octop agent create               # create an expert
octop channel list               # IM channels
octop skills list --agent main   # skills
octop cron list                  # scheduled jobs
```

Environment variables and the full `config.json` schema: [docs/configuration.md](docs/configuration.md).

## 📁 Data Directory & Backups

```
~/.octop/                          ← install and data root
├── config.json                    # process settings (port, TLS, database, …)
├── env                            # optional environment variables (API keys, …)
├── octop.db                       # SQLite control plane
├── secrets/                       # Tencent Cloud authorization cache (cloud/, cloud.key)
├── agents/<agent_id>/             # per-expert workspace
├── security/tool_guard/           # shell allow / deny rules
├── backups/                       # archives written by octop backup create
├── logs/                          # runtime logs
├── venv/                          # Python environment created by the installer
└── bin/octop                      # command wrapper
```

Set `OCTOP_HOME` to move the whole data root to another disk.

### Backup and restore

```bash
octop backup create              # archive DB + workspaces + config
octop backup restore <archive>   # restore into ~/.octop
octop backup auto status         # automatic backup settings
octop backup auto run            # run one automatic backup now
```

Automatic backups are **off by default** (`backup.auto_enabled`). Once enabled, they run inside the `octop run` process daily at 04:00 and keep 7 archives by default. Retention only prunes `octop-auto-backup-*` archives; manual backups are never deleted.

> Archives exclude chat history by default; add `--include-chats` for a full migration. SQLite and PostgreSQL backups are not interchangeable. Restore with the same database engine that produced the archive.

Step-by-step move / rollback commands: [docs/migration-and-restore.md](docs/migration-and-restore.md).

## 📖 CLI Reference

| Command | Description |
|---------|-------------|
| `octop init` | Bootstrap `~/.octop/` (database and runtime directories) |
| `octop run` | Start the server in the foreground |
| `octop service start` | Install and start as a system service (systemd / launchd) |
| `octop agent` | Create, list, start, and stop experts |
| `octop channel` | Install and manage IM channels |
| `octop chats` | Session list and interactive chat |
| `octop acp` | stdio ACP server for IDEs |
| `octop cron` | Manage scheduled jobs |
| `octop models` | Provider presets and model resolution |
| `octop skills` | Enable or disable skills per expert |
| `octop plugin` | Install and manage third-party plugins |
| `octop backup` | Create and restore backups |
| `octop update` | Check for and install updates |
| `octop clean` | Clear CLI state or wipe `~/.octop/` |

Full reference: [docs/cli.md](docs/cli.md).

## 📚 Documentation

| Document | What it covers |
|----------|----------------|
| [docs/quickstart.md](docs/quickstart.md) | 5-minute Windows-first walkthrough |
| [docs/user-guide.md](docs/user-guide.md) | Install, models, experts, channels, cron, FAQ |
| [docs/migration-and-restore.md](docs/migration-and-restore.md) | Back up, move to another machine, roll back a failed restore |
| [docs/configuration.md](docs/configuration.md) | Environment variables and `config.json` |
| [docs/cli.md](docs/cli.md) | Every CLI command and flag |
| [docs/api.md](docs/api.md) | HTTP API reference |
| [docs/architecture.md](docs/architecture.md) | Runtime layout and module boundaries |
| [docs/connectors.md](docs/connectors.md) | OAuth / MCP connector catalog |
| [docs/RELEASE-CHECKLIST.md](docs/RELEASE-CHECKLIST.md) | Pre-release verification checklist |

## 🖥️ Web Console

After `octop run`, open **http://127.0.0.1:8088**; it opens straight into the workspace.

- **Chat** — talk to experts and teams
- **Experts** — create experts, pick library templates or MBTI personas, configure providers and workspaces
- **Connectors** — OAuth apps and MCP gateways
- **Channels** — IM platform setup
- **Cron** — visual scheduled-job management
- **Knowledge** — document corpora and semantic retrieval
- **Plugins** — install, enable, and configure
- **Control** — remote desktop and Browser AI+
- **ACP** — outbound coding-agent runners
- **Settings** — models, backups, TLS, bind address, logging

Interactive API docs are off by default; set `"enable_api_docs": true` in `config.json` to enable `/api/docs`.

## 🏗️ Architecture & Layout

```
OctopServer
 ├─ DatabasePool          SQLite (WAL) or PostgreSQL
 ├─ SharedServices        DI root — repositories and config
 ├─ ExpertCatalog         scans the expert library at boot
 ├─ LocalOwner            the local user (resolved/created at boot)
 └─ AgentRuntime (per expert)
     ├─ HarnessAgent      agent runtime (octop-harness)
     ├─ HarnessProcessor  IM / UI / cron entry point
     ├─ ChannelManager    IM connections (octop-gateway)
     └─ CronManager       APScheduler
```

```
src/octop/
  config.py    env-var config
  launch.py    OctopServer boot + uvicorn
  infra/       business core (agents, gateway, cron, db, …)
  api/         HTTP layer — FastAPI routers and SSE
  cli/         CLI layer — Click commands
  dashboard/   built React SPA (wheel artifact)

dashboard/     frontend source (Vite) — edit here, run make build-frontend
docker/        Docker Compose, entrypoint, build scripts
docs/          usage and architecture docs
tests/         unit/ + integration/
```

See [docs/architecture.md](docs/architecture.md).

## 🛠️ Development

**Prerequisites:** Python 3.12+, Node 20 with npm 10 (the frontend lockfile is npm 10; `mise.toml` pins the toolchain), and [uv](https://docs.astral.sh/uv/).

```bash
# Backend
make install
make all                   # format + lint + typecheck + test

# Frontend (separate terminal)
make dev-frontend          # Vite dev server on :5173
make build-frontend        # production build → src/octop/dashboard/
```

Individual targets: `make test`, `make lint`, `make typecheck`, `make format`.

## 🔒 Security & Privacy

- **Local-first** — config, chats, workspaces, and credentials live in `~/.octop/`.
- **Local boundary** — binds to `127.0.0.1` by default; exposing it on a LAN requires an explicit `--host`.
- **Tool guardrails** — risky tools and shell commands follow the rules in `~/.octop/security/tool_guard/`.
- **PII redaction** — sensitive data is redacted before leaving the workspace.
- **No vendor lock-in** — swap model providers, storage backends, and channels.

## ❓ FAQ

**The page at http://127.0.0.1:8088 does not open.**
Make sure `octop run` is still running without errors, and use the actual port if you changed it.

**Do I need to log in?**
No. Single-user mode has no login page and no account system; the console opens as the local user.

**How do I reach it from another device on my LAN?**
`octop run --host 0.0.0.0 --port 8088`, or set `OCTOP_BIND_HOST=0.0.0.0`. This exposes the console to your LAN — make sure that is what you want.

**Model test connection fails.**
Check the API key, base URL, network access, and account quota. For local models, confirm Ollama is running.

**Where is my data, and how do I move it?**
Everything is under `~/.octop/`. Run `octop backup create --include-chats -o <path>`, copy the archive to the new machine, then `octop backup restore <archive> --yes`. Full steps and rollback: [docs/migration-and-restore.md](docs/migration-and-restore.md).

**Port already in use?**
Start on another port with `octop run --port 8090`, or edit `port` in `~/.octop/config.json`.

More troubleshooting: [docs/user-guide.md](docs/user-guide.md).

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Run `make all` before submitting
4. Open a pull request

See [CONTRIBUTING.md](CONTRIBUTING.md). Security issues: [SECURITY.md](SECURITY.md). Module boundaries: [AGENTS.md](AGENTS.md).

## 📋 Changelog

See [CHANGELOG.md](CHANGELOG.md).

## 📄 License

MIT — see [LICENSE](LICENSE).
