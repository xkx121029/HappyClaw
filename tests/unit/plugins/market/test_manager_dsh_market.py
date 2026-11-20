"""End-to-end manager tests for DSH sources over a local HTTP fixture."""

from __future__ import annotations

import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator

import pytest

from octop.infra.agents.plugins.manager import PluginManager
from octop.infra.plugins.market import DshSource
from octop.infra.plugins.market.errors import IndexFormatError
from octop.infra.plugins.profile.market_source import MarketInstallSource

from .conftest import dsh_package, make_tgz

_PATCH = "- insert:\n    - id: fixture\n      name: dsh-fixture-tool\n"


def _bundle(name: str, version: str, **kwargs: Any) -> bytes:
    """A real DSH bundle: package.json + cordis.patch.yml + entry."""

    return make_tgz(
        {
            "package.json": dsh_package(
                name, version, capabilities=["tool"], **kwargs
            ),
            "index.js": "export const name = 'fixture'\n",
            "cordis.patch.yml": _PATCH,
        }
    )

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
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:  # noqa: D401 - silence tests
        return


@pytest.fixture
def http_base() -> Iterator[tuple[str, dict[str, bytes]]]:
    routes: dict[str, bytes] = {}
    handler = type("Handler", (_Handler,), {"routes": routes})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", routes
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PluginManager:
    monkeypatch.setenv("OCTOP_DSH_MARKET_ROOT", str(tmp_path / "market"))
    monkeypatch.delenv("OCTOP_DSH_EXEC_PLUGINS", raising=False)
    monkeypatch.delenv("OCTOP_DSH_NPM_REGISTRY", raising=False)
    config = tmp_path / "config.json"
    # Explicit empty list: these tests exercise user sources only and must
    # never reach the built-in public indexes.
    config.write_text(
        json.dumps({"plugin_market": {"dsh_sources": []}}), encoding="utf-8"
    )
    return PluginManager(
        plugins_dir=tmp_path / "plugins",
        config_path=config,
    )


def _publish_fixture_index(
    base: str, routes: dict[str, bytes]
) -> dict[str, Any]:
    document = json.loads((FIXTURES / "index.json").read_text(encoding="utf-8"))
    routes["/index.json"] = json.dumps(document).encode("utf-8")
    routes["/dsh-plugin-demo/-/dsh-plugin-demo-1.0.0.tgz"] = _bundle(
        "dsh-plugin-demo", "1.0.0"
    )
    routes["/dsh-plugin-demo/-/dsh-plugin-demo-1.1.0.tgz"] = _bundle(
        "dsh-plugin-demo", "1.1.0"
    )
    routes["/@demo/scoped-plugin/-/scoped-plugin-0.1.0.tgz"] = _bundle(
        "@demo/scoped-plugin", "0.1.0"
    )
    return document


