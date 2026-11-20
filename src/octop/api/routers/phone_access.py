"""Phone access: LAN binding, access token, and the URL to type on a phone.

Everything here edits ``config.json``. The values only take effect after a
restart (uvicorn binds the socket and the credential middleware is installed
at boot), so every mutating response reports ``restart_required`` and the
settings UI shows an explicit restart prompt.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from octop.api.deps import get_server, require_permission
from octop.config import load_config

router = APIRouter()

LAN_BIND_HOST = "0.0.0.0"
LOOPBACK_BIND_HOST = "127.0.0.1"


class PhoneAccessUpdate(BaseModel):
    """Toggle LAN exposure; optionally rotate the credential."""

    enabled: bool | None = None
    regenerate_token: bool = False


def _read_raw(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_raw(path: Path, data: dict[str, Any]) -> None:
    """Atomic write so a crash never leaves a half-written config."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".config-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _lan_addresses() -> list[str]:
    addresses: set[str] = set()
    # No packets are sent; this just asks the routing table for the source IP.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            addresses.add(probe.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addresses.add(str(info[4][0]))
    except OSError:
        pass
    return sorted(
        ip
        for ip in addresses
        if ip and not ip.startswith("127.") and not ip.startswith("169.254.")
    )


def _urls(bind_host: str, port: int) -> list[str]:
    if bind_host in {LOOPBACK_BIND_HOST, "localhost", "::1"}:
        return [f"http://127.0.0.1:{port}"]
    return [f"http://{ip}:{port}" for ip in _lan_addresses()]


def _env_managed() -> bool:
    return bool(os.environ.get("OCTOP_BIND_HOST") or os.environ.get("OCTOP_ACCESS_TOKEN"))


def _status(server: Any, config_path: Path) -> dict[str, Any]:
    cfg = load_config(config_path)
    running = getattr(server, "config", None)
    desired_token = (cfg.access_token or "").strip()
    running_token = (getattr(running, "access_token", None) or "").strip()
    running_host = getattr(running, "bind_host", None)
    restart_required = bool(
        running is None or running_host != cfg.bind_host or running_token != desired_token
    )
    return {
        "enabled": cfg.bind_host not in {LOOPBACK_BIND_HOST, "localhost", "::1"},
        "bind_host": cfg.bind_host,
        "running_bind_host": running_host,
        "port": cfg.port,
        "token": desired_token,
        "urls": _urls(cfg.bind_host, cfg.port),
        "restart_required": restart_required,
        "managed_by_env": _env_managed(),
        "config_path": str(config_path),
    }


@router.get("", summary="Phone access settings")
async def get_phone_access(
    server: Any = Depends(get_server),
    _: Any = Depends(require_permission("envs")),
) -> dict[str, Any]:
    return _status(server, server.paths.config)


@router.put("", summary="Enable/disable LAN access")
async def update_phone_access(
    body: PhoneAccessUpdate,
    server: Any = Depends(get_server),
    _: Any = Depends(require_permission("envs")),
) -> dict[str, Any]:
    path = server.paths.config
    raw = _read_raw(path)
    if body.enabled is not None:
        raw["bind_host"] = LAN_BIND_HOST if body.enabled else LOOPBACK_BIND_HOST
    token = str(raw.get("access_token") or "").strip()
    if body.regenerate_token or (body.enabled and not token):
        token = secrets.token_urlsafe(24)
        raw["access_token"] = token
    _write_raw(path, raw)
    return _status(server, path)


@router.post("/token", summary="Rotate the access token")
async def rotate_phone_token(
    server: Any = Depends(get_server),
    _: Any = Depends(require_permission("envs")),
) -> dict[str, Any]:
    path = server.paths.config
    raw = _read_raw(path)
    raw["access_token"] = secrets.token_urlsafe(24)
    _write_raw(path, raw)
    return _status(server, path)
