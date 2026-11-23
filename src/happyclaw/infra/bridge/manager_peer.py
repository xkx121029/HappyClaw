"""Peer turn protocol: inbound turn dispatch plus peer-side turn, listen and cancel handlers."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

from happyclaw.infra.bridge.ids import (
    format_bridge_agent_id,
    restore_peer_path_ids,
)
from happyclaw.infra.bridge.manager_base import BridgeManagerBase, logger
from happyclaw.infra.bridge.peer_turn import PeerTurnRejected


class BridgePeerMixin(BridgeManagerBase):
    """对端回合协议：入站回合分发，以及对端侧的回合 / 监听 / 取消处理。"""

    async def open_turn_waiter(self, request_id: str) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._turn_waiters[request_id] = q
        return q

    def close_turn_waiter(self, request_id: str) -> None:
        self._turn_waiters.pop(request_id, None)

    async def _handle_inbound_turn(self, connection_id: str, payload: dict[str, Any]) -> None:
        msg_type = str(payload.get("type") or "")
        request_id = str(payload.get("request_id") or "").strip()
        if msg_type in {"turn.chunk", "turn.end", "turn.error"} and request_id:
            q = self._turn_waiters.get(request_id)
            if q is not None:
                await q.put(payload)
            return
        if msg_type == "turn.unlisten" and request_id:
            self._stop_peer_listen(request_id)
            return
        if msg_type == "turn.listen":
            await self._execute_peer_listen(connection_id, payload)
            return
        if msg_type == "turn.start":
            await self._execute_peer_turn(connection_id, payload)
            return
        if msg_type == "turn.cancel":
            await self._execute_peer_cancel(connection_id, payload)
            return
        if msg_type == "turn.steer_remove":
            await self._execute_peer_steer_remove(connection_id, payload)
            return
        if request_id:
            sess = self._sessions.get(connection_id)
            if sess is not None and not sess.closed:
                await sess.send_json(
                    {
                        "type": "turn.error",
                        "request_id": request_id,
                        "message": f"unknown turn type: {msg_type}",
                    }
                )
                await sess.send_json({"type": "turn.end", "request_id": request_id})

    async def _execute_peer_turn(self, connection_id: str, payload: dict[str, Any]) -> None:
        """Peer asked us to run a turn on a local agent; stream chunks back."""
        from happyclaw.infra.gateway.ws import WS_CHANNEL_ID
        from happyclaw.infra.gateway.ws.ws_hub import stamp_thread_id

        request_id = str(payload.get("request_id") or "").strip()
        agent_id = str(payload.get("agent_id") or "").strip()
        sess = self._sessions.get(connection_id)
        if sess is None or not request_id or not agent_id:
            return
        row = self._repo.get(connection_id)
        if row is None:
            return
        if self._asgi_app is None:
            await sess.send_json(
                {
                    "type": "turn.error",
                    "request_id": request_id,
                    "message": "bridge owner unavailable",
                }
            )
            return
        server = self._asgi_app.state.octop_server
        user = (
            server.app_runtime.user_manager.get_by_id(row.owner_user_id)
            if server.app_runtime is not None
            else None
        )
        if user is None:
            await sess.send_json(
                {
                    "type": "turn.error",
                    "request_id": request_id,
                    "message": "bridge owner unavailable",
                }
            )
            return
        assert server.app_runtime is not None
        gateway = server.app_runtime.gateway
        hub = gateway.ws_hub
        channel_manager = gateway.channel_manager
        if channel_manager is None:
            await sess.send_json(
                {
                    "type": "turn.error",
                    "request_id": request_id,
                    "message": "gateway not ready",
                }
            )
            return

        bridge_conn_id = f"bridge-turn-{request_id}"
        chunk_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def send_frame(frame: dict[str, Any]) -> None:
            await chunk_queue.put(frame)

        runner = self._peer_turn_runner
        if runner is None:
            await sess.send_json(
                {
                    "type": "turn.error",
                    "request_id": request_id,
                    "message": "peer turn runner not wired",
                }
            )
            return

        hub.register(bridge_conn_id, send_frame, user_id=user.id)
        try:
            prepared = await runner(
                server=server,
                user=user,
                agent_id=agent_id,
                payload=payload,
                ws_connection_id=bridge_conn_id,
            )
            if prepared.inbound is None:
                # Mid-turn steer: frames already went to the live subscriber.
                await sess.send_json({"type": "turn.end", "request_id": request_id})
                return
            hub.subscribe(prepared.thread_id, bridge_conn_id)
            await sess.send_json(
                {
                    "type": "turn.chunk",
                    "request_id": request_id,
                    "frame": {
                        "type": "thread",
                        "thread_id": prepared.thread_id,
                    },
                }
            )
            channel_manager.enqueue(WS_CHANNEL_ID, prepared.inbound)
            # Host ``turn.ended`` is not the end of a team room. Members flush
            # only after the host goes idle. Keep this subscriber until the
            # hub unlistens, same as a local dashboard socket.
            stop = asyncio.Event()
            self._listen_stops[request_id] = stop

            async def _queue_stop() -> None:
                await stop.wait()
                await chunk_queue.put(None)

            stop_task = asyncio.create_task(_queue_stop())
            try:
                while True:
                    if sess.closed:
                        break
                    item = await chunk_queue.get()
                    if item is None:
                        break
                    if sess.closed:
                        break
                    stamped = stamp_thread_id(item, prepared.thread_id)
                    await sess.send_json(
                        {
                            "type": "turn.chunk",
                            "request_id": request_id,
                            "frame": stamped,
                        }
                    )
                if not sess.closed:
                    await sess.send_json({"type": "turn.end", "request_id": request_id})
            finally:
                stop_task.cancel()
                with suppress(asyncio.CancelledError):
                    await stop_task
                self._listen_stops.pop(request_id, None)
        except PeerTurnRejected as exc:
            await sess.send_json(
                {
                    "type": "turn.error",
                    "request_id": request_id,
                    "message": str(exc)[:500],
                }
            )
        except Exception as exc:
            logger.exception("bridge peer turn failed")
            await sess.send_json(
                {
                    "type": "turn.error",
                    "request_id": request_id,
                    "message": str(exc)[:500],
                }
            )
        finally:
            hub.unregister(bridge_conn_id)

    def _stop_peer_listen(self, request_id: str) -> None:
        stop = self._listen_stops.get(request_id)
        if stop is not None and not stop.is_set():
            stop.set()

    async def _execute_peer_listen(self, connection_id: str, payload: dict[str, Any]) -> None:
        """Subscribe to a peer room so team members / wrap-up keep flowing."""
        from happyclaw.infra.agents.teams.team_manager import (  # noqa: PLC0415
            subscribe_with_member_catchup,
        )
        from happyclaw.infra.gateway.ws.ws_hub import stamp_thread_id

        request_id = str(payload.get("request_id") or "").strip()
        agent_id = str(payload.get("agent_id") or "").strip()
        thread_id = str(payload.get("thread_id") or "").strip()
        sess = self._sessions.get(connection_id)
        if sess is None or not request_id or not agent_id or not thread_id:
            return
        row = self._repo.get(connection_id)
        if row is None:
            return
        if self._asgi_app is None:
            await sess.send_json(
                {
                    "type": "turn.error",
                    "request_id": request_id,
                    "message": "bridge owner unavailable",
                }
            )
            await sess.send_json({"type": "turn.end", "request_id": request_id})
            return
        server = self._asgi_app.state.octop_server
        user = (
            server.app_runtime.user_manager.get_by_id(row.owner_user_id)
            if server.app_runtime is not None
            else None
        )
        if user is None or server.app_runtime is None:
            await sess.send_json(
                {
                    "type": "turn.error",
                    "request_id": request_id,
                    "message": "bridge owner unavailable",
                }
            )
            await sess.send_json({"type": "turn.end", "request_id": request_id})
            return
        gateway = server.app_runtime.gateway
        hub = gateway.ws_hub
        thread_id = restore_peer_path_ids(
            thread_id,
            bridge_agent_id=format_bridge_agent_id(connection_id, agent_id),
            remote_agent_id=agent_id,
        )
        found = gateway.thread_registry.get_thread(thread_id)
        if found is None or found.agent_id != agent_id or found.user_id != user.id:
            await sess.send_json(
                {
                    "type": "turn.error",
                    "request_id": request_id,
                    "message": f"thread {thread_id!r} not found",
                }
            )
            await sess.send_json({"type": "turn.end", "request_id": request_id})
            return

        bridge_conn_id = f"bridge-listen-{request_id}"
        chunk_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        stop = asyncio.Event()
        self._listen_stops[request_id] = stop

        async def send_frame(frame: dict[str, Any]) -> None:
            await chunk_queue.put(frame)

        hub.register(bridge_conn_id, send_frame, user_id=user.id)

        async def _queue_stop() -> None:
            await stop.wait()
            await chunk_queue.put(None)

        stop_task = asyncio.create_task(_queue_stop())
        try:

            async def _send_catchup(frame: dict[str, Any]) -> None:
                await sess.send_json(
                    {
                        "type": "turn.chunk",
                        "request_id": request_id,
                        "frame": stamp_thread_id(frame, thread_id),
                    }
                )

            def _subscribe(tid: str = thread_id, cid: str = bridge_conn_id) -> None:
                hub.subscribe(tid, cid)

            await subscribe_with_member_catchup(
                gateway,
                thread_id,
                subscribe=_subscribe,
                send=_send_catchup,
            )
            await sess.send_json(
                {
                    "type": "turn.chunk",
                    "request_id": request_id,
                    "frame": {
                        "type": "turn_status",
                        "thread_id": thread_id,
                        "active": hub.is_turn_active(thread_id),
                    },
                }
            )
            while not sess.closed:
                item = await chunk_queue.get()
                if item is None:
                    break
                stamped = stamp_thread_id(item, thread_id)
                await sess.send_json(
                    {
                        "type": "turn.chunk",
                        "request_id": request_id,
                        "frame": stamped,
                    }
                )
            if not sess.closed:
                await sess.send_json({"type": "turn.end", "request_id": request_id})
        except Exception:
            logger.exception("bridge peer listen failed")
            if not sess.closed:
                await sess.send_json(
                    {
                        "type": "turn.error",
                        "request_id": request_id,
                        "message": "bridge listen failed",
                    }
                )
                await sess.send_json({"type": "turn.end", "request_id": request_id})
        finally:
            stop_task.cancel()
            with suppress(asyncio.CancelledError):
                await stop_task
            self._listen_stops.pop(request_id, None)
            hub.unregister(bridge_conn_id)

    async def _peer_control_owner(
        self,
        connection_id: str,
        payload: dict[str, Any],
    ) -> tuple[str, str, Any, Any, Any] | None:
        """Resolve ``(request_id, agent_id, sess, user, gateway)`` or fail the request."""
        request_id = str(payload.get("request_id") or "").strip()
        agent_id = str(payload.get("agent_id") or "").strip()
        sess = self._sessions.get(connection_id)
        if sess is None or not request_id or not agent_id:
            return None
        row = self._repo.get(connection_id)
        if row is None:
            return None

        async def _fail(message: str) -> None:
            if sess.closed:
                return
            await sess.send_json(
                {
                    "type": "turn.error",
                    "request_id": request_id,
                    "message": message,
                }
            )
            await sess.send_json({"type": "turn.end", "request_id": request_id})

        if self._asgi_app is None:
            await _fail("bridge owner unavailable")
            return None
        server = self._asgi_app.state.octop_server
        user = (
            server.app_runtime.user_manager.get_by_id(row.owner_user_id)
            if server.app_runtime is not None
            else None
        )
        if user is None or server.app_runtime is None:
            await _fail("bridge owner unavailable")
            return None
        gateway = server.app_runtime.gateway
        return request_id, agent_id, sess, user, gateway

    def _restore_peer_thread_id(
        self,
        connection_id: str,
        agent_id: str,
        thread_id: str,
    ) -> str:
        return restore_peer_path_ids(
            thread_id,
            bridge_agent_id=format_bridge_agent_id(connection_id, agent_id),
            remote_agent_id=agent_id,
        )

    async def _execute_peer_cancel(self, connection_id: str, payload: dict[str, Any]) -> None:
        """Stop the peer stream for a dashboard cancel, matching local WS."""
        resolved = await self._peer_control_owner(connection_id, payload)
        if resolved is None:
            return
        request_id, agent_id, sess, user, gateway = resolved
        thread_id = self._restore_peer_thread_id(
            connection_id,
            agent_id,
            str(payload.get("thread_id") or "").strip(),
        )
        if not thread_id:
            await sess.send_json(
                {
                    "type": "turn.error",
                    "request_id": request_id,
                    "message": "cancel requires thread_id",
                }
            )
            await sess.send_json({"type": "turn.end", "request_id": request_id})
            return
        found = gateway.thread_registry.get_thread(thread_id)
        if found is None or found.agent_id != agent_id or found.user_id != user.id:
            await sess.send_json(
                {
                    "type": "turn.error",
                    "request_id": request_id,
                    "message": f"thread {thread_id!r} not found",
                }
            )
            await sess.send_json({"type": "turn.end", "request_id": request_id})
            return
        gateway.steer.mark_cancelling(thread_id)
        discarded = gateway.steer.discard(thread_id, reason="turn_cancelled")
        if discarded is not None:
            await gateway.ws_hub.push_to_thread(
                thread_id,
                {
                    "type": "steer.discarded",
                    "seq": discarded.seq,
                    "client_pending_ids": discarded.client_pending_ids,
                    "pending_ids": discarded.pending_ids,
                    "turn_id": discarded.turn_id,
                    "reason": discarded.reason,
                    "thread_id": thread_id,
                },
            )
        server = self._asgi_app.state.octop_server if self._asgi_app is not None else None
        if server is not None and server.app_runtime is not None:
            server.app_runtime.agent_registry.cancel_stream(agent_id, thread_id)
        if not sess.closed:
            await sess.send_json({"type": "turn.end", "request_id": request_id})

    async def _execute_peer_steer_remove(self, connection_id: str, payload: dict[str, Any]) -> None:
        """Withdraw a queued steer on the peer, matching local ``steer_remove``."""
        resolved = await self._peer_control_owner(connection_id, payload)
        if resolved is None:
            return
        request_id, agent_id, sess, user, gateway = resolved
        thread_id = self._restore_peer_thread_id(
            connection_id,
            agent_id,
            str(payload.get("thread_id") or "").strip(),
        )
        turn_id = str(payload.get("turn_id") or "").strip()
        client_pending_id = str(payload.get("client_pending_id") or "").strip()
        pending_id = str(payload.get("pending_id") or "").strip()

        async def send_ack(frame: dict[str, Any]) -> None:
            if sess.closed:
                return
            await sess.send_json(
                {
                    "type": "turn.chunk",
                    "request_id": request_id,
                    "frame": frame,
                }
            )

        if not thread_id or not turn_id:
            await send_ack(
                {
                    "type": "steer.ack",
                    "status": "rejected",
                    "reason": "turn_id_required",
                    "client_pending_id": client_pending_id or None,
                    "thread_id": thread_id or None,
                }
            )
            if not sess.closed:
                await sess.send_json({"type": "turn.end", "request_id": request_id})
            return
        found = gateway.thread_registry.get_thread(thread_id)
        if found is None or found.agent_id != agent_id or found.user_id != user.id:
            await send_ack(
                {
                    "type": "steer.ack",
                    "status": "rejected",
                    "reason": "forbidden",
                    "client_pending_id": client_pending_id or None,
                    "thread_id": thread_id,
                }
            )
            if not sess.closed:
                await sess.send_json({"type": "turn.end", "request_id": request_id})
            return
        if not client_pending_id or not pending_id:
            await send_ack(
                {
                    "type": "steer.ack",
                    "status": "rejected",
                    "reason": "client_pending_id_required",
                    "client_pending_id": client_pending_id or None,
                    "thread_id": thread_id,
                }
            )
            if not sess.closed:
                await sess.send_json({"type": "turn.end", "request_id": request_id})
            return
        result = gateway.steer.remove(
            thread_id,
            turn_id=turn_id,
            client_pending_id=client_pending_id,
            pending_id=pending_id,
        )
        await send_ack(
            {
                "type": "steer.ack",
                "status": "removed",
                "turn_id": result.turn_id,
                "pending_id": result.pending_id,
                "client_pending_id": result.client_pending_id,
                "already_drained": result.already_drained or None,
                "already_gone": result.already_gone or None,
                "thread_id": thread_id,
            }
        )
        if result.emit_removed and result.seq is not None:
            await gateway.ws_hub.push_to_thread(
                thread_id,
                {
                    "type": "steer.removed",
                    "seq": result.seq,
                    "client_pending_id": result.client_pending_id,
                    "pending_id": result.pending_id,
                    "turn_id": result.turn_id,
                    "already_drained": result.already_drained or None,
                    "already_gone": result.already_gone or None,
                    "thread_id": thread_id,
                },
            )
        if not sess.closed:
            await sess.send_json({"type": "turn.end", "request_id": request_id})
