# octop-launcher

A thin, dependency-free process launcher for Octop. It wraps the real backend
process and improves **perceived startup time** without touching the Python
codebase or the AI ecosystem.

## Why

Profiling (see `docs/perf/rust-rewrite-vs-lazy-import.md`) showed that Octop's
bottleneck is **startup import time**, not runtime CPU. A full Rust rewrite of
807 files / ~197k lines + the entire Python AI ecosystem is not worth it.
Instead, this launcher does the small, high-value part in Rust:

1. Spawns the backend immediately.
2. Polls `GET /api/health` and emits a machine-readable `OCTOP_READY` line the
   moment the backend is usable — so the desktop shell / dashboard splash can
   switch away from the loading screen at the earliest correct moment.
3. Two readiness modes:
   - `--chat-ready` (default): wait until the health JSON reports
     `agents_running > 0`, i.e. a chat turn can actually be served.
   - `--liveness-only`: emit READY as soon as health returns 2xx (faster, but
     the agent stack may still be loading).
4. Forwards signals (Unix: SIGINT/SIGTERM via FFI; Windows: console group) and
   passes through the child's exit code.

Design: **std-only, zero external crates**. Builds offline, ~352 KB release
binary.

## Build

Requires a Rust toolchain. On this machine it is installed under `E:/rust`
(rustup home `E:/rust/rustup`, cargo home `E:/rust/cargo`), target
`x86_64-pc-windows-gnu`, using the system MinGW gcc as linker.

```bash
# If 'cargo' is not on PATH (rustup shim has no default configured), call the
# toolchain binary directly:
export CARGO="E:/rust/rustup/toolchains/stable-x86_64-pc-windows-gnu/bin/cargo.exe"
cd tools/octop-launcher
"$CARGO" test                 # 14 unit tests
"$CARGO" build --release      # -> target/release/octop-launcher.exe
```

A default toolchain can also be set once with `rustup default stable` so the
`cargo` shim works without the explicit path.

## Usage

```
octop-launcher [LAUNCHER OPTIONS] [--] [BACKEND ARGS...]

LAUNCHER OPTIONS (before `--`):
  --backend <exe>          Backend executable (default: octop)
  --host <host>            Health-check host (default: 127.0.0.1)
  --port <port>            Health-check port (default: 8097)
  --health-timeout <secs>  Wait seconds for /api/health; 0 disables (default: 90)
  --chat-ready             Wait until agents_running > 0 (default)
  --liveness-only          Emit READY as soon as health returns 2xx
  --workdir <dir>          Working directory for the backend process
  -h, --help               Show this help

Everything else is forwarded to the backend verbatim.
```

Examples:

```bash
octop-launcher --port 8097 -- run --port 8097
octop-launcher --liveness-only --backend octop.exe -- run --port 8097
octop-launcher --workdir E:/HAPPYclaw/Octop/src run --port 8097
```

The readiness line looks like:

```
OCTOP_READY pid=12345 elapsed_ms=3910
```

Consumers should treat any `OCTOP_READY` line on stdout as "safe to leave the
splash". If health times out, a warning is printed to stderr but the backend is
**not killed** — a slow boot is not a failed boot, and the launcher keeps
proxying its lifetime and exit code.

## Integrating

The launcher is an **opt-in wrapper**. It does not replace `octop run`; you
point the desktop shell / service definition at `octop-launcher` instead:

- Desktop shell: set the sidecar command to
  `octop-launcher --port <port> -- run --port <port>` and watch stdout for
  `OCTOP_READY`.
- Service / Docker entrypoint: use it as the container entrypoint with the same
  flags.

Until a consumer opts in, nothing changes — all existing `octop run` paths are
untouched.

## Fallback

If the launcher misbehaves or Rust is unavailable, run the backend directly:

```bash
octop run --port 8097
```

The launcher is a thin convenience layer; it holds no state and owns no logic
the backend cannot do without.

## Verification

```bash
"$CARGO" test                            # unit tests
python tools/octop-launcher/smoke_test.py # end-to-end: chat-ready vs liveness-only timing
```

The smoke test spins up a fake `/api/health` whose `agents_running` flips to 1
after 2.5s, then asserts `chat-ready` waits for it while `liveness-only` does
not. Last run: chat-ready 3910ms, liveness-only 1254ms (PASS).
