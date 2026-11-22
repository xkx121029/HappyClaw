"""Guard: importing the i18n domains package must not pull in LangChain.

``octop.i18n.domains`` used to eagerly import every domain, including
``domains.stream`` whose top level imports ``langchain_core``.  That made any
error-handling / CLI path (e.g. ``from happyclaw.infra.errors import OctopError``)
drag in the whole LangChain import tree.  Exports are now PEP 562 lazy.

These guards run in fresh interpreters so ``sys.modules`` reflects only what
each import actually pulled in, and verify the full public surface still
resolves (including the ``slash_tr`` -> ``slash.tr`` alias).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _env_with_src() -> dict[str, str]:
    import os

    env = dict(os.environ)
    src = str(_ROOT / "src")
    env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def _run(code: str) -> str:
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
        env=_env_with_src(),
    )
    return proc.stdout


def test_domains_package_import_is_lightweight() -> None:
    out = _run(
        """
import sys
import happyclaw.i18n.domains
print("LANGCHAIN_LOADED=" + str("langchain_core" in sys.modules))
"""
    )
    assert "LANGCHAIN_LOADED=False" in out, f"domains import pulled langchain: {out}"


def test_errors_and_cli_run_import_are_lightweight() -> None:
    out = _run(
        """
import sys
from happyclaw.infra.errors import OctopError
import happyclaw.cli.commands.run
print("LANGCHAIN_LOADED=" + str("langchain_core" in sys.modules))
"""
    )
    assert "LANGCHAIN_LOADED=False" in out, f"error/CLI import pulled langchain: {out}"


def test_lazy_exports_all_resolve() -> None:
    out = _run(
        """
import happyclaw.i18n.domains as d
missing = []
for name in d.__all__:
    try:
        getattr(d, name)
    except Exception as exc:
        missing.append(f"{name}:{exc}")
print("COUNT=" + str(len(d.__all__)))
print("MISSING=" + ",".join(missing))
print("SLASH_TR_CALLABLE=" + str(callable(d.slash_tr)))
print("ERROR_MESSAGE=" + d.error_message("AUTH_FAILED"))
"""
    )
    assert "COUNT=25" in out, f"unexpected export count: {out}"
    missing_line = next((ln for ln in out.splitlines() if ln.startswith("MISSING=")), "")
    assert missing_line == "MISSING=", f"unresolved exports: {out}"
    assert "SLASH_TR_CALLABLE=True" in out, f"slash_tr alias broken: {out}"


def test_direct_submodule_import_still_works() -> None:
    """Direct submodule imports bypass the package __init__ aggregation."""
    out = _run(
        """
from happyclaw.i18n.domains.stream import classify_stream_error_message
from happyclaw.i18n.domains.channel import channel_tool_hint_start
assert callable(classify_stream_error_message)
assert callable(channel_tool_hint_start)
print("OK")
"""
    )
    assert "OK" in out
