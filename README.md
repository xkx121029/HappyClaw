<p align="center">
  <img src="docs/assets/readme-banner.png" alt="HappyClaw Banner" width="600" />
</p>

<p align="center">
  <strong>A single-person AI workbench on your own machine — one process, one you.</strong>
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img alt="Python 3.12+" src="https://img.shields.io/badge/python-3.12%2B-blue?logo=python&logoColor=white" /></a>
  <a href="https://github.com/xkx121029/HappyClaw/blob/main/LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-green" /></a>
  <img alt="Version 1.0.3b6" src="https://img.shields.io/badge/version-1.0.3b6-orange" />
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

**HappyClaw** is a local AI workbench for one person. There is no account system, no login page, and no member or permission setup: install it, start it, open the browser, and you are working as the local owner.

One server process serves the web console, the IM channels, and the scheduled jobs; the CLI talks to the same control-plane database. Everything stays under `~/.happyclaw/`. You can create several experts, each with its own model, workspace, skills, and cron jobs, then reach them from the browser or from Feishu, DingTalk, WeCom, WeChat, QQ, Yuanbao, Xiaoyi, MQTT, Telegram, and Discord.

> The product is called HappyClaw, but the Python distribution, the `octop` command, the `~/.happyclaw/` data root, and the `HAPPYCLAW_*` environment variables keep their original names. Both names refer to the same thing.

## 🚀 Quick Start

> Windows-first walkthrough in 5 minutes: [docs/quickstart.md](docs/quickstart.md).

**Windows (PowerShell)**

```powershell
if (-not $env:HAPPYCLAW_INSTALL_BASE) { $env:HAPPYCLAW_INSTALL_BASE = 'https://raw.githubusercontent.com/xkx121029/HappyClaw/main' }; irm "$env:HAPPYCLAW_INSTALL_BASE/scripts/install.ps1" | iex
```

**macOS / Linux**

```bash
curl -fsSL "${HAPPYCLAW_INSTALL_BASE:-https://raw.githubusercontent.com/xkx121029/HappyClaw/main}/scripts/install.sh" | bash
```

> Both one-liners read `HAPPYCLAW_INSTALL_BASE` and default to this repository's `main` branch on GitHub. If GitHub is unreachable from your network, export that variable with a mirror that serves the same `scripts/` tree and re-run the one-liner.

Then open a new terminal and start the server:

```bash
octop run
```

Open **http://127.0.0.1:8088**. The first boot creates the local owner and the database automatically — no registration and no password prompt. You land in the console and can add a model under **Admin → Models** right away.

## 🧭 What You Get

| | Capability | Description |
|---|------------|-------------|
| 💬 | **Local chat** | Real-time conversation in the web console, with attachments and tool-call traces |
| 🎭 | **Multiple experts** | Each expert has its own workspace, model, skills, and scheduled jobs; three bundled experts plus 16 MBTI persona templates |
| ⏰ | **Automations (tasks)** | Natural-language or cron-triggered jobs, per expert |
| 🎯 | **Agent Teams** *(Beta)* | A coordinator schedules several experts for multi-step work — [details](docs/expert-teams.md) |
| 🔌 | **Connectors** | 30 presets — Tencent Docs, Tencent Meeting, Notion, TickTick, Obsidian, Youdao Note, Feishu / WeCom / DingTalk CLI and more — over OAuth, API keys, or MCP — [catalog](docs/connectors.md) |
| 📚 | **Knowledge base** | RAG over your own documents |
| 🧩 | **Plugins & skills** | Install third-party plugins; enable skills per expert |
| ↔️ | **ACP in both directions** | `octop acp` serves IDEs such as Zed; the `acp_runner` tool delegates to OpenCode, CodeBuddy, Claude Code, Codex, Kimi Code, Cursor CLI, or `pi` |
| 💻 | **Terminal AI+** | Interactive shell in the browser with the agent beside it |
| 🌐 | **Browser AI+** | Chromium sessions for web automation, screenshots, and remote browsing |
| 🖥️ | **Remote desktop** | Live screen and input from the console on Linux, Windows, and macOS |
| 🌉 | **Bridge** | Pair this machine with another HappyClaw instance and hand tasks to it |
| 🏠 | **Fully local** | Config, chats, workspaces, and credentials stay in `~/.happyclaw/` |

