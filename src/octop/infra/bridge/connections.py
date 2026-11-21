"""Connection rows: lookup, validation, probe and CRUD."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any
from urllib.parse import urljoin

import httpx

from octop.infra.bridge.crypto import decrypt_payload, encrypt_payload
from octop.infra.bridge.identity import (
    _is_inbound,
    _probe_agent_summary,
)
from octop.infra.bridge.manager_base import BridgeManagerBase
from octop.infra.bridge.peer_auth import (
    is_self_peer_url,
    login_peer,
    normalize_peer_base_url,
    peer_identity_key,
)
from octop.infra.db.repos.bridge_connections import BridgeConnectionRow
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.utils.ulid import new_short_id

MAX_CONNECTIONS_PER_USER = 10


class ConnectionRegistryMixin(BridgeManagerBase):
    def list_connections(self, owner_user_id: int) -> list[BridgeConnectionRow]:
        """Owned connections only (management / limits)."""
        return self._repo.list_for_owner(owner_user_id)

    def list_visible_connections(self, user_id: int) -> list[BridgeConnectionRow]:
        """Owned plus shared links the user may use."""
        return self._repo.list_visible(user_id)

    def get(self, connection_id: str) -> BridgeConnectionRow | None:
        return self._repo.get(connection_id)

    def get_owned(self, connection_id: str, owner_user_id: int) -> BridgeConnectionRow:
        row = self._repo.get_for_owner(connection_id, owner_user_id)
        if row is None:
            raise OctopError(ErrorCode.BRIDGE_NOT_FOUND, "bridge connection not found")
        return row

    def get_usable(self, connection_id: str, user_id: int) -> BridgeConnectionRow:
        """Owner, or a user the link was shared with.

        Management (connect, edit, delete) stays on ``get_owned``. Chat and
        read tunnels use this so a shared recipient is not told the link is
        missing.
        """
        row = self._repo.get_visible(connection_id, user_id)
        if row is None:
            raise OctopError(ErrorCode.BRIDGE_NOT_FOUND, "bridge connection not found")
        return row

    def _find_peer_link(
        self,
        owner_user_id: int,
        peer_base_url: str,
        peer_username: str,
        *,
        exclude_connection_id: str | None = None,
    ) -> BridgeConnectionRow | None:
        want = peer_identity_key(peer_base_url, peer_username)
        for row in self._repo.list_for_owner(owner_user_id):
            if exclude_connection_id and row.connection_id == exclude_connection_id:
                continue
            try:
                if peer_identity_key(row.peer_base_url, row.peer_username) == want:
                    return row
            except OctopError:
                continue
        return None

    def _validate_peer_endpoint(
        self,
        owner_user_id: int,
        peer_base_url: str,
        peer_username: str,
        *,
        exclude_connection_id: str | None = None,
    ) -> None:
        if is_self_peer_url(peer_base_url, self._advertise_base_url):
            raise OctopError(
                ErrorCode.BRIDGE_SELF_CONNECT,
                "cannot link this HappyClaw instance to itself",
            )
        other = self._find_peer_link(
            owner_user_id,
            peer_base_url,
            peer_username,
            exclude_connection_id=exclude_connection_id,
        )
        if other is not None:
            raise OctopError(
                ErrorCode.BRIDGE_PEER_ALREADY_LINKED,
                f"already linked as {other.display_name!r}",
                details={"name": other.display_name, "connection_id": other.connection_id},
            )

    def _at_connection_limit(self, owner_user_id: int) -> bool:
        return len(self._repo.list_for_owner(owner_user_id)) >= MAX_CONNECTIONS_PER_USER

    def _allocate_display_name(
        self,
        *,
        owner_user_id: int,
        preferred: str,
        exclude_connection_id: str | None = None,
    ) -> str:
        base = preferred.strip() or "Remote"
        candidate = base
        n = 2
        while True:
            other = self._repo.find_by_display_name(owner_user_id, candidate)
            if other is None or other.connection_id == exclude_connection_id:
                return candidate
            candidate = f"{base} ({n})"
            n += 1

    def connection_public(self, row: BridgeConnectionRow) -> dict[str, Any]:
        live = self._sessions.get(row.connection_id)
        status = row.status
        if live is not None and not live.closed:
            status = "connected"
        elif status == "connected":
            status = "disconnected"
        return {
            "connection_id": row.connection_id,
            "peer_base_url": row.peer_base_url,
            "peer_username": row.peer_username,
            "display_name": row.display_name,
            "notes": row.notes,
            "icon_name": row.icon_name,
            "icon_url": str(getattr(row, "icon_url", "") or "").strip(),
            "shared": bool(getattr(row, "shared", False)),
            "status": status,
            "last_error": row.last_error,
            "last_seen_at": row.last_seen_at,
            "auto_reconnect": bool(row.auto_reconnect),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "has_password": bool(row.credential_blob),
            "inbound": _is_inbound(row),
            "peer_client_host": row.peer_client_host,
        }

    async def probe_peer(
        self,
        *,
        peer_base_url: str,
        peer_username: str,
        password: str,
        connection_id: str | None = None,
    ) -> dict[str, Any]:
        """Login to peer over HTTP and list experts (no connection row / WS)."""
        base = normalize_peer_base_url(peer_base_url)
        username = peer_username.strip()
        if not username or not password:
            raise OctopError(ErrorCode.BRIDGE_AUTH_FAILED, "username and password required")
        login = await login_peer(base_url=base, username=username, password=password)
        token = str(login["access_token"])
        raw_user = login.get("user")
        user_info: dict[str, Any] = raw_user if isinstance(raw_user, dict) else {}
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                resp = await client.get(
                    urljoin(base + "/", "api/agents"),
                    params={"scope": "mine"},
                    headers={"Authorization": f"Bearer {token}"},
                )
        except httpx.HTTPError as exc:
            raise OctopError(
                ErrorCode.BRIDGE_PEER_UNREACHABLE,
                f"peer agents probe failed: {exc}",
            ) from exc
        if resp.status_code >= 400:
            raise OctopError(
                ErrorCode.BRIDGE_AUTH_FAILED,
                f"peer agents HTTP {resp.status_code}: {resp.text[:200]}",
            )
        try:
            data = resp.json()
        except ValueError as exc:
            raise OctopError(
                ErrorCode.BRIDGE_TUNNEL_FAILED,
                "peer agents returned non-JSON",
            ) from exc
        if not isinstance(data, list):
            raise OctopError(ErrorCode.BRIDGE_TUNNEL_FAILED, "peer agents payload invalid")
        agents = [
            _probe_agent_summary(item, peer_base_url=base, connection_id=connection_id)
            for item in data
            if isinstance(item, dict) and str(item.get("agent_id") or item.get("id") or "").strip()
        ]
        return {
            "peer_base_url": base,
            "peer_username": username,
            "peer_display_name": (
                str(user_info.get("display_name") or "").strip()
                or str(user_info.get("username") or username).strip()
            ),
            "agent_count": len(agents),
            "agents": agents,
        }

    def _stored_peer_password(self, row: BridgeConnectionRow) -> str:
        if not row.credential_blob:
            raise OctopError(ErrorCode.BRIDGE_AUTH_FAILED, "password required")
        secret = str(decrypt_payload(self._secrets, row.credential_blob).get("password") or "")
        if not secret:
            raise OctopError(ErrorCode.BRIDGE_AUTH_FAILED, "password required")
        return secret

    async def probe_owned_connection(
        self,
        connection_id: str,
        *,
        owner_user_id: int,
        peer_base_url: str,
        peer_username: str,
        password: str | None = None,
    ) -> dict[str, Any]:
        """Probe using the form endpoint; empty password reuses the stored secret."""
        row = self.get_owned(connection_id, owner_user_id)
        if _is_inbound(row):
            raise OctopError(
                ErrorCode.BRIDGE_INBOUND_PASSIVE,
                "inbound bridge cannot probe peer",
            )
        secret = (password or "").strip() or self._stored_peer_password(row)
        return await self.probe_peer(
            peer_base_url=peer_base_url,
            peer_username=peer_username,
            password=secret,
            connection_id=connection_id,
        )

    def _allocate_connection_id(self) -> str:
        for _ in range(16):
            cid = new_short_id()
            if self._repo.get(cid) is None:
                return cid
        raise RuntimeError("failed to allocate unique bridge connection_id")

    async def create_connection(
        self,
        *,
        owner_user_id: int,
        peer_base_url: str,
        peer_username: str,
        password: str,
        display_name: str,
        notes: str | None = None,
        icon_name: str | None = None,
        shared: bool = False,
        connect: bool = True,
    ) -> BridgeConnectionRow:
        """Create a bridge link.

        With ``connect=True`` (Dashboard default), the row is only kept when the
        peer login **and** Bridge WS handshake both succeed. A failed dial rolls
        back the insert so a retry can reuse the same display name.
        """
        base = normalize_peer_base_url(peer_base_url)
        username = peer_username.strip()
        name = display_name.strip()
        note = (notes or "").strip() or None
        icon = (icon_name or "").strip() or None
        if not username or not password:
            raise OctopError(ErrorCode.BRIDGE_AUTH_FAILED, "username and password required")
        self._validate_peer_endpoint(owner_user_id, base, username)
        if self._at_connection_limit(owner_user_id):
            raise OctopError(
                ErrorCode.BRIDGE_CONNECTION_LIMIT,
                f"at most {MAX_CONNECTIONS_PER_USER} cloud collab connections",
                details={"limit": MAX_CONNECTIONS_PER_USER},
            )
        if not name:
            raise OctopError(
                ErrorCode.FORBIDDEN,
                "display_name required",
                status=400,
                details={"field": "display_name"},
            )
        if self._repo.find_by_display_name(owner_user_id, name) is not None:
            raise OctopError(
                ErrorCode.BRIDGE_DISPLAY_NAME_TAKEN,
                f"display name {name!r} already in use",
                details={"name": name},
            )

        # Login first — no DB row yet on auth / unreachable peer.
        login = await login_peer(base_url=base, username=username, password=password)
        token = str(login["access_token"])
        expires_in = int(login.get("expires_in") or 0)
        from octop.infra.db.repos._base import now_ts

        expires_at = now_ts() + expires_in if expires_in > 0 else None
        connection_id = self._allocate_connection_id()
        cred_blob = encrypt_payload(self._secrets, {"password": password})
        token_blob = encrypt_payload(self._secrets, {"access_token": token})
        row = self._repo.create(
            connection_id=connection_id,
            owner_user_id=owner_user_id,
            peer_base_url=base,
            peer_username=username,
            display_name=name,
            notes=note,
            icon_name=icon,
            shared=bool(shared),
            credential_blob=cred_blob,
            access_token_blob=token_blob,
            token_expires_at=expires_at,
            status="connecting" if connect else "disconnected",
        )
        if not connect:
            return self._repo.get(connection_id) or row
        try:
            return await self.connect(connection_id, owner_user_id=owner_user_id)
        except Exception:
            # Roll back so a failed "Save & connect" does not occupy display_name
            # or leave a dead card in the list.
            with suppress(Exception):
                await self.disconnect(connection_id)
            self._repo.delete(connection_id)
            raise

    async def delete_connection(self, connection_id: str, *, owner_user_id: int) -> None:
        self.get_owned(connection_id, owner_user_id)
        sess = self._sessions.get(connection_id)
        if sess is not None and not sess.closed:
            with suppress(Exception):
                await sess.send_json({"type": "close", "reason": "deleted"})
                await asyncio.sleep(0.1)
        await self.disconnect(connection_id)
        self._repo.delete(connection_id)

    def set_shared(
        self, connection_id: str, *, owner_user_id: int, shared: bool
    ) -> BridgeConnectionRow:
        self.get_owned(connection_id, owner_user_id)
        updated = self._repo.set_shared(connection_id, shared)
        if updated is None:
            raise OctopError(ErrorCode.BRIDGE_NOT_FOUND, "bridge connection not found")
        return updated

    def set_icon_url(
        self, connection_id: str, *, owner_user_id: int, icon_url: str | None
    ) -> BridgeConnectionRow:
        self.get_owned(connection_id, owner_user_id)
        updated = self._repo.set_icon_url(connection_id, icon_url)
        if updated is None:
            raise OctopError(ErrorCode.BRIDGE_NOT_FOUND, "bridge connection not found")
        return updated
