//! Command-line configuration parsing (pure, unit-testable).

use std::path::PathBuf;

pub struct Config {
    pub help: bool,
    /// Backend executable, e.g. `octop` or `path/to/octop.exe`.
    pub backend: String,
    /// Extra args forwarded verbatim to the backend (e.g. `run --port 8097`).
    pub backend_args: Vec<String>,
    pub host: String,
    pub port: u16,
    /// `None` disables the health gate entirely.
    pub health_timeout_secs: Option<u64>,
    /// `true` waits for agents_running > 0 (chat-ready), else just liveness.
    pub chat_ready: bool,
    pub workdir: Option<PathBuf>,
}

impl Config {
    /// Parse argv (without the program name).
    ///
    /// Recognised launcher flags (must appear before `--`):
    ///   - `--backend <exe>`          backend executable (default `octop`)
    ///   - `--host <host>`            health-check host (default `127.0.0.1`)
    ///   - `--port <port>`            health-check port (default `8097`)
    ///   - `--health-timeout <secs>`  seconds to wait for /api/health; `0` disables
    ///   - `--chat-ready`             also wait until agents_running > 0 (default)
    ///   - `--liveness-only`          emit READY as soon as health returns 2xx
    ///   - `--workdir <dir>`          working directory for the child
    ///   - `-h`, `--help`             print usage
    ///   - `--`                       everything after is forwarded to the backend
    ///
    /// Anything not recognised before `--` is also forwarded to the backend, so
    /// `octop-launcher run --port 8097` just works with no leading `--`.
    pub fn parse(args: &[String]) -> Result<Self, String> {
        let mut help = false;
        let mut backend = "octop".to_string();
        let mut host = "127.0.0.1".to_string();
        let mut port: u16 = 8097;
        let mut health_timeout_secs: Option<u64> = Some(90);
        let mut chat_ready = true;
        let mut workdir: Option<PathBuf> = None;
        let mut backend_args: Vec<String> = Vec::new();

        let mut i = 0;
        let mut passthrough = false;
        while i < args.len() {
            let a = &args[i];
            if passthrough {
                backend_args.push(a.clone());
                i += 1;
                continue;
            }
            match a.as_str() {
                "--" => {
                    passthrough = true;
                    i += 1;
                }
                "-h" | "--help" => {
                    help = true;
                    i += 1;
                }
                "--chat-ready" => {
                    chat_ready = true;
                    i += 1;
                }
                "--liveness-only" => {
                    chat_ready = false;
                    i += 1;
                }
                "--backend" | "--host" | "--port" | "--health-timeout" | "--workdir" => {
                    let val = args
                        .get(i + 1)
                        .ok_or_else(|| format!("missing value for {a}"))?;
                    match a.as_str() {
                        "--backend" => backend = val.clone(),
                        "--host" => host = val.clone(),
                        "--port" => {
                            port = val.parse::<u16>().map_err(|_| {
                                format!("invalid port: '{val}' (expected 1-65535)")
                            })?;
                            if port == 0 {
                                return Err("port must be > 0".to_string());
                            }
                        }
                        "--health-timeout" => {
                            let n = val.parse::<u64>().map_err(|_| {
                                format!("invalid health timeout: '{val}' (expected seconds)")
                            })?;
                            health_timeout_secs = if n == 0 { None } else { Some(n) };
                        }
                        "--workdir" => workdir = Some(PathBuf::from(val)),
                        _ => unreachable!(),
                    }
                    i += 2;
                }
                _ => {
                    // Unrecognised token: treat as start of backend args, and
                    // forward this and everything after verbatim.
                    backend_args.push(a.clone());
                    passthrough = true;
                    i += 1;
                }
            }
        }

        if backend.is_empty() {
            return Err("backend executable must not be empty".to_string());
        }

        Ok(Self {
            help,
            backend,
            backend_args,
            host,
            port,
            health_timeout_secs,
            chat_ready,
            workdir,
        })
    }

    pub fn health_url(&self) -> String {
        format!("http://{}:{}/api/health", self.host, self.port)
    }

    pub fn print_usage() {
        eprintln!(
            "\
octop-launcher — health-gated process launcher for Octop

USAGE:
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

EXAMPLE:
    octop-launcher --port 8097 -- run --port 8097
    octop-launcher run --port 8097 --host 127.0.0.1"
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn a(v: &[&str]) -> Vec<String> {
        v.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn defaults() {
        let c = Config::parse(&[]).unwrap();
        assert!(!c.help);
        assert_eq!(c.backend, "octop");
        assert_eq!(c.health_url(), "http://127.0.0.1:8097/api/health");
        assert_eq!(c.health_timeout_secs, Some(90));
        assert!(c.chat_ready);
        assert!(c.backend_args.is_empty());
    }

    #[test]
    fn liveness_only_flag() {
        let c = Config::parse(&a(&["--liveness-only"])).unwrap();
        assert!(!c.chat_ready);
        let c2 = Config::parse(&a(&["--liveness-only", "--chat-ready"])).unwrap();
        assert!(c2.chat_ready);
    }

    #[test]
    fn parses_launcher_flags() {
        let c = Config::parse(&a(&[
            "--backend", "octop.exe",
            "--host", "0.0.0.0",
            "--port", "9000",
            "--health-timeout", "30",
            "--workdir", "E:/octop",
        ]))
        .unwrap();
        assert_eq!(c.backend, "octop.exe");
        assert_eq!(c.host, "0.0.0.0");
        assert_eq!(c.port, 9000);
        assert_eq!(c.health_timeout_secs, Some(30));
        assert_eq!(c.workdir, Some(PathBuf::from("E:/octop")));
        assert_eq!(c.health_url(), "http://0.0.0.0:9000/api/health");
    }

    #[test]
    fn disables_health_gate_with_zero() {
        let c = Config::parse(&a(&["--health-timeout", "0"])).unwrap();
        assert_eq!(c.health_timeout_secs, None);
    }

    #[test]
    fn forwards_args_after_separator() {
        let c = Config::parse(&a(&["--port", "8097", "--", "run", "--port", "8097"]))
            .unwrap();
        assert_eq!(c.backend_args, a(&["run", "--port", "8097"]));
    }

    #[test]
    fn forwards_implicit_backend_args() {
        let c = Config::parse(&a(&["run", "--port", "8097"])).unwrap();
        assert!(c.backend_args.is_empty() == false);
        assert_eq!(c.backend_args, a(&["run", "--port", "8097"]));
    }

    #[test]
    fn rejects_bad_port_and_missing_value() {
        assert!(Config::parse(&a(&["--port", "abc"])).is_err());
        assert!(Config::parse(&a(&["--port", "0"])).is_err());
        assert!(Config::parse(&a(&["--backend"])).is_err());
    }

    #[test]
    fn help_flag() {
        let c = Config::parse(&a(&["--help"])).unwrap();
        assert!(c.help);
    }
}
