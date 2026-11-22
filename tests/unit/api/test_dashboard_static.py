"""Static-file delivery for the bundled dashboard.

Regressions this pins down:

* a missing static file must be a 404, never a 500 ``FileNotFoundError``
  (``/sw.js`` used to surface as a server error on cold start);
* the service worker path stays usable when the dashboard was built without the
  PWA plugin (``npm run build:fast`` emits no ``sw.js``);
* real SPA routes still fall back to ``index.html``.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from tests.support.app import ensure_control_plane_bound

import happyclaw.api.app as app_module
from happyclaw.api.app import build_app
from happyclaw.infra.server import OctopServer


@pytest.fixture
async def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    dash = tmp_path / "dashboard"
    dash.mkdir()
    (dash / "index.html").write_text(
        "<!doctype html><title>octop-shell</title>", encoding="utf-8"
    )
    monkeypatch.setattr(app_module, "default_dashboard_dir", lambda: dash)
    home = tmp_path / "home"
    home.mkdir()
    srv = OctopServer(home=home)
    await srv.start()
    await ensure_control_plane_bound(srv)
    app = build_app(srv)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as c:
        yield c, dash
    await srv.stop()


async def test_missing_static_file_is_404_not_500(client) -> None:
    c, _dash = client
    for path in ("/favicon.ico", "/missing.png", "/assets/index.deadbeef.js"):
        response = await c.get(path)
        assert response.status_code == 404, f"{path} -> {response.status_code}"


async def test_missing_service_worker_unregisters_instead_of_erroring(client) -> None:
    c, _dash = client
    response = await c.get("/sw.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/javascript")
    assert "registration.unregister()" in response.text
    assert response.headers["cache-control"] == "no-cache"


async def test_bundled_service_worker_is_served(client) -> None:
    c, dash = client
    body = "self.addEventListener('install', () => self.skipWaiting());\n"
    (dash / "sw.js").write_text(body, encoding="utf-8", newline="")

    response = await c.get("/sw.js")
    assert response.status_code == 200
    assert response.text == body
    assert response.headers["cache-control"] == "no-cache"


async def test_spa_deep_link_still_serves_shell(client) -> None:
    c, _dash = client
    response = await c.get("/chat/threads/42")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "octop-shell" in response.text
