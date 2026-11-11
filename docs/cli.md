# CLI Reference

`octop` is a single Click app installed as `octop` on `pip install octop`.
It is registered in `src/octop/cli/main.py`; commands are loaded
lazily from `src/octop/cli/registry.py`.

```
$ octop --help
Usage: octop [OPTIONS] COMMAND [ARGS]...

  HappyClaw command-line interface.

Options:
  -v, --version           Show the installed octop version.
  --user TEXT             Compatibility flag; ignored in single-user mode.
                          [env: OCTOP_USER]
  --agent TEXT            Default --agent for subcommands. [env: OCTOP_AGENT]
  --json                  Emit machine-readable JSON for list-style commands.
  -h, --help              Show this message and exit.

Commands:
  acp        Run HappyClaw agent as ACP server (stdio).
  admin      Admin commands.
  agent      Agent lifecycle commands.
  backup     Export and restore HappyClaw backups.
  bridge     Manage remote HappyClaw bridge peers.
  chat       [deprecated] Alias for `octop chats`.
  chats      Chat REPL and session management.
  channel    Channel management commands.
  clean      Remove CLI state or wipe all of ~/.octop.
  completion Shell completion utilities.
  config     CLI state (base URL, defaults).
  cron       Cron job management commands.
  init       Bootstrap an HappyClaw server install.
  migrate    Migrate an OpenClaw or Hermes Agent setup into an expert.
  models     Model catalog and active-model settings.
  plugin     Install and manage plugins.
  provider   Provider management (admin write).
  run        Run octop-server in the foreground.
  service    System service lifecycle (start/stop/restart/status).
  skills     Per-agent skill enable/disable.
  update     Check for and install a newer HappyClaw release.
  user       [deprecated] Account commands; no-op in single-user mode.
  version    Show the installed octop version.
```

> **Tip.** Regenerate the per-subcommand listings below with
> `make docs-cli` (each `octop <cmd> --help` is captured to stdout).

## Global options

| Option | Env | Effect |
|--------|-----|--------|
| `--user NAME` | `OCTOP_USER` | Compatibility flag. Single-user mode always uses the local owner, so this value is ignored. |
| `--agent ID` | `OCTOP_AGENT` | Default `--agent` for subcommands |
| `--json` | — | Emit machine-readable JSON for list-style commands |
| `-v, --version` | — | Print version and exit |

## Transport layers

HappyClaw commands pick one of these transports. Single-user mode needs no
login for any of them; where a step used to require a token, the CLI now uses
the local owner directly.

| Layer | When | Examples |
|-------|------|----------|
| **Offline** (local DB only) | Read/write `~/.octop` without a running server | `init`, `backup`, `plugin`, `agent list`, `chats list/get/create/update/delete`, `cron list`, `admin overview/audit`, `models presets/list/active`, `bridge list/get` |
| **Attach** (HTTP / WS) | Need a live `octop run` process (IM, streams, model pulls) | `chats send/repl`, `channel test/probe`, `models ollama-*`, `skills enable/disable`, `provider test` |
| **Embedded** (in-process) | CLI boots `OctopServer` for a single command | `octop acp`, `octop chats repl`, `octop chats send` (defaults to embedded), `octop agent create/from-expert/start/stop/reload` |
| **Embedded (bridge)** | In-process `BridgeManager` (no full server); CLI cannot keep the WS after exit | `bridge probe/create/patch/delete/connect/disconnect/agents` |

The dashboard talks to the API directly; it does not share
`~/.octop/cli_state.json` with the CLI.

## `octop init`

Bootstrap a fresh install (database migrations and runtime directories).
Idempotent on the DB; pass `--force` to delete application state under `~/.octop` first. The install runtime (`venv/`, `bin/`) is kept.

```
Usage: octop init [OPTIONS]

  Bootstrap a HappyClaw server (~/.octop dir, DB migrations).

Options:
  --admin-username TEXT      [legacy] First admin username.
  --admin-password TEXT      [legacy] First admin password.
  --admin-display-name TEXT  [legacy] Optional display name.
  --force                    Delete HappyClaw data under ~/.octop. Keeps venv/ and bin/.
  --yes                      Skip all interactive prompts.
  -h, --help                 Show this message and exit.
```

