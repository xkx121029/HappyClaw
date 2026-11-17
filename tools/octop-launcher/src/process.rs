//! Child-process lifecycle: spawn backend, wait, forward signals, map exit code.

use crate::config::Config;
use std::process::{Child, Command, ExitStatus, Stdio};

/// Spawn the backend with inherited stdio so logs flow straight through.
pub fn spawn_backend(cfg: &Config) -> Result<Child, String> {
    let mut cmd = Command::new(&cfg.backend);
    cmd.args(&cfg.backend_args)
        .stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());

    if let Some(dir) = &cfg.workdir {
        cmd.current_dir(dir);
    }

    cmd.spawn()
        .map_err(|e| format!("failed to spawn backend '{}': {e}", cfg.backend))
}

/// Wait for the child. On Unix, install a SIGINT/SIGTERM handler that forwards
/// the signal to the child so Ctrl-C behaves as if the backend ran directly.
///
/// Uses only std. The signal handler stores the child pid in an atomic; the
/// handler sends the signal via `libc::kill` through a tiny extern declaration
/// (no crate dependency, since libc symbols are linked on every Unix).
#[cfg(unix)]
pub fn wait_with_signals(child: &mut Child) -> Result<ExitStatus, String> {
    use std::sync::atomic::{AtomicI32, Ordering};

    type SigHandler = extern "C" fn(i32);
    static CHILD_PID: AtomicI32 = AtomicI32::new(0);
    extern "C" {
        fn kill(pid: i32, sig: i32) -> i32;
        fn signal(sig: i32, handler: SigHandler) -> usize;
    }
    extern "C" fn forward(sig: i32) {
        let pid = CHILD_PID.load(Ordering::SeqCst);
        if pid > 0 {
            unsafe {
                kill(pid, sig);
            }
        }
    }

    CHILD_PID.store(child.id() as i32, Ordering::SeqCst);
    unsafe {
        signal(2, forward); // SIGINT
        signal(15, forward); // SIGTERM
    }
    let status = child.wait().map_err(|e| format!("wait failed: {e}"))?;
    CHILD_PID.store(0, Ordering::SeqCst);
    Ok(status)
}

/// On Windows, console Ctrl-C is delivered to every process attached to the
/// console (including the child), so the launcher just waits.
#[cfg(windows)]
pub fn wait_with_signals(child: &mut Child) -> Result<ExitStatus, String> {
    child.wait().map_err(|e| format!("wait failed: {e}"))
}

/// Map a child's ExitStatus to the launcher's own exit code (u8).
/// Signals / abnormal termination map to 128 + signal on Unix, 1 elsewhere.
pub fn exit_code(status: ExitStatus) -> u8 {
    if let Some(code) = status.code() {
        return (code & 0xFF) as u8;
    }
    #[cfg(unix)]
    {
        use std::os::unix::process::ExitStatusExt;
        if let Some(sig) = status.signal() {
            return (128 + (sig & 0x7F)) as u8;
        }
    }
    1
}

#[cfg(test)]
mod tests {
    use super::*;

    #[cfg(unix)]
    fn status_from_code(c: i32) -> ExitStatus {
        use std::os::unix::process::ExitStatusExt;
        ExitStatus::from_raw(c << 8)
    }

    #[cfg(unix)]
    #[test]
    fn passthrough_normal_codes() {
        assert_eq!(exit_code(status_from_code(0)), 0);
        assert_eq!(exit_code(status_from_code(1)), 1);
        assert_eq!(exit_code(status_from_code(42)), 42);
    }

    #[cfg(unix)]
    #[test]
    fn masks_high_bits() {
        assert_eq!(exit_code(status_from_code(300)), 44);
    }

    #[cfg(unix)]
    #[test]
    fn signal_maps_to_128_plus_sig() {
        use std::os::unix::process::ExitStatusExt;
        let s = ExitStatus::from_raw(15); // terminated by SIGTERM
        assert_eq!(exit_code(s), 143);
    }
}
