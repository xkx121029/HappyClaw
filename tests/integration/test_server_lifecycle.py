"""tests/integration/test_server_lifecycle.py"""

from __future__ import annotations

from pathlib import Path

import pytest

from happyclaw.infra.server import HappyclawServer
from tests.support.app import ensure_control_plane_bound


async def _bind_default_sqlite(srv: HappyclawServer) -> None:
    await ensure_control_plane_bound(srv)


@pytest.fixture
async def server(tmp_octop_home: Path):
    srv = HappyclawServer(home=tmp_octop_home)
    await srv.start()
    await _bind_default_sqlite(srv)
    yield srv
    await srv.stop()


async def test_start_opens_default_db_at_boot(tmp_octop_home: Path):
    """Single-user mode binds the default SQLite DB during ``start()``.

    b16cd5c5 removed the greenfield deferral so a stale ``database`` config can
    no longer leave ``/api/health`` waiting on a control plane that isn't there.
    """
    srv = HappyclawServer(home=tmp_octop_home)
    await srv.start()
    try:
        assert tmp_octop_home.is_dir()
        assert (tmp_octop_home / "config.json").exists()
        assert (tmp_octop_home / "octop.db").exists()
        assert srv.database_bound is True
        assert srv.services is not None
        # Already bound: the first-run wizard path must not rebind a live pool.
        before = srv.services
        await _bind_default_sqlite(srv)
        assert srv.services is before
    finally:
        await srv.stop()


async def test_start_creates_root_and_db(server: HappyclawServer, tmp_octop_home: Path):
    assert tmp_octop_home.is_dir()
    assert (tmp_octop_home / "octop.db").exists()
    assert (tmp_octop_home / "config.json").exists()


async def test_jwt_secret_seeded(server: HappyclawServer):
    assert server.services is not None
    secret = server.services.secret_repo.get("jwt")
    assert secret is not None
    assert len(secret) >= 32


async def test_user_manager_loaded(server: HappyclawServer):
    assert server.user_manager is not None
    # Single-user mode resolves the one local owner before serving traffic.
    assert server.user_manager.count() == 1


async def test_boot_then_stop_idempotent(tmp_octop_home: Path):
    srv = HappyclawServer(home=tmp_octop_home)
    await srv.start()
    await _bind_default_sqlite(srv)
    await srv.stop()
    await srv.stop()  # idempotent
