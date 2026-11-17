//! Thin process launcher for Octop.
//!
//! Responsibilities (kept deliberately small):
//!   1. Spawn the real backend (`octop run ...`) as a child process.
//!   2. Poll `GET /api/health` until the backend is ready, then emit a
//!      machine-readable readiness line to stdout (used by the desktop shell
//!      / dashboard splash to switch away from the loading screen ASAP).
//!   3. Forward OS signals (SIGINT/SIGTERM) to the child.
//!   4. Passthrough the child's exit code.
//!
//! Design notes:
//!   - std-only, zero external crates -> builds offline, fast, reproducible.
//!   - Pure helpers are unit-tested without spawning real processes.

mod config;
mod health;
mod process;

use config::Config;
use std::process::ExitCode;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();

    let cfg = match Config::parse(&args) {
        Ok(c) => c,
        Err(msg) => {
            eprintln!("octop-launcher: {msg}");
            Config::print_usage();
            return ExitCode::from(2);
        }
    };

    if cfg.help {
        Config::print_usage();
        return ExitCode::SUCCESS;
    }

    match run(cfg) {
        Ok(code) => ExitCode::from(code),
        Err(msg) => {
            eprintln!("octop-launcher: {msg}");
            ExitCode::from(1)
        }
    }
}

fn run(cfg: Config) -> Result<u8, String> {
    let mut child = process::spawn_backend(&cfg)?;
    let pid = child.id();

    if let Some(timeout) = cfg.health_timeout_secs {
        let mode = if cfg.chat_ready {
            health::ReadyMode::ChatReady
        } else {
            health::ReadyMode::Liveness
        };
        match health::wait_until_ready(&cfg.health_url(), timeout, mode) {
            Ok(elapsed) => {
                println!("OCTOP_READY pid={pid} elapsed_ms={}", elapsed.as_millis());
            }
            Err(_) => {
                eprintln!(
                    "octop-launcher: health check timed out after {timeout}s; \
                     backend may still be booting (pid={pid})"
                );
                // Do not kill the child: a slow boot is not a failed boot.
                // Stop waiting and just proxy the remaining lifetime.
            }
        }
    }

    // Block until the child exits, forwarding signals along the way.
    let status = process::wait_with_signals(&mut child)?;
    Ok(process::exit_code(status))
}