Single-user mode has no account to create. `octop init` only prepares the
directory and database; the local owner is created on the first `octop run`.
The `--admin-*` flags are kept for compatibility with existing install scripts
and databases: they may still seed a row, but single-user mode never asks for
those credentials and binds every request to the local owner.

## `octop run`

Start the FastAPI app in the foreground (delegates to
`octop.launch.run_foreground_blocking`).

```
Usage: octop run [OPTIONS]

  Start the HappyClaw server (foreground; uvicorn).

Options:
  --host TEXT                 Override OCTOP_BIND_HOST.
  --port INTEGER RANGE        Override OCTOP_PORT (0-65535, 0 = OS-assigned).
  --reload / --no-reload      Enable uvicorn auto-reload (dev only).
  --ssl / --no-ssl            Enable HTTPS with a self-signed cert (or a real one).
  --certfile PATH             TLS certificate (PEM).
  --keyfile PATH              TLS private key (PEM).
  --log-level [debug|info|warning|error]
  -h, --help                  Show this message and exit.
```

## `octop service`

Install and manage the HappyClaw system service. The backend is detected
automatically (systemd on Linux, launchd on macOS); the scope
(`user` vs `system`) can be forced via `--scope` or
`OCTOP_SERVICE_SCOPE`.

```
Usage: octop service [OPTIONS] COMMAND [ARGS]...

  Manage the HappyClaw system service (systemd on Linux, launchd on macOS).

Commands:
  start     Install (if missing) and start the service.
  stop      Stop the service.
  restart   Restart the service.
  status    Print whether the service is installed / running / healthy.
```

`status` probes the HTTP health endpoint and prints journal/log hints
on failure.

On Linux, `start` and `restart` install a systemd drop-in
(`octop.service.d/10-nofile.conf`) with `LimitNOFILE=65535` (user
units are capped to the process hard rlimit so systemd cannot fail to
spawn). The main unit file is not rewritten unless it is missing or
you pass `--force-install`. `restart` always runs `systemctl restart`
even if writing the drop-in fails, so an upgrade that only restarts
still comes back. To undo: delete the drop-in, then
`systemctl daemon-reload && systemctl restart octop`.

## `octop user` (deprecated)

Kept so existing scripts fail softly in single-user mode: reads return the
local owner, writes return a Chinese message explaining that multiple accounts
are not supported. There is nothing to log in to.

## `octop agent`

Lifecycle and templates. Most commands boot an embedded
`OctopServer` to operate on the local DB without a remote round-trip.

```
Usage: octop agent [OPTIONS] COMMAND [ARGS]...

  Agent lifecycle commands.

Commands:
  create        Create a new agent.
  from-expert   Create an agent from a bundled expert template.
  list          List agents.
  use           Pin this agent as the default for subsequent commands.
  start         Start the agent runtime.
  stop          Stop the agent runtime.
  reload        Reload the agent runtime.
  delete        Delete the agent row (and runtime).
  experts       List bundled expert templates.
```

`create` and `from-expert` accept `--user` for compatibility; single-user mode
always creates the expert for the local owner. `use` writes the agent id into
`~/.octop/cli_state.json` so subsequent commands default to it.

## `octop chats`

Thread CRUD + interactive REPL. The REPL and `send` use an embedded
server (no separate `octop run` needed); `list` / `get` / `create` /
`update` / `delete` work fully offline against `~/.octop/octop.db`.

```
Usage: octop chats [OPTIONS] COMMAND [ARGS]...

  Thread list/history and interactive chat (CLI channel / local DB).

Commands:
  list        List conversation threads for an agent.
  get         Show message history for a thread.
  create      Start a new thread (/new equivalent).
  update      Rename or pin a thread.
  delete      Delete a thread.
  send        Send one message and stream the response.
  repl        Interactive chat REPL (embedded server + CLI gateway channel).
```