## 🧠 Core Technology

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12+ |
| Web framework | FastAPI + uvicorn |
| Agent runtime | `happyclaw-harness` (installed with the `[all]` extra) |
| Memory & retrieval | `happyclaw-memory` |
| IM bridge | `happyclaw-gateway` |
| Browser host | `happyclaw-browser` + Playwright |
| Control-plane DB | SQLite (WAL, default) or PostgreSQL (optional) |
| Frontend | React 18 + TypeScript + Vite + Ant Design |
| Scheduling | APScheduler |
| ACP | stdio JSON-RPC — inbound server (`octop acp`) and outbound `acp_runner` tool |
| Build / quality | hatchling · ruff · mypy · pytest |

The web UI, the IM channels, and the scheduled jobs all run inside one `HappyclawServer` process — no external queue or broker. State lives in the control-plane database and is rebuilt on restart.

## 📦 Install

| Method | Platform | Command |
|--------|----------|---------|
| One-liner | macOS / Linux | `curl -fsSL https://raw.githubusercontent.com/xkx121029/HappyClaw/main/scripts/install.sh \| bash` |
| One-liner | Windows | `irm https://raw.githubusercontent.com/xkx121029/HappyClaw/main/scripts/install.ps1 \| iex` |
| Repo script | macOS / Linux | `bash scripts/install.sh` |
| Repo script | Windows | `powershell -ExecutionPolicy Bypass -File scripts/install.ps1` |
| PyPI | Any | `pip install octop` |
| Docker | Any | `docker compose -f docker/docker-compose.yml up -d --build` |

Installers provision an isolated environment at `~/.happyclaw/venv` and a command wrapper at `~/.happyclaw/bin/octop`; the system Python is untouched. On macOS and Linux the installer also links `octop` into a directory that is already on `PATH`, so it works in the current shell. On Windows it appends `%USERPROFILE%\.octop\bin` to your user `PATH`, which a newly opened terminal picks up.

`pip install octop` installs the latest **stable** release from PyPI. The version in this repository is a beta line: use `pip install --pre octop` to get a `1.0.3b*` prerelease.

Optional extras:

```bash
# Playwright Chromium for browser automation (skipped if a system Chrome/Chromium exists)
bash scripts/install.sh --extras browser

# Local ONNX / fastembed embeddings, or OCR for the knowledge base
bash scripts/install.sh --extras local-embedding
bash scripts/install.sh --extras knowledge-ocr
```

Install flags — `--version`, `--from-source`, `--from-pypi`, `--extras`, and `--mirror` (Unix only; Windows uses `-Version`, `-FromSource`, `-SourceDir`, `-Extras`, `-UvPath`): [scripts/README.md](scripts/README.md).

### Docker

```bash
docker compose -f docker/docker-compose.yml up -d --build
# open http://localhost:8088
```

The container runs `octop init` on first boot, starts the server, and keeps data in `/data/.octop` (Compose mounts `${HAPPYCLAW_DATA:-~/.happyclaw}` there). No administrator password is required for single-user mode. See [docker/README.md](docker/README.md).

Other Compose files in the same directory: `docker-compose.postgres.yml` (PostgreSQL + pgvector) and `docker-compose.cn.yml` (pull the published image instead of building).

> **升级到 HappyClaw 命名（1.0.3b6 之后）**：包里的一切从 `octop` 改名为 `happyclaw`。
> 安装命令变成 `pip install happyclaw`（或照下文的 Docker / 一键脚本）；命令是 `happyclaw`，
> 旧的 `octop` 会继续工作但打印弃用提示，**下一个小版本移除**。环境变量改用 `HAPPYCLAW_*`
> 前缀——旧的 `OCTOP_*` 仍会被读取并给出一次弃用警告。数据目录从 `~/.octop` 迁到
> `~/.happyclaw`，首次启动自动复制旧目录（原目录保留，可随时回滚）。

