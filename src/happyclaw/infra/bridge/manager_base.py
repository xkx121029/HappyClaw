"""Shared state and collaborator surface of :class:`BridgeManager`.

``BridgeManager`` is assembled from the responsibility mixins beside this module
(transport, remote queries, peer turn protocol, outbound relay, browser channel).
Each mixin reaches the manager's own state and the collaborators it calls through
this protocol, so every module type-checks on its own under ``mypy --strict``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

import httpx

from happyclaw.infra.bridge.peer_turn import PeerBrowserRunner, PeerTurnRunner
from happyclaw.infra.bridge.transport import BridgeSession
from happyclaw.infra.db.repos.bridge_connections import BridgeConnectionRepo, BridgeConnectionRow
from happyclaw.infra.db.repos.secrets import SecretRepo
from happyclaw.infra.db.repos.users import UserRepo
from happyclaw.infra.errors import HappyclawError

# One logger for the whole BridgeManager family; kept under the historical name
# so existing log filters and tests keep matching.
logger = logging.getLogger("happyclaw.infra.bridge.manager")


class BridgeManagerBase(Protocol):
    """State and collaborators shared by ``BridgeManager`` and its mixins."""

    _repo: BridgeConnectionRepo
    _secrets: SecretRepo
    _users: UserRepo
    _advertise_base_url: str
    _token_signer: Any | None
    _sessions: dict[str, BridgeSession]
    _client_tasks: dict[str, asyncio.Task[None]]
    _turn_waiters: dict[str, asyncio.Queue[dict[str, Any]]]
    _listen_stops: dict[str, asyncio.Event]
    _browser_waiters: dict[str, asyncio.Queue[dict[str, Any]]]
    _browser_peer_clients: dict[str, asyncio.Queue[dict[str, Any] | None]]
    _asgi_app: Any | None
    _peer_turn_runner: PeerTurnRunner | None
    _peer_browser_runner: PeerBrowserRunner | None
    _lock: asyncio.Lock
    _user_stopped: set[str]
    _reconnect_failures: dict[str, int]

    def list_connections(self, owner_user_id: int) -> list[BridgeConnectionRow]: ...

    def list_visible_connections(self, user_id: int) -> list[BridgeConnectionRow]: ...

    def get(self, connection_id: str) -> BridgeConnectionRow | None: ...

    def get_owned(self, connection_id: str, owner_user_id: int) -> BridgeConnectionRow: ...

    def get_usable(self, connection_id: str, user_id: int) -> BridgeConnectionRow: ...

    def _find_peer_link(
        self,
        owner_user_id: int,
        peer_base_url: str,
        peer_username: str,
        *,
        exclude_connection_id: str | None = None,
    ) -> BridgeConnectionRow | None: ...

    def _validate_peer_endpoint(
        self,
        owner_user_id: int,
        peer_base_url: str,
        peer_username: str,
        *,
        exclude_connection_id: str | None = None,
    ) -> None: ...

    def _at_connection_limit(self, owner_user_id: int) -> bool: ...

    def _allocate_display_name(
        self, *, owner_user_id: int, preferred: str, exclude_connection_id: str | None = None
    ) -> str: ...

    def connection_public(self, row: BridgeConnectionRow) -> dict[str, Any]: ...

    async def connect(self, connection_id: str, *, owner_user_id: int) -> BridgeConnectionRow: ...

    async def disconnect(self, connection_id: str) -> None: ...

    async def _outbound_supervisor(self, connection_id: str) -> None: ...

    async def _require_live_session(self, connection_id: str) -> BridgeSession: ...

    async def _unregister_session(
        self, connection_id: str, *, expected: BridgeSession | None = None
    ) -> None: ...

    def _bridge_link_error(self, exc: BaseException) -> HappyclawError: ...

    async def tunnel_http(
        self,
        *,
        connection_id: str,
        owner_user_id: int,
        method: str,
        path: str,
        query: str = "",
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> httpx.Response: ...

    async def _handle_inbound_tunnel(
        self, connection_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]: ...

    async def _handle_inbound_turn(self, connection_id: str, payload: dict[str, Any]) -> None: ...

    async def open_turn_waiter(self, request_id: str) -> asyncio.Queue[dict[str, Any]]: ...

    def close_turn_waiter(self, request_id: str) -> None: ...

    async def _handle_inbound_browser(
        self, connection_id: str, payload: dict[str, Any]
    ) -> None: ...

    async def open_browser_waiter(self, request_id: str) -> asyncio.Queue[dict[str, Any]]: ...

    def close_browser_waiter(self, request_id: str) -> None: ...

    async def tunnel_json_get(
        self, connection_id: str, *, owner_user_id: int, path: str, query: str = ""
    ) -> Any: ...
