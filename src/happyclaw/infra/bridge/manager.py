"""BridgeManager — connections, live sessions, tunnels and the turn relay."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import (
    Any,
    NoReturn,
)
from urllib.parse import (
    urljoin,
    urlsplit,
)

import httpx

from happyclaw.infra.bridge.crypto import (
    decrypt_payload,
    encrypt_payload,
)
from happyclaw.infra.bridge.dial_policy import (
    _AUTO_RECONNECT_BACKOFF_SEC as _AUTO_RECONNECT_BACKOFF_SEC,
)
from happyclaw.infra.bridge.dial_policy import (
    _AUTO_RECONNECT_MAX_FAILURES as _AUTO_RECONNECT_MAX_FAILURES,
)
from happyclaw.infra.bridge.dial_policy import (
    _DIAL_ERROR_PREFIX as _DIAL_ERROR_PREFIX,
)
from happyclaw.infra.bridge.dial_policy import (
    _PERMANENT_DIAL_CODES as _PERMANENT_DIAL_CODES,
)
from happyclaw.infra.bridge.dial_policy import (
    _RECONNECT_GRACE_SEC as _RECONNECT_GRACE_SEC,
)
from happyclaw.infra.bridge.dial_policy import (
    MAX_CONNECTIONS_PER_USER as MAX_CONNECTIONS_PER_USER,
)
from happyclaw.infra.bridge.dial_policy import (
    _annotate_bridge_dial_error as _annotate_bridge_dial_error,
)
from happyclaw.infra.bridge.dial_policy import (
    _close_code as _close_code,
)
from happyclaw.infra.bridge.dial_policy import (
    _close_frame as _close_frame,
)
from happyclaw.infra.bridge.dial_policy import (
    _close_reason as _close_reason,
)
from happyclaw.infra.bridge.dial_policy import (
    _handshake_http_status as _handshake_http_status,
)
from happyclaw.infra.bridge.dial_policy import (
    _should_refresh_peer_token as _should_refresh_peer_token,
)
from happyclaw.infra.bridge.dial_policy import (
    bridge_failure_from_dial as bridge_failure_from_dial,
)
from happyclaw.infra.bridge.dial_policy import (
    dial_error_note as dial_error_note,
)
from happyclaw.infra.bridge.dial_policy import (
    error_from_dial_note as error_from_dial_note,
)
from happyclaw.infra.bridge.manager_base import logger
from happyclaw.infra.bridge.manager_browser import BridgeBrowserMixin
from happyclaw.infra.bridge.manager_peer import BridgePeerMixin
from happyclaw.infra.bridge.manager_relay import BridgeRelayMixin
from happyclaw.infra.bridge.manager_remote import BridgeRemoteMixin
from happyclaw.infra.bridge.manager_transport import BridgeTransportMixin
from happyclaw.infra.bridge.peer_auth import (
    is_self_peer_url,
    login_peer,
    normalize_peer_base_url,
    peer_identity_key,
)
from happyclaw.infra.bridge.peer_identity import (
    _absolute_peer_url as _absolute_peer_url,
)
from happyclaw.infra.bridge.peer_identity import (
    _advertise_host_label as _advertise_host_label,
)
from happyclaw.infra.bridge.peer_identity import (
    _bridge_turn_ws_payload as _bridge_turn_ws_payload,
)
from happyclaw.infra.bridge.peer_identity import (
    _host_label as _host_label,
)
from happyclaw.infra.bridge.peer_identity import (
    _is_inbound as _is_inbound,
)
from happyclaw.infra.bridge.peer_identity import (
    _probe_agent_summary as _probe_agent_summary,
)
from happyclaw.infra.bridge.peer_identity import (
    inbound_default_display_name as inbound_default_display_name,
)
from happyclaw.infra.bridge.peer_identity import (
    observe_ws_client_host as observe_ws_client_host,
)
from happyclaw.infra.bridge.peer_turn import (
    PeerBrowserRunner,
    PeerTurnRunner,
)
from happyclaw.infra.bridge.transport import BridgeSession
from happyclaw.infra.db.repos.bridge_connections import (
    BridgeConnectionRepo,
    BridgeConnectionRow,
)
from happyclaw.infra.db.repos.secrets import SecretRepo
from happyclaw.infra.db.repos.users import UserRepo
from happyclaw.infra.errors import (
    ErrorCode,
    HappyclawError,
)
from happyclaw.infra.utils.ulid import new_short_id


class BridgeManager(
    BridgeTransportMixin,
    BridgePeerMixin,
    BridgeRelayMixin,
    BridgeBrowserMixin,
    BridgeRemoteMixin,
):
    """Bridge connections: registry, lifecycle, and the capability mixins above."""

    def __init__(
        self,
        *,
        bridge_repo: BridgeConnectionRepo,
        secret_repo: SecretRepo,
        user_repo: UserRepo,
        advertise_base_url: str,
        token_signer: Any | None = None,
    ) -> None:
        self._repo = bridge_repo
        self._secrets = secret_repo
        self._users = user_repo
        self._advertise_base_url = advertise_base_url.rstrip("/")
        self._token_signer = token_signer
        self._sessions: dict[str, BridgeSession] = {}
        self._client_tasks: dict[str, asyncio.Task[None]] = {}
        self._turn_waiters: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self._listen_stops: dict[str, asyncio.Event] = {}
        self._browser_waiters: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self._browser_peer_clients: dict[str, asyncio.Queue[dict[str, Any] | None]] = {}
        self._asgi_app: Any | None = None
        self._peer_turn_runner: PeerTurnRunner | None = None
        self._peer_browser_runner: PeerBrowserRunner | None = None
        self._lock = asyncio.Lock()
        # Manual disconnect / intentional stop — do not auto-reconnect until connect().
        self._user_stopped: set[str] = set()
        self._reconnect_failures: dict[str, int] = {}

    def bind_asgi_app(
        self,
        app: Any,
        *,
        peer_turn_runner: PeerTurnRunner | None = None,
        peer_browser_runner: PeerBrowserRunner | None = None,
    ) -> None:
        """Attach the local ASGI app and optional HTTP-layer peer runners.

        ``peer_turn_runner`` / ``peer_browser_runner`` are provided by
        ``api.app`` so this module never imports ``happyclaw.api``.
        """
        self._asgi_app = app
        self._peer_turn_runner = peer_turn_runner
        self._peer_browser_runner = peer_browser_runner

    def set_token_signer(self, signer: Any) -> None:
        self._token_signer = signer

    def set_advertise_base_url(self, url: str) -> None:
        self._advertise_base_url = url.rstrip("/")

    # -- persistence helpers -------------------------------------------------

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
            raise HappyclawError(ErrorCode.BRIDGE_NOT_FOUND, "bridge connection not found")
        return row

    def get_usable(self, connection_id: str, user_id: int) -> BridgeConnectionRow:
        """Owner, or a user the link was shared with.

        Management (connect, edit, delete) stays on ``get_owned``. Chat and
        read tunnels use this so a shared recipient is not told the link is
        missing.
        """
        row = self._repo.get_visible(connection_id, user_id)
        if row is None:
            raise HappyclawError(ErrorCode.BRIDGE_NOT_FOUND, "bridge connection not found")
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
            except HappyclawError:
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
            raise HappyclawError(
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
            raise HappyclawError(
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
            raise HappyclawError(ErrorCode.BRIDGE_AUTH_FAILED, "username and password required")
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
            raise HappyclawError(
                ErrorCode.BRIDGE_PEER_UNREACHABLE,
                f"peer agents probe failed: {exc}",
            ) from exc
        if resp.status_code >= 400:
            raise HappyclawError(
                ErrorCode.BRIDGE_AUTH_FAILED,
                f"peer agents HTTP {resp.status_code}: {resp.text[:200]}",
            )
        try:
            data = resp.json()
        except ValueError as exc:
            raise HappyclawError(
                ErrorCode.BRIDGE_TUNNEL_FAILED,
                "peer agents returned non-JSON",
            ) from exc
        if not isinstance(data, list):
            raise HappyclawError(ErrorCode.BRIDGE_TUNNEL_FAILED, "peer agents payload invalid")
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
            raise HappyclawError(ErrorCode.BRIDGE_AUTH_FAILED, "password required")
        secret = str(decrypt_payload(self._secrets, row.credential_blob).get("password") or "")
        if not secret:
            raise HappyclawError(ErrorCode.BRIDGE_AUTH_FAILED, "password required")
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
            raise HappyclawError(
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

    # -- create / delete / connect -------------------------------------------

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
            raise HappyclawError(ErrorCode.BRIDGE_AUTH_FAILED, "username and password required")
        self._validate_peer_endpoint(owner_user_id, base, username)
        if self._at_connection_limit(owner_user_id):
            raise HappyclawError(
                ErrorCode.BRIDGE_CONNECTION_LIMIT,
                f"at most {MAX_CONNECTIONS_PER_USER} cloud collab connections",
                details={"limit": MAX_CONNECTIONS_PER_USER},
            )
        if not name:
            raise HappyclawError(
                ErrorCode.FORBIDDEN,
                "display_name required",
                status=400,
                details={"field": "display_name"},
            )
        if self._repo.find_by_display_name(owner_user_id, name) is not None:
            raise HappyclawError(
                ErrorCode.BRIDGE_DISPLAY_NAME_TAKEN,
                f"display name {name!r} already in use",
                details={"name": name},
            )

        # Login first — no DB row yet on auth / unreachable peer.
        login = await login_peer(base_url=base, username=username, password=password)
        token = str(login["access_token"])
        expires_in = int(login.get("expires_in") or 0)
        from happyclaw.infra.db.repos._base import now_ts

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

    def _allocate_connection_id(self) -> str:
        for _ in range(16):
            cid = new_short_id()
            if self._repo.get(cid) is None:
                return cid
        raise RuntimeError("failed to allocate unique bridge connection_id")

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
            raise HappyclawError(ErrorCode.BRIDGE_NOT_FOUND, "bridge connection not found")
        return updated

    def set_icon_url(
        self, connection_id: str, *, owner_user_id: int, icon_url: str | None
    ) -> BridgeConnectionRow:
        self.get_owned(connection_id, owner_user_id)
        updated = self._repo.set_icon_url(connection_id, icon_url)
        if updated is None:
            raise HappyclawError(ErrorCode.BRIDGE_NOT_FOUND, "bridge connection not found")
        return updated

    async def connect(self, connection_id: str, *, owner_user_id: int) -> BridgeConnectionRow:
        row = self.get_owned(connection_id, owner_user_id)
        if _is_inbound(row):
            raise HappyclawError(
                ErrorCode.BRIDGE_INBOUND_PASSIVE,
                "inbound bridge cannot dial out",
            )
        self._user_stopped.discard(connection_id)
        async with self._lock:
            existing = self._sessions.get(connection_id)
            if existing is not None and not existing.closed:
                return row
            task = self._client_tasks.get(connection_id)
            if task is not None and not task.done():
                # Supervisor already running (reconnect wait) — wait for live session.
                pass
            else:
                self._repo.update_status(connection_id, status="connecting", last_error=None)
                self._reconnect_failures[connection_id] = 0
                task = asyncio.create_task(
                    self._outbound_supervisor(connection_id),
                    name=f"bridge-out-{connection_id}",
                )
                self._client_tasks[connection_id] = task
        assert task is not None
        # Wait briefly for hello_ack / live session
        for _ in range(50):
            sess = self._sessions.get(connection_id)
            if sess is not None and not sess.closed:
                self._repo.update_status(
                    connection_id, status="connected", last_error=None, touch_seen=True
                )
                self._reconnect_failures[connection_id] = 0
                return self._repo.get(connection_id) or row
            if task.done():
                self._raise_dial_failure(connection_id)
            await asyncio.sleep(0.1)
        self._raise_dial_failure(connection_id, fallback="bridge connect timeout")

    def _raise_dial_failure(
        self, connection_id: str, *, fallback: str = "bridge connect failed"
    ) -> NoReturn:
        latest = self._repo.get(connection_id)
        note = latest.last_error if latest is not None else None
        known = error_from_dial_note(note)
        if known is not None:
            if latest is not None and latest.status != "error":
                self._repo.update_status(
                    connection_id, status="error", last_error=(note or "")[:500]
                )
            raise known
        detail = (note or fallback)[:500]
        if latest is not None and latest.status != "error":
            self._repo.update_status(connection_id, status="error", last_error=detail)
        raise HappyclawError(ErrorCode.BRIDGE_PEER_UNREACHABLE, detail)

    async def disconnect(self, connection_id: str) -> None:
        self._user_stopped.add(connection_id)
        task = self._client_tasks.pop(connection_id, None)
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task
        sess = self._sessions.pop(connection_id, None)
        if sess is not None:
            await sess.close()
        if self._repo.get(connection_id) is not None:
            self._repo.update_status(connection_id, status="disconnected", last_error=None)

    async def set_auto_reconnect(
        self, connection_id: str, *, owner_user_id: int, enabled: bool
    ) -> BridgeConnectionRow:
        row = self.get_owned(connection_id, owner_user_id)
        if enabled and _is_inbound(row):
            raise HappyclawError(
                ErrorCode.BRIDGE_INBOUND_PASSIVE,
                "inbound bridge cannot auto-reconnect",
            )
        self._repo.set_auto_reconnect(connection_id, enabled)
        if enabled:
            self._user_stopped.discard(connection_id)
            self._reconnect_failures[connection_id] = 0
            live = self._sessions.get(connection_id)
            if live is None or live.closed:
                return await self.connect(connection_id, owner_user_id=owner_user_id)
        return self._repo.get(connection_id) or row

    async def update_connection_meta(
        self,
        connection_id: str,
        *,
        owner_user_id: int,
        display_name: str | None = None,
        notes: str | None = None,
        update_notes: bool = False,
        icon_name: str | None = None,
        update_icon: bool = False,
        peer_base_url: str | None = None,
        peer_username: str | None = None,
        password: str | None = None,
    ) -> BridgeConnectionRow:
        """Update display / notes / icon and optionally remote endpoint credentials.

        When URL, username, or password changes, re-login against the peer and
        bounce the live Bridge session if it was connected.
        """
        row = self.get_owned(connection_id, owner_user_id)
        if _is_inbound(row):
            url_touch = peer_base_url is not None and peer_base_url.strip().rstrip(
                "/"
            ) != row.peer_base_url.rstrip("/")
            user_touch = peer_username is not None and peer_username.strip() != row.peer_username
            pwd_touch = bool((password or "").strip())
            if url_touch or user_touch or pwd_touch:
                raise HappyclawError(
                    ErrorCode.BRIDGE_INBOUND_PASSIVE,
                    "inbound bridge cannot change peer credentials",
                )
            peer_base_url = None
            peer_username = None
            password = None
        name = row.display_name
        if display_name is not None:
            name = display_name.strip()
            if not name:
                raise HappyclawError(
                    ErrorCode.FORBIDDEN,
                    "display_name required",
                    status=400,
                    details={"field": "display_name"},
                )
            other = self._repo.find_by_display_name(owner_user_id, name)
            if other is not None and other.connection_id != connection_id:
                raise HappyclawError(
                    ErrorCode.BRIDGE_DISPLAY_NAME_TAKEN,
                    f"display name {name!r} already in use",
                    details={"name": name},
                )
        note = row.notes
        if update_notes:
            note = (notes or "").strip() or None
        icon = row.icon_name
        if update_icon:
            icon = (icon_name or "").strip() or None

        next_user = peer_username.strip() if peer_username is not None else row.peer_username
        if not next_user:
            raise HappyclawError(ErrorCode.BRIDGE_AUTH_FAILED, "username required")

        pwd_raw = (password or "").strip()
        url_changed = False
        next_base = row.peer_base_url
        if peer_base_url is not None:
            stripped = peer_base_url.strip().rstrip("/")
            stored = row.peer_base_url.rstrip("/")
            if stripped != stored:
                url_changed = True

        user_changed = next_user != row.peer_username
        password_changed = bool(pwd_raw)
        need_reauth = url_changed or user_changed or password_changed

        if not need_reauth:
            updated = self._repo.update_settings(
                connection_id,
                display_name=name,
                notes=note,
                icon_name=icon,
            )
            if updated is None:
                raise HappyclawError(ErrorCode.BRIDGE_NOT_FOUND, "bridge connection not found")
            return updated

        if password_changed:
            secret = pwd_raw
        else:
            if not row.credential_blob:
                raise HappyclawError(ErrorCode.BRIDGE_AUTH_FAILED, "password required")
            secret = str(decrypt_payload(self._secrets, row.credential_blob).get("password") or "")
            if not secret:
                raise HappyclawError(ErrorCode.BRIDGE_AUTH_FAILED, "password required")

        if url_changed:
            assert peer_base_url is not None
            next_base = normalize_peer_base_url(peer_base_url)

        if url_changed or user_changed:
            self._validate_peer_endpoint(
                owner_user_id,
                next_base,
                next_user,
                exclude_connection_id=connection_id,
            )

        login = await login_peer(base_url=next_base, username=next_user, password=secret)
        token = str(login["access_token"])
        expires_in = int(login.get("expires_in") or 0)
        from happyclaw.infra.db.repos._base import now_ts

        expires_at = now_ts() + expires_in if expires_in > 0 else None
        live = self._sessions.get(connection_id)
        was_live = live is not None and not live.closed

        updated = self._repo.update_settings(
            connection_id,
            display_name=name,
            notes=note,
            icon_name=icon,
            peer_base_url=next_base,
            peer_username=next_user,
            credential_blob=encrypt_payload(self._secrets, {"password": secret}),
            access_token_blob=encrypt_payload(self._secrets, {"access_token": token}),
            token_expires_at=expires_at,
            update_credentials=True,
        )
        if updated is None:
            raise HappyclawError(ErrorCode.BRIDGE_NOT_FOUND, "bridge connection not found")

        await self.disconnect(connection_id)
        self._user_stopped.discard(connection_id)
        if was_live or updated.auto_reconnect:
            try:
                return await self.connect(connection_id, owner_user_id=owner_user_id)
            except HappyclawError:
                return self._repo.get(connection_id) or updated
        return self._repo.get(connection_id) or updated

    async def resume_auto_connections(self) -> None:
        """Boot-time: dial every connection with auto_reconnect enabled."""
        for row in self._repo.list_auto_reconnect():
            if _is_inbound(row):
                continue
            if row.connection_id in self._user_stopped:
                continue
            live = self._sessions.get(row.connection_id)
            if live is not None and not live.closed:
                continue
            try:
                await self.connect(row.connection_id, owner_user_id=row.owner_user_id)
            except Exception as exc:
                logger.warning(
                    "bridge auto-resume failed connection=%s: %s",
                    row.connection_id,
                    exc,
                )


def public_base_url_from_config(bind_host: str, port: int) -> str:
    host = bind_host if bind_host not in {"0.0.0.0", "::"} else "127.0.0.1"
    return f"http://{host}:{port}"


def split_request_path(path: str) -> tuple[str, str]:
    """Return (path_without_query, query)."""
    parts = urlsplit(path)
    return parts.path, parts.query