### Upgrade

```bash
octop update --check    # show whether a newer release exists
octop update            # install it
```

`octop update` replaces the program only; the database, workspaces, secrets, and `config.json` under `~/.happyclaw/` are preserved, and schema migrations run on the next boot. Back up first:

```bash
octop backup create
```

## ⚙️ Configure Models

Models are configured per expert, or once for all of them under **Admin → Models**.

```bash
octop models                       # provider presets and resolved models
octop models active                # the model an expert currently resolves to
octop provider list                # configured providers
octop provider create              # add one; also `delete` and `test`
```

Built-in presets cover OpenAI and OpenAI-compatible endpoints, Anthropic, Google Gemini, AWS Bedrock, DashScope (Qwen), DeepSeek, Groq, OpenRouter, SiliconFlow, Zhipu, and local Ollama. Add a provider with its Base URL and API key, enable the models you want, then run **Test connection** (`octop provider test`) before saving. Ollama talks to the local daemon and needs no API key; `octop models ollama-pull <model>` pulls weights.

### Common commands

```bash
octop agent list                 # experts
octop agent create               # create an expert
octop agent experts              # bundled expert-library templates
octop channel list               # IM channels
octop skills list --agent main   # skills of one expert
octop cron list                  # scheduled jobs
```

Environment variables and the full `config.json` schema: [docs/configuration.md](docs/configuration.md).

## 📁 Data Directory & Backups

```
~/.happyclaw/                          ← install and data root
├── config.json                    # process settings (port, TLS, database, …)
├── env                            # optional environment variables (API keys, …)
├── octop.db                       # SQLite control plane (settings table for PostgreSQL installs)
├── secrets/                       # Tencent Cloud authorization cache (cloud/, cloud.key)
├── agents/<agent_id>/             # per-expert workspace (SOUL.md, skills, memory …)
├── plugins/                       # bundled and installed plugins
├── knowledge/                     # global knowledge-base files
├── security/tool_guard/           # shell allow / deny rules
├── ssl/                           # TLS certificates and ACME account keys
├── backups/                       # archives written by octop backup create
├── logs/                          # runtime logs
├── venv/                          # Python environment created by the installer
└── bin/octop                      # command wrapper
```

Set `HAPPYCLAW_HOME` to move the whole data root to another disk.

### Backup and restore

```bash
octop backup create              # archive DB + workspaces + config
octop backup restore <archive>   # restore into ~/.happyclaw
octop backup auto status         # automatic backup settings
octop backup auto run            # run one automatic backup now
```

Automatic backups are **off by default** (`backup.auto_enabled`). Once enabled they run inside the `octop run` process on the `backup.schedule` cron (daily at 04:00 by default) and keep 7 archives (`backup.retention_count`). Retention only prunes `octop-auto-backup-*` archives; manual backups are never deleted.

`octop backup create` takes `-o/--output` for the archive path and `--include-chats` to include conversation history (excluded by default), and `--no-config` / `--no-workspaces` / `--no-skill-packages` / `--no-plugins` / `--no-knowledge` to leave sections out. SQLite and PostgreSQL archives are not interchangeable: restore with the same database engine that produced the archive.

Step-by-step move / rollback commands: [docs/migration-and-restore.md](docs/migration-and-restore.md).

## 📖 CLI Reference

