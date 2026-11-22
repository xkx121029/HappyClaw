"""Launch composition root must expose config even with a lazy mobile probe."""

from __future__ import annotations

from pathlib import Path

import pytest

from happyclaw.infra.server import OctopServer


@pytest.mark.asyncio
async def test_deferred_start_exposes_config_for_listen(tmp_octop_home: Path, monkeypatch) -> None:
    """``octop run`` reads bind host/port from config after the probe runs."""
    from happyclaw.infra import server as server_module
    from happyclaw.infra.control.mobile import config_probe

    guarded = []
    monkeypatch.setattr(server_module, "ensure_nofile_limit", lambda: guarded.append(True))
    original_probe = config_probe.ensure_mobile_capabilities_probed

    def probe(path):
        assert guarded == [True]  # Resource guard runs before runtime/config initialization.
        return original_probe(path)

    monkeypatch.setattr(config_probe, "ensure_mobile_capabilities_probed", probe)
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
