"""Regression lock for single-user mode: multi-account surfaces stay retired.

Covers the single-user demolition contract:

- Retired multi-account prefixes (``/api/auth/oidc``, ``/api/users/roles`` ...)
  must answer ``404 NOT_FOUND`` on every method, including the IdP callback
  paths that used to create additional accounts.
- ``/api/users`` and ``/api/user-groups`` are fully unmounted: reads and
  writes alike answer ``404 NOT_FOUND`` (only the read-only avatar GET
  survives).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from octop.api.app import _RETIRED_MULTI_USER_PREFIXES, build_app
from octop.infra.server import OctopServer
from tests.support.app import ensure_control_plane_bound, write_octop_config


@asynccontextmanager
async def _client(tmp_octop_home: Path) -> AsyncIterator[TestClient]:
    write_octop_config(tmp_octop_home)
    srv = OctopServer(home=tmp_octop_home)
    await srv.start()
    await ensure_control_plane_bound(srv)
    try:
        with TestClient(build_app(srv)) as c:
            yield c
    finally:
        await srv.stop()


async def test_retired_prefixes_answer_not_found(tmp_octop_home: Path) -> None:
    async with _client(tmp_octop_home) as c:
        for prefix in _RETIRED_MULTI_USER_PREFIXES:
            for method in ("get", "post", "put", "patch", "delete"):
                resp = getattr(c, method)(f"/api{prefix}")
                assert resp.status_code == 404, (prefix, method, resp.text)
                body = resp.json()
                assert body["error"]["code"] == "NOT_FOUND", (prefix, method, body)


async def test_idp_callback_paths_answer_not_found(tmp_octop_home: Path) -> None:
    """The two former account-creation write ports must never come back."""
    async with _client(tmp_octop_home) as c:
        for path in ("/api/auth/oidc/callback", "/api/auth/oauth/callback"):
            resp = c.get(path)
            assert resp.status_code == 404, (path, resp.text)
            assert resp.json()["error"]["code"] == "NOT_FOUND", (path, resp.text)


async def test_account_routers_are_fully_retired(tmp_octop_home: Path) -> None:
    async with _client(tmp_octop_home) as c:
        for path in ("/api/users", "/api/user-groups"):
            write = c.post(path, json={"username": "extra", "password": "x"})
            assert write.status_code == 404, (path, write.text)
            assert write.json()["error"]["code"] == "NOT_FOUND", (path, write.text)

            listing = c.get(path)
            assert listing.status_code == 404, (path, listing.text)
            assert listing.json()["error"]["code"] == "NOT_FOUND", (path, listing.text)
