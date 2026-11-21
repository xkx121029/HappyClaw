"""Peer browser relay: handoff, streaming and waiters."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any

from octop.infra.bridge.manager_base import BridgeManagerBase

logger = logging.getLogger(__name__)


class PeerBrowserMixin(BridgeManagerBase):
    async def open_browser_waiter(self, request_id: str) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._browser_waiters[request_id] = q
        return q

    def close_browser_waiter(self, request_id: str) -> None:
        self._browser_waiters.pop(request_id, None)

    async def _handle_inbound_browser(self, connection_id: str, payload: dict[str, Any]) -> None:
        msg_type = str(payload.get("type") or "")
        request_id = str(payload.get("request_id") or "").strip()
        if msg_type in {"browser.server", "browser.error"} and request_id:
            q = self._browser_waiters.get(request_id)
            if q is not None:
                await q.put(payload)
            return
        if msg_type == "browser.end" and request_id:
            q = self._browser_waiters.get(request_id)
            if q is not None:
                await q.put(payload)
            client_q = self._browser_peer_clients.get(request_id)
            if client_q is not None:
                await client_q.put({"type": "stop"})
            return
        if msg_type == "browser.client" and request_id:
            client_q = self._browser_peer_clients.get(request_id)
            if client_q is not None:
                message = payload.get("message")
                if isinstance(message, dict):
                    await client_q.put(message)
            return
        if msg_type == "browser.start":
            asyncio.create_task(
                self._execute_peer_browser(connection_id, payload),
                name=f"bridge-browser-{request_id or 'unknown'}",
            )

    async def _execute_peer_browser(self, connection_id: str, payload: dict[str, Any]) -> None:
        """Peer asked us to attach to the local browser harness and stream frames."""
        request_id = str(payload.get("request_id") or "").strip()
        sess = self._sessions.get(connection_id)
        if sess is None or not request_id:
            return
        row = self._repo.get(connection_id)
        if row is None:
            return
        user = self._users.get(row.owner_user_id)
        if user is None:
            await sess.send_json(
                {
                    "type": "browser.error",
                    "request_id": request_id,
                    "message": "bridge owner unavailable",
                }
            )
            await sess.send_json({"type": "browser.end", "request_id": request_id})
            return

        client_q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._browser_peer_clients[request_id] = client_q
        closed = False

        async def send_json(frame: dict[str, Any]) -> None:
            if closed or sess.closed:
                return
            await sess.send_json(
                {
                    "type": "browser.server",
                    "request_id": request_id,
                    "frame": frame,
                }
            )

        def is_connected() -> bool:
            return not closed and not sess.closed

        async def receive_text() -> Any:
            item = await client_q.get()
            if item is None:
                return {"type": "stop"}
            return item

        start_msg = payload.get("start")
        if not isinstance(start_msg, dict):
            start_msg = {"type": "start", "url": "", "reuse_session": True}
        else:
            start_msg = {**start_msg, "type": "start"}

        runner = self._peer_browser_runner
        if runner is None:
            await sess.send_json(
                {
                    "type": "browser.error",
                    "request_id": request_id,
                    "message": "peer browser runner not wired",
                }
            )
            await sess.send_json({"type": "browser.end", "request_id": request_id})
            return

        try:
            await runner(
                send_json=send_json,
                is_connected=is_connected,
                receive_text=receive_text,
                user_id=int(user.id),
                listen_only=bool(payload.get("listen_only")),
                default_width=int(payload.get("width") or 1280),
                default_height=int(payload.get("height") or 800),
                start_msg=start_msg,
            )
        except Exception as exc:
            logger.exception("bridge peer browser stream failed")
            with suppress(Exception):
                await sess.send_json(
                    {
                        "type": "browser.error",
                        "request_id": request_id,
                        "message": str(exc)[:500],
                    }
                )
        finally:
            closed = True
            self._browser_peer_clients.pop(request_id, None)
            with suppress(Exception):
                await sess.send_json({"type": "browser.end", "request_id": request_id})

    async def relay_browser_stream(
        self,
        *,
        connection_id: str,
        owner_user_id: int,
        listen_only: bool,
        width: int,
        height: int,
        on_frame: Any,
        client_messages: asyncio.Queue[dict[str, Any] | None],
    ) -> None:
        """Relay dashboard browser WS traffic to the peer harness."""
        import uuid

        self.get_usable(connection_id, owner_user_id)
        sess = await self._require_live_session(connection_id)
        request_id = uuid.uuid4().hex
        queue = await self.open_browser_waiter(request_id)

        forward_task: asyncio.Task[None] | None = None

        async def forward_client() -> None:
            while True:
                msg = await client_messages.get()
                if msg is None:
                    await sess.send_json({"type": "browser.end", "request_id": request_id})
                    return
                if msg.get("type") == "start":
                    # Already sent in browser.start; ignore duplicate.
                    continue
                await sess.send_json(
                    {
                        "type": "browser.client",
                        "request_id": request_id,
                        "message": msg,
                    }
                )

        try:
            # Wait for the client's start message before opening the peer stream.
            first = await asyncio.wait_for(client_messages.get(), timeout=15.0)
            if first is None:
                return
            if not isinstance(first, dict) or first.get("type") != "start":
                await on_frame({"type": "error", "message": "expected start message"})
                return

            await sess.send_json(
                {
                    "type": "browser.start",
                    "request_id": request_id,
                    "listen_only": listen_only,
                    "width": width,
                    "height": height,
                    "start": first,
                }
            )
            forward_task = asyncio.create_task(forward_client())

            while True:
                msg = await sess.next_queue_item(queue, timeout=600.0)
                msg_type = str(msg.get("type") or "")
                if msg_type == "browser.server":
                    frame = msg.get("frame")
                    if isinstance(frame, dict):
                        await on_frame(frame)
                elif msg_type == "browser.error":
                    await on_frame(
                        {
                            "type": "error",
                            "message": str(msg.get("message") or "bridge browser error"),
                        }
                    )
                    await on_frame({"type": "status", "status": "error"})
                    break
                elif msg_type == "browser.end":
                    break
        except (TimeoutError, ConnectionError):
            await on_frame({"type": "error", "message": "bridge browser timed out"})
            await on_frame({"type": "status", "status": "error"})
            with suppress(Exception):
                await self._unregister_session(connection_id)
        finally:
            self.close_browser_waiter(request_id)
            if forward_task is not None:
                forward_task.cancel()
                with suppress(asyncio.CancelledError):
                    await forward_task
            with suppress(Exception):
                await sess.send_json({"type": "browser.end", "request_id": request_id})
