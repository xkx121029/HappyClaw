# CLI Reference

`octop` is a single Click app installed as `octop` on `pip install octop`.
The entry point lives in `src/octop/cli/main.py`; commands are registered in
`src/octop/cli/registry.py` and imported lazily, so `octop --help` never
imports the agent stack.

Every table below is the command tree of the installed package, not a
hand-written summary: `octop <group> --help` prints the same rows.

## Global options

| Option | Env | Effect |
|--------|-----|--------|
| `-v, --version` | — | Print the installed version and exit |
| `--user TEXT` | `OCTOP_USER` | Default `--user` for subcommands (admin acting on behalf of a user). Ignored in single-user mode. |
| `--agent TEXT` | `OCTOP_AGENT` | Default `--agent` for subcommands |
| `--json` | — | Emit machine-readable JSON for list-style commands |

## Command groups

| Group | What it covers |
|-------|----------------|
| `acp` | Run an agent as an ACP server (stdio) for IDE clients |
| `admin` | Overview, audit log, global providers |
| `agent` | Agent lifecycle and bundled expert templates |
| `backup` | Create / restore archives; automatic-backup status |
| `bridge` | HappyClaw-to-HappyClaw peer links |
| `captcha` | Clear legacy captcha settings |
| `channel` | Local channel CRUD plus platform bot creators |
| `chats` | Thread CRUD, `send`, interactive `repl` |
| `clean` | Remove CLI state or wipe `~/.octop` |
| `cloud` | Import `tccli` credentials into the local cloud store |
| `completion` | Shell completion snippets |
| `config` | Pinned CLI defaults (`cli_state.json`) |
| `cron` | Cron job CRUD and `run-now` |
| `init` | Bootstrap the data directory, migrate the DB |
| `memory` | Live memory maintenance (`list`, `slim`) |
| `migrate` | Import an OpenClaw / Hermes Agent setup into an expert |
| `models` | Provider presets and the resolved model catalog |
| `plugin` | Install / remove / reload plugins |
| `provider` | Provider CRUD and a one-token probe |
| `run` | Start the server in the foreground |
| `selfcheck` | Import the agent stack and compile a throwaway graph |
| `service` | systemd / launchd service lifecycle |
| `skills` | Per-agent skill enable / disable |
| `update` | Check for and install a newer release |
| `user` | Deprecated in single-user mode; see `octop user` |
| `version` | Print the installed version |

## Transport layers

Commands pick one of four transports. Single-user mode needs no login for any
of them: where a step used to require a token, the CLI resolves the local
owner directly.

| Layer | When | Examples |
|-------|------|----------|
| **Offline** (local DB / files only) | Read/write `~/.octop` with no server boot | `init`, `backup create/restore`, `plugin`, `agent list/use`, `chats list/get/create/update/delete`, `cron list/create/delete`, `admin overview/audit`, `models presets/list/active/config`, `provider list/create/delete`, `skills enable/disable`, `bridge list/get`, `cloud import-tccli`, `captcha reset`, `config`, `clean` |
| **Embedded** (in-process `OctopServer`) | Needs the harness / gateway runtime for one command | `chats send/repl`, `cron run-now`, `agent create/from-expert/start/stop/reload`, `provider test`, `channel test/config/feishu-setup/bind`, `migrate openclaw/hermes`, `acp` |
| **Embedded (bridge)** | In-process `BridgeManager` only; the CLI cannot hold the Bridge WebSocket after exit | `bridge probe/create/patch/delete/connect/disconnect/agents` |
| **External** | Talks to an OS daemon or the system service manager; no HappyClaw HTTP | `models ollama-list/pull/rm` (local Ollama daemon), `service start/stop/restart/status`, `update`, `completion install` |

`octop run` itself is the server. Embedded commands always boot their own
short-lived in-process `OctopServer` (`octop.cli.support.embedded_ops` →
`embedded_runtime()`) — they do not attach to a running `octop run`, and they
exit when the command finishes. Data changes made offline (channels, cron,
providers) are written to the same control-plane database and are picked up the
next time `octop run` starts.

## `octop init`

Prepare `~/.octop` and migrate the control-plane database. It also creates a
first **admin user row**: without `--yes` it prompts for a username and
password, and with `--yes` it requires `--admin-username` / `--admin-password`
(or `OCTOP_ADMIN_USERNAME` / `OCTOP_ADMIN_PASSWORD`).

