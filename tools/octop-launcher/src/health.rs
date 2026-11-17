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

/// Wait until the health endpoint returns a 2xx, or `timeout_secs` elapses.
///
/// Returns the elapsed duration on success. On timeout returns the last error
/// so callers can decide to keep proxying a slow-but-alive child anyway.
pub fn wait_until_ready(url: &str, timeout_secs: u64) -> Result<Duration, String> {
    let (host, port, path) = parse_http_url(url)?;
    let started = Instant::now();
    let deadline = started + Duration::from_secs(timeout_secs);
    let mut last_err = String::new();

    loop {
        match probe(&host, port, &path) {
            Ok(()) => return Ok(started.elapsed()),
            Err(e) => last_err = e,
        }
        if Instant::now() >= deadline {
            return Err(format!("timeout after {timeout_secs}s: {last_err}"));
        }
        std::thread::sleep(POLL_INTERVAL);
    }
}

/// One HTTP GET; Ok only if the status line carries a 2xx code.
fn probe(host: &str, port: u16, path: &str) -> Result<(), String> {
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

    let mut buf = [0u8; 128];
    let n = stream
        .read(&mut buf)
        .map_err(|e| format!("read response: {e}"))?;
    let head = String::from_utf8_lossy(&buf[..n]);
    let status = head.lines().next().unwrap_or("").trim();

    // HTTP/1.1 200 OK / HTTP/1.1 204 No Content, etc.
    if status.contains(" 2") {
        Ok(())
    } else {
        Err(format!("unhealthy status: {status:?}"))
    }
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
}
