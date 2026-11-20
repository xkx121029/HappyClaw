"""Tests for the ``present_file`` chat-dock tool."""

from __future__ import annotations

import json
from pathlib import Path

from deepagents.backends import FilesystemBackend
from octop_harness.backends.workspace import BackendWorkspace

from octop.infra.agents.workspace.present_file import build_present_file_tool


def _tool(root: Path):
    workspace = BackendWorkspace(
        FilesystemBackend(root_dir=str(root), virtual_mode=True), root
    )
    return build_present_file_tool(workspace)


def _result(tool, path: str) -> dict:
    return json.loads(tool.invoke({"path": path}))


def test_present_file_returns_workspace_relative_path(tmp_path: Path) -> None:
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "summary.md").write_text("# hi", encoding="utf-8")
    tool = _tool(tmp_path)

    assert _result(tool, "notes/summary.md") == {
        "status": "ok",
        "path": "notes/summary.md",
    }


def test_present_file_missing_file(tmp_path: Path) -> None:
    tool = _tool(tmp_path)

    result = _result(tool, "missing.html")
    assert result["status"] == "error"
    assert "does not exist" in result["error"]


def test_present_file_rejects_paths_outside_workspace(tmp_path: Path) -> None:
    (tmp_path / "secret.md").write_text("secret", encoding="utf-8")
    root = tmp_path / "ws"
    root.mkdir()
    tool = _tool(root)

    result = _result(tool, "../secret.md")
    assert result["status"] == "error"
    assert "path" not in result
