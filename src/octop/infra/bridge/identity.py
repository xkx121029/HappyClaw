"""Host labels, inbound display names and peer agent summaries."""

from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urljoin, urlparse

from octop.infra.bridge.icons import rewrite_remote_icon_url
from octop.infra.bridge.ids import (
    format_bridge_agent_id,
)
from octop.infra.db.repos.bridge_connections import BridgeConnectionRow


def _is_inbound(row: BridgeConnectionRow) -> bool:
    """Peer-dialed reverse rows store no password and cannot redial."""
    return not bool(row.credential_blob)


def _host_label(raw: str) -> str:
    """Return a host suitable as a peer label, or empty for loopback / blank."""
    text = (raw or "").strip().strip("[]")
    if not text or text.lower() == "unknown":
        return ""
    if text.count(":") == 1 and "." in text:
        text = text.split(":", 1)[0].strip()
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        if text.lower() == "localhost":
            return ""
        return text[:64]
    if addr.is_loopback or addr.is_unspecified:
        return ""
    return str(addr)


def _advertise_host_label(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        host = urlparse(raw).hostname or ""
    except ValueError:
        return ""
    return _host_label(host)


def observe_ws_client_host(websocket: Any) -> str:
    """Peer address of an inbound Bridge socket.

    Trusts ``X-Forwarded-For`` only when the direct peer is loopback (a local
    reverse proxy). The right-most hop is the one that proxy actually saw.
    """
    client = getattr(websocket, "client", None)
    host = ""
    if client is not None:
        raw_host = getattr(client, "host", None)
        if isinstance(raw_host, str) and raw_host.strip():
            host = raw_host.strip()
        elif isinstance(client, (tuple, list)) and client:
            host = str(client[0]).strip()
    headers = getattr(websocket, "headers", None)
    forwarded = ""
    if headers is not None:
        raw_fwd = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For")
        if isinstance(raw_fwd, str) and raw_fwd.strip():
            hops = [part.strip() for part in raw_fwd.split(",") if part.strip()]
            forwarded = hops[-1] if hops else ""
    try:
        direct = ipaddress.ip_address(host) if host else None
    except ValueError:
        direct = None
    if direct is not None and direct.is_loopback and forwarded:
        return _host_label(forwarded) or _host_label(host)
    return _host_label(host)


def inbound_default_display_name(
    *,
    connection_id: str,
    client_host: str = "",
    advertise_base_url: str = "",
    peer_username: str = "",
    existing_name: str | None = None,
) -> str:
    """Local label for a reverse row.

    A name already stored on this side always wins, so renaming here does not
    follow the initiator and an initiator rename does not overwrite this side.
    New rows default to the observed client IP (or a non-loopback advertised
    host), which the owner can edit afterwards.
    """
    existing = (existing_name or "").strip()
    if existing:
        return existing[:64]
    for candidate in (
        _host_label(client_host),
        _advertise_host_label(advertise_base_url),
        (peer_username or "").strip(),
        connection_id,
    ):
        if candidate:
            return candidate[:64]
    return "Remote"


def _absolute_peer_url(base_url: str, maybe_path: str | None) -> str | None:
    raw = (maybe_path or "").strip()
    if not raw:
        return None
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    root = base_url.rstrip("/") + "/"
    return urljoin(root, raw.lstrip("/"))


def _probe_agent_summary(
    item: dict[str, Any],
    *,
    peer_base_url: str,
    connection_id: str | None = None,
) -> dict[str, Any]:
    remote_id = str(item.get("agent_id") or item.get("id") or "").strip()
    raw_icon = str(item.get("icon_url") or "").strip()
    if not raw_icon:
        legacy = str(item.get("icon") or "").strip()
        if legacy.startswith("/") or legacy.startswith("http://") or legacy.startswith("https://"):
            raw_icon = legacy
    bridge_id = (
        format_bridge_agent_id(connection_id, remote_id) if connection_id and remote_id else None
    )
    _ = peer_base_url  # probe never returns peer-absolute URLs (browser cannot auth to them)
    icon_name = item.get("icon_name")
    color = item.get("color")
    return {
        "agent_id": remote_id,
        "name": str(item.get("name") or remote_id or "").strip() or remote_id,
        "description": str(item.get("description") or "").strip() or None,
        "icon_url": rewrite_remote_icon_url(
            raw_icon or None,
            remote_agent_id=remote_id,
            bridge_agent_id=bridge_id,
        ),
        "icon_name": str(icon_name).strip() or None if isinstance(icon_name, str) else None,
        "color": str(color).strip() or None if isinstance(color, str) else None,
        "state": item.get("state"),
        "kind": item.get("kind") or "expert",
    }
