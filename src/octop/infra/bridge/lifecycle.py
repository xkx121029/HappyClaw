"""Dial, supervise, accept inbound sockets and own live sessions."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from typing import Any, NoReturn

import websockets

from octop.infra.bridge.crypto import decrypt_payload, encrypt_payload
from octop.infra.bridge.dial_errors import (
    _PERMANENT_DIAL_CODES,
    _should_refresh_peer_token,
    bridge_failure_from_dial,
    dial_error_note,
    error_from_dial_note,
)
from octop.infra.bridge.identity import (
    _advertise_host_label,
    _is_inbound,
    inbound_default_display_name,
    observe_ws_client_host,
)
from octop.infra.bridge.ids import (
    PROTOCOL_VERSION,
)
from octop.infra.bridge.manager_base import BridgeManagerBase
from octop.infra.bridge.peer_auth import (
    is_self_peer_url,
    login_peer,
    normalize_peer_base_url,
    peer_ws_url,
)
from octop.infra.bridge.transport import (
    ADVERTISED_BRIDGE_FEATURES,
    BRIDGE_WS_MAX_BYTES,
    BridgeSession,
    peer_feature_set,
)
from octop.infra.db.repos.bridge_connections import BridgeConnectionRow
from octop.infra.errors import ErrorCode, OctopError

logger = logging.getLogger(__name__)


_AUTO_RECONNECT_MAX_FAILURES = 5

_AUTO_RECONNECT_BACKOFF_SEC = (2.0, 4.0, 8.0, 16.0, 30.0)

_RECONNECT_GRACE_SEC = 5.0


class ConnectionLifecycleMixin(BridgeManagerBase):
    async def connect(self, connection_id: str, *, owner_user_id: int) -> BridgeConnectionRow:
        row = self.get_owned(connection_id, owner_user_id)
        if _is_inbound(row):
            raise OctopError(
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
        raise OctopError(ErrorCode.BRIDGE_PEER_UNREACHABLE, detail)

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
            raise OctopError(
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
                raise OctopError(
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
                raise OctopError(
                    ErrorCode.FORBIDDEN,
                    "display_name required",
                    status=400,
                    details={"field": "display_name"},
                )
            other = self._repo.find_by_display_name(owner_user_id, name)
            if other is not None and other.connection_id != connection_id:
                raise OctopError(
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
            raise OctopError(ErrorCode.BRIDGE_AUTH_FAILED, "username required")

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
                raise OctopError(ErrorCode.BRIDGE_NOT_FOUND, "bridge connection not found")
            return updated

        if password_changed:
            secret = pwd_raw
        else:
            if not row.credential_blob:
                raise OctopError(ErrorCode.BRIDGE_AUTH_FAILED, "password required")
            secret = str(decrypt_payload(self._secrets, row.credential_blob).get("password") or "")
            if not secret:
                raise OctopError(ErrorCode.BRIDGE_AUTH_FAILED, "password required")

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
        from octop.infra.db.repos._base import now_ts

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
            raise OctopError(ErrorCode.BRIDGE_NOT_FOUND, "bridge connection not found")

        await self.disconnect(connection_id)
        self._user_stopped.discard(connection_id)
        if was_live or updated.auto_reconnect:
            try:
                return await self.connect(connection_id, owner_user_id=owner_user_id)
            except OctopError:
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

    async def _outbound_supervisor(self, connection_id: str) -> None:
        """Keep an outbound Bridge WS alive while auto_reconnect is on."""
        retried_auth = False
        while True:
            if connection_id in self._user_stopped:
                return
            row = self._repo.get(connection_id)
            if row is None:
                return
            try:
                token = await self._ensure_peer_token(row, force_refresh=retried_auth)
                self._repo.update_status(connection_id, status="connecting", last_error=None)
                await self._run_outbound_client(connection_id, row.peer_base_url, token)
                retried_auth = False
                # Clean close (peer hung up) — reset failure streak.
                self._reconnect_failures[connection_id] = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not retried_auth and _should_refresh_peer_token(exc):
                    retried_auth = True
                    logger.info(
                        "bridge handshake rejected connection=%s; refreshing peer token",
                        connection_id,
                    )
                    continue
                retried_auth = False
                detail = dial_error_note(exc)
                if bridge_failure_from_dial(exc).code in _PERMANENT_DIAL_CODES:
                    if self._repo.get(connection_id) is not None:
                        self._repo.update_status(
                            connection_id, status="error", last_error=detail[:500]
                        )
                    # Leave auto-reconnect enabled, but stop this supervisor so a
                    # rejected login does not wait out the backoff or overwrite
                    # the readable error with the English disable line.
                    self._user_stopped.add(connection_id)
                    return
                failures = self._reconnect_failures.get(connection_id, 0) + 1
                self._reconnect_failures[connection_id] = failures
                if self._repo.get(connection_id) is not None:
                    self._repo.update_status(
                        connection_id, status="disconnected", last_error=detail[:500]
                    )
                row = self._repo.get(connection_id)
                if row is None or connection_id in self._user_stopped:
                    return
                if not row.auto_reconnect:
                    return
                if failures >= _AUTO_RECONNECT_MAX_FAILURES:
                    msg = (
                        f"Auto-reconnect disabled after {failures} failed attempts. "
                        f"Last error: {detail[:300]}"
                    )
                    self._repo.set_auto_reconnect(connection_id, False)
                    self._repo.update_status(connection_id, status="error", last_error=msg[:500])
                    self._user_stopped.add(connection_id)
                    logger.warning(
                        "bridge auto-reconnect disabled connection=%s after %s failures",
                        connection_id,
                        failures,
                    )
                    return
                delay = _AUTO_RECONNECT_BACKOFF_SEC[
                    min(failures - 1, len(_AUTO_RECONNECT_BACKOFF_SEC) - 1)
                ]
                logger.info(
                    "bridge reconnecting connection=%s in %.0fs (attempt %s)",
                    connection_id,
                    delay,
                    failures,
                )
                try:
                    await asyncio.sleep(delay)
                except asyncio.CancelledError:
                    raise
                continue

            # Session ended without exception — reconnect if still enabled.
            if connection_id in self._user_stopped:
                return
            row = self._repo.get(connection_id)
            if row is None or not row.auto_reconnect:
                if self._repo.get(connection_id) is not None:
                    self._repo.update_status(connection_id, status="disconnected")
                return
            delay = _AUTO_RECONNECT_BACKOFF_SEC[0]
            logger.info(
                "bridge session ended; reconnecting connection=%s in %.0fs",
                connection_id,
                delay,
            )
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                raise

    async def _ensure_peer_token(
        self, row: BridgeConnectionRow, *, force_refresh: bool = False
    ) -> str:
        from octop.infra.db.repos._base import now_ts

        if row.access_token_blob and not force_refresh:
            data = decrypt_payload(self._secrets, row.access_token_blob)
            token = str(data.get("access_token") or "").strip()
            exp = row.token_expires_at
            if token and (exp is None or exp > now_ts() + 60):
                return token
        if not row.credential_blob:
            raise OctopError(ErrorCode.BRIDGE_AUTH_FAILED, "no peer credentials stored")
        creds = decrypt_payload(self._secrets, row.credential_blob)
        password = str(creds.get("password") or "")
        login = await login_peer(
            base_url=row.peer_base_url,
            username=row.peer_username,
            password=password,
        )
        token = str(login["access_token"])
        expires_in = int(login.get("expires_in") or 0)
        expires_at = now_ts() + expires_in if expires_in > 0 else None
        self._repo.update_credentials(
            row.connection_id,
            access_token_blob=encrypt_payload(self._secrets, {"access_token": token}),
            token_expires_at=expires_at,
        )
        return token

    async def _run_outbound_client(
        self, connection_id: str, peer_base_url: str, token: str
    ) -> None:
        url = peer_ws_url(peer_base_url, token=token)
        session: BridgeSession | None = None
        try:
            # websockets 15 uses the system proxy by default. A proxy that
            # allows HTTP login often answers the upgrade with an empty 403.
            # Dial the peer URL directly. The bearer header survives proxies
            # that strip the query string; peers that only read ``token``
            # still see the query.
            #
            # Library keepalive is off. A 20s protocol ping_timeout closes the
            # socket when a busy peer (demo.octop.chat) is late to pong, and
            # the supervisor immediately redials, so the link flaps. NAT / L7
            # idle timers are reset by BridgeSession application pings instead.
            async with websockets.connect(
                url,
                open_timeout=20,
                max_size=BRIDGE_WS_MAX_BYTES,
                ping_interval=None,
                ping_timeout=None,
                proxy=None,
                additional_headers={"Authorization": f"Bearer {token}"},
            ) as ws:
                owner = self._repo.get(connection_id)
                local_user = self._users.get(owner.owner_user_id) if owner is not None else None
                hello = {
                    "type": "hello",
                    "protocol_version": PROTOCOL_VERSION,
                    "connection_id": connection_id,
                    "role": "initiator",
                    "advertise_base_url": self._advertise_base_url or "http://127.0.0.1",
                    "advertise_username": (local_user.username if local_user is not None else ""),
                    "display_name": owner.display_name if owner else None,
                    "features": list(ADVERTISED_BRIDGE_FEATURES),
                }
                await ws.send(json.dumps(hello, ensure_ascii=False))

                # Wait for hello_ack before advertising the session as connected.
                while True:
                    raw_ack = await asyncio.wait_for(ws.recv(), timeout=20.0)
                    text_ack = (
                        raw_ack
                        if isinstance(raw_ack, str)
                        else raw_ack.decode("utf-8", errors="replace")
                    )
                    try:
                        ack = json.loads(text_ack)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(ack, dict):
                        continue
                    if str(ack.get("type") or "") != "hello_ack":
                        continue
                    ack_id = str(ack.get("connection_id") or "").strip()
                    if ack_id and ack_id != connection_id:
                        raise OctopError(
                            ErrorCode.BRIDGE_PEER_UNREACHABLE,
                            "peer rebound this link onto another connection",
                        )
                    peer_version = int(ack.get("protocol_version") or 0)
                    if peer_version != PROTOCOL_VERSION:
                        raise OctopError(
                            ErrorCode.BRIDGE_PEER_UNREACHABLE,
                            f"bridge protocol mismatch: peer={peer_version} local={PROTOCOL_VERSION}",
                        )
                    break

                async def close_transport() -> None:
                    with suppress(Exception):
                        await ws.close()

                session = BridgeSession(
                    connection_id=connection_id,
                    send_text=ws.send,
                    peer_features=peer_feature_set(ack),
                    on_tunnel_request=lambda p: self._handle_inbound_tunnel(connection_id, p),
                    on_turn_frame=lambda p: self._handle_inbound_turn(connection_id, p),
                    on_browser_frame=lambda p: self._handle_inbound_browser(connection_id, p),
                    close_transport=close_transport,
                )
                await self._register_session(connection_id, session)
                session.start_heartbeat()
                if self._repo.get(connection_id) is not None:
                    self._repo.update_status(
                        connection_id, status="connected", last_error=None, touch_seen=True
                    )
                    self._reconnect_failures[connection_id] = 0
                async for raw in ws:
                    text = raw if isinstance(raw, str) else raw.decode("utf-8", errors="replace")
                    await session.handle_message(text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("bridge outbound closed connection=%s: %s", connection_id, exc)
            raise
        finally:
            if session is not None:
                await self._unregister_session(connection_id, expected=session)

    async def accept_inbound(
        self,
        *,
        websocket: Any,
        user: Any,
    ) -> None:
        """Handle an inbound ``/api/bridge/ws`` after JWT auth + accept()."""
        connection_id: str | None = None
        session: BridgeSession | None = None

        async def send_text(text: str) -> None:
            await websocket.send_text(text)

        async def close_transport() -> None:
            with suppress(Exception):
                await websocket.close()

        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            payload = json.loads(raw)
        except Exception:
            await websocket.close(code=4000, reason="hello required")
            return
        if not isinstance(payload, dict) or str(payload.get("type") or "") != "hello":
            await websocket.close(code=4000, reason="hello required")
            return
        peer_version = int(payload.get("protocol_version") or 0)
        if peer_version != PROTOCOL_VERSION:
            await websocket.close(code=4002, reason="protocol mismatch")
            return
        connection_id = str(payload.get("connection_id") or "").strip()
        if not connection_id:
            await websocket.close(code=4000, reason="connection_id required")
            return
        advertise_base = str(payload.get("advertise_base_url") or "").strip() or "http://127.0.0.1"
        advertise_user = str(payload.get("advertise_username") or "").strip() or "peer"
        try:
            advertise_base = normalize_peer_base_url(advertise_base)
        except OctopError:
            advertise_base = "http://127.0.0.1"

        # Default installs advertise http://127.0.0.1:<port>. That URL is shared
        # by every instance on the same port, so it is not proof this socket
        # looped back to us. Outbound dials already reject a loopback self URL.
        # A non-loopback advertise URL (explicit bind address) still is.
        if is_self_peer_url(advertise_base, self._advertise_base_url) and _advertise_host_label(
            self._advertise_base_url
        ):
            await websocket.close(code=4004, reason="self connect")
            return

        existing = self._repo.get(connection_id)
        # An outbound row (we stored the peer password) only exists on the
        # instance that allocated this connection id. A hello for that id means
        # the dial reached this same Octop — often because the typed URL does
        # not match the advertised address, so the earlier self-check missed it.
        if existing is not None and bool(existing.credential_blob):
            await websocket.close(code=4004, reason="self connect")
            return
        if existing is not None and int(existing.owner_user_id) != int(user.id):
            await websocket.close(code=4003, reason="connection owned by another user")
            return
        # Do not merge a new connection_id onto an older row that happens to
        # advertise the same URL and username. Loopback / NAT addresses are not
        # unique, so several people logging into this account would otherwise
        # steal one socket and the later link would never stay up.
        if existing is None and self._at_connection_limit(int(user.id)):
            await websocket.close(code=4008, reason="connection limit")
            return
        client_host = observe_ws_client_host(websocket)
        preferred = inbound_default_display_name(
            connection_id=connection_id,
            client_host=client_host,
            advertise_base_url=advertise_base,
            peer_username=advertise_user,
            existing_name=existing.display_name if existing is not None else None,
        )
        display_name = self._allocate_display_name(
            owner_user_id=int(user.id),
            preferred=preferred,
            exclude_connection_id=connection_id if existing is not None else None,
        )

        self._repo.upsert_reverse(
            connection_id=connection_id,
            owner_user_id=int(user.id),
            peer_base_url=advertise_base,
            peer_username=advertise_user,
            display_name=display_name,
            status="connected",
            peer_client_host=client_host or None,
        )

        session = BridgeSession(
            connection_id=connection_id,
            send_text=send_text,
            peer_features=peer_feature_set(payload),
            on_tunnel_request=lambda p: self._handle_inbound_tunnel(connection_id, p),
            on_turn_frame=lambda p: self._handle_inbound_turn(connection_id, p),
            on_browser_frame=lambda p: self._handle_inbound_browser(connection_id, p),
            close_transport=close_transport,
        )
        await self._register_session(connection_id, session)
        session.start_heartbeat()
        await session.send_json(
            {
                "type": "hello_ack",
                "protocol_version": PROTOCOL_VERSION,
                "connection_id": connection_id,
                "peer_username": user.username,
                "features": list(ADVERTISED_BRIDGE_FEATURES),
            }
        )
        try:
            while True:
                message = await websocket.receive_text()
                await session.handle_message(message)
                if session.closed:
                    break
        except Exception:
            logger.info("bridge inbound closed connection=%s", connection_id)
        finally:
            if connection_id:
                await self._finalize_inbound(connection_id, session)

    async def _register_session(self, connection_id: str, session: BridgeSession) -> None:
        old = self._sessions.get(connection_id)
        if old is not None and old is not session:
            await old.close()
        self._sessions[connection_id] = session

    async def _unregister_session(
        self, connection_id: str, *, expected: BridgeSession | None = None
    ) -> None:
        current = self._sessions.get(connection_id)
        if expected is not None and current is not expected:
            return
        sess = self._sessions.pop(connection_id, None)
        if sess is not None:
            await sess.close()

    async def _finalize_inbound(self, connection_id: str, session: BridgeSession | None) -> None:
        """Drop this socket only. A replacement for the same id must stay up."""
        current = self._sessions.get(connection_id)
        replaced = current is not None and session is not None and current is not session
        if not replaced:
            await self._unregister_session(connection_id, expected=session)
        if replaced:
            return
        if session is not None and session.close_reason == "deleted":
            self._repo.delete(connection_id)
            return
        if self._repo.get(connection_id) is not None:
            self._repo.update_status(connection_id, status="disconnected")

    def require_session(self, connection_id: str) -> BridgeSession:
        sess = self._sessions.get(connection_id)
        if sess is None or sess.closed:
            raise OctopError(ErrorCode.BRIDGE_NOT_CONNECTED, "bridge not connected")
        return sess

    async def _require_live_session(self, connection_id: str) -> BridgeSession:
        """Return a live session. Drop a half-open one; wait briefly if we can redial."""
        sess = self._sessions.get(connection_id)
        if sess is not None and not sess.closed and sess.is_stale():
            logger.warning(
                "bridge session stale connection=%s idle=%.0fs; dropping",
                connection_id,
                sess.idle_seconds(),
            )
            await self._unregister_session(connection_id, expected=sess)
            sess = None
        if sess is not None and not sess.closed:
            return sess
        supervisor = self._client_tasks.get(connection_id)
        if supervisor is None or supervisor.done():
            raise OctopError(ErrorCode.BRIDGE_NOT_CONNECTED, "bridge not connected")
        deadline = asyncio.get_running_loop().time() + _RECONNECT_GRACE_SEC
        while asyncio.get_running_loop().time() < deadline:
            live = self._sessions.get(connection_id)
            if live is not None and not live.closed:
                return live
            await asyncio.sleep(0.1)
        raise OctopError(ErrorCode.BRIDGE_NOT_CONNECTED, "bridge not connected")

    def _bridge_link_error(self, exc: BaseException) -> OctopError:
        if isinstance(exc, TimeoutError):
            return OctopError(ErrorCode.BRIDGE_TUNNEL_FAILED, str(exc) or "bridge tunnel timeout")
        return OctopError(ErrorCode.BRIDGE_NOT_CONNECTED, "bridge not connected")
