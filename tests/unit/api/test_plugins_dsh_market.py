"""Router wiring for the DSH market endpoints (no real installs)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from octop.api.deps import current_user
from octop.api.routers import plugins as plugins_router
from octop.infra.errors import ErrorCode, OctopError


class FakeManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def list_market(self, language: str = "zh") -> list[dict[str, Any]]:
        return [{"id": "portal-only", "language": language}]

    def list_dsh_market(
        self,
        language: str = "zh",
        *,
        query: str = "",
        page: int = 1,
        page_size: int = 50,
        refresh: bool = False,
    ) -> dict[str, Any]:
        self.calls.append(("list_dsh", (language, query, page, page_size, refresh)))
        return {
            "market_root": "/tmp/market",
            "sources": [
                {
                    "url": "https://host/index.json",
                    "builtin": True,
                    "status": "ok",
                    "error": None,
                    "entry_count": 1,
                    "diagnostics": "",
                    "fetched_at": "2026-11-14T00:00:00+00:00",
                }
            ],
            "entries": [
                {
                    "plugin_id": "dsh:demo",
                    "name": "Demo",
                    "versions": ["1.0.0"],
                    "recommended_version": "1.0.0",
                    "installed": False,
                    "runtime": {"status": "missing"},
                }
            ],
            "total": 1,
            "page": page,
            "page_size": page_size,
            "total_pages": 1,
            "query": query,
            "fetched_at": "2026-11-14T00:00:00+00:00",
            "cached": not refresh,
        }

    def dsh_status(
        self,
        *,
        language: str = "zh",
        probe: bool = False,
        agent_manager: Any = None,
    ) -> dict[str, Any]:
        self.calls.append(("dsh_status", (language, probe, agent_manager)))
        return {
            "schema_version": 1,
            "runtime": {
                "enabled": False,
                "ready": False,
                "reason_code": "DSH_RUNTIME_DISABLED",
                "reason": "off",
                "node": {"required": False, "available": None, "version": None},
            },
            "stages": [],
            "sources": {"checked_at": None, "probed": probe, "items": []},
            "installed": [],
            "installed_error": None,
            "tools": {"stage_enabled": False, "report": None, "error": None},
            "llm": {"stage_enabled": False, "installation": None, "error": None},
            "last_failure": None,
            "recent_failures": [],
        }

    def add_dsh_source(self, url: str) -> list[str]:
        self.calls.append(("add", url))
        if url == "bad":
            raise OctopError(
                ErrorCode.PLUGIN_MARKET_SOURCE_INVALID,
                "bad url",
                details={"url": url},
            )
        return [url]

    def remove_dsh_source(self, url: str) -> list[str]:
        self.calls.append(("remove", url))
        return []

    def install_dsh_market(
        self, plugin_id: str, *, version: str | None = None, force: bool = False,
        language: str = "zh",
    ) -> dict[str, Any]:
        self.calls.append(("install", (plugin_id, version, force)))
        return {
            "plugin_id": plugin_id,
            "version": version or "1.0.0",
            "install_dir": "/tmp/market/dsh/demo/1.0.0",
            "status": "installed_not_ready",
            "runtime": {
                "status": "not_loaded",
                "error_code": "TOOL_RUNTIME_PLUGIN_NOT_LOADED",
                "reason": "缺少 npm 依赖闭包：left-pad",
            },
        }

    def upgrade_dsh_market(
        self, plugin_id: str, *, version: str | None = None,
        allow_capability_expansion: bool = False, language: str = "zh",
    ) -> dict[str, Any]:
        self.calls.append(("upgrade", (plugin_id, version, allow_capability_expansion)))
        return {
            "plugin_id": plugin_id,
            "previous_version": "0.9.0",
            "version": version or "1.0.0",
            "install_dir": "/tmp/market/dsh/demo/1.0.0",
            "status": "upgraded",
            "runtime": {"status": "visible"},
        }

    def install_bundled(self, plugin_id: str, *, force: bool = False):
        from types import SimpleNamespace

        self.calls.append(("install_bundled", (plugin_id, force)))
        return SimpleNamespace(
            manifest=SimpleNamespace(
                id=plugin_id, version="0.1.0", name="实时任务进度", kind="tool"
            )
        )

    def dsh_install_progress(self, plugin_id: str) -> dict[str, Any]:
        self.calls.append(("progress", plugin_id))
        return {
            "plugin_id": plugin_id,
            "progress": {
                "plugin_id": plugin_id,
                "phase": "dependencies",
                "status": "running",
                "progress": 0.6,
                "message": "正在安装依赖闭包（pnpm/npm）",
                "detail": "npm http fetch GET 200",
            },
        }

    def uninstall_dsh_market(
        self, plugin_id: str, *, version: str | None = None
    ) -> dict[str, Any]:
        self.calls.append(("uninstall", (plugin_id, version)))
        return {
            "plugin_id": plugin_id,
            "version": version or "1.0.0",
            "install_dir": "/tmp/market/dsh/demo",
            "cleaned": True,
            "remaining_versions": [],
        }


class FakeServer:
    _started = True
    app_runtime = None
    services = None

    def __init__(self) -> None:
        self.plugin_manager = FakeManager()


@pytest.fixture
def client() -> TestClient:
    server = FakeServer()
    app = FastAPI()
    app.include_router(plugins_router.router)
    app.state.octop_server = server

    @app.exception_handler(OctopError)
    async def _octop_error(_request, exc: OctopError) -> JSONResponse:
        return JSONResponse(exc.to_envelope(), status_code=exc.status)

    app.dependency_overrides[current_user] = lambda: object()
    return TestClient(app)


def test_octop_market_stays_separate(client: TestClient) -> None:
    response = client.get("/plugins/market")
    assert response.status_code == 200
    assert response.json() == [{"id": "portal-only", "language": "zh"}]

    dsh = client.get("/plugins/market/dsh")
    assert dsh.status_code == 200
    assert dsh.json()["entries"][0]["plugin_id"] == "dsh:demo"


def test_ui_capabilities_declare_trust_model(client: TestClient) -> None:
    response = client.get("/plugins/ui/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert body["api_version"] == 1
    assert body["trust"]["sandboxed"] is False
    assert "不是沙箱" in body["trust"]["warning"]
    assert [slot["id"] for slot in body["slots"]] == [
        "home.sidebar",
        "chat.messages.top",
        "conversation.view",
        "conversation.input.left",
        "conversation.input.overlay",
        "settings.section",
    ]
    services = {row["id"]: row for row in body["host_services"]}
    assert services["jobs"]["supported"] is False
    assert services["jobs"]["reason_code"] == "HOST_JOBS_UNSUPPORTED"
    assert services["webServer.tapIndex"]["supported"] is False
    assert services["agentDefaultModel"]["supported"] is True
    assert body["data_domains"] == [
        "runtime.activity",
        "sessions.running",
        "plugins.installed",
        "host.context",
    ]
    assert body["event_names"] == [
        "session.started",
        "session.updated",
        "session.ended",
    ]


def test_bundled_install_forwards_to_manager(client: TestClient) -> None:
    response = client.post(
        "/plugins/market/bundled/task-progress-monitor/install",
        params={"force": "true"},
    )
    assert response.status_code == 200
    assert response.json()["source"] == "bundled"
    fake = client.app.state.octop_server.plugin_manager
    assert ("install_bundled", ("task-progress-monitor", True)) in fake.calls


def test_dsh_market_forwards_paging_and_search(client: TestClient) -> None:
    response = client.get(
        "/plugins/market/dsh",
        params={"q": "演示", "page": 2, "page_size": 24},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "演示"
    assert body["page"] == 2
    assert body["page_size"] == 24
    assert body["cached"] is True

    refreshed = client.post("/plugins/market/dsh/refresh", params={"q": "demo"})
    assert refreshed.status_code == 200
    assert refreshed.json()["cached"] is False


def test_dsh_status_is_a_dedicated_endpoint(client: TestClient) -> None:
    response = client.get("/plugins/dsh/status")
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == 1
    assert body["runtime"]["reason_code"] == "DSH_RUNTIME_DISABLED"
    assert body["installed"] == []

    probed = client.get("/plugins/dsh/status", params={"probe": "true"})
    assert probed.status_code == 200
    assert probed.json()["sources"]["probed"] is True


def test_install_progress_endpoint_reports_phase(client: TestClient) -> None:
    response = client.get("/plugins/dsh/progress", params={"plugin_id": "dsh:demo"})
    assert response.status_code == 200
    progress = response.json()["progress"]
    assert progress["phase"] == "dependencies"
    assert progress["detail"].startswith("npm http fetch")

    fake = client.app.state.octop_server.plugin_manager
    assert ("progress", "dsh:demo") in fake.calls


def test_source_routes_forward_values(client: TestClient) -> None:
    added = client.post("/plugins/market/dsh/sources", json={"url": "https://host/index.json"})
    assert added.status_code == 200
    assert added.json() == {"sources": ["https://host/index.json"]}

    removed = client.request(
        "DELETE",
        "/plugins/market/dsh/sources",
        params={"url": "https://host/index.json"},
    )
    assert removed.status_code == 200
    assert removed.json() == {"sources": []}


def test_invalid_source_keeps_error_code(client: TestClient) -> None:
    response = client.post("/plugins/market/dsh/sources", json={"url": "bad"})
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "PLUGIN_MARKET_SOURCE_INVALID"
    assert error["details"]["url"] == "bad"


def test_install_upgrade_uninstall_forward_parameters(client: TestClient) -> None:
    installed = client.post(
        "/plugins/market/dsh/install",
        params={"plugin_id": "dsh:demo", "version": "1.0.0", "force": "true"},
    )
    assert installed.status_code == 200
    assert installed.json()["status"] == "installed_not_ready"
    assert installed.json()["runtime"]["error_code"] == "TOOL_RUNTIME_PLUGIN_NOT_LOADED"

    upgraded = client.post(
        "/plugins/market/dsh/upgrade",
        params={"plugin_id": "dsh:demo", "version": "1.1.0"},
    )
    assert upgraded.status_code == 200
    assert upgraded.json()["previous_version"] == "0.9.0"

    removed = client.request(
        "DELETE",
        "/plugins/market/dsh/plugin",
        params={"plugin_id": "dsh:demo", "version": "1.1.0"},
    )
    assert removed.status_code == 200
    assert removed.json()["cleaned"] is True
