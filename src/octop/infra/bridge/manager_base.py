"""Attribute contract shared by the bridge manager mixins."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from octop.infra.bridge.peer_turn import PeerBrowserRunner, PeerTurnRunner
    from octop.infra.bridge.transport import BridgeSession
    from octop.infra.db.repos.bridge_connections import BridgeConnectionRepo
    from octop.infra.db.repos.secrets import SecretRepo
    from octop.infra.db.repos.users import UserRepo


class BridgeManagerBase:
    """Declares the state :class:`BridgeManager` owns."""

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
