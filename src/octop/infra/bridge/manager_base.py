"""Attribute contract shared by the bridge manager mixins."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from octop.infra.bridge.peer_turn import PeerBrowserRunner, PeerTurnRunner
    from octop.infra.bridge.transport import BridgeSession
    from octop.infra.db.repos.bridge_connections import BridgeConnectionRepo, BridgeConnectionRow
    from octop.infra.db.repos.secrets import SecretRepo
    from octop.infra.db.repos.users import UserRepo
    from octop.infra.errors import OctopError


class BridgeManagerBase:
    """Declares the state :class:`BridgeManager` owns.

    Cross-mixin calls are declared here as stubs so each mixin type-checks on
    its own; the mixins themselves supply the implementations and win in MRO.
    """

    _repo: BridgeConnectionRepo
    _secrets: SecretRepo
    _users: UserRepo
    _advertise_base_url: str
    _token_signer: Any
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

    # -- connection registry (ConnectionRegistryMixin)

    def get_owned(self, connection_id: str, owner_user_id: int) -> BridgeConnectionRow:
        raise NotImplementedError

    def get_usable(self, connection_id: str, user_id: int) -> BridgeConnectionRow:
        raise NotImplementedError

    def _validate_peer_endpoint(
        self,
        owner_user_id: int,
        peer_base_url: str,
        peer_username: str,
        *,
        exclude_connection_id: str | None = None,
    ) -> None:
        raise NotImplementedError

    def _at_connection_limit(self, owner_user_id: int) -> bool:
        raise NotImplementedError

    def _allocate_display_name(
        self,
        *,
        owner_user_id: int,
        preferred: str,
        exclude_connection_id: str | None = None,
    ) -> str:
        raise NotImplementedError

    # -- lifecycle (ConnectionLifecycleMixin)

    async def connect(self, connection_id: str, *, owner_user_id: int) -> BridgeConnectionRow:
        raise NotImplementedError

    async def disconnect(self, connection_id: str) -> None:
        raise NotImplementedError

    async def _unregister_session(
        self, connection_id: str, *, expected: BridgeSession | None = None
    ) -> None:
        raise NotImplementedError

    async def _require_live_session(self, connection_id: str) -> BridgeSession:
        raise NotImplementedError

    def _bridge_link_error(self, exc: BaseException) -> OctopError:
        raise NotImplementedError

    # -- inbound frame handlers (one per relay kind)

    async def _handle_inbound_tunnel(
        self, connection_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        raise NotImplementedError

    async def _handle_inbound_turn(self, connection_id: str, payload: dict[str, Any]) -> None:
        raise NotImplementedError

    async def _handle_inbound_browser(self, connection_id: str, payload: dict[str, Any]) -> None:
        raise NotImplementedError


__all__ = ["BridgeManagerBase"]