```
Usage: octop init [OPTIONS]

  Bootstrap an Octop server (~/.octop dir, DB migrations, first admin).

Options:
  --admin-username TEXT      First admin username (or set OCTOP_ADMIN_USERNAME).
  --admin-password TEXT      First admin password (or set OCTOP_ADMIN_PASSWORD).
  --admin-display-name TEXT  Optional display name for the admin user.
  --force                    Delete HappyClaw application state under ~/.octop
                             before bootstrapping. Keeps the install runtime
                             (venv/, bin/).
  --yes                      Skip all interactive prompts.
  -h, --help                 Show this message and exit.
```

A normal install does not need this command: the first `octop run` creates the
data directory and resolves the local owner by itself. Use `octop init` when
you want to migrate the database ahead of time, or to script an unattended
install together with the `--admin-*` flags.

## `octop run`

Start the FastAPI app in the foreground (delegates to
`octop.launch.run_foreground_blocking`).

```
Usage: octop run [OPTIONS]

  Run octop-server in the foreground.

Options:
  --host TEXT                 Override bind host
  --port INTEGER RANGE        Override port (0-65535; 0 = let the OS pick).
  --reload                    Enable uvicorn auto-reload (dev).
  --workers INTEGER           Worker process count (default 1).
  --log-level [critical|error|warning|info|debug|trace]
  --ssl                       Enable HTTPS (auto-generates self-signed if no
                              cert/key given).
  --ssl-certfile TEXT         TLS certificate file.
  --ssl-keyfile TEXT          TLS private key file.
  -h, --help                  Show this message and exit.
```

Host and port resolve as CLI flag → `OCTOP_BIND_HOST` / `OCTOP_PORT` →
`config.json` → default (`127.0.0.1:8088`).

## `octop service`

Install and manage the HappyClaw system service. The backend is detected
automatically (systemd on Linux, launchd on macOS); this is the only
platform-limited command group in the CLI, and it fails with an explicit
message elsewhere.

```
Usage: octop service [OPTIONS] COMMAND [ARGS]...

  Manage the Octop system service (systemd on Linux, launchd on macOS).

Commands:
  start    Install if needed, ensure the NOFILE drop-in, then start the service.
  stop     Stop the system service.
  restart  Restart the system service. Adds a LimitNOFILE drop-in if missing.
  status   Show system service and HTTP health status.
```

`start`, `stop`, `restart` and `status` accept `--scope`
(`user` vs `system`; default `auto`, also settable via `OCTOP_SERVICE_SCOPE`).
`start` takes `--host` / `--port` to write the bind address into `config.json`
before installing, and `--force-install` to rewrite the unit file. `status`
takes `--host` / `--port` for the health probe and `--no-health` to skip it.

On Linux, `start` and `restart` write two drop-ins under
`octop.service.d/` and never rewrite the main unit:

| Drop-in | Contents |
|---------|----------|
| `10-nofile.conf` | `LimitNOFILE` (user units are capped to the process hard rlimit) |
| `15-resource-limits.conf` | `MemoryHigh=60%`, `MemoryMax=75%` of RAM, `MemorySwapMax=512M`, `OOMPolicy=kill`, restart delay and start limit |