| Command | Description |
|---------|-------------|
| `octop run` | Start the server in the foreground (`--host`, `--port`, `--ssl`, `--workers`) |
| `octop init` | Re-bootstrap `~/.happyclaw/` and run migrations; `--force` wipes application state. Optional — a normal install bootstraps on first run |
| `octop service` | Install / start / stop / restart / status as a system service (Linux systemd, macOS launchd; **not** Windows) |
| `octop agent` | Create, list, use, start, stop, delete experts; `agent experts` lists library templates |
| `octop chats` | Thread list, history, one-shot `send`, and an interactive `repl` |
| `octop channel` | IM channel CRUD, `config`, `test`, `feishu-setup` |
| `octop cron` | Scheduled jobs: `list`, `create`, `delete`, `run-now` |
| `octop models` | Provider presets, resolved models, active model, Ollama pull / list / rm |
| `octop provider` | Provider records: `list`, `create`, `delete`, `test` |
| `octop skills` | Enable, disable, and configure skills per expert |
| `octop plugin` | `list`, `install`, `uninstall`, `reload` |
| `octop memory` | Memory maintenance: `list` agents, `slim` their memory files |
| `octop backup` | `create`, `restore`, `auto status`, `auto run` |
| `octop update` | Check for and install updates (`--check`, `--yes`, `--allow-prerelease`) |
| `octop acp` | stdio ACP server for IDE clients |
| `octop bridge` | Remote bridge peers: `list`, `create`, `connect`, `probe`, … |
| `octop migrate` | Import an OpenClaw or Hermes Agent setup into an expert |
| `octop clean` | Clear CLI state, or wipe `~/.happyclaw/` with `--all` |
| `octop config` | Show or pin the CLI defaults (`config show`, `config set-user`) |
| `octop admin` | Admin operations: `overview`, `audit`, `rotate-jwt-secret`, user `list` / `create` / `delete` |
| `octop user` | User rows kept for compatibility: `list`, `create`, `passwd`, `role`, … |
| `octop cloud` | Tencent Cloud credential bridge (`import-tccli`) |
| `octop captcha` | Clear a login-captcha lockout (escape hatch) |
| `octop version` | Print the installed version |
| `octop selfcheck` | Import the agent stack and compile a throwaway graph (packaging check) |
| `octop completion` | Shell completion: `show`, `install` |

Full reference: [docs/cli.md](docs/cli.md).

## 📚 Documentation

| Document | What it covers |
|----------|----------------|
| [docs/quickstart.md](docs/quickstart.md) | 5-minute Windows-first walkthrough |
| [docs/user-guide.md](docs/user-guide.md) | Install, models, experts, channels, cron, logs, FAQ |
| [docs/migration-and-restore.md](docs/migration-and-restore.md) | Back up, move to another machine, roll back a failed restore |
| [docs/configuration.md](docs/configuration.md) | Environment variables and `config.json` |
| [docs/cli.md](docs/cli.md) | Every CLI command and flag |
| [docs/api.md](docs/api.md) | HTTP API reference |
| [docs/architecture.md](docs/architecture.md) | Runtime layout and module boundaries |
| [docs/connectors.md](docs/connectors.md) | OAuth / MCP connector catalog |
| [docs/acp.md](docs/acp.md) | ACP in both directions and the built-in runners |
| [docs/personas.md](docs/personas.md) | Expert personas and the MBTI templates |
| [docs/RELEASE-CHECKLIST.md](docs/RELEASE-CHECKLIST.md) | Pre-release verification checklist |

## 🖥️ Web Console

After `octop run`, open **http://127.0.0.1:8088**; it opens straight into the chat.

| Sidebar group | Pages |
|---------------|-------|
| Top | **Chat** (threads and history), **Experts**, **Tasks** (scheduled automations), **Token usage** |
| Settings | **Personalization** (per-expert config, MBTI personas, channels), **Channels**, **Connectors**, **Skill packages**, **Knowledge bases**, **Bridge** |
| Control | **Workbench** — terminal AI+, browser AI+, cloud browser; **Remote desktop**; **ACP** (outbound coding-agent runners) |
| Admin | **Models**, **Storage** (database and object storage), **Plugins**, **Security** (tool approval, command guard, filesystem rules, PII redaction), **Advanced** (TLS, bind address, logging, backups, updates) |

Interactive API docs are off by default; set `"enable_api_docs": true` in `~/.happyclaw/config.json` (or `HAPPYCLAW_ENABLE_API_DOCS=1`) to enable `/api/docs`.

## 🏗️ Architecture & Layout

```
HappyclawServer                        launch.py → infra/server.py
 ├─ DatabasePool                    SQLite (WAL) or PostgreSQL
 ├─ SharedServices                  DI root — repositories and config
 ├─ ExpertCatalog                   scans the expert library at boot
 ├─ OwnerIdentityService            the local owner (resolved/created at boot)
 ├─ AgentManager                    owns one HarnessAgent per expert
 ├─ ChannelManager (happyclaw-gateway)  IM connections
 └─ CronManager                     APScheduler
```

