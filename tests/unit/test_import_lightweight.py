"""Guard: lightweight gateway submodules must stay off the heavy import path.

Regression guard for the cold-start work that made ``gateway/__init__.py`` use
PEP 562 lazy exports and ``wecom_creds`` defer its ``cryptography`` import.
Each assertion runs in a fresh interpreter so ``sys.modules`` reflects only
what that import actually pulled in.
"""

from __future__ import annotations

import subprocess
import sys

_HEAVY = ("langchain_core", "happyclaw_harness", "cryptography", "deepagents")
# Cron manager legitimately imports ``cryptography`` (credential decryption), but
# must never drag in the agent stack that binds /api/agents during boot.
_AGENT_STACK = ("langchain_core", "happyclaw_harness", "deepagents")
# ``happyclaw.api.app`` (the boot-time app factory) must not pull the JWT stack;
# tokens defer ``jwt`` to first sign/decode call.
_JWT_STACK = ("jwt", "cryptography")

_PROBE = """
import sys
{import_line}
heavy = [m for m in {heavy} if m in sys.modules]
print("HEAVY=" + ",".join(heavy))
"""


def _imports_heavy(import_line: str, heavy: tuple[str, ...] = _HEAVY) -> list[str]:
    code = _PROBE.format(import_line=import_line, heavy=repr(heavy))
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
    heavy = _imports_heavy("import happyclaw.infra.connectors.gateway")
    assert heavy == [], f"gateway package pulled heavy modules at import: {heavy}"


def test_wecom_creds_import_is_lightweight() -> None:
    heavy = _imports_heavy("import happyclaw.infra.connectors.gateway.wecom_creds")
    assert heavy == [], f"wecom_creds pulled heavy modules at import: {heavy}"


def test_cron_manager_import_is_lightweight() -> None:
    """``_prepare_runtime`` imports CronManager; that must not pull the agent stack."""
    heavy = _imports_heavy("import happyclaw.infra.cron.manager", _AGENT_STACK)
    assert heavy == [], f"cron manager pulled heavy modules at import: {heavy}"


def test_cron_delivery_heavy_symbols_still_resolve() -> None:
    """Laziness must not break the symbols delivery uses at runtime."""
    code = """
from happyclaw.infra.cron.delivery import (
    CronDeliveryCommand,
    CronDeliveryService,
    command_from_row,
)
from happyclaw.infra.cron.manager import CronCreateSpec, CronManager
assert callable(CronDeliveryService.deliver)
assert callable(command_from_row)
assert CronCreateSpec is not None and CronManager is not None
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


def test_gateway_lazy_exports_still_resolve() -> None:
    """Laziness must not break the public API used by builder/service/server."""
    code = """
from happyclaw.infra.connectors.gateway import (
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


def test_api_app_import_is_jwt_free() -> None:
    """The boot-time app factory must not pull the JWT/cryptography stack."""
    heavy = _imports_heavy("import happyclaw.api.app", _JWT_STACK)
    assert heavy == [], f"happyclaw.api.app pulled jwt stack at import: {heavy}"


def test_auth_tokens_lazy_jwt_still_roundtrips() -> None:
    """Deferral must not break sign/decode; ``jwt`` loads on first use."""
    code = """
import sys
from happyclaw.infra.auth.tokens import sign_token, decode_token, InvalidToken, TokenExpired
secret = b"k" * 32
token = sign_token(secret, sub=1, uname="u", role="owner", purpose="access")
payload = decode_token(secret, token)
assert payload["sub"] == 1 and payload["purpose"] == "access"
try:
    decode_token(secret, token + "x")
except InvalidToken:
    pass
else:
    raise AssertionError("tampered token must raise InvalidToken")
import jwt
assert "jwt" in sys.modules
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