def test_list_separates_sources_and_reports_runtime(
    manager: PluginManager,
    http_base: tuple[str, dict[str, bytes]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base, routes = http_base
    _publish_fixture_index(base, routes)
    monkeypatch.setenv("OCTOP_DSH_NPM_REGISTRY", base)
    manager.add_dsh_source(f"{base}/index.json")

    view = manager.list_dsh_market()

    assert view["market_root"].endswith("market")
    assert len(view["sources"]) == 1
    assert view["sources"][0]["status"] == "ok"
    assert view["sources"][0]["entry_count"] == 2
    assert [row["plugin_id"] for row in view["entries"]] == [
        "dsh:demo__scoped-plugin",
        "dsh:dsh-plugin-demo",
    ]
    demo = next(row for row in view["entries"] if row["plugin_id"] == "dsh:dsh-plugin-demo")
    assert demo["recommended_version"] == "1.1.0"
    assert demo["versions"] == ["1.1.0", "1.0.0"]
    assert demo["icon"] == f"{base}/icon.png"
    assert demo["installed"] is False
    assert demo["runtime"]["status"] == "missing"


def test_install_upgrade_uninstall_and_cleanup(
    manager: PluginManager,
    http_base: tuple[str, dict[str, bytes]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base, routes = http_base
    _publish_fixture_index(base, routes)
    monkeypatch.setenv("OCTOP_DSH_NPM_REGISTRY", base)
    manager.add_dsh_source(f"{base}/index.json")

    installed = manager.install_dsh_market("dsh:dsh-plugin-demo", version="1.0.0")
    assert installed["version"] == "1.0.0"
    # The fixture declares the "tool" capability, so a fresh install is visible
    # to agents without any host exec grant.
    assert installed["status"] == "installed"
    assert installed["runtime"]["status"] == "visible"
    assert installed["runtime"]["visible_to_agents"] is True
    assert Path(installed["install_dir"]).is_dir()

    view = manager.list_dsh_market()
    demo = next(row for row in view["entries"] if row["plugin_id"] == "dsh:dsh-plugin-demo")
    assert demo["installed"] is True
    assert demo["installed_version"] == "1.0.0"
    assert demo["update_available"] is True
    assert demo["runtime"]["status"] == "visible"

    upgraded = manager.upgrade_dsh_market("dsh:dsh-plugin-demo", version="1.1.0")
    assert upgraded["previous_version"] == "1.0.0"
    assert upgraded["version"] == "1.1.0"
    assert upgraded["status"] == "upgraded"

    removed = manager.uninstall_dsh_market("dsh:dsh-plugin-demo")
    assert removed["cleaned"] is False
    assert removed["remaining_versions"] == ["1.0.0"]

    final = manager.uninstall_dsh_market("dsh:dsh-plugin-demo", version="1.0.0")
    assert final["cleaned"] is True
    assert not Path(final["install_dir"]).exists()
    view = manager.list_dsh_market()
    demo = next(row for row in view["entries"] if row["plugin_id"] == "dsh:dsh-plugin-demo")
    assert demo["installed"] is False


def test_scoped_package_is_visible_and_legacy_ledger_still_reads(
    manager: PluginManager,
    http_base: tuple[str, dict[str, bytes]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base, routes = http_base
    _publish_fixture_index(base, routes)
    monkeypatch.setenv("OCTOP_DSH_NPM_REGISTRY", base)
    manager.add_dsh_source(f"{base}/index.json")

    # Catalog id ``demo__scoped-plugin`` must stay visible even though the
    # package manifest is ``@demo/scoped-plugin``.
    installed = manager.install_dsh_market("dsh:demo__scoped-plugin", version="0.1.0")
    assert installed["status"] == "installed"
    assert installed["runtime"]["status"] == "visible"
    assert installed["runtime"]["visible_to_agents"] is True

    # A ledger written by an older build keeps its own id and stays readable.
    root = Path(installed["install_dir"]).parents[2]
    ledger = root / "dsh" / "demo__scoped-plugin" / "index.json"
    data = json.loads(ledger.read_text(encoding="utf-8"))
    data["plugin_id"] = "dsh:scoped-plugin"
    ledger.write_text(json.dumps(data), encoding="utf-8")
    slots = MarketInstallSource(root).installed_slots()
    assert "dsh:scoped-plugin" in slots


def test_missing_npm_dependency_closure_is_reported(
    manager: PluginManager,
    http_base: tuple[str, dict[str, bytes]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base, routes = http_base
    package = json.loads(dsh_package("dsh-plugin-needs-dep", "1.0.0"))
    package["dependencies"] = {"left-pad": "1.0.0"}
    routes["/needs/index.json"] = json.dumps(
        {
            "format": 1,
            "title": {"en": "needs dep"},
            "plugins": [
                {
                    "name": "dsh-plugin-needs-dep",
                    "title": {"en": "Needs dependency"},
                    "versions": [
                        {
                            "version": "1.0.0",
                            "publishTimestamp": 1788000000,
                            "source": {"type": "npm"},
                        }
                    ],
                }
            ],
        }
    ).encode("utf-8")
    routes["/dsh-plugin-needs-dep/-/dsh-plugin-needs-dep-1.0.0.tgz"] = make_tgz(
        {
            "package.json": json.dumps(package),
            "index.js": "export const name = 'needs'\n",
        }
    )
    monkeypatch.setenv("OCTOP_DSH_NPM_REGISTRY", base)
    manager.add_dsh_source(f"{base}/needs/index.json")

    result = manager.install_dsh_market("dsh:dsh-plugin-needs-dep")

    # The fixture registry does not serve ``left-pad``: the tarball installed
    # but the dependency closure could not, which is its own outcome.
    assert result["status"] == "installed_dependency_failed"
    assert result["dependency"]["status"] == "failed"
    assert result["dependency"]["code"] in {
        "DSH_DEP_RESOLVE",
        "DSH_DEP_NETWORK",
        "DSH_DEP_INSTALL_FAILED",
    }
    assert "left-pad" in result["dependency"]["missing"]
    assert result["runtime"]["status"] == "not_loaded"
    assert result["runtime"]["error_code"] == "DSH_DEP_MISSING"
    assert "left-pad" in result["runtime"]["reason"]

    progress = manager.dsh_install_progress("dsh:dsh-plugin-needs-dep")["progress"]
    assert progress is not None
    assert progress["phase"] == "done"
    assert progress["status"] == "not_ready"
    assert progress["error_code"] == result["dependency"]["code"]


def test_dependency_closure_and_probe_make_bundle_usable(
    manager: PluginManager,
    http_base: tuple[str, dict[str, bytes]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bundle with a real dependency must become usable, not just unpacked."""

    if shutil.which("npm") is None and shutil.which("pnpm") is None:
        pytest.skip("no npm/pnpm on this host")

    base, routes = http_base
    package = json.loads(
        dsh_package("dsh-plugin-with-dep", "1.0.0", capabilities=["tool"])
    )
    package["type"] = "module"
    package["main"] = "index.js"
    package["dependencies"] = {"left-pad": "1.0.0"}
    routes["/needs/index.json"] = json.dumps(
        {
            "format": 1,
            "title": {"en": "needs dep"},
            "plugins": [
                {
                    "name": "dsh-plugin-with-dep",
                    "title": {"en": "With dependency"},
                    "versions": [
                        {
                            "version": "1.0.0",
                            "publishTimestamp": 1788000000,
                            "source": {"type": "npm"},
                        }
                    ],
                }
            ],
        }
    ).encode("utf-8")
    routes["/dsh-plugin-with-dep/-/dsh-plugin-with-dep-1.0.0.tgz"] = make_tgz(
        {
            "package.json": json.dumps(package),
            "index.js": "import leftPad from 'left-pad'\nexport const name = 'with-dep'\nexport const pad = leftPad\n",
            "cordis.patch.yml": _PATCH,
        }
    )
    # Minimal npm registry metadata so the closure can really be installed.
    routes["/left-pad"] = json.dumps(
        {
            "name": "left-pad",
            "dist-tags": {"latest": "1.0.0"},
            "versions": {
                "1.0.0": {
                    "name": "left-pad",
                    "version": "1.0.0",
                    "main": "index.js",
                    "dist": {"tarball": f"{base}/left-pad/-/left-pad-1.0.0.tgz"},
                }
            },
        }
    ).encode("utf-8")
    routes["/left-pad/-/left-pad-1.0.0.tgz"] = make_tgz(
        {
            "package.json": json.dumps(
                {"name": "left-pad", "version": "1.0.0", "main": "index.js"}
            ),
            "index.js": "module.exports = (value) => value\n",
        }
    )
    monkeypatch.setenv("OCTOP_DSH_NPM_REGISTRY", base)
    manager.add_dsh_source(f"{base}/needs/index.json")

    result = manager.install_dsh_market("dsh:dsh-plugin-with-dep")

    assert result["dependency"]["status"] == "installed"
    assert result["dependency"]["missing"] == []
    assert result["status"] == "installed"
    assert result["runtime"]["status"] == "visible"
    assert result["runtime"]["probe"]["attempted"] is True
    assert result["runtime"]["probe"]["ok"] is True
    assert "实测加载成功" in result["runtime"]["reason"]
    assert (
        Path(result["install_dir"]) / "node_modules" / "left-pad" / "index.js"
    ).is_file()


def test_install_survives_unreachable_mirror(
    manager: PluginManager,
    http_base: tuple[str, dict[str, bytes]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One dead mirror must not turn install into "plugin is not listed"."""

    base, routes = http_base
    _publish_fixture_index(base, routes)
    monkeypatch.setenv("OCTOP_DSH_NPM_REGISTRY", base)
    manager.add_dsh_source(f"{base}/index.json")
    # Port 9 refuses immediately, so the dead source costs no wait budget.
    manager.add_dsh_source("http://127.0.0.1:9/index.json")

    result = manager.install_dsh_market("dsh:dsh-plugin-demo", version="1.0.0")

    assert result["status"].startswith("installed")
    assert Path(result["install_dir"]).is_dir()


def test_unreachable_source_serves_cached_index_as_stale(
    manager: PluginManager,
    http_base: tuple[str, dict[str, bytes]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A source that goes slow keeps its rows from the last successful read."""

    base, routes = http_base
    _publish_fixture_index(base, routes)
    monkeypatch.setenv("OCTOP_DSH_NPM_REGISTRY", base)
    manager.add_dsh_source(f"{base}/index.json")

    first = manager.list_dsh_market()
    assert first["sources"][0]["status"] == "ok"
    assert first["total"] == 2

    routes.clear()  # the source now answers 404 instead of an index
    manager._invalidate_dsh_market_cache()
    second = manager.list_dsh_market()

    source = second["sources"][0]
    assert source["status"] == "stale"
    assert source["stale"] is True
    assert source["entry_count"] == 2
    assert source["error"]["code"]
    assert source["budget_seconds"] == 20.0
    assert second["total"] == 2


def test_missing_entry_and_engine_are_reported(
    manager: PluginManager,
    http_base: tuple[str, dict[str, bytes]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base, routes = http_base
    _publish_fixture_index(base, routes)
    monkeypatch.setenv("OCTOP_DSH_NPM_REGISTRY", base)
    manager.add_dsh_source(f"{base}/index.json")
    manager.install_dsh_market("dsh:dsh-plugin-demo", version="1.0.0")

    market_root = manager.dsh_market_root()
    ledger = json.loads(
        (market_root / "dsh" / "dsh-plugin-demo" / "index.json").read_text(encoding="utf-8")
    )
    slot = market_root / "dsh" / "dsh-plugin-demo" / ledger["current"]["slot"]
    (slot / "index.js").unlink()

    broken = manager._dsh_runtime_status("dsh:dsh-plugin-demo")
    assert broken["status"] == "not_loaded"
    assert broken["error_code"] == "TOOL_RUNTIME_ENTRY_MISSING"

    # Node engine constraint is checked against the host version.
    package = json.loads(dsh_package("dsh-plugin-engine", "1.0.0"))
    package["engines"] = {"node": ">=99.0.0"}
    routes["/engine.json"] = json.dumps(
        {
            "format": 1,
            "title": {"en": "engine"},
            "plugins": [
                {
                    "name": "dsh-plugin-engine",
                    "title": {"en": "Engine"},
                    "versions": [
                        {
                            "version": "1.0.0",
                            "publishTimestamp": 1788000000,
                            "source": {"type": "npm"},
                        }
                    ],
                }
            ],
        }
    ).encode("utf-8")
    routes["/dsh-plugin-engine/-/dsh-plugin-engine-1.0.0.tgz"] = make_tgz(
        {
            "package.json": json.dumps(package),
            "index.js": "export const name = 'engine'\n",
        }
    )
    manager.add_dsh_source(f"{base}/engine.json")
    result = manager.install_dsh_market("dsh:dsh-plugin-engine")
    assert result["runtime"]["error_code"] == "TOOL_RUNTIME_ENGINE_UNSATISFIED"


def test_bad_indexes_surface_code_and_path(
    manager: PluginManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCTOP_DSH_NPM_REGISTRY", "https://registry.npmjs.org")
    manager.add_dsh_source(str(FIXTURES / "index-bad-format.json"))
    manager.add_dsh_source(str(FIXTURES / "index-bad-row.json"))
    manager.add_dsh_source(str(FIXTURES / "index-bad-icon.json"))

    view = manager.list_dsh_market()

    assert [source["status"] for source in view["sources"]] == ["error"] * 3
    assert view["entries"] == []
    assert view["sources"][0]["builtin"] is False
    format_error = view["sources"][0]["error"]
    assert format_error["code"] == "PLUGIN_MANIFEST_INVALID"
    assert format_error["details"]["path"] == "$.format"
    assert "version must be an exact semver" in view["sources"][1]["error"]["message"]
    assert "$.plugins[0].versions[0].version" in view["sources"][1]["error"]["message"]
    assert "icon" in view["sources"][2]["error"]["message"].lower()


def test_market_search_and_paging(
    manager: PluginManager,
    http_base: tuple[str, dict[str, bytes]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base, routes = http_base
    _publish_fixture_index(base, routes)
    monkeypatch.setenv("OCTOP_DSH_NPM_REGISTRY", base)
    manager.add_dsh_source(f"{base}/index.json")

    first = manager.list_dsh_market(page=1, page_size=1)
    assert first["total"] == 2
    assert first["total_pages"] == 2
    assert len(first["entries"]) == 1
    assert first["cached"] is False

    second = manager.list_dsh_market(page=2, page_size=1)
    assert second["cached"] is True
    assert second["entries"][0]["plugin_id"] != first["entries"][0]["plugin_id"]

    # Name and description are both searched (the fixture uses Chinese titles).
    hits = manager.list_dsh_market(query="作用域")
    assert hits["total"] == 1
    assert hits["entries"][0]["plugin_id"] == "dsh:demo__scoped-plugin"
    assert hits["query"] == "作用域"

    assert manager.list_dsh_market(query="no-such-plugin")["total"] == 0

    # refresh=true re-reads the source instead of reusing the snapshot.
    refreshed = manager.list_dsh_market(refresh=True)
    assert refreshed["cached"] is False
    assert refreshed["total"] == 2


def test_unreachable_source_is_isolated(
    manager: PluginManager, http_base: tuple[str, dict[str, bytes]]
) -> None:
    base, routes = http_base
    _publish_fixture_index(base, routes)
    manager.add_dsh_source(f"{base}/index.json")
    manager.add_dsh_source(f"{base}/missing.json")

    view = manager.list_dsh_market()

    statuses = {source["url"]: source["status"] for source in view["sources"]}
    assert statuses[f"{base}/index.json"] == "ok"
    assert statuses[f"{base}/missing.json"] == "error"
    missing = next(
        source for source in view["sources"] if source["url"].endswith("missing.json")
    )
    assert missing["error"]["code"] == "PLUGIN_SOURCE_UNREACHABLE"
    assert len(view["entries"]) == 2


def test_file_index_relative_icon_is_rejected() -> None:
    with pytest.raises(IndexFormatError) as exc:
        DshSource(FIXTURES / "index-bad-icon.json").fetch_index()
    assert exc.value.path == "$.plugins[0].icon"
    assert "icon" in str(exc.value).lower()