`octop chat` is a deprecated alias that prints a stderr warning and
forwards to `chats`.

## `octop bridge`

HappyClaw-to-HappyClaw peer links (same surface as Dashboard **远程桥接**).
`--user` / pinned `default_user` are compatibility fields; the local owner is
always used. `--peer-user` is the **remote** peer's username. Single-user
peers accept any username/password; older multi-user peers require a valid
account. `probe` talks HTTP only; `create --connect` /
`connect` / `agents` verify the Bridge WebSocket then close it — start
`octop run` to keep a link alive (auto-reconnect).

```
Usage: octop bridge [OPTIONS] COMMAND [ARGS]...

  Manage remote HappyClaw bridge peers (add / edit / probe / connect).

Commands:
  list        List saved bridge connections.
  get         Show one saved connection.
  probe       Test peer reachability (bind + list experts).
  create      Add a peer (optional Bridge WS handshake).
  patch       Update name / notes / icon / credentials / auto-reconnect.
  delete      Delete a saved connection.
  connect     Dial and verify Bridge WS, then close the CLI session.
  disconnect  Mark a connection disconnected in the local DB.
  agents      Dial, list remote experts via the tunnel, then close.
```

`probe` without `CONNECTION_ID` requires `--url` and `--peer-user`.
`probe CONNECTION_ID` reuses the stored password when `--peer-password`
is omitted. `create` always needs the remote password: pass
`--peer-password` or type it at the hidden prompt.

## `octop channel`

Local DB channel CRUD plus platform-specific bot creators. The
`wecom` / `weixin` / `feishu-setup` subcommands drive the QR-code
bot-creator flows; `config` is the offline config editor.

```
Usage: octop channel [OPTIONS] COMMAND [ARGS]...

  Channel management commands.

Commands:
  list          List channels for an agent.
  get           Show one channel row.
  create        Create a channel.
  patch         Update a channel.
  delete        Delete a channel.
  test          Test a channel (instantiate → start → stop).
  config        Edit channel config offline.
  feishu-setup  Drive the Feishu bot-creator flow.
  bind          Bind-group helper for WeCom / Weixin (QR login, etc.).
```

## `octop cron`

Local DB cron management. `run-now` requires a running `octop run`
because the actual fire is dispatched through the live
`CronManager`.

```
Usage: octop cron [OPTIONS] COMMAND [ARGS]...

  Cron job management commands.

Commands:
  list        List cron jobs for an agent.
  create      Create a cron job.
  delete      Delete a cron job.
  run-now     Trigger a cron job immediately.
```

`create --trigger` accepts cron expressions (`"0 9 * * *"`) and the
`interval:N` / `date:ISO8601` aliases. A `date:` job runs once and
then disables itself, whether the run succeeds or fails. If the
server is down for more than 24 hours past that time and the job
never ran, it is marked `missed` and disabled. The row stays in the
list. `--task-type text` pushes the prompt verbatim; `--task-type
agent` (default) runs the LLM and pushes the reply. `--prompt` is
required, must be non-empty and ≤ 2000 characters.

## `octop provider`

Local DB provider CRUD. `test` requires a running server.

```
Usage: octop provider [OPTIONS] COMMAND [ARGS]...

  Provider management commands (local DB).

Commands:
  list      List providers.
  create    Create a provider.
  delete    Delete a provider.
  test      Ping the provider (requires running server).
```

## `octop models`

Provider presets and active model management.

```
Usage: octop models [OPTIONS] COMMAND [ARGS]...

  Model catalog and active-model settings.

Commands:
  presets       List built-in provider templates from octop-harness.
  list          List all resolved models across enabled providers.
  active        Show or set the global default model (admin).
  config        Interactively create a provider from presets and set the active model.
  ollama-list   List local Ollama models (requires a running server).
  ollama-pull   Pull a model via Ollama (requires a running server).
  ollama-rm     Remove a local Ollama model (requires a running server).
```

## `octop skills`

Per-agent skill enable / disable. All subcommands need a running
server (the dashboard's Skill Hub and bundled `~/.octop/skills/`
library are queried at boot).

