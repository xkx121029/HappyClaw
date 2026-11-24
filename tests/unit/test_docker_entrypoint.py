"""Docker entrypoint: single-user first boot (dirs + DB, no account)."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path

import pytest

# Entrypoint helpers are bash, so these run wherever a bash is on PATH (e.g. Git Bash on Windows).
bash_exe = shutil.which("bash")
bash_only = pytest.mark.skipif(bash_exe is None, reason="requires a bash shell")

REPO = Path(__file__).resolve().parents[2]
ENTRYPOINT = REPO / "docker" / "docker-entrypoint.sh"


def _bash_path(path: Path) -> str:
    """Path bash can open. Git Bash does not treat ``C:\\...`` as a filesystem path."""
    posix = path.resolve().as_posix()
    if os.name == "nt" and len(posix) >= 3 and posix[1] == ":":
        return f"/{posix[0].lower()}{posix[2:]}"
    return posix


def _source_helpers() -> str:
    return f'HAPPYCLAW_ENTRYPOINT_LIB=1; source "{_bash_path(ENTRYPOINT)}"'


def _bash(script: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    # A bare "bash" on Windows is CreateProcess's System32\bash.exe (the WSL
    # launcher), which is found before Git Bash on PATH. which() searches PATH.
    if bash_exe is None:
        raise RuntimeError("bash is not on PATH")
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        [bash_exe, "-c", script],
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=merged,
        timeout=15,
    )


# ---------------------------------------------------------------------------
# Init guard across restarts (issue #1866). PostgreSQL / external backends
# never create ``octop.db`` in the data volume, so "already bootstrapped"
# must be tracked with a backend-agnostic marker written by the entrypoint
# after a successful ``octop init``.
# ---------------------------------------------------------------------------

_STUB_OCTOP = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$OCTOP_STUB_LOG"
if [ "$1" = "init" ] && [ "${OCTOP_STUB_INIT_FAIL:-0}" = "1" ]; then
    echo "unexpected database error" >&2
    exit 1
fi
exit 0
"""


def _init_marker(tmp_path: Path) -> Path:
    return tmp_path / "data" / ".happyclaw" / ".initialized"


def _posix_path(path: Path) -> str:
    """MSYS spelling of a Windows path (drive letter to /c form); POSIX paths pass through."""
    text = path.resolve().as_posix()
    if len(text) >= 3 and text[1] == ":":
        return "/" + text[0].lower() + text[2:]
    return text


def _posix_path_list(value: str) -> str:
    """Rewrite every Windows entry of a PATH into the MSYS form."""
    parts = [part for part in value.split(os.pathsep) if part.strip()]
    return ":".join(
        _posix_path(Path(part)) if "\\" in part or ":" in part[:2] else part for part in parts
    )


