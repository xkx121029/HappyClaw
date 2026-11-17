"""Guard: lightweight gateway submodules must stay off the heavy import path.

Regression guard for the cold-start work that made ``gateway/__init__.py`` use
PEP 562 lazy exports and ``wecom_creds`` defer its ``cryptography`` import.
Each assertion runs in a fresh interpreter so ``sys.modules`` reflects only
what that import actually pulled in.
"""

from __future__ import annotations

import subprocess
import sys

_HEAVY = ("langchain_core", "octop_harness", "cryptography")

_PROBE = """
import sys
{import_line}
heavy = [m for m in {heavy} if m in sys.modules]
print("HEAVY=" + ",".join(heavy))
"""


def _imports_heavy(import_line: str) -> list[str]:
    code = _PROBE.format(import_line=import_line, heavy=repr(_HEAVY))
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_project_root()),
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
        env={**_environ_with_src()},
    )
    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("HEAVY=")), "")
    raw = line.split("=", 1)[1] if "=" in line else ""
    return [m for m in raw.split(",") if m]


def _project_root():
    from pathlib import Path

    return Path(__file__).resolve().parents[2]


def _environ_with_src() -> dict[str, str]:
    import os

    env = dict(os.environ)
    src = str(_project_root() / "src")
    env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def test_gateway_package_import_is_lightweight() -> None:
    heavy = _imports_heavy("import octop.infra.connectors.gateway")
    assert heavy == [], f"gateway package pulled heavy modules at import: {heavy}"


def test_wecom_creds_import_is_lightweight() -> None:
    heavy = _imports_heavy("import octop.infra.connectors.gateway.wecom_creds")
    assert heavy == [], f"wecom_creds pulled heavy modules at import: {heavy}"


def test_gateway_lazy_exports_still_resolve() -> None:
    """Laziness must not break the public API used by builder/service/server."""
    code = """
from octop.infra.connectors.gateway import (
    build_gateway_langchain_tools,
    handle_mcp_request,
    mcp_tools_for_kind,
    agently_auth,
)
assert callable(build_gateway_langchain_tools)
assert callable(handle_mcp_request)
assert callable(mcp_tools_for_kind)
assert hasattr(agently_auth, "authorize")
print("OK")
"""
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_project_root()),
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
        env=_environ_with_src(),
    )
    assert "OK" in proc.stdout