```
src/happyclaw/
  config.py    env-var config
  launch.py    HappyclawServer boot + uvicorn
  infra/       business core (agents, gateway, cron, db, …)
  api/         HTTP layer — FastAPI routers and SSE
  cli/         CLI layer — Click commands
  dashboard/   built React SPA — wheel artifact, empty until you run make build-frontend

dashboard/     frontend source (Vite) — edit here, run make build-frontend
docker/        Docker Compose, entrypoint, build scripts
docs/          usage and architecture docs
tests/         unit/, integration/, dsh_integration/, live/
```

See [docs/architecture.md](docs/architecture.md).

## 🛠️ Development

**Prerequisites:** Python 3.12+, Node 20 with npm 10 (the frontend lockfile is npm 10; `mise.toml` pins the toolchain), and [uv](https://docs.astral.sh/uv/).

```bash
# Backend
make install               # uv sync (falls back to pip install -e ".[dev]")
make all                   # format (BE+FE) + lint + typecheck + test

# Frontend (separate terminal)
make dev                   # Vite dev server on :5173 + octop run together
make dev-frontend          # Vite dev server only
make build-frontend        # production build → src/happyclaw/dashboard/
```

Individual targets: `make test`, `make test-fast` (skips `slow`), `make test-live`, `make lint`, `make typecheck`, `make format`, `make check-all`. Frontend only: `make lint-frontend`, `make typecheck-frontend`. pytest markers are declared in `pyproject.toml`: `live` (real LLM calls), `slow`, and `postgresql` (needs `HAPPYCLAW_TEST_DATABASE_URL`).

## 🔒 Security & Privacy

- **Local-first** — config, chats, workspaces, and credentials live in `~/.happyclaw/`.
- **Local boundary** — binds to `127.0.0.1` by default; exposing it on a LAN requires an explicit `--host`.
- **Security policy** — tool approval (human-in-the-loop), command guard rules, filesystem rules, and PII redaction are configured per agent under **Admin → Security**; shell rules are editable in `~/.happyclaw/security/tool_guard/dangerous_shell_commands.yaml`.
- **Secret masking** — the environment API returns masked values, and agent CLI output is redacted before it reaches the console.
- **No vendor lock-in** — swap model providers, storage backends, and channels.

## ❓ FAQ

**The page at http://127.0.0.1:8088 does not open.**
Make sure `octop run` is still running without errors, and use the actual port if you changed it.

**Do I need to log in?**
No. Single-user mode has no login page and no account system; the console opens as the local owner. `/login` and `/invite` simply redirect to the chat.

**Do I have to run `octop init` first?**
No. The first `octop run` creates `~/.happyclaw/`, the database, and the local owner. `octop init` exists for re-bootstrapping and migrations; `octop init --force` deletes application state.

**How do I reach it from another device on my LAN?**
`octop run --host 0.0.0.0 --port 8088`, or set `HAPPYCLAW_BIND_HOST=0.0.0.0`. Note that `--host` / `--port` on the command line are persisted to `config.json`. This exposes the console to your LAN — make sure that is what you want.

**Model test connection fails.**
Check the API key, base URL, network access, and account quota. For local models, confirm Ollama is running.

**Where is my data, and how do I move it?**
Everything is under `~/.happyclaw/`. Run `octop backup create --include-chats -o <path>`, copy the archive to the new machine, then `octop backup restore <archive> --yes`. Full steps and rollback: [docs/migration-and-restore.md](docs/migration-and-restore.md).

**Port already in use?**
Start on another port with `octop run --port 8090`, or edit `port` in `~/.happyclaw/config.json`.

**Why is the package still called `octop`?**
The distribution, the CLI command, the data directory, and the `HAPPYCLAW_*` variables predate the HappyClaw name and are kept for compatibility. HappyClaw is the product you install; `octop` is what it ships as.

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
