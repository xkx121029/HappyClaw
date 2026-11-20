"""Serve the DSH market fixtures over HTTP for local end-to-end checks.

The DSH project does not publish an official index, so this script is the only
"remote" the UI is pointed at during manual verification: it exposes a format-1
index plus the npm tarballs the index references.

The demo bundles declare ``capabilities: ["tool"]`` so that a plain market
install reaches the agent-visible branch without any host exec grant; the
``needs-dep`` bundle stays undeclared on purpose, it is the failure fixture.
The served index points every npm release at this server's own origin, so the
install works without extra registry environment variables.

    python tests/fixtures/dsh_market/serve.py --port 8765

Then add ``http://127.0.0.1:8765/index.json`` as a DSH source.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import tarfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
_PATCH = "- insert:\n    - id: fixture\n      name: dsh-fixture-tool\n"
# A real Cordis plugin: the S10 runner mounts it and reads back the service it
# publishes, so a granted exec call returns data instead of an empty registry.
_INDEX_JS = """export const name = 'dsh-plugin-demo'
export const inject = []

export const DEMO_SERVICE = 'demo'

export function apply(ctx) {
  const cmdline = ctx.get('cmdlineArgs')
  ctx.provide('demo', {
    greeting: 'hello from dsh-plugin-demo',
    argv: cmdline && typeof cmdline.get === 'function' ? cmdline.get() : [],
    started_at: new Date().toISOString(),
  })
}
"""
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _tgz(
    name: str,
    version: str,
    *,
    dependencies: dict[str, str] | None = None,
    tool_capability: bool = True,
) -> bytes:
    package: dict[str, object] = {
        "name": name,
        "version": version,
        "main": "index.js",
        "dsh": {"bundle": {"name": name}},
        "files": ["index.js", "cordis.patch.yml"],
    }
    if tool_capability:
        package["capabilities"] = ["tool"]
    if dependencies:
        package["dependencies"] = dependencies
    files = {
        "package.json": json.dumps(package),
        "index.js": _INDEX_JS,
        "cordis.patch.yml": _PATCH,
    }
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for filename, text in files.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(f"package/{filename}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _needs_index() -> bytes:
    document = {
        "format": 1,
        "title": {"en": "DSH fixture: missing dependency closure", "zh": "DSH 示例：缺依赖闭包"},
        "plugins": [
            {
                "name": "dsh-plugin-needs-dep",
                "title": {"en": "Needs left-pad", "zh": "缺依赖示例插件"},
                "description": {
                    "en": "Declares a dependency the unpack-only install never fetches.",
                    "zh": "声明了市场安装不会下载的依赖。",
                },
                "versions": [
                    {
                        "version": "1.0.0",
                        "publishTimestamp": 1788000300,
                        "source": {"type": "npm"},
                    }
                ],
            }
        ],
    }
    return json.dumps(document, ensure_ascii=False).encode("utf-8")


def _index(registry: str | None) -> bytes:
    document = json.loads((HERE / "index.json").read_text(encoding="utf-8"))
    if registry:
        for plugin in document["plugins"]:
            for version in plugin["versions"]:
                version["source"]["registry"] = registry
    return json.dumps(document, ensure_ascii=False).encode("utf-8")


def routes(registry: str | None = None) -> dict[str, tuple[str, bytes]]:
    table: dict[str, tuple[str, bytes]] = {
        "/index.json": ("application/json", _index(registry)),
        "/index-needs.json": ("application/json", _needs_index()),
        "/index-bad-format.json": (
            "application/json",
            (HERE / "index-bad-format.json").read_bytes(),
        ),
        "/index-bad-row.json": (
            "application/json",
            (HERE / "index-bad-row.json").read_bytes(),
        ),
        "/index-bad-icon.json": (
            "application/json",
            (HERE / "index-bad-icon.json").read_bytes(),
        ),
        "/icon.png": ("image/png", _PNG),
        "/dsh-plugin-demo/-/dsh-plugin-demo-1.0.0.tgz": (
            "application/octet-stream",
            _tgz("dsh-plugin-demo", "1.0.0"),
        ),
        "/dsh-plugin-demo/-/dsh-plugin-demo-1.1.0.tgz": (
            "application/octet-stream",
            _tgz("dsh-plugin-demo", "1.1.0"),
        ),
        "/@demo/scoped-plugin/-/scoped-plugin-0.1.0.tgz": (
            "application/octet-stream",
            _tgz("@demo/scoped-plugin", "0.1.0"),
        ),
        "/dsh-plugin-needs-dep/-/dsh-plugin-needs-dep-1.0.0.tgz": (
            "application/octet-stream",
            _tgz(
                "dsh-plugin-needs-dep",
                "1.0.0",
                dependencies={"left-pad": "1.0.0"},
                tool_capability=False,
            ),
        ),
    }
    return table


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    table = routes(f"http://{args.host}:{args.port}")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http.server API
            entry = table.get(self.path.split("?")[0])
            if entry is None:
                self.send_response(404)
                self.end_headers()
                return
            content_type, body = entry
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            return

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"DSH fixture index: http://{args.host}:{args.port}/index.json", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
