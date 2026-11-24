"""Offline fixtures for the unified plugin market tests."""

from __future__ import annotations

import io
import json
import tarfile
import zipfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "plugin_market"


def make_zip(files: Mapping[str, str], *, root: str = "") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in files.items():
            archive.writestr(f"{root}/{name}" if root else name, text.encode("utf-8"))
    return buffer.getvalue()


def make_tgz(files: Mapping[str, str], *, root: str = "package") -> bytes:
    buffer = io.BytesIO()
    payload = {name: text.encode("utf-8") for name, text in files.items()}
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, data in payload.items():
            info = tarfile.TarInfo(f"{root}/{name}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def octop_package(
    plugin_id: str = "weather",
    version: str = "1.2.0",
    *,
    entry: str = "main.py",
    config_schema: Mapping[str, str] | None = None,
    permissions: Sequence[str] | None = None,
    extra: Mapping[str, str] | None = None,
) -> bytes:
    manifest = (
        f"id: {plugin_id}\n"
        f"version: {version}\n"
        "name: Weather\n"
        "description: Look up city weather\n"
        "kind: tool\n"
        f"entry: {entry}\n"
    )
    if config_schema:
        manifest += "config_schema:\n"
        for key, type_name in config_schema.items():
            manifest += f"  {key}: {{type: {type_name}}}\n"
    if permissions:
        manifest += "permissions:\n"
        for name in permissions:
            manifest += f"  - {name}\n"
    files = {
        "plugin.yaml": manifest,
        entry: "def main() -> str:\n    return 'ok'\n",
    }
    files.update(extra or {})
    return make_zip(files)


def dsh_package(
    name: str = "dsh-plugin-weather",
    version: str = "1.0.0",
    *,
    main: str = "index.js",
    config_schema: Mapping[str, str] | None = None,
    capabilities: Sequence[str] | None = None,
) -> str:
    package: dict[str, Any] = {
        "name": name,
        "version": version,
        "main": main,
        "dsh": {"bundle": {"name": name}},
    }
    if config_schema:
        package["config_schema"] = {
            key: {"type": type_name} for key, type_name in config_schema.items()
        }
    if capabilities:
        package["dsh"]["bundle"]["capabilities"] = list(capabilities)
    return json.dumps(package)


def dsh_tarball(
    name: str = "dsh-plugin-weather",
    version: str = "1.0.0",
    *,
    config_schema: Mapping[str, str] | None = None,
    capabilities: Sequence[str] | None = None,
) -> bytes:
    package_json = dsh_package(
        name, version, config_schema=config_schema, capabilities=capabilities
    )
    return make_tgz({"package.json": package_json, "index.js": "export const name = 'x'\n"})


def dsh_git_zip(
    name: str = "@example/dsh-git-plugin",
    version: str = "0.3.0",
    *,
    commit: str = "0123456789abcdef0123456789abcdef01234567",
    path: str = "packages/plugin",
) -> bytes:
    return make_zip(
        {
            "README.md": "fixture repo\n",
            f"{path}/package.json": dsh_package(name, version),
            f"{path}/index.js": "export const name = 'x'\n",
        },
        root=f"monorepo-{commit}",
    )


@pytest.fixture
def portal_items() -> list[dict[str, Any]]:
    return json.loads((FIXTURES / "octop_portal.json").read_text(encoding="utf-8"))


@pytest.fixture
def dsh_index_document() -> dict[str, Any]:
    return json.loads((FIXTURES / "dsh_index.json").read_text(encoding="utf-8"))


@pytest.fixture
def write_index(tmp_path: Path) -> Callable[[dict[str, Any]], Path]:
    def write(document: dict[str, Any]) -> Path:
        path = tmp_path / "dsh-index.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    return write


@pytest.fixture
def transport() -> Callable[[str], bytes]:
    def missing(url: str) -> bytes:
        raise AssertionError(f"unexpected network access: {url}")

    return missing
