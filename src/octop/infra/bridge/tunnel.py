"""HTTP tunnel plus the remote getters built on it."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from octop.infra.bridge.http_tunnel import decode_body_b64, execute_local_http
from octop.infra.bridge.icons import rewrite_remote_icon_url
from octop.infra.bridge.identity import (
    _is_inbound,
)
from octop.infra.bridge.ids import (
    format_bridge_agent_id,
    rewrite_peer_agent_ids,
)
from octop.infra.bridge.manager_base import BridgeManagerBase
from octop.infra.bridge.transport import (
    BRIDGE_TUNNEL_CHUNKED_MAX_BODY_BYTES,
    BRIDGE_TUNNEL_MAX_BODY_BYTES,
    FEATURE_BODY_CHUNKS,
)
from octop.infra.errors import ErrorCode, OctopError

logger = logging.getLogger(__name__)


class PeerTunnelMixin(BridgeManagerBase):
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
    ) -> httpx.Response:
        from octop.infra.bridge.tunnel_policy import (  # noqa: PLC0415
            is_tunnel_path_allowed,
            shared_viewer_may_tunnel,
        )

        row = self.get_usable(connection_id, owner_user_id)
        # The peer runs this hop as the connection owner. A shared recipient
        # may chat and read, not edit / start / reload / delete the expert.
        if int(row.owner_user_id) != int(owner_user_id) and not shared_viewer_may_tunnel(
            method, path
        ):
            raise OctopError(
                ErrorCode.FORBIDDEN,
                "shared cloud collab users cannot manage this expert",
            )
        # Fail fast with a user-facing "unsupported on remote" code before the hop.
        if not is_tunnel_path_allowed(method, path):
            raise OctopError(
                ErrorCode.BRIDGE_REMOTE_UNSUPPORTED,
                "This action is not available through the remote bridge. Manage it on the peer HappyClaw.",
            )
        sess = await self._require_live_session(connection_id)
        if body:
            chunked = FEATURE_BODY_CHUNKS in sess.peer_features
            limit = (
                BRIDGE_TUNNEL_CHUNKED_MAX_BODY_BYTES if chunked else BRIDGE_TUNNEL_MAX_BODY_BYTES
            )
            if len(body) > limit:
                max_mb = max(1, limit // (1024 * 1024))
                raise OctopError(
                    ErrorCode.ATTACHMENT_TOO_LARGE,
                    f"file too large (max {max_mb}MB)",
                    details={"max_mb": max_mb},
                )
        try:
            result = await sess.tunnel_request(
                method=method,
                path=path,
                query=query,
                headers=headers,
                body=body,
            )
        except (TimeoutError, ConnectionError) as exc:
            # Only drop the socket that failed. A replacement for this id must stay up.
            await self._unregister_session(connection_id, expected=sess)
            raise self._bridge_link_error(exc) from exc
        if str(result.get("type") or "") == "tunnel.error":
            code_raw = str(result.get("code") or "").strip()
            logger.warning(
                "bridge peer tunnel rejected connection=%s method=%s path=%s code=%s",
                connection_id,
                method,
                path,
                code_raw or "unknown",
            )
            if code_raw == ErrorCode.BRIDGE_REMOTE_UNSUPPORTED.value:
                raise OctopError(
                    ErrorCode.BRIDGE_REMOTE_UNSUPPORTED,
                    "This action is not available through the remote bridge. Manage it on the peer HappyClaw.",
                )
            raise OctopError(
                ErrorCode.BRIDGE_TUNNEL_FAILED,
                str(result.get("message") or "tunnel error"),
            )
        status = int(result.get("status") or 502)
        hdrs = result.get("headers") if isinstance(result.get("headers"), dict) else {}
        content = decode_body_b64(result)
        return httpx.Response(status, headers=hdrs, content=content)

    async def _owner_access_token(self, connection_id: str) -> str:
        row = self._repo.get(connection_id)
        if row is None:
            raise OctopError(ErrorCode.BRIDGE_NOT_FOUND, "bridge connection not found")
        if self._token_signer is None:
            raise OctopError(ErrorCode.INTERNAL_ERROR, "bridge token signer not configured")
        user = self._users.get(row.owner_user_id)
        if user is None:
            raise OctopError(ErrorCode.BRIDGE_NOT_FOUND, "bridge owner missing")
        return str(self._token_signer(user))

    async def _handle_inbound_tunnel(
        self, connection_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if self._asgi_app is None:
            raise RuntimeError("ASGI app not bound")
        token = await self._owner_access_token(connection_id)
        method = str(payload.get("method") or "GET")
        path = str(payload.get("path") or "/")
        query = str(payload.get("query") or "")
        headers_raw = payload.get("headers")
        headers: dict[str, Any] = headers_raw if isinstance(headers_raw, dict) else {}
        body = decode_body_b64(payload)
        return await execute_local_http(
            app=self._asgi_app,
            method=method,
            path=path,
            query=query,
            headers={str(k): str(v) for k, v in headers.items()},
            body=body,
            access_token=token,
        )

    async def list_remote_agents(
        self, connection_id: str, *, owner_user_id: int
    ) -> list[dict[str, Any]]:
        row = self.get_owned(connection_id, owner_user_id)
        resp = await self.tunnel_http(
            connection_id=connection_id,
            owner_user_id=owner_user_id,
            method="GET",
            path="/api/agents",
            query="scope=mine",
        )
        if resp.status_code >= 400:
            raise OctopError(
                ErrorCode.BRIDGE_TUNNEL_FAILED,
                f"peer agents HTTP {resp.status_code}: {resp.text[:200]}",
            )
        data = resp.json()
        if not isinstance(data, list):
            raise OctopError(ErrorCode.BRIDGE_TUNNEL_FAILED, "peer agents payload invalid")
        out: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            # Prefer public agent_id; integer ``id`` is the DB surrogate PK.
            remote_id = str(item.get("agent_id") or item.get("id") or "").strip()
            if not remote_id:
                continue
            mapped = dict(item)
            mapped["id"] = format_bridge_agent_id(connection_id, remote_id)
            mapped["agent_id"] = mapped["id"]
            mapped["bridge_connection_id"] = connection_id
            mapped["bridge_connection_name"] = row.display_name
            mapped["remote_agent_id"] = remote_id
            mapped["bridge"] = True
            mapped["bridge_inbound"] = _is_inbound(row)
            # scope=mine also includes experts shared by other users. Keep the
            # peer account's ownership so mutation controls are shown only for
            # peer-owned rows. Older peers may omit this field; fail closed so
            # the UI does not offer an action that the peer will reject.
            mapped["is_owner"] = item.get("is_owner") is True
            mapped["is_shared"] = bool(item.get("is_shared"))
            # Keep the peer runtime state. A stopped expert must not look chat-ready
            # just because the bridge link itself is up.
            raw_state = item.get("state")
            state = raw_state.strip() if isinstance(raw_state, str) else ""
            mapped["state"] = state or "stopped"
            # Keep bundled /experts/avatars and CDN URLs; proxy uploaded avatars.
            mapped["icon_url"] = rewrite_remote_icon_url(
                str(mapped.get("icon_url") or mapped.get("icon") or "").strip() or None,
                remote_agent_id=remote_id,
                bridge_agent_id=str(mapped["id"]),
            )
            members = mapped.get("member_ids")
            if isinstance(members, list):
                mapped["member_ids"] = rewrite_peer_agent_ids(connection_id, members)
            out.append(mapped)
        return out

    async def tunnel_json_get(
        self,
        connection_id: str,
        *,
        owner_user_id: int,
        path: str,
        query: str = "",
    ) -> Any:
        """GET a JSON body from the peer via the HTTP tunnel."""
        resp = await self.tunnel_http(
            connection_id=connection_id,
            owner_user_id=owner_user_id,
            method="GET",
            path=path,
            query=query,
        )
        if resp.status_code >= 400:
            raise OctopError(
                ErrorCode.BRIDGE_TUNNEL_FAILED,
                f"peer {path} HTTP {resp.status_code}: {resp.text[:200]}",
            )
        try:
            return resp.json()
        except Exception as exc:
            raise OctopError(
                ErrorCode.BRIDGE_TUNNEL_FAILED,
                f"peer {path} returned invalid JSON",
            ) from exc

    async def list_remote_resolved_models(
        self, connection_id: str, *, owner_user_id: int
    ) -> list[dict[str, Any]]:
        data = await self.tunnel_json_get(
            connection_id,
            owner_user_id=owner_user_id,
            path="/api/providers/resolved",
        )
        if not isinstance(data, list):
            raise OctopError(
                ErrorCode.BRIDGE_TUNNEL_FAILED,
                "peer providers/resolved payload invalid",
            )
        return [item for item in data if isinstance(item, dict)]

    async def get_remote_active_model(
        self, connection_id: str, *, owner_user_id: int
    ) -> dict[str, Any]:
        data = await self.tunnel_json_get(
            connection_id,
            owner_user_id=owner_user_id,
            path="/api/providers/active-model",
        )
        if not isinstance(data, dict):
            raise OctopError(
                ErrorCode.BRIDGE_TUNNEL_FAILED,
                "peer providers/active-model payload invalid",
            )
        return data

    async def list_remote_knowledge_bases(
        self, connection_id: str, *, owner_user_id: int
    ) -> list[dict[str, Any]]:
        data = await self.tunnel_json_get(
            connection_id,
            owner_user_id=owner_user_id,
            path="/api/knowledge-bases",
        )
        if not isinstance(data, list):
            raise OctopError(
                ErrorCode.BRIDGE_TUNNEL_FAILED,
                "peer knowledge-bases payload invalid",
            )
        return [item for item in data if isinstance(item, dict)]

    async def get_remote_knowledge_capability(
        self, connection_id: str, *, owner_user_id: int
    ) -> dict[str, Any]:
        data = await self.tunnel_json_get(
            connection_id,
            owner_user_id=owner_user_id,
            path="/api/knowledge-bases/capability",
        )
        if not isinstance(data, dict):
            raise OctopError(
                ErrorCode.BRIDGE_TUNNEL_FAILED,
                "peer knowledge-bases/capability payload invalid",
            )
        return data

    async def get_remote_browser_env_status(
        self, connection_id: str, *, owner_user_id: int
    ) -> dict[str, Any]:
        data = await self.tunnel_json_get(
            connection_id,
            owner_user_id=owner_user_id,
            path="/api/browser/env-status",
        )
        if not isinstance(data, dict):
            raise OctopError(
                ErrorCode.BRIDGE_TUNNEL_FAILED,
                "peer browser/env-status payload invalid",
            )
        return data

    async def get_remote_browser_sessions(
        self, connection_id: str, *, owner_user_id: int
    ) -> dict[str, Any]:
        data = await self.tunnel_json_get(
            connection_id,
            owner_user_id=owner_user_id,
            path="/api/browser/harness-sessions",
        )
        if not isinstance(data, dict):
            raise OctopError(
                ErrorCode.BRIDGE_TUNNEL_FAILED,
                "peer browser/harness-sessions payload invalid",
            )
        return data

    async def post_remote_browser_handoff(
        self,
        connection_id: str,
        *,
        owner_user_id: int,
        session_id: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        sid = (session_id or "").strip()
        if not sid or "/" in sid or ".." in sid:
            raise OctopError(ErrorCode.BRIDGE_TUNNEL_FAILED, "invalid browser session_id")
        raw = json.dumps(body).encode("utf-8")
        resp = await self.tunnel_http(
            connection_id=connection_id,
            owner_user_id=owner_user_id,
            method="POST",
            path=f"/api/browser/sessions/{sid}/handoff",
            headers={"content-type": "application/json"},
            body=raw,
        )
        if resp.status_code >= 400:
            raise OctopError(
                ErrorCode.BRIDGE_TUNNEL_FAILED,
                f"peer browser handoff HTTP {resp.status_code}: {resp.text[:200]}",
            )
        try:
            data = resp.json()
        except Exception as exc:
            raise OctopError(
                ErrorCode.BRIDGE_TUNNEL_FAILED,
                "peer browser handoff returned invalid JSON",
            ) from exc
        if not isinstance(data, dict):
            raise OctopError(
                ErrorCode.BRIDGE_TUNNEL_FAILED,
                "peer browser handoff payload invalid",
            )
        return data
