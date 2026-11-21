"""BridgeManager — connection lifecycle, live sessions, HTTP tunnel, turn relay."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlsplit

from octop.infra.bridge.browser import PeerBrowserMixin
from octop.infra.bridge.connections import ConnectionRegistryMixin
from octop.infra.bridge.dial_errors import (
    _annotate_bridge_dial_error,
    _close_code,
    _close_frame,
    _close_reason,
    _handshake_http_status,
    _should_refresh_peer_token,
    bridge_failure_from_dial,
    dial_error_note,
    error_from_dial_note,
)
from octop.infra.bridge.identity import (
    _absolute_peer_url,
    _advertise_host_label,
    _host_label,
    _is_inbound,
    _probe_agent_summary,
    inbound_default_display_name,
    observe_ws_client_host,
)
from octop.infra.bridge.lifecycle import ConnectionLifecycleMixin
from octop.infra.bridge.manager_base import BridgeManagerBase
from octop.infra.bridge.peer_turn import (
    PeerBrowserRunner,
    PeerTurnRunner,
    bridge_turn_ws_payload,
)
from octop.infra.bridge.transport import (
    BridgeSession,
)
from octop.infra.bridge.tunnel import PeerTunnelMixin
from octop.infra.bridge.turns import PeerTurnMixin
from octop.infra.db.repos.bridge_connections import BridgeConnectionRepo
from octop.infra.db.repos.secrets import SecretRepo
from octop.infra.db.repos.users import UserRepo

logger = logging.getLogger(__name__)


_bridge_turn_ws_payload = bridge_turn_ws_payload


class BridgeManager(
    ConnectionRegistryMixin,
    ConnectionLifecycleMixin,
    PeerTunnelMixin,
    PeerTurnMixin,
    PeerBrowserMixin,
    BridgeManagerBase,
):
    """Connection registry, live sessions, tunnel and turn relay."""

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
        ``api.app`` so this module never imports ``octop.api``.
        """
        self._asgi_app = app
        self._peer_turn_runner = peer_turn_runner
        self._peer_browser_runner = peer_browser_runner

    def set_token_signer(self, signer: Any) -> None:
        self._token_signer = signer

    def set_advertise_base_url(self, url: str) -> None:
        self._advertise_base_url = url.rstrip("/")


def public_base_url_from_config(bind_host: str, port: int) -> str:
    host = bind_host if bind_host not in {"0.0.0.0", "::"} else "127.0.0.1"
    return f"http://{host}:{port}"


def split_request_path(path: str) -> tuple[str, str]:
    """Return (path_without_query, query)."""
    parts = urlsplit(path)
    return parts.path, parts.query


# --- historical import surface -------------------------------------
__all__ = [
    "BridgeManager",
    "MAX_CONNECTIONS_PER_USER",
    "_DIAL_ERROR_PREFIX",
    "_PERMANENT_DIAL_CODES",
    "_absolute_peer_url",
    "_advertise_host_label",
    "_annotate_bridge_dial_error",
    "_close_code",
    "_close_frame",
    "_close_reason",
    "_handshake_http_status",
    "_host_label",
    "_is_inbound",
    "_probe_agent_summary",
    "_should_refresh_peer_token",
    "bridge_failure_from_dial",
    "dial_error_note",
    "error_from_dial_note",
    "inbound_default_display_name",
    "observe_ws_client_host",
    "public_base_url_from_config",
    "split_request_path",
]

from octop.infra.bridge.connections import (  # noqa: E402,F401
    MAX_CONNECTIONS_PER_USER,
)
from octop.infra.bridge.dial_errors import (  # noqa: E402,F401
    _DIAL_ERROR_PREFIX,
    _PERMANENT_DIAL_CODES,
)
