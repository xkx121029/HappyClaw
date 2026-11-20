"""Launch composition root must expose config loaded during startup."""

from __future__ import annotations

from pathlib import Path

import pytest

from octop.infra.server import OctopServer


@pytest.mark.asyncio
async def test_deferred_start_exposes_config_for_listen(tmp_octop_home: Path, monkeypatch) -> None:
    """``octop run`` reads bind host/port from config after startup."""
    from octop.infra import server as server_module

    guarded = []
    monkeypatch.setattr(server_module, "ensure_nofile_limit", lambda: guarded.append(True))
    original_load_config = server_module.load_config

    def load(path):
        assert guarded == [True]  # Resource guard runs before runtime/config initialization.
        return original_load_config(path)

    monkeypatch.setattr(server_module, "load_config", load)
    srv = OctopServer(home=tmp_octop_home)
    await srv.start()
    try:
        # Single-user boot always binds SQLite, so services exist right away.
        assert srv.services is not None
        cfg = srv.config
        assert cfg is not None
        assert isinstance(cfg.port, int)
        assert cfg.bind_host
    finally:
        await srv.stop()