To undo, delete the drop-ins and run
`systemctl daemon-reload && systemctl restart octop`. See
[Configuration](configuration.md#local-knowledge-indexing-and-systemd-resource-limits)
for the memory-budget override.

## `octop user` (deprecated)

Kept so existing scripts fail softly in single-user mode: reads return the
local owner, writes return a message explaining that multiple accounts are not
supported. The subcommands (`create`, `delete`, `disable`, `list`, `passwd`,
`reset-mfa`, `role`, `set-email`) still parse; there is nothing to log in to.

## `octop agent`

Lifecycle and templates. `create`, `from-expert`, `start`, `stop` and `reload`
boot an embedded `OctopServer`; `list`, `use` and `delete` work offline.

```
Usage: octop agent [OPTIONS] COMMAND [ARGS]...

  Agent lifecycle commands.

Commands:
  create       Create a new agent (boots embedded server).
  delete
  experts      List bundled expert (scene) templates.
  from-expert  Create an agent from a bundled expert template (embedded server).
  list         List agents from local DB.
  reload
  start
  stop
  use          Pin default agent in CLI state (~/.octop/cli_state.json).
```

`create` and `from-expert` accept `--user` for compatibility; single-user mode
always creates the expert for the local owner. `use` writes the agent id into
`~/.octop/cli_state.json` so later commands default to it.

## `octop chats`

Thread CRUD plus `send` / `repl`. `list` / `get` / `create` / `update` /
`delete` / `gc-orphans` work offline against `~/.octop/octop.db`; `send` and
`repl` boot an embedded server and stream through the CLI gateway channel.

```
Usage: octop chats [OPTIONS] COMMAND [ARGS]...

  Chat REPL and session management.

Commands:
  create      Start a new thread (/new equivalent).
  delete      Delete a thread.
  gc-orphans  Report checkpoint rows whose thread was already removed.
  get         Show message history for a thread.
  list        List conversation threads for an agent.
  repl        Interactive chat REPL (embedded server + CLI gateway channel).
  send        Send one message and stream the response (CLI channel).
  update      Rename or pin a thread.
```

`send` takes `--session-key`, `--thread-id` (pin a thread for every turn),
`--model`, `--mode` (`ask` / `plan` / `default`) and `--plain` (raw token
stream). `gc-orphans` scans checkpoints whose thread row is gone and, with
`--yes`, deletes them. There is no `octop chat` alias.

## `octop memory`

Live memory maintenance for running agents. Both subcommands need the agent
stack; see [memory slim](memory-slim.md) for what they do to the database.

```
Usage: octop memory [OPTIONS] COMMAND [ARGS]...

  Live memory maintenance (backup and slim).

Commands:
  list  List eligible running agents without starting maintenance.
  slim  Back up and slim memory, pausing new turns until completion. Keeps all history.
```

## `octop cron`

Local DB cron management. `run-now` boots an embedded server because the fire
is dispatched through the live `CronManager`.

```
Usage: octop cron [OPTIONS] COMMAND [ARGS]...

  Cron job management commands.

Commands:
  create   Create a cron job.
  delete   Delete a cron job.
  list     List cron jobs for an agent.
  run-now  Run a cron job to completion (embedded server).
```

`create --trigger` accepts cron expressions (`"0 9 * * *"`) and the
`interval:N` / `date:ISO8601` aliases. A `date:` job runs once and then
disables itself, whether the run succeeds or fails. If the server is down for
more than 24 hours past that time and the job never ran, it is marked `missed`
and disabled. The row stays in the list. `--task-type text` pushes the prompt
verbatim; `--task-type agent` (default) runs the LLM and pushes the reply.
`--prompt` is required, must be non-empty and ≤ 2000 characters.

## `octop channel`

Local channel CRUD plus platform-specific bot creators. `bind` drives the QR
flows for QQ / WeCom / WeChat, `feishu-setup` drives Feishu scan-to-create, and
`config` is an interactive editor. `test` boots the channel, starts it, then
stops it.

```
Usage: octop channel [OPTIONS] COMMAND [ARGS]...

  Channel management commands.

Commands:
  bind          QR-based channel binding (QQ / WeCom / WeChat).
  config        Interactively create or configure a channel.
  create        Create a channel.
  delete        Delete a channel.
  feishu-setup  Run Feishu scan-to-create (lark-oapi QR) and save app credentials.
  get           Show channel details including config (secrets masked).
  list          List channels for an agent.
  patch         Update channel fields.
  test          Probe a channel: instantiate, start(), then stop().
```

## `octop bridge`

HappyClaw-to-HappyClaw peer links (same surface as dashboard **云端协同**,
`/bridge`). `--user` / pinned `default_user` are compatibility fields; the
local owner is always used. `--peer-user` is the **remote** peer's username.

```
Usage: octop bridge [OPTIONS] COMMAND [ARGS]...

  Manage remote HappyClaw bridge peers (add / edit / probe / connect).

Commands:
  agents      Dial the peer, list remote experts via the tunnel, then close.
  connect     Dial the peer and verify Bridge WS, then close the CLI session.
  create      Add a bridge peer. With --connect, keep the row only if handshake succeeds.
  delete      Delete a saved bridge connection.
  disconnect  Mark a connection disconnected in the local DB.
  get         Show one saved bridge connection.
  list        List saved bridge connections for the acting user.
  patch       Update display name, notes, icon, peer credentials, or auto-reconnect.
  probe       Test peer credentials (login + list experts). Does not open Bridge WS.
```

`probe` without `CONNECTION_ID` requires `--url` and `--peer-user`.
`probe CONNECTION_ID` reuses the stored password when `--peer-password` is
omitted. `create` always needs the remote password: pass `--peer-password` or
type it at the hidden prompt. `connect` and `agents` open the Bridge
WebSocket, verify it, then close it — start `octop run` to keep a link alive.

## `octop provider`

Local DB provider CRUD. `test` boots an embedded server and sends a one-token
ping.

```
Usage: octop provider [OPTIONS] COMMAND [ARGS]...

  Provider management commands (local DB).

Commands:
  create  Create a provider.
  delete  Delete a provider.
  list    List providers.
  test    Probe a provider with a one-token ping.
```

There is no `octop provider edit`: change a provider in the dashboard
(**管理 → 模型配置**) or delete and re-create it.

## `octop models`

Provider presets and the resolved model catalog.

```
Usage: octop models [OPTIONS] COMMAND [ARGS]...

  Model catalog and active-model settings.

Commands:
  active       Show or set the global default model (admin).
  config       Interactively create a provider from presets and set the active model.
  list         List all resolved models across enabled providers.
  ollama-list  List models available in the local Ollama daemon.
  ollama-pull  Pull an Ollama model from the local daemon.
  ollama-rm    Delete a model from the local Ollama daemon.
  presets      List built-in provider templates from octop-harness.
```

The `ollama-*` subcommands talk to the Ollama daemon on this machine
(`OllamaModelManager`), not to a running `octop run`. `ollama-pull --no-wait`
is rejected: local pulls always block.

## `octop skills`

Per-agent skill enable / disable, plus an interactive `config`. These write the
local DB and workspace skill config; no server is required.

```
Usage: octop skills [OPTIONS] COMMAND [ARGS]...

  Manage agent skills (enable / disable / list).

Commands:
  config   Interactively toggle which skills are enabled.
  disable  Disable a skill.
  enable   Enable a skill.
  list     List skills for an agent.
```

## `octop plugin`

Install and manage third-party plugins (they live in `~/.octop/plugins/`). The
same plugin manager powers the dashboard's **管理 → 插件管理** page.

HappyClaw also **seeds bundled plugins** into `~/.octop/plugins/` during
`octop init` and every `octop run` start. They are listed in the dashboard but
stay **globally disabled** until you turn them on. An id already recorded in
`config.json` → `bundled_plugins_seeded` is not copied again after uninstall.

```
Usage: octop plugin [OPTIONS] COMMAND [ARGS]...

  Install and manage plugins.

Commands:
  install    Install from a local directory or ZIP URL.
  list       List installed plugins.
  reload     Reload plugins from disk (offline; restart `octop run` to apply to agents).
  uninstall  Remove an installed plugin.
```

## `octop backup`

Export and restore HappyClaw backups. Works fully offline.

```
Usage: octop backup [OPTIONS] COMMAND [ARGS]...

  Backup and restore database + local agent workspaces.

Commands:
  auto     Automatic backup status and one-shot run (schedule requires `octop run`).
  create   Create a selected-content backup archive.
  restore  Restore from a backup archive. Stop `octop run` first for a clean restore.
```

`create` takes `-o/--output`, `--home`, `--include-chats`, and the
`--no-config` / `--no-workspaces` / `--no-skill-packages` / `--no-plugins` /
`--no-knowledge` opt-outs. `restore` takes the archive path plus `--home`,
`--no-config`, `--owner-user-id` and `--yes`.

### `octop backup auto`

Automatic backups are scheduled **inside** a running `octop run` process (the
same system-job mechanism as TLS renewal). Configure in `config.json` under
`backup`, with env overrides `OCTOP_BACKUP_AUTO_ENABLED`,
`OCTOP_BACKUP_SCHEDULE`, `OCTOP_BACKUP_RETENTION_COUNT`, or via the dashboard.

```
Usage: octop backup auto [OPTIONS] COMMAND [ARGS]...

  Automatic backup status and one-shot run (schedule requires `octop run`).

Commands:
  status  Print automatic backup settings from config.json.
  run     Create one automatic backup now and prune by retention.
```

Default schedule when enabled: `cron:0 4 * * *` (daily 04:00, server
timezone). Automatic archives are named `octop-auto-backup-*.tar.gz`;
retention only deletes those files and never touches manual
`octop-backup-*.tar.gz` archives.

## `octop admin`

Local DB admin operations: overview, audit log, and global providers.
`rotate-jwt-secret` is kept for compatibility but has no effect in single-user
mode (there is no token check).

```
Usage: octop admin [OPTIONS] COMMAND [ARGS]...

  Admin commands (local DB).

Commands:
  audit              Show audit log entries.
  overview           Show admin overview (user count, agent state distribution).
  providers          Global (admin) providers.
  rotate-jwt-secret  Rotate the JWT secret directly via the local DB.
```

## `octop captcha`

Single-user mode has no login form, so the only thing left to do here is clear
stored captcha settings; the command exists so old recovery scripts still run.

```
Usage: octop captcha [OPTIONS] COMMAND [ARGS]...

  Login captcha maintenance (lockout escape hatch).

Commands:
  reset  Clear stored captcha settings so login falls back to the slider default.
```

## `octop cloud`

Import a `tccli` credential profile into the local cloud store under
`~/.octop/secrets/`.

```
Usage: octop cloud [OPTIONS] COMMAND [ARGS]...

  Tencent Cloud credential bridge (tccli import).

Commands:
  import-tccli  Import `~/.tccli/<profile>.credential` into the Octop cloud store.
```

## `octop selfcheck`

Packaging check: imports the whole agent stack and compiles a throwaway graph,
so a broken wheel fails loudly instead of at the first chat turn.

```
Usage: octop selfcheck [OPTIONS]

  Import the agent stack and compile a throwaway graph (packaging check).

Options:
  -h, --help  Show this message and exit.
```

## `octop update`

Check for and install a newer release from the configured channel (PyPI by
default).

```
Usage: octop update [OPTIONS]

  Check for and install a newer Octop release.

Options:
  --check              Only check, do not install.
  -y, --yes            Skip confirmation.
  -v, --verbose        Verbose installer output.
  --allow-prerelease   Include and allow installing pre-releases (alpha / beta / rc / dev).
  -h, --help           Show this message and exit.
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
  --user TEXT          Owner of the migrated connectors.
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
  --agent TEXT  Agent ID (defaults to CLI state / first agent)
  --debug       Enable debug logging to stderr
  -h, --help    Show this message and exit.
```

See [ACP integration](./acp.md) for the Zed setup example and the
runner object schema.

## `octop clean`

Reset CLI state (the default) or delete HappyClaw data under `~/.octop`
(`--all`). `--all` keeps the install runtime (`venv/`, `bin/`). Destructive.

```
Usage: octop clean [OPTIONS]

  Remove the CLI state file (default) or Octop data (--all).

Options:
  --all      Delete HappyClaw data under ~/.octop. Keeps the install runtime
             (venv/, bin/).
  --yes      Skip confirmation.
  --dry-run  Show targets without deleting.
  -h, --help Show this message and exit.
```

## `octop config`

Inspect or edit `~/.octop/cli_state.json`.

```
Usage: octop config [OPTIONS] COMMAND [ARGS]...

  View or update CLI defaults (~/.octop/cli_state.json).

Commands:
  set-user  Pin default --user for subcommands.
  show      Print pinned default user and agent.
```

## `octop completion` / `octop version`

```text
$ octop completion show bash   # print a completion script to stdout
$ octop completion install     # append the eval line to your rc file
$ octop version                # print the installed octop version
```

## CLI state file

`~/.octop/cli_state.json` stores two keys:

```json
{
  "default_user": null,
  "default_agent": null
}
```

The path is exposed as `octop.cli.support.state.default_state_path()` and
follows `OCTOP_HOME`. `default_user` is a compatibility field that single-user
mode ignores; `default_agent` is what `octop agent use` writes and what
`--agent` falls back to. Delete the file to reset CLI defaults.