```
Usage: octop skills [OPTIONS] COMMAND [ARGS]...

  Manage agent skills (enable / disable / list).

Commands:
  list      List skills for an agent.
  enable    Enable a skill for the agent.
  disable   Disable a skill for the agent.
  config    Show / edit the per-agent skills config.
```

## `octop admin`

Local DB admin operations: overview, audit log, and global providers.
`rotate-jwt-secret` is kept for compatibility but has no effect in
single-user mode (there is no token check).

```
Usage: octop admin [OPTIONS] COMMAND [ARGS]...

  Admin commands (local DB).

Commands:
  overview             Show admin overview (agent state distribution).
  audit                Show audit log entries.
  providers            Global providers.
  rotate-jwt-secret    Deprecated; no-op in single-user mode.
```

## `octop captcha` (deprecated)

Captcha is disabled in single-user mode, so this command only clears legacy
settings. It exists so old recovery scripts still run.

## `octop backup`

Export and restore HappyClaw backups. Works fully offline.

```
Usage: octop backup [OPTIONS] COMMAND [ARGS]...

  Backup and restore database + local agent workspaces.

Commands:
  create     Create a backup archive (DB + workspaces + config).
  restore    Restore a backup archive into ~/.octop.
  auto       Automatic backup status and one-shot run.
```

### `octop backup auto`

Automatic backups are scheduled **inside** a running `octop run` process
(via the same system-job mechanism as TLS renewal). Configure in
`config.json` under `backup`, with env overrides
`OCTOP_BACKUP_AUTO_ENABLED`, `OCTOP_BACKUP_SCHEDULE`,
`OCTOP_BACKUP_RETENTION_COUNT`, or via the dashboard Backup settings.

```
Usage: octop backup auto [OPTIONS] COMMAND [ARGS]...

Commands:
  status  Print automatic backup settings from config.json.
  run     Create one automatic backup now and prune by retention.
```

Default schedule when enabled: `cron:0 4 * * *` (daily 04:00, server
timezone). Automatic archives are named `octop-auto-backup-*.tar.gz`;
retention only deletes those files and never touches manual
`octop-backup-*.tar.gz` archives.

## `octop update`

Check for and install a newer HappyClaw release from the configured
channel (PyPI by default).

```
Usage: octop update [OPTIONS]

  Check for and install a newer HappyClaw release.

Options:
  --check / --no-check     Only check; do not install.
  --channel TEXT           Release channel (pypi, testpypi, custom index).
  -h, --help               Show this message and exit.
```

## `octop plugin`

Install and manage third-party plugins (drop into `~/.octop/plugins/`).
The same plugin manager powers the dashboard's "Plugins" page.

HappyClaw also **seeds bundled plugins** into `~/.octop/plugins/` during
`octop init` and every `octop run` start. They are listed in Admin →
Plugins but stay **globally disabled** until you turn them on. An id
already recorded in `config.json` → `bundled_plugins_seeded` is not
copied again after uninstall.

```
Usage: octop plugin [OPTIONS] COMMAND [ARGS]...

  Install and manage plugins.

Commands:
  list       List installed plugins.
  install    Install a plugin (local path or git URL).
  uninstall  Remove an installed plugin.
  reload     Reload all installed plugins without restart.
```

## `octop migrate`

Bring an existing OpenClaw or Hermes Agent setup into one HappyClaw expert. The
source is read where it lives (`~/.openclaw`, `~/.hermes`, or `--from`) and is
never modified.

```
Usage: octop migrate openclaw [OPTIONS]
       octop migrate hermes [OPTIONS]

Options:
  --from DIRECTORY     Source home directory (default: auto-detect).
  --agent TEXT         Expert to migrate into.
  --user TEXT          Compatibility flag; the local owner is used.
  --skip [models|files|skills|mcp|channels]
                       Leave one kind of content out (repeatable).
  --overwrite          Replace existing workspace files and skills, and the
                       default model.
  --dry-run            Show what would happen; write nothing.
  -h, --help           Show this message and exit.
```

