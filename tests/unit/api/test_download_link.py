from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from tests.support.app import ensure_control_plane_bound
from tests.support.auth import bearer, bootstrap_admin, login

from happyclaw.api.app import build_app
from happyclaw.infra.server import HappyclawServer


@pytest.fixture
async def client(tmp_path: Path):
    srv = HappyclawServer(home=tmp_path)
    await srv.start()
    await ensure_control_plane_bound(srv)
    app = build_app(srv)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as c:
        yield c, tmp_path
    await srv.stop()


async def test_download_link_opens_without_credentials(client) -> None:
    c, home = client
    await bootstrap_admin(c, home)
    token = await login(c)
    created = await c.post(
        "/api/downloads/link",
        headers=bearer(token),
        files={"file": ("报告.docx", b"hello", "application/octet-stream")},
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["filename"] == "报告.docx"
    assert body["expires_in"] > 0
    assert body["url"].startswith("/api/downloads/link/")

    opened = await c.get(body["url"])
    assert opened.status_code == 200, opened.text
    assert opened.content == b"hello"
    assert opened.headers["content-type"] == "application/octet-stream"
    assert "filename*=UTF-8''%E6%8A%A5%E5%91%8A.docx" in opened.headers["content-disposition"]
    assert opened.headers["cache-control"] == "no-store"


async def test_download_link_create_needs_no_login(client) -> None:
    """Single-user mode has no login: the local owner creates links directly."""
    c, home = client
    await bootstrap_admin(c, home)
    response = await c.post(
        "/api/downloads/link",
        files={"file": ("note.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["url"].startswith("/api/downloads/link/")


async def test_unknown_download_link_is_not_found(client) -> None:
    c, home = client
    await bootstrap_admin(c, home)
    response = await c.get("/api/downloads/link/not-a-real-token")
    assert response.status_code == 404
