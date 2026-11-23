"""Outbound relay: forward local client turns, listens and control frames to the peer."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

from happyclaw.infra.bridge.ids import rewrite_peer_stream_frame
from happyclaw.infra.bridge.manager_base import BridgeManagerBase
from happyclaw.infra.bridge.transport import FEATURE_TURN_CONTROL


class BridgeRelayMixin(BridgeManagerBase):
    """出站中继：把本端客户端的回合、监听与控制帧转发给对端。"""

    async def relay_user_turn(
        self,
        *,
        connection_id: str,
        owner_user_id: int,
        remote_agent_id: str,
        turn_payload: dict[str, Any],
        on_frame: Any,
    ) -> None:
        """Send turn.start to peer and forward turn.chunk frames to ``on_frame``."""
        import uuid

        self.get_usable(connection_id, owner_user_id)
        sess = await self._require_live_session(connection_id)
        request_id = uuid.uuid4().hex
        queue = await self.open_turn_waiter(request_id)
        try:
            await sess.send_json(
                {
                    "type": "turn.start",
                    "request_id": request_id,
                    "agent_id": remote_agent_id,
                    **turn_payload,
                }
            )
            saw_turn_ended = False
            while True:
                try:
                    msg = await sess.next_queue_item(queue, timeout=600.0)
                except TimeoutError:
                    # After host ``turn.ended`` the peer may hold the room
                    # subscriber with no frames for a long time (team idle).
                    if saw_turn_ended:
                        continue
                    raise
                msg_type = str(msg.get("type") or "")
                if msg_type == "turn.chunk":
                    frame = msg.get("frame")
                    if isinstance(frame, dict):
                        rewritten = rewrite_peer_stream_frame(
                            connection_id,
                            frame,
                            remote_agent_id=remote_agent_id,
                        )
                        if str(rewritten.get("type") or "") == "turn.ended":
                            saw_turn_ended = True
                        await on_frame(rewritten)
                elif msg_type == "turn.error":
                    await on_frame(
                        {
                            "type": "error",
                            "message": str(msg.get("message") or "bridge turn error"),
                        }
                    )
                    await on_frame({"type": "done"})
                    return
                elif msg_type == "turn.end":
                    # Older peers stop at harness ``done`` and never send
                    # ``turn.ended``. The dashboard leaves Generating on until
                    # that frame arrives.
                    if not saw_turn_ended:
                        await on_frame({"type": "turn.ended"})
                    return
        except asyncio.CancelledError:
            if not sess.closed:
                with suppress(Exception):
                    await sess.send_json({"type": "turn.unlisten", "request_id": request_id})
            raise
        except (TimeoutError, ConnectionError) as exc:
            await self._unregister_session(connection_id)
            raise self._bridge_link_error(exc) from exc
        finally:
            self.close_turn_waiter(request_id)

    async def relay_user_listen(
        self,
        *,
        connection_id: str,
        owner_user_id: int,
        remote_agent_id: str,
        thread_id: str,
        on_frame: Any,
    ) -> None:
        """Keep a listen-only subscription on the peer room thread."""
        import uuid

        tid = (thread_id or "").strip()
        if not tid:
            return
        self.get_usable(connection_id, owner_user_id)
        sess = await self._require_live_session(connection_id)
        request_id = uuid.uuid4().hex
        queue = await self.open_turn_waiter(request_id)
        try:
            await sess.send_json(
                {
                    "type": "turn.listen",
                    "request_id": request_id,
                    "agent_id": remote_agent_id,
                    "thread_id": tid,
                }
            )
            while True:
                try:
                    msg = await sess.next_queue_item(queue, timeout=600.0)
                except TimeoutError:
                    continue
                msg_type = str(msg.get("type") or "")
                if msg_type == "turn.chunk":
                    frame = msg.get("frame")
                    if isinstance(frame, dict):
                        await on_frame(
                            rewrite_peer_stream_frame(
                                connection_id,
                                frame,
                                remote_agent_id=remote_agent_id,
                            )
                        )
                elif msg_type == "turn.error":
                    await on_frame(
                        {
                            "type": "error",
                            "message": str(msg.get("message") or "bridge listen error"),
                        }
                    )
                    return
                elif msg_type == "turn.end":
                    return
        except asyncio.CancelledError:
            if not sess.closed:
                with suppress(Exception):
                    await sess.send_json({"type": "turn.unlisten", "request_id": request_id})
            raise
        except (TimeoutError, ConnectionError) as exc:
            await self._unregister_session(connection_id)
            raise self._bridge_link_error(exc) from exc
        finally:
            self.close_turn_waiter(request_id)

    async def _relay_turn_control(
        self,
        *,
        connection_id: str,
        owner_user_id: int,
        remote_agent_id: str,
        msg_type: str,
        payload: dict[str, Any],
        on_frame: Any,
    ) -> None:
        """One-shot peer control (cancel / steer_remove) with chunk forwarding."""
        import uuid

        self.get_usable(connection_id, owner_user_id)
        sess = await self._require_live_session(connection_id)
        if FEATURE_TURN_CONTROL not in sess.peer_features:
            await on_frame(
                {
                    "type": "error",
                    "message": f"peer does not support {msg_type}",
                }
            )
            return
        request_id = uuid.uuid4().hex
        queue = await self.open_turn_waiter(request_id)
        try:
            await sess.send_json(
                {
                    "type": msg_type,
                    "request_id": request_id,
                    "agent_id": remote_agent_id,
                    **payload,
                }
            )
            while True:
                msg = await sess.next_queue_item(queue, timeout=30.0)
                msg_kind = str(msg.get("type") or "")
                if msg_kind == "turn.chunk":
                    frame = msg.get("frame")
                    if isinstance(frame, dict):
                        await on_frame(
                            rewrite_peer_stream_frame(
                                connection_id,
                                frame,
                                remote_agent_id=remote_agent_id,
                            )
                        )
                elif msg_kind == "turn.error":
                    await on_frame(
                        {
                            "type": "error",
                            "message": str(msg.get("message") or "bridge control error"),
                        }
                    )
                    return
                elif msg_kind == "turn.end":
                    return
        except (TimeoutError, ConnectionError) as exc:
            await self._unregister_session(connection_id)
            raise self._bridge_link_error(exc) from exc
        finally:
            self.close_turn_waiter(request_id)

    async def relay_turn_cancel(
        self,
        *,
        connection_id: str,
        owner_user_id: int,
        remote_agent_id: str,
        thread_id: str,
        on_frame: Any,
    ) -> None:
        """Ask the peer to cancel the live stream for ``thread_id``."""
        tid = (thread_id or "").strip()
        if not tid:
            await on_frame({"type": "error", "message": "cancel requires thread_id"})
            return
        await self._relay_turn_control(
            connection_id=connection_id,
            owner_user_id=owner_user_id,
            remote_agent_id=remote_agent_id,
            msg_type="turn.cancel",
            payload={"thread_id": tid},
            on_frame=on_frame,
        )

    async def relay_turn_steer_remove(
        self,
        *,
        connection_id: str,
        owner_user_id: int,
        remote_agent_id: str,
        payload: dict[str, Any],
        on_frame: Any,
    ) -> None:
        """Ask the peer to withdraw a queued mid-turn steer."""
        await self._relay_turn_control(
            connection_id=connection_id,
            owner_user_id=owner_user_id,
            remote_agent_id=remote_agent_id,
            msg_type="turn.steer_remove",
            payload={
                key: payload[key]
                for key in ("thread_id", "turn_id", "client_pending_id", "pending_id")
                if isinstance(payload.get(key), str) and str(payload[key]).strip()
            },
            on_frame=on_frame,
        )

    # -- browser stream relay ------------------------------------------------
