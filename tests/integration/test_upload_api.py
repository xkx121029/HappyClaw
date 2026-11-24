"""Integration tests for dashboard chat attachments in agent workspace."""

from __future__ import annotations

import re
from typing import Any


async def test_upload_and_workspace_download(env_with_agent: Any) -> None:
    client, _srv, auth, aid = env_with_agent
    files = {"file": ("note.txt", b"hello attachment", "text/plain")}
    r = await client.post(f"/api/agents/{aid}/upload", files=files, headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["path"] == body["workspace_path"]
    assert body["access_url"].startswith(f"/api/agents/{aid}/workspace/download")
    assert body["filename"] == "note.txt"
    assert body["media_type"] == "text/plain"
    assert body["workspace_path"].endswith(".txt")
    assert body["workspace_path"].startswith("inbound/")
    assert re.search(r"inbound/\d{10,}_note\.txt$", body["workspace_path"])
    assert "file_id" not in body
    assert "legacy_url" not in body

    r2 = await client.get(body["access_url"], headers=auth)
    assert r2.status_code == 200, r2.text
    assert r2.content == b"hello attachment"


async def test_upload_pdf_workspace_path(env_with_agent: Any) -> None:
    client, _srv, auth, aid = env_with_agent
    files = {"file": ("report.pdf", b"%PDF-1.4", "application/pdf")}
    r = await client.post(f"/api/agents/{aid}/upload", files=files, headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["workspace_path"].endswith(".pdf")
    assert body["filename"] == "report.pdf"

    r2 = await client.get(body["access_url"], headers=auth)
    assert r2.status_code == 200, r2.text
    assert r2.content == b"%PDF-1.4"


async def test_upload_requires_auth(env: Any) -> None:
    """Uploads need no bearer: the request resolves the local owner."""
    client, _srv, auth = env
    provider = await client.post(
        "/api/admin/providers",
        headers=auth,
        json={
            "name": "upload-openai",
            "kind": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-x",
            "models": [{"id": "gpt-4o", "name": "GPT-4o", "enabled": True, "input": ["text"]}],
        },
    )
    assert provider.status_code == 201, provider.text
    created = await client.post(
        "/api/agents",
        headers=auth,
        json={"name": "upload-bot", "default_model": "openai:gpt-4o"},
    )
    assert created.status_code == 201, created.text
    aid = created.json()["agent_id"]

    files = {"file": ("note.txt", b"x", "text/plain")}
    r = await client.post(f"/api/agents/{aid}/upload", files=files)
    assert r.status_code == 200, r.text
