//! Health-check gate: poll `GET /api/health` until the backend answers 200.
//!
//! Implemented with std-only building blocks (TcpStream + a minimal HTTP/1.1
//! GET). No HTTP crate, so it builds offline.

use std::io::{Read, Write};
use std::net::{TcpStream, ToSocketAddrs};
use std::time::{Duration, Instant};

const POLL_INTERVAL: Duration = Duration::from_millis(250);
const CONNECT_TIMEOUT: Duration = Duration::from_millis(800);
const READ_TIMEOUT: Duration = Duration::from_secs(3);

/// What counts as "ready enough" to tell the frontend to leave the splash.
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum ReadyMode {
    /// Socket accepts + health returns 2xx. Fast, but agents may still be loading.
    Liveness,
    /// Additionally require `"agents_running": N` with N > 0 in the JSON body.
    /// This is when a chat turn can actually be served.
    ChatReady,
}

/// Wait until the health endpoint satisfies `mode`, or `timeout_secs` elapses.
///
/// Returns elapsed duration on success. On timeout returns the last error so
/// callers can keep proxying a slow-but-alive child anyway.
pub fn wait_until_ready(url: &str, timeout_secs: u64, mode: ReadyMode) -> Result<Duration, String> {
    let (host, port, path) = parse_http_url(url)?;
    let started = Instant::now();
    let deadline = started + Duration::from_secs(timeout_secs);
    let mut last_err = String::new();

    loop {
        match probe(&host, port, &path) {
            Ok(body) => {
                let satisfied = match mode {
                    ReadyMode::Liveness => true,
                    ReadyMode::ChatReady => agents_running(&body) > 0,
                };
                if satisfied {
                    return Ok(started.elapsed());
                }
                last_err = "health OK but agents not running yet".to_string();
            }
            Err(e) => last_err = e,
        }
        if Instant::now() >= deadline {
            return Err(format!("timeout after {timeout_secs}s: {last_err}"));
        }
        std::thread::sleep(POLL_INTERVAL);
    }
}

/// One HTTP GET; Ok with the response body if the status line carries a 2xx.
fn probe(host: &str, port: u16, path: &str) -> Result<String, String> {
    let addr = (host, port)
        .to_socket_addrs()
        .map_err(|e| format!("resolve {host}:{port}: {e}"))?
        .next()
        .ok_or_else(|| format!("no socket address for {host}:{port}"))?;

    let mut stream = TcpStream::connect_timeout(&addr, CONNECT_TIMEOUT)
        .map_err(|e| format!("connect {host}:{port}: {e}"))?;
    stream
        .set_read_timeout(Some(READ_TIMEOUT))
        .map_err(|e| format!("set_read_timeout: {e}"))?;
    stream
        .set_write_timeout(Some(READ_TIMEOUT))
        .map_err(|e| format!("set_write_timeout: {e}"))?;

    let req = format!(
        "GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nConnection: close\r\n\r\n"
    );
    stream
        .write_all(req.as_bytes())
        .map_err(|e| format!("write request: {e}"))?;

    let mut raw = Vec::with_capacity(512);
    let mut buf = [0u8; 512];
    loop {
        match stream.read(&mut buf) {
            Ok(0) => break,
            Ok(n) => raw.extend_from_slice(&buf[..n]),
            Err(e) => return Err(format!("read response: {e}")),
        }
        if raw.len() > 64 * 1024 {
            break;
        }
    }
    let text = String::from_utf8_lossy(&raw);
    let status = text.lines().next().unwrap_or("").trim();
    if !status.contains(" 2") {
        return Err(format!("unhealthy status: {status:?}"));
    }
    // Body is everything after the first blank line.
    let body = text
        .split_once("\r\n\r\n")
        .map(|(_, b)| b)
        .or_else(|| text.split_once("\n\n").map(|(_, b)| b))
        .unwrap_or("")
        .to_string();
    Ok(body)
}

/// Extract `"agents_running": <int>` from a JSON body without a JSON crate.
///
/// Deliberately simple: scan for the key, then the first integer after ':'.
/// Returns 0 if absent/unparseable (caller treats that as "not ready").
pub fn agents_running(body: &str) -> u64 {
    let key = "\"agents_running\"";
    let Some(pos) = body.find(key) else {
        return 0;
    };
    let rest = &body[pos + key.len()..];
    let Some(colon) = rest.find(':') else {
        return 0;
    };
    let value_part = rest[colon + 1..].trim_start();
    let digits: String = value_part
        .chars()
        .skip_while(|c| c.is_whitespace())
        .take_while(|c| c.is_ascii_digit())
        .collect();
    digits.parse::<u64>().unwrap_or(0)
}

/// Parse `http://host:port/path` -> (host, port, path).
/// Pure function, unit-tested. Supports IPv4/hostnames and an explicit port.
pub fn parse_http_url(url: &str) -> Result<(String, u16, String), String> {
    let rest = url
        .strip_prefix("http://")
        .or_else(|| url.strip_prefix("https://"))
        .ok_or_else(|| format!("expected http:// or https:// URL, got {url:?}"))?;

    let (authority, path) = match rest.find('/') {
        Some(idx) => (&rest[..idx], &rest[idx..]),
        None => (rest, "/"),
    };

    let (host, port) = match authority.rsplit_once(':') {
        Some((h, p)) => {
            let port = p
                .parse::<u16>()
                .map_err(|_| format!("invalid port in URL: {p:?}"))?;
            (h.to_string(), port)
        }
        None => (authority.to_string(), 80),
    };

    if host.is_empty() {
        return Err("empty host in URL".to_string());
    }
    Ok((host, port, path.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_full_url() {
        let (h, p, path) = parse_http_url("http://127.0.0.1:8097/api/health").unwrap();
        assert_eq!(h, "127.0.0.1");
        assert_eq!(p, 8097);
        assert_eq!(path, "/api/health");
    }

    #[test]
    fn parses_hostname_default_port_and_root() {
        let (h, p, path) = parse_http_url("http://localhost").unwrap();
        assert_eq!(h, "localhost");
        assert_eq!(p, 80);
        assert_eq!(path, "/");
    }

    #[test]
    fn rejects_bad_scheme_and_port() {
        assert!(parse_http_url("ftp://x:1/").is_err());
        assert!(parse_http_url("http://x:abc/").is_err());
        assert!(parse_http_url("http://:80/").is_err());
    }

    #[test]
    fn extracts_agents_running() {
        let body = r#"{"ok":true,"agents_running":3,"users_loaded":1}"#;
        assert_eq!(agents_running(body), 3);
    }

    #[test]
    fn agents_running_zero_and_missing() {
        assert_eq!(agents_running(r#"{"agents_running":0}"#), 0);
        assert_eq!(agents_running(r#"{"ok":true}"#), 0);
        assert_eq!(agents_running("not json"), 0);
    }

    #[test]
    fn agents_running_tolerates_spacing() {
        assert_eq!(agents_running(r#"{ "agents_running" : 12 }"#), 12);
    }
}
