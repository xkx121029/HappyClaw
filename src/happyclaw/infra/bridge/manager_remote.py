"""Remote peer resources tunnelled over a live bridge connection."""

from __future__ import annotations

import json
from typing import Any

from happyclaw.infra.bridge.icons import rewrite_remote_icon_url
from happyclaw.infra.bridge.ids import (
    format_bridge_agent_id,
    rewrite_peer_agent_ids,
)
from happyclaw.infra.bridge.manager_base import BridgeManagerBase
from happyclaw.infra.bridge.peer_identity import _is_inbound
from happyclaw.infra.errors import (
    ErrorCode,
    HappyclawError,
)


class BridgeRemoteMixin(BridgeManagerBase):
    """经桥接连结访问对端资源：智能体、模型、知识库与浏览器状态。"""

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
            raise HappyclawError(
                ErrorCode.BRIDGE_TUNNEL_FAILED,
                f"peer agents HTTP {resp.status_code}: {resp.text[:200]}",
            )
        data = resp.json()
        if not isinstance(data, list):
            raise HappyclawError(ErrorCode.BRIDGE_TUNNEL_FAILED, "peer agents payload invalid")
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
            raise HappyclawError(
                ErrorCode.BRIDGE_TUNNEL_FAILED,
                f"peer {path} HTTP {resp.status_code}: {resp.text[:200]}",
            )
        try:
            return resp.json()
        except Exception as exc:
            raise HappyclawError(
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
            raise HappyclawError(
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
            raise HappyclawError(
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
            raise HappyclawError(
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
            raise HappyclawError(
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
            raise HappyclawError(
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
            raise HappyclawError(
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
            raise HappyclawError(ErrorCode.BRIDGE_TUNNEL_FAILED, "invalid browser session_id")
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
            raise HappyclawError(
                ErrorCode.BRIDGE_TUNNEL_FAILED,
                f"peer browser handoff HTTP {resp.status_code}: {resp.text[:200]}",
            )
        try:
            data = resp.json()
        except Exception as exc:
            raise HappyclawError(
                ErrorCode.BRIDGE_TUNNEL_FAILED,
                "peer browser handoff returned invalid JSON",
            ) from exc
        if not isinstance(data, dict):
            raise HappyclawError(
                ErrorCode.BRIDGE_TUNNEL_FAILED,
                "peer browser handoff payload invalid",
            )
        return data

    # -- chat turn relay -----------------------------------------------------
