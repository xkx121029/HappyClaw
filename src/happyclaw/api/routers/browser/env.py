"""Browser environment probe and Chromium install (SSE).

Live sessions are happyclaw-browser (see ``harness.py`` / ``stream.py``), not
in-process Playwright.

  GET    /api/browser/env-status  → { playwright, browsers_ok, harness_browser, … }
  POST   /api/browser/install     → SSE Playwright Chromium install (or reuse system Chrome)
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from happyclaw.api.deps import current_user, require_permission

router = APIRouter()


def _probe_env() -> dict[str, Any]:
    """Cheap synchronous probe of browser environment availability.

    Requirements:
      1. Detect system Chrome/Chromium **or** Playwright-managed Chromium
         via the same ``find_chrome`` path used at launch time.
      2. ``browsers_ok`` means launch can use that binary (screenshot stream).
      3. Install (elsewhere) downloads Playwright Chromium only when missing.
      4. ``playwright_chromium`` flags whether *our* install exists (uninstall
         target); never implies deleting the user's system browser.

    ``verify_chromium`` is install-time only (see ``POST /browser/install``).
    """
    out: dict[str, Any] = {
        "playwright": False,
        "browsers_ok": False,
        "harness_browser": False,
        "playwright_chromium": False,
        "chrome_path": None,
        "chrome_source": None,  # "system" | "playwright" | None
        "needs_enable": False,
        "error": None,
        # Chinese, user-facing copy. Frozen bundles ship the Playwright driver
        # but not the browser binary (that lives in %LOCALAPPDATA%\ms-playwright),
        # so "not found" is a normal state, not a crash.
        "hint_zh": None,
    }

    from happyclaw.infra.control.browser.bundled import browser_enabled  # noqa: PLC0415
    from happyclaw.infra.control.browser.setup import (  # noqa: PLC0415
        chrome_source_for_path,
        playwright_chromium_installed,
    )

    out["playwright_chromium"] = playwright_chromium_installed()

    try:
        from happyclaw_browser import BrowserSession  # noqa: F401, PLC0415
        from happyclaw_browser.cdp.launcher import find_chrome  # noqa: PLC0415

        out["harness_browser"] = True
        try:
            chrome = find_chrome()
        except Exception as exc:  # noqa: BLE001
            # A broken/missing Playwright driver must degrade to "not installed",
            # never turn /browser/env-status into a 500.
            chrome = None
            out["error"] = f"browser probe failed: {exc}"
        if chrome:
            out["chrome_path"] = chrome
            out["chrome_source"] = chrome_source_for_path(chrome)
            if browser_enabled():
                out["browsers_ok"] = True
            else:
                out["needs_enable"] = True
                out["error"] = (
                    "Chromium is installed but not enabled. Confirm it on the Remote Browser page."
                )
        else:
            out["error"] = (
                "Chrome/Chromium not found. Install Google Chrome, or run "
                "POST /api/browser/install to download Playwright Chromium."
            )
            out["hint_zh"] = (
                "未找到可用的 Chrome/Chromium。可以安装本机 Chrome，或在「远程浏览器」页面点击"
                "下载 Playwright Chromium 后重试。"
            )
    except ImportError:
        out["hint_zh"] = "当前安装不包含浏览器组件（happyclaw-browser），远程浏览器功能不可用。"

    try:
        import playwright  # noqa: F401, PLC0415

        out["playwright"] = True
    except ImportError as exc:
        if not out["harness_browser"]:
            out["error"] = (
                f"playwright not installed: {exc}. Install octop[browser] extras or happyclaw-browser."
            )
            out["hint_zh"] = "当前安装缺少 Playwright 组件，远程浏览器功能不可用。"
        return out

    if not out["browsers_ok"] and not out.get("error"):
        out["error"] = (
            "Chrome/Chromium not found. Install Google Chrome, or run "
            "POST /api/browser/install to download Playwright Chromium."
        )
        out["hint_zh"] = (
            "未找到可用的 Chrome/Chromium。可以安装本机 Chrome，或在「远程浏览器」页面点击"
            "下载 Playwright Chromium 后重试。"
        )
    return out


@router.get("/browser/env-status")
async def env_status(_: Any = Depends(current_user)) -> dict[str, Any]:
    return _probe_env()


def _verify_browser_binary(exe: str) -> tuple[bool, str]:
    """Install-time check: binary exists and responds to ``--version``."""
    import subprocess  # noqa: PLC0415

    try:
        result = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"Browser verification timed out: {exe}"
    except OSError as exc:
        return False, f"Browser verification failed: {exc}"

    if result.returncode == 0:
        version = (result.stdout or result.stderr or "").strip() or exe
        return True, version
    detail = (result.stderr or result.stdout or "").strip()
    return False, f"Browser exited with code {result.returncode}: {detail}"


@router.post("/browser/install")
async def install(_: Any = Depends(require_permission("browser"))) -> StreamingResponse:
    """Stream Chromium install progress as SSE.

    Each event is a JSON line conforming to ``happyclaw_browser.InstallEvent``:
      ``{"log": "..."}``                              — progress line
      ``{"done": true, "success": true}``             — finished OK
      ``{"done": true, "success": false, "error": "..."}``  — failed

    If a system Chrome/Chromium is already resolvable via ``find_chrome``,
    verify it with ``--version`` and short-circuit (no Playwright download).
    Otherwise delegate to ``install_chromium_stream`` (which runs its own
    ``verify_chromium`` after download).

    Returns ``text/event-stream``; the client reads until ``done`` appears.
    """

    async def _event_stream() -> AsyncGenerator[str, None]:
        try:
            from happyclaw_browser.cdp.launcher import find_chrome  # noqa: PLC0415

            from happyclaw.infra.control.browser.bundled import (  # noqa: PLC0415
                confirm_browser_enabled,
            )

            chrome = find_chrome()
            if chrome:
                yield ("data: " + json.dumps({"log": f"Found browser: {chrome}"}) + "\n\n")
                yield ("data: " + json.dumps({"log": "Verifying installation ..."}) + "\n\n")
                ok, msg = _verify_browser_binary(chrome)
                if ok:
                    confirm_browser_enabled()
                    yield "data: " + json.dumps({"log": msg}) + "\n\n"
                    yield ("data: " + json.dumps({"done": True, "success": True}) + "\n\n")
                    return
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "log": (
                                f"System browser not usable ({msg}); "
                                "falling back to Playwright Chromium download ..."
                            )
                        }
                    )
                    + "\n\n"
                )

            from happyclaw_browser import install_chromium_stream  # noqa: PLC0415

            async for event in install_chromium_stream():
                if isinstance(event, dict) and event.get("done") and event.get("success"):
                    confirm_browser_enabled()
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:  # pragma: no cover
            yield f"data: {json.dumps({'done': True, 'success': False, 'error': str(exc)})}\n\n"

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