def _run_entrypoint(
    tmp_path: Path,
    *,
    extra_env: dict[str, str] | None = None,
    args: tuple[str, ...] = (),
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Run the real entrypoint with a stub ``octop`` on PATH; return (result, octop argv lines)."""
    assert bash_exe is not None
    home = tmp_path / "data"
    stub_dir = tmp_path / "stub-bin"
    stub_dir.mkdir(exist_ok=True)
    stub = stub_dir / "happyclaw"
    if not stub.exists():
        stub.write_text(_STUB_OCTOP, encoding="utf-8", newline="\n")
        stub.chmod(0o755)
    log = tmp_path / "octop-calls.log"
    log.write_text("", encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "HAPPYCLAW_HOME": str(home / ".happyclaw"),
            # MSYS resolves POSIX-style PATH entries; a Windows path here leaves the
            # stub unreachable and the entrypoint reports "command not found".
            "PATH": _posix_path(stub_dir) + ":" + _posix_path_list(env.get("PATH", "")),
            "OCTOP_STUB_LOG": str(log),
            "OCTOP_PORT": "8088",
        }
    )
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        [bash_exe, str(ENTRYPOINT), *args],
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=60,
    )
    calls = [line for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    return result, calls


@bash_only
def test_entrypoint_restart_skips_init_for_external_db(tmp_path: Path) -> None:
    """Issue #1866: with PostgreSQL there is no octop.db; a restart must not re-run init."""
    pg_env = {
        "OCTOP_DATABASE_DRIVER": "postgresql",
        "HAPPYCLAW_DATABASE_URL": "postgresql://octop:octop@postgres:5432/octop",
    }
    first, calls = _run_entrypoint(tmp_path, extra_env=pg_env)
    assert first.returncode == 0, first.stderr
    assert any(call.startswith("init ") for call in calls), calls
    assert any(call.startswith("run --host") for call in calls), calls
    assert not (tmp_path / "data" / ".happyclaw" / "octop.db").exists()
    assert _init_marker(tmp_path).is_file(), first.stdout

    second, calls = _run_entrypoint(tmp_path, extra_env=pg_env)
    assert second.returncode == 0, second.stderr
    assert not any(call.startswith("init") for call in calls), calls
    assert any(call.startswith("run --host") for call in calls), calls


@bash_only
def test_entrypoint_sqlite_install_skips_init_without_marker(tmp_path: Path) -> None:
    """Backward compat: an existing octop.db still short-circuits the guard."""
    octop_home = tmp_path / "data" / ".happyclaw"
    octop_home.mkdir(parents=True)
    (octop_home / "octop.db").write_text("", encoding="utf-8")

    result, calls = _run_entrypoint(tmp_path)
    assert result.returncode == 0, result.stderr
    assert not any(call.startswith("init") for call in calls), calls
    assert any(call.startswith("run --host") for call in calls), calls


@bash_only
def test_entrypoint_writes_no_credentials_on_first_boot(tmp_path: Path) -> None:
    """Single-user mode creates no account, so there is nothing to write to disk."""
    result, calls = _run_entrypoint(tmp_path)
    assert result.returncode == 0, result.stderr
    octop_home = tmp_path / "data" / ".happyclaw"
    assert not (octop_home / "credential.txt").exists()
    assert not (octop_home / "octop-login.txt").exists()
    init_call = next(call for call in calls if call.startswith("init"))
    assert init_call.strip() == "init --yes", calls


@bash_only
def test_entrypoint_init_failure_leaves_no_marker_and_retries_next_boot(tmp_path: Path) -> None:
    first, _ = _run_entrypoint(tmp_path, extra_env={"OCTOP_STUB_INIT_FAIL": "1"})
    assert first.returncode == 1, first.stdout
    assert not _init_marker(tmp_path).exists()

    second, calls = _run_entrypoint(tmp_path)
    assert second.returncode == 0, second.stderr
    assert any(call.startswith("init ") for call in calls), calls


def _df_stub(size: int) -> str:
    """Shell function so the warning logic does not depend on an executable ``df`` on PATH."""
    return f"df() {{ printf '%s\\n' size {size}; }}\n"


@bash_only
def test_entrypoint_warns_when_desktop_shm_is_default(tmp_path: Path) -> None:
    conf = tmp_path / "happyclaw-desktop"
    conf.mkdir()
    script = (
        _source_helpers()
        + "\n"
        + _df_stub(67108864)
        + f'octop_warn_small_shm "{_bash_path(conf)}"\n'
    )
    result = _bash(script)
    assert result.returncode == 0, result.stderr
    assert "--shm-size=1g" in result.stderr
    assert "64MB" in result.stderr


@bash_only
def test_entrypoint_stays_quiet_when_shm_is_enough(tmp_path: Path) -> None:
    conf = tmp_path / "happyclaw-desktop"
    conf.mkdir()
    missing = tmp_path / "missing"
    script = (
        _source_helpers()
        + "\n"
        + _df_stub(1073741824)
        + f'octop_warn_small_shm "{_bash_path(conf)}"\n'
        + f'octop_warn_small_shm "{_bash_path(missing)}"\n'
    )
    result = _bash(script)
    assert result.returncode == 0, result.stderr
    assert "shm" not in result.stderr


@bash_only
def test_entrypoint_arm_prepare_skips_non_arm() -> None:
    script = (
        _source_helpers()
        + "\nunset OPENBLAS_CORETYPE\n"
        + 'octop_prepare_arm_runtime\nprintf "%s" "${OPENBLAS_CORETYPE:-}"\n'
    )
    result = _bash(script)
    if platform.machine().lower() in {"aarch64", "arm64"}:
        assert result.returncode == 0, result.stderr
        assert result.stdout == "ARMV8"
        return
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_init_skip_message_still_marked_in_init_command() -> None:
    """Legacy admin bootstraps (fnOS) stay idempotent; ``octop init`` keeps the marker."""
    marker_text = "already exists, skipping"
    init_cmd = REPO / "src" / "happyclaw" / "cli" / "commands" / "init.py"
    assert marker_text in init_cmd.read_text(encoding="utf-8")


def test_entrypoint_ignores_legacy_admin_password_env() -> None:
    """The entrypoint no longer reads the legacy admin variables or writes credential files."""
    text = ENTRYPOINT.read_text(encoding="utf-8")
    for legacy in ("OCTOP_DEFAULT_PASSWORD", "OCTOP_ADMIN_USERNAME", "OCTOP_ADMIN_DISPLAY_NAME"):
        assert f"${{{legacy}" not in text
        assert f"$env:{legacy}" not in text
    for legacy_file in ("credential.txt", "octop-login.txt"):
        assert legacy_file not in text
