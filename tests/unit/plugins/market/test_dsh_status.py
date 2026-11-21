"""Shape and semantics of the dedicated DSH status payload."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator

import pytest

from octop.infra.agents.plugins.constants import DSH_STATUS_SCHEMA_VERSION
from octop.infra.agents.plugins.manager import PluginManager
from octop.infra.dsh.diagnostics import clear_failures, record_failure

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "dsh_market"


class _Handler(BaseHTTPRequestHandler):
    routes: dict[str, bytes] = {}

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        body = self.routes.get(self.path.split("?")[0])
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: Any) -> None:  # noqa: D401 - silence tests
        return


@pytest.fixture
def index_url() -> Iterator[str]:
    routes = {"/index.json": (FIXTURES / "index.json").read_bytes()}
    handler = type("Handler", (_Handler,), {"routes": routes})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/index.json"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture(autouse=True)
def _isolated_diagnostics() -> Iterator[None]:
    clear_failures()
    yield
    clear_failures()


@pytest.fixture
def manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PluginManager:
    monkeypatch.setenv("OCTOP_DSH_MARKET_ROOT", str(tmp_path / "market"))
    for name in (
        "OCTOP_DSH_RUNTIME",
        "OCTOP_DSH_TOOLS",
        "OCTOP_DSH_HITL",
        "OCTOP_DSH_EXEC",
        "OCTOP_DSH_SHADOW",
        "OCTOP_DSH_LLM",
        "OCTOP_DSH_SKILLS_PROMPTS",
    ):
        monkeypatch.delenv(name, raising=False)
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"plugin_market": {"dsh_sources": []}}), encoding="utf-8"
    )
    return PluginManager(plugins_dir=tmp_path / "plugins", config_path=config)


def test_disabled_runtime_reports_codes_without_touching_sources(
    manager: PluginManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCTOP_DSH_RUNTIME", "1")

    status = manager.dsh_status()

    assert status["schema_version"] == DSH_STATUS_SCHEMA_VERSION
    assert status["runtime"]["enabled"] is True
    assert status["runtime"]["ready"] is False
    assert status["runtime"]["reason_code"] == "DSH_NO_STAGE_ENABLED"
    assert status["sources"] == {"checked_at": None, "probed": False, "items": []}
    assert status["installed"] == []
    assert status["tools"] == {"stage_enabled": False, "report": None, "error": None}
    assert status["llm"] == {"stage_enabled": False, "installation": None, "error": None}
    assert status["last_failure"] is None


def test_master_switch_off_is_distinguishable(
    manager: PluginManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCTOP_DSH_TOOLS", "1")

    status = manager.dsh_status()

    assert status["runtime"]["enabled"] is False
    assert status["runtime"]["reason_code"] == "DSH_RUNTIME_DISABLED"
    stages = {stage["name"]: stage for stage in status["stages"]}
    # Configured but neutralised by the master switch.
    assert stages["tools"]["configured"] is True
    assert stages["tools"]["effective"] is False
    assert stages["tools"]["gated_by_master"] is True
    assert stages["skills_prompts"]["gated_by_master"] is False


def test_ready_runtime_and_stage_metadata(
    manager: PluginManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCTOP_DSH_RUNTIME", "1")
    monkeypatch.setenv("OCTOP_DSH_TOOLS", "1")

    status = manager.dsh_status()

    assert status["runtime"]["ready"] is True
    assert status["runtime"]["reason_code"] is None
    assert status["runtime"]["node"] == {
        "required": False,
        "available": None,
        "version": None,
    }
    tools = {stage["name"]: stage for stage in status["stages"]}["tools"]
    assert tools["env"] == "OCTOP_DSH_TOOLS"
    assert tools["effective"] is True


def test_probe_reports_source_health_and_warms_the_catalog(
    manager: PluginManager, index_url: str
) -> None:
    manager.add_dsh_source(index_url)
    before = manager.dsh_status()
    assert before["sources"]["items"][0]["status"] == "unknown"
    assert before["sources"]["items"][0]["checked_at"] is None

    probed = manager.dsh_status(probe=True)
    item = probed["sources"]["items"][0]
    assert probed["sources"]["probed"] is True
    assert item["status"] == "ok"
    assert item["entry_count"] == 2
    assert item["checked_at"] == probed["sources"]["checked_at"]
    assert item["error"] is None

    # The probe reused its snapshot for the catalog instead of re-downloading.
    view = manager.list_dsh_market()
    assert view["cached"] is True
    assert view["total"] == 2

    after = manager.dsh_status()
    assert after["sources"]["probed"] is False
    assert after["sources"]["items"][0]["status"] == "ok"


def test_last_failure_is_typed_and_deduplicated(manager: PluginManager) -> None:
    record_failure(
        kind="execute",
        plugin_id="dsh:demo",
        code="TOOL_RUNTIME_PLUGIN_NOT_LOADED",
        reason="依赖未安装",
    )
    record_failure(
        kind="execute",
        plugin_id="dsh:demo",
        code="TOOL_RUNTIME_PLUGIN_NOT_LOADED",
        reason="依赖未安装",
    )
    record_failure(
        kind="load", plugin_id="dsh:other", code="no_tool_provider", reason="没有工具入口"
    )

    status = manager.dsh_status()

    assert status["last_failure"]["plugin_id"] == "dsh:other"
    assert status["last_failure"]["kind"] == "load"
    assert {item["plugin_id"] for item in status["recent_failures"]} == {
        "dsh:demo",
        "dsh:other",
    }
    assert len(status["recent_failures"]) == 2
