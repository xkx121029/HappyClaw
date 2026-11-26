from __future__ import annotations

from typing import Any

import pytest

from octop.infra.market import clear_market_cache


@pytest.fixture(autouse=True)
def _empty_portal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCTOP_PORTAL_ORIGIN", "")
    clear_market_cache()


async def test_list_market_without_portal_still_lists_bundled(env: Any) -> None:
    """当 portal 为空时远程市场不可用，但 bundled 插件仍在列表中（source=bundled）。"""
    client, _srv, auth = env
    response = await client.get("/api/plugins/market", headers=auth)
    assert response.status_code == 200, response.text
    items = response.json()
    assert isinstance(items, list)
    bundled = [p for p in items if p.get("source") == "bundled"]
    assert bundled, "bundled 插件必须出现在市场列表中"
    any(b.get("id") == "task-progress-monitor" for b in bundled)


async def test_market_requires_plugin_market_permission(env_admin_alice: Any) -> None:
    client, _srv, _admin_auth, alice_auth = env_admin_alice
    listed = await client.get("/api/plugins/market", headers=alice_auth)
    assert listed.status_code == 403, listed.text
    installed = await client.post(
        "/api/plugins/market/any-plugin/install",
        headers=alice_auth,
    )
    assert installed.status_code == 403, installed.text
