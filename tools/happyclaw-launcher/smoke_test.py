"""End-to-end smoke test for happyclaw-launcher health gating."""
import os, subprocess, sys, time, signal

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
LAUNCHER = os.path.join(HERE, "target", "release", "happyclaw-launcher.exe")
FAKE = os.path.join(HERE, "smoke_backend.py")
PORT = 18097

def run_mode(mode_flag, delay):
    env = dict(os.environ, FAKE_PORT=str(PORT), FAKE_AGENT_DELAY=str(delay))
    fake = subprocess.Popen([PY, FAKE], env=env)
    time.sleep(0.4)  # let fake backend bind
    # Backend process launcher will spawn: a long sleep via python
    cmd = [LAUNCHER, "--host", "127.0.0.1", "--port", str(PORT),
           "--health-timeout", "15", mode_flag,
           "--backend", PY, "--", "-c", "import time; time.sleep(30)"]
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    ready_ms = None
    for line in proc.stdout:
        line = line.strip()
        if line.startswith("HAPPYCLAW_READY"):
            ready_ms = (time.monotonic() - t0) * 1000
            break
    # cleanup
    proc.terminate()
    try: proc.wait(timeout=5)
    except Exception: proc.kill()
    fake.terminate()
    try: fake.wait(timeout=5)
    except Exception: fake.kill()
    return ready_ms

print("=== chat-ready mode (expect ready >= 2500ms) ===")
r1 = run_mode("--chat-ready", 2.5)
print(f"  HAPPYCLAW_READY after {r1:.0f}ms" if r1 else "  NO READY SIGNAL")
print("=== liveness-only mode (expect ready before chat-ready) ===")
r2 = run_mode("--liveness-only", 2.5)
print(f"  HAPPYCLAW_READY after {r2:.0f}ms" if r2 else "  NO READY SIGNAL")

# Core assertion: chat-ready must be clearly slower than liveness-only
# (it waits for agents_running to flip). Absolute time varies with load,
# so compare the two modes against each other for robustness.
ok = (
    r1 is not None
    and r2 is not None
    and r1 >= 2300          # chat-ready actually waited past the 2.5s flip
    and r1 - r2 >= 800      # and is clearly slower than liveness-only
)
print("SMOKE:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
