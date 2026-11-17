"""Guard: importing octop must not eagerly load httpx.

The NO_PROXY CIDR patch (issue #1347) used to be installed at ``import octop``
time, which pulled in the whole httpx stack (~1.1s) on every CLI meta-command,
pytest collection and plugin scan.  It is now installed via a one-shot import
hook the moment httpx is actually imported.  These guards lock in both halves
of that contract:

  1. ``import octop`` leaves httpx unloaded (the speed win).
  2. a later ``import httpx`` still gets the patch before any Client is made
     (behavior unchanged), and CIDR bypass still works.

Each check runs in a fresh interpreter so ``sys.modules`` reflects only what
that import actually pulled in.
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


def test_import_octop_does_not_load_httpx() -> None:
    out = _run(
        """
import sys
import octop
print("HTTPX_LOADED=" + str("httpx" in sys.modules))
"""
    )
    assert "HTTPX_LOADED=False" in out, f"octop import pulled httpx: {out}"


def test_httpx_import_still_gets_cidr_patch() -> None:
    out = _run(
        """
import os
import octop  # registers the lazy hook
os.environ["NO_PROXY"] = "192.168.0.0/16"
import httpx
from httpx._utils import URLPattern
patched = getattr(URLPattern.matches, "_octop_cidr_no_proxy", False)
client = httpx.Client()
direct = client._transport_for_url(httpx.URL("http://192.168.5.5/x")) is client._transport
print("PATCHED=" + str(patched))
print("CIDR_DIRECT=" + str(direct))
"""
    )
    assert "PATCHED=True" in out, f"CIDR patch not installed on httpx import: {out}"
    assert "CIDR_DIRECT=True" in out, f"CIDR bypass stopped working: {out}"


def test_lazy_hook_install_is_idempotent() -> None:
    out = _run(
        """
import sys
import octop
from octop.infra.utils.httpx_proxy import install_lazy_httpx_proxy_patch
install_lazy_httpx_proxy_patch()
install_lazy_httpx_proxy_patch()
hooks = [f for f in sys.meta_path if type(f).__name__ == "_HttpxPatchFinder"]
print("HOOK_COUNT=" + str(len(hooks)))
"""
    )
    assert "HOOK_COUNT=1" in out, f"lazy hook registered more than once: {out}"