| Section | OpenClaw | Hermes Agent | Lands in HappyClaw as |
|---------|----------|--------------|-------------------|
| `models` | `models.providers`, `agents.defaults.model`, keys from `.env` / `env` / legacy `auth-profiles.json` | `model`, `providers` / `custom_providers`, keys from `.env` | Model providers and, when none is set yet, the default model |
| `files` | Workspace `AGENTS.md`, `SOUL.md`, `IDENTITY.md`, `USER.md`, `MEMORY.md`, `TOOLS.md`, `HEARTBEAT.md`, `memory/*.md` | `SOUL.md`, `memories/MEMORY.md`, `memories/USER.md` | Files in the expert's workspace |
| `skills` | `<workspace>/skills`, `~/.openclaw/skills` | `~/.hermes/skills` except the bundled ones | Workspace skills of the expert |
| `mcp` | `mcp.servers` | `mcp_servers` | Custom MCP servers of the local owner (stdio and streamable HTTP) |
| `channels` | `channels.*` for Telegram, Discord, Feishu, QQ, WeCom, DingTalk | The same platforms' variables in `.env` | Channels of the expert, **disabled** |

Nothing that already exists is replaced: a second run reports everything as
skipped. `--overwrite` replaces workspace files, skills and the default model;
providers, MCP servers and channels are never overwritten. Channels arrive
disabled so the old assistant and HappyClaw do not both answer on the same bot —
stop the old one, then enable the channel.

Scheduled jobs, SSE-only MCP servers, OAuth-only model logins and platforms
HappyClaw has no channel for are listed after the table and left behind. Start
with `--dry-run`; root `--json` prints the same report as JSON. The command
exits with status 1 when any item failed.

```text
$ octop --agent <id> migrate openclaw --dry-run
$ octop --agent <id> migrate hermes --from /srv/hermes --skip channels
```

Like `agent create`, the command boots a short-lived in-process server; if
`octop run` is already running, restart it afterwards to load the migrated
providers and channels.

## `octop acp`

Expose an HappyClaw agent as a stdio JSON-RPC ACP server. Boots a
standalone `OctopServer` (reads `~/.octop`); does **not** require
`octop run` to be running.

```
Usage: octop acp [OPTIONS]

  Run HappyClaw agent as ACP server (stdio).

Options:
  --agent TEXT   Agent to expose (default: OCTOP_AGENT or first agent).
  --debug        Log to stderr.
  -h, --help     Show this message and exit.
```

See [ACP integration](./acp.md) for the Zed setup example and the
runner object schema.

## `octop clean`

Reset CLI state, or delete HappyClaw data under `~/.octop`. `--all` keeps the
install runtime (`venv/`, `bin/`). Destructive — read the help carefully.

```
Usage: octop clean [OPTIONS]

  Remove CLI state, or delete HappyClaw data under ~/.octop (keeps venv/ and bin/).

Options:
  --state / --all       What to remove.
  --yes                 Skip the confirmation prompt.
  -h, --help            Show this message and exit.
```

## `octop config`

Inspect / edit `~/.octop/cli_state.json` (default base URL and agent).

```
Usage: octop config [OPTIONS] COMMAND [ARGS]...

  CLI state (base URL, defaults).

Commands:
  show       Print the current CLI state.
  set-user   [deprecated] Kept for compatibility; ignored.
```

## `octop completion` / `octop version`

```text
$ octop completion show bash   # dump a shell snippet
$ octop completion install     # append to ~/.zshrc / ~/.bashrc
$ octop version                # print the installed octop version
```

## CLI state file

`~/.octop/cli_state.json` stores:

```json
{
  "base_url": "http://127.0.0.1:8088",
  "token": null,
  "default_user": null,
  "default_agent": null
}
```

The path is exposed as `octop.cli.support.state.default_state_path()`
and can be overridden via `OCTOP_HOME`. `token` and `default_user` are kept
for compatibility; single-user mode ignores both. Delete the file to reset
CLI defaults.
