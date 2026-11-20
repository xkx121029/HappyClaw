"""Bao companion API: cross-project status and task dispatch.

Bao is the dashboard's always-on companion. Everything returned here is read
from the same registries the chat page uses (agent registry, thread registry,
WebSocket hub, HITL store), so the panel never shows optimistic placeholder
state. Dispatch reuses the chat turn preparation path and the existing WS
channel queue instead of introducing a second execution route.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import PurePosixPath
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from octop.api.common.agent import require_agent_row
from octop.api.deps import current_user, get_server
from octop.api.routers.chat.models import ChatTurnBody
from octop.api.routers.chat.turn import (
    build_dashboard_inbound,
    prepare_dashboard_turn,
    turn_has_content,
)
from octop.infra.agents.teams.service import is_team_agent
from octop.infra.agents.workspace.dir import workspace_dir_from_config_json
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.gateway.threads import (
    ThreadRegistry,
    thread_row_has_messages,
    thread_visible_to,
)
from octop.infra.gateway.ws.ws_channel import WS_CHANNEL_ID
from octop.infra.utils.host_dirs import host_path_text
from octop.infra.utils.llm_text import ainvoke_text

router = APIRouter()
logger = logging.getLogger(__name__)

DEFAULT_PROJECT_KEY = "default"
DEFAULT_SESSION_LIMIT = 20
MAX_SESSION_LIMIT = 100
_BUSY_STATES = frozenset({"running", "working"})


class BaoDispatchBody(BaseModel):
    """A single task dispatched by Bao.

    ``thread_id`` may be omitted: Bao then creates a fresh dashboard thread for
    the agent and delivers the task into it, so the panel does not need a
    separate create-then-send round trip.
    """

    agent_id: str = Field(min_length=1)
    thread_id: str | None = Field(default=None, description="Target conversation; omit to create one")
    text: str = Field(min_length=1, max_length=20_000)
    route_reason: dict[str, Any] | None = Field(
        default=None, description="Router decision persisted for audit"
    )
    source: str = Field(default="bao", max_length=32)


class BaoTaskImportBody(BaseModel):
    """One-time import of dispatch records kept in browser storage."""

    tasks: list[dict[str, Any]] = Field(default_factory=list, max_length=50)


class BaoChatBody(BaseModel):
    """One turn of the ongoing conversation with Bao.

    Bao answers, resolves references to earlier tasks and may dispatch through
    the same path as ``/dispatch``. It never reads files or runs commands.
    """

    text: str = Field(min_length=1, max_length=20_000)
    scope: Literal["global", "project"] = "global"
    project_key: str | None = None
    agent_id: str | None = Field(default=None, description="Manual target override")
    thread_id: str | None = None


class BaoSettingsBody(BaseModel):
    proactive_muted: bool | None = None
    name: str | None = None
    identity_set: bool | None = None
    onboarding_done: bool | None = None
    shape: str | None = None
    color: str | None = None
    body_color: str | None = None
    eye_color: str | None = None
    follow_theme: bool | None = None


BAO_PREFS_KEY = "bao"
DEFAULT_BAO_NAME = "宝"
DEFAULT_BAO_SHAPE = "pebble"
DEFAULT_BAO_COLOR = "black"
BAO_NAME_MAX = 24
BAO_LOOK_MAX = 32
_BAO_LOOK_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_BAO_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_UNSET: Any = object()
CHAT_HISTORY_LIMIT = 30
CHAT_CONTEXT_MESSAGES = 12

_WAIT_MARKERS = ("再等", "等等", "等一下", "先等", "稍等")
_OVERVIEW_MARKERS = ("有哪些项目", "有什么项目", "项目有哪些", "看看项目", "有哪些工作区")
_STATUS_MARKERS = (
    "怎么样了",
    "怎么样",
    "进度",
    "完成了吗",
    "完成没",
    "好了吗",
    "做到哪",
    "状态",
)
_ALSO_MARKERS = ("把那个也", "也一起", "一起做", "顺便把", "那个也")
_RETRY_MARKERS = ("再试一次", "重试", "继续那个")
_CANCEL_MARKERS = ("算了", "不用了", "取消")
_TARGET_PREFIXES = ("派给", "交给")

_REPLY_TEXT = {
    "wait": "好，我继续盯着。完成、卡住或需要你决定时我再叫你。",
    "cancel": "好，这条我不再跟了。",
    "no_task": "我这边还没有可以接着做的任务，先告诉我要做什么。",
    "clarify": "要把这件事派给哪个项目或专家？",
    "busy": "那个会话还在回复中，等这一回合结束我再派。",
    "dispatch": "已经派给 {agent}，我盯着进度，有结果或卡住会告诉你。",
    "team_member": "「{agent}」是团队「{team}」的成员，不能直接派活；请派给这个团队，或该项目里的会话。",
    "overview": "现在有 {count} 个项目，共 {agents} 位专家。{names}",
    "status_empty": "目前还没有派出去的任务。",
    "status": "最近的任务：{summary}",
}


def _json_object(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _bao_section(server: Any, user: Any) -> dict[str, Any]:
    row = server.services.user_repo.get(user.id)
    data = _json_object(getattr(row, "preferences_json", None) if row is not None else None)
    section = data.get(BAO_PREFS_KEY)
    return dict(section) if isinstance(section, dict) else {}


def _look_id(value: Any, fallback: str) -> str:
    """Return a stored engine id, or the default when the value is unusable."""
    if isinstance(value, str) and _BAO_LOOK_RE.match(value):
        return value
    return fallback


def _hex_or_none(value: Any) -> str | None:
    """Stored custom colours may predate validation; keep valid ones only."""
    if isinstance(value, str) and _BAO_HEX_RE.match(value.strip()):
        return value.strip().lower()
    return None


def _bao_settings(server: Any, user: Any) -> dict[str, Any]:
    section = _bao_section(server, user)
    name = section.get("name")
    return {
        "proactive_muted": bool(section.get("proactive_muted")),
        "name": name.strip() if isinstance(name, str) and name.strip() else DEFAULT_BAO_NAME,
        "identity_set": bool(section.get("identity_set")),
        "onboarding_done": bool(section.get("onboarding_done")),
        "shape": _look_id(section.get("shape"), DEFAULT_BAO_SHAPE),
        "color": _look_id(section.get("color"), DEFAULT_BAO_COLOR),
        "body_color": _hex_or_none(section.get("body_color")),
        "eye_color": _hex_or_none(section.get("eye_color")),
        "follow_theme": bool(section.get("follow_theme")),
    }


def _set_bao_settings(
    server: Any,
    user: Any,
    *,
    muted: bool | None = None,
    name: str | None = None,
    identity_set: bool | None = None,
    onboarding_done: bool | None = None,
    shape: str | None = None,
    color: str | None = None,
    body_color: Any = _UNSET,
    eye_color: Any = _UNSET,
    follow_theme: bool | None = None,
) -> dict[str, Any]:
    row = server.services.user_repo.get(user.id)
    data = _json_object(getattr(row, "preferences_json", None) if row is not None else None)
    section = data.get(BAO_PREFS_KEY)
    merged = dict(section) if isinstance(section, dict) else {}
    if muted is not None:
        merged["proactive_muted"] = bool(muted)
    if name is not None:
        cleaned = " ".join(name.split())
        if not cleaned:
            raise OctopError(ErrorCode.SLASH_BAD_ARGS, "assistant name must not be blank")
        if len(cleaned) > BAO_NAME_MAX:
            raise OctopError(
                ErrorCode.SLASH_BAD_ARGS,
                f"assistant name must be at most {BAO_NAME_MAX} characters",
            )
        merged["name"] = cleaned
        merged["identity_set"] = True
    if identity_set is not None:
        merged["identity_set"] = bool(identity_set)
    if onboarding_done is not None:
        merged["onboarding_done"] = bool(onboarding_done)
    for field, value in (("shape", shape), ("color", color)):
        if value is None:
            continue
        cleaned = value.strip()
        if not _BAO_LOOK_RE.match(cleaned):
            raise OctopError(
                ErrorCode.SLASH_BAD_ARGS,
                f"assistant {field} must be a mascot engine id",
            )
        merged[field] = cleaned
    for field, value in (("body_color", body_color), ("eye_color", eye_color)):
        if value is _UNSET:
            continue
        if value is None:
            merged.pop(field, None)
            continue
        if not isinstance(value, str) or not _BAO_HEX_RE.match(value.strip()):
            raise OctopError(
                ErrorCode.SLASH_BAD_ARGS,
                f"assistant {field} must be a #rrggbb colour",
            )
        merged[field] = value.strip().lower()
    if follow_theme is not None:
        merged["follow_theme"] = bool(follow_theme)
    data[BAO_PREFS_KEY] = merged
    server.services.user_repo.set_preferences_json(
        user.id, json.dumps(data, ensure_ascii=False)
    )
    return _bao_settings(server, user)


def _reply(code: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    template = _REPLY_TEXT.get(code, "")
    return {
        "reply_code": code,
        "reply_params": params,
        "reply_text": template.format(**params) if params else template,
    }


def _match_any(text_cf: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text_cf for marker in markers)


def _chat_tasks(server: Any, user: Any, limit: int = 3) -> list[dict[str, Any]]:
    rows = server.services.bao_task_repo.list_for_user(user.id, limit=limit)
    return [row.to_dict() for row in rows]


def _task_summary(tasks: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for task in tasks:
        label = {
            "running": "进行中",
            "awaiting": "等你审批",
            "done": "已完成",
            "failed": "失败",
        }.get(str(task.get("status")), str(task.get("status")))
        detail = str(task.get("result_text") or task.get("error_text") or "").strip()
        detail = detail[:80]
        parts.append(
            f"{task.get('agent_name') or task.get('agent_id')}「{task.get('task_text')}」{label}"
            + (f"：{detail}" if detail else "")
        )
    return "；".join(parts)


def _referenced_task(
    server: Any, user: Any, history: list[Any]
) -> dict[str, Any] | None:
    """Resolve "刚才那个" using message refs first, then the ledger."""
    repo = server.services.bao_task_repo
    for message in reversed(history):
        refs = message.refs() if hasattr(message, "refs") else {}
        task_id = refs.get("task_id") or getattr(message, "task_id", None)
        if task_id:
            row = repo.get(str(task_id))
            if row is not None:
                return row.to_dict()
    rows = repo.list_for_user(user.id, limit=1)
    return rows[0].to_dict() if rows else None


def _pending_clarify(history: list[Any]) -> dict[str, Any] | None:
    for message in reversed(history):
        if getattr(message, "intent", "") != "clarify":
            continue
        refs = message.refs() if hasattr(message, "refs") else {}
        if isinstance(refs.get("pending_text"), str) and refs["pending_text"].strip():
            return refs
    return None


def _agent_from_text(
    server: Any, user: Any, text_cf: str
) -> tuple[str, str] | None:
    """Deterministic ``(agent_id, agent_name)`` lookup from a target reply."""
    for row in _visible_agent_rows(server, user):
        name = str(row.name or "").strip()
        if name and name.casefold() in text_cf:
            return row.agent_id, name
    return None


def _norm_path(value: str) -> str:
    text = str(value or "").replace("\\", "/").rstrip("/")
    # Windows paths are case-insensitive; compare them the same way Chat's
    # workspace grouping does so two agents on the same folder share a project.
    return text.casefold() if os.name == "nt" else text


def project_identity(workspace_dir: str, default_root: str) -> tuple[str, str, bool]:
    """Map a workspace folder to ``(key, name, is_default)``.

    Agents whose workspace lives under ``{OCTOP_HOME}/agents`` (the create-time
    default) are grouped into the default project, mirroring the dashboard's
    sidebar grouping. Explicit workspace folders become their own project.
    """
    normalized = _norm_path(workspace_dir)
    root = _norm_path(default_root)
    if not normalized or normalized == root or normalized.startswith(f"{root}/"):
        return DEFAULT_PROJECT_KEY, "", True
    name = PurePosixPath(normalized).name or normalized
    return f"ws:{normalized}", name, False


def _visible_agent_rows(server: Any, user: Any) -> list[Any]:
    registry = server.app_runtime.agent_registry
    owned = registry.list_agents(user.id)
    shared = server.services.agent_repo.list_shared(
        exclude_user_id=user.id,
        viewer_user_id=None if user.is_admin else user.id,
    )
    return list({row.agent_id: row for row in [*shared, *owned]}.values())


def _agent_workspace(server: Any, row: Any) -> str:
    try:
        path = workspace_dir_from_config_json(
            row.config_json,
            paths=server.paths,
            agent_id=row.agent_id,
            ensure=False,
        )
    except Exception:  # noqa: BLE001 - a broken config must not blank the panel
        return ""
    return host_path_text(path)


def _team_hosts(
    server: Any, rows: list[Any] | None = None, user: Any | None = None
) -> dict[str, dict[str, str]]:
    """Map ``member_agent_id -> {team_agent_id, team_name}``.

    Team members have no independently started runtime, so dispatching to them
    ends in ``409 AGENT_NOT_RUNNING``. The router must know that up front and
    send work to the team (or the member's project conversation) instead.
    """
    registry = getattr(server.app_runtime, "agent_registry", None)
    teams = getattr(registry, "teams", None)
    if teams is None or not hasattr(teams, "visible_member_ids"):
        return {}
    candidates = rows if rows is not None else []
    hosts: dict[str, dict[str, str]] = {}
    for row in candidates:
        if not is_team_agent(row):
            continue
        try:
            members = teams.visible_member_ids(row.agent_id)
        except Exception:  # noqa: BLE001 - a broken manifest must not break routing
            continue
        if not isinstance(members, (list, tuple, set, frozenset)):
            continue
        for member_id in members:
            hosts.setdefault(
                str(member_id),
                {
                    "team_agent_id": str(row.agent_id),
                    "team_name": str(row.name or row.agent_id),
                },
            )
    return hosts


def _team_member_info(server: Any, user: Any, agent_id: str) -> dict[str, str] | None:
    try:
        rows = _visible_agent_rows(server, user)
    except Exception:  # noqa: BLE001 - routing must not fail on a registry hiccup
        return None
    return _team_hosts(server, rows).get(agent_id)


def _reject_team_member(server: Any, user: Any, agent_id: str) -> None:
    info = _team_member_info(server, user, agent_id)
    if info is None:
        return
    raise OctopError(
        ErrorCode.TEAM_MEMBER_NOT_DIRECT,
        f"{agent_id} is a member of team {info['team_name']}; "
        "dispatch to that team or the project conversation instead",
        details={"agent_id": agent_id, **info},
    )


@router.get("/overview", summary="Bao cross-project overview")
async def get_overview(
    session_limit: int = Query(DEFAULT_SESSION_LIMIT, ge=1, le=MAX_SESSION_LIMIT),
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Aggregate projects, agent state and live conversation state for Bao."""
    return _overview_payload(server, user, session_limit)


def _overview_payload(server: Any, user: Any, session_limit: int) -> dict[str, Any]:
    assert server.app_runtime is not None  # noqa: S101
    gateway = server.app_runtime.gateway
    thread_registry = gateway.thread_registry
    hub = gateway.ws_hub
    hitl_store = gateway.processor.hitl_coordinator.store
    message_repo = server.services.thread_message_repo
    default_root = host_path_text(server.paths.agents_dir)

    projects: dict[str, dict[str, Any]] = {}
    visible_rows = _visible_agent_rows(server, user)
    team_hosts = _team_hosts(server, visible_rows)
    for row in visible_rows:
        workspace = _agent_workspace(server, row)
        key, name, is_default = project_identity(workspace, default_root)
        project = projects.get(key)
        if project is None:
            project = projects[key] = {
                "key": key,
                "name": name,
                "is_default": is_default,
                "workspace_dir": workspace,
                "agents": [],
                "sessions": [],
            }
        state = str(row.last_state or "stopped")
        # Most agents leave ``default_model`` empty and rely on the provider's
        # auto-selected model, so a bare ``default_model`` check would mark
        # working agents as model-less. Mirror the registry's own rule.
        registry = server.app_runtime.agent_registry
        harness_manager = getattr(registry, "_harness_manager", None)
        shared_factory = getattr(harness_manager, "shared_factory", None)
        model_ready = bool(shared_factory) or bool((row.default_model or "").strip())
        team_host = team_hosts.get(row.agent_id)
        agent_entry = {
            "agent_id": row.agent_id,
            "name": row.name,
            "state": state,
            "last_error": row.last_error or None,
            "model_ready": model_ready,
            "direct_dispatchable": team_host is None,
            "direct_dispatch_hint": "team_member" if team_host else None,
            "team_name": team_host["team_name"] if team_host else None,
        }
        project["agents"].append(agent_entry)

        threads = thread_registry.list_visible_threads(
            agent_id=row.agent_id,
            user_id=user.id,
            limit=session_limit,
        )
        awaiting_ids = hitl_store.pending_thread_ids(agent_id=row.agent_id, user_id=user.id)
        shared_awaiting_ids = hitl_store.pending_thread_ids(
            agent_id=row.agent_id,
            user_id=user.id,
            any_user=True,
        )
        ids_with_messages = message_repo.threads_with_messages([t.thread_id for t in threads])
        for thread in threads:
            # Same "has real content" rule as the chat sidebar: a title alone
            # does not mean a usable conversation.
            has_messages = thread_row_has_messages(thread) and (
                thread.thread_id in ids_with_messages
                or message_repo.projection_status(thread.thread_id) != "ready"
            )
            if not has_messages:
                continue
            project["sessions"].append(
                {
                    "agent_id": row.agent_id,
                    "agent_name": row.name,
                    "thread_id": thread.thread_id,
                    "title": thread.title if isinstance(thread.title, str) else None,
                    "last_active": thread.last_active,
                    "created_at": thread.created_at,
                    "turn_active": hub.is_turn_active(thread.thread_id),
                    "awaiting_user": thread.thread_id
                    in (shared_awaiting_ids if thread.contributed else awaiting_ids),
                    "contributed": bool(thread.contributed),
                }
            )

    payload_projects: list[dict[str, Any]] = []
    for project in projects.values():
        agents = project["agents"]
        sessions = sorted(
            project["sessions"],
            key=lambda item: int(item["last_active"] or 0),
            reverse=True,
        )
        running_agents = sum(1 for agent in agents if agent["state"] in _BUSY_STATES)
        active_turns = sum(1 for session in sessions if session["turn_active"])
        awaiting_user = sum(1 for session in sessions if session["awaiting_user"])
        failed_agents = sum(1 for agent in agents if agent["last_error"])
        payload_projects.append(
            {
                **project,
                "agents": sorted(agents, key=lambda item: str(item["name"] or "").casefold()),
                "sessions": sessions[:session_limit],
                "running_agents": running_agents,
                "active_turns": active_turns,
                "awaiting_user": awaiting_user,
                "failed_agents": failed_agents,
            }
        )

    payload_projects.sort(
        key=lambda project: (
            0 if project["is_default"] else 1,
            -max((int(s["last_active"] or 0) for s in project["sessions"]), default=0),
            str(project["name"] or "").casefold(),
        )
    )
    return {
        "updated_at": int(time.time()),
        "projects": payload_projects,
        "totals": {
            "projects": len(payload_projects),
            "agents": sum(len(project["agents"]) for project in payload_projects),
            "running_agents": sum(project["running_agents"] for project in payload_projects),
            "active_turns": sum(project["active_turns"] for project in payload_projects),
            "awaiting_user": sum(project["awaiting_user"] for project in payload_projects),
            "failed_agents": sum(project["failed_agents"] for project in payload_projects),
        },
    }


class BaoRouteBody(BaseModel):
    """A user request Bao must map onto a project / expert / conversation."""

    text: str = Field(min_length=1, max_length=20_000)
    scope: Literal["global", "project"] = "global"
    project_key: str | None = None


def _text_matches(text: str, value: str | None) -> bool:
    needle = (value or "").strip().casefold()
    return len(needle) >= 2 and needle in text


def _project_ref(project: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": project["key"],
        "name": project["name"],
        "is_default": project["is_default"],
    }


def _agent_ref(agent: dict[str, Any]) -> dict[str, Any]:
    return {
        "agent_id": agent["agent_id"],
        "name": agent["name"],
        "state": agent["state"],
        "model_ready": agent["model_ready"],
        "direct_dispatchable": agent.get("direct_dispatchable", True),
        "direct_dispatch_hint": agent.get("direct_dispatch_hint"),
        "team_name": agent.get("team_name"),
    }


def _session_ref(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "agent_id": session["agent_id"],
        "agent_name": session["agent_name"],
        "thread_id": session["thread_id"],
        "title": session["title"],
        "last_active": session["last_active"],
        "turn_active": session["turn_active"],
        "awaiting_user": session["awaiting_user"],
    }


def _decision(
    project: dict[str, Any],
    agent: dict[str, Any],
    session: dict[str, Any] | None,
    *,
    code: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    if agent.get("direct_dispatchable") is False:
        # A team member has no independently started runtime. Routing to it would
        # only fail later with 409 AGENT_NOT_RUNNING, so refuse with the reason
        # and the owning team here.
        return {
            "decided": False,
            "needs_target": True,
            "direct_dispatchable": False,
            "blocked": "team_member",
            "project": _project_ref(project),
            "agent": _agent_ref(agent),
            "thread": None,
            "create_thread": False,
            "reason": {
                "code": "team_member",
                "params": {
                    "agent": agent["name"],
                    "team": agent.get("team_name") or "",
                },
            },
        }
    return {
        "decided": True,
        "needs_target": False,
        "project": _project_ref(project),
        "agent": _agent_ref(agent),
        "thread": _session_ref(session) if session else None,
        "create_thread": session is None,
        "reason": {"code": code, "params": params},
    }


def _project_of_session(
    candidates: list[dict[str, Any]], session: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    for project in candidates:
        for item in project["sessions"]:
            if item["thread_id"] == session["thread_id"]:
                agent = next(
                    (a for a in project["agents"] if a["agent_id"] == session["agent_id"]),
                    None,
                )
                if agent is not None:
                    return project, agent
    raise OctopError(ErrorCode.NOT_FOUND, "conversation not found")


def _candidates_payload(projects: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "projects": [_project_ref(project) for project in projects[:5]],
        "agents": [
            {
                **_agent_ref(agent),
                "project_key": project["key"],
                "project_name": project["name"],
            }
            for project in projects
            for agent in project["agents"]
        ][:8],
        "sessions": [
            _session_ref(session)
            for project in projects
            for session in project["sessions"]
        ][:5],
    }


def _needs_target(
    code: str,
    *,
    projects: list[dict[str, Any]],
    attempt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "decided": False,
        "needs_target": True,
        "reason": {"code": code, "params": {}},
        "candidates": _candidates_payload(projects),
    }
    if attempt is not None:
        payload["model_attempt"] = attempt
    return payload


def _parse_model_json(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(cleaned[start : end + 1])
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _pick_router_agent(
    server: Any, projects: list[dict[str, Any]]
) -> tuple[Any, str] | None:
    pairs = [(project, agent) for project in projects for agent in project["agents"]]
    pairs = [
        pair
        for pair in pairs
        if pair[1].get("model_ready") and pair[1].get("direct_dispatchable", True)
    ]
    if not pairs:
        return None
    pairs.sort(key=lambda pair: 0 if pair[1].get("state") in _BUSY_STATES else 1)
    registry = server.app_runtime.agent_registry
    for _project, agent in pairs:
        try:
            runtime_agent = registry.get_agent(agent["agent_id"])
        except Exception:  # noqa: BLE001 - stopped agents may not be loaded
            continue
        if runtime_agent is not None:
            return runtime_agent, agent["agent_id"]
    return None


async def _model_route(
    server: Any,
    *,
    text: str,
    projects: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """One lightweight model call used only when determinism asked for a target.

    Returns ``(decision, attempt)``. ``decision`` is ``None`` whenever the model
    is unavailable, fails, or is not confident enough — the caller then keeps
    ``needs_target`` instead of force-dispatching.
    """
    picked = _pick_router_agent(server, projects)
    if picked is None:
        return None, {
            "tried": False,
            "code": "model_unavailable",
            "detail": "no runnable agent with a configured model",
        }
    runtime_agent, model_agent_id = picked
    catalog = _candidates_payload(projects)
    # Team members are not dispatchable targets; never let the fallback model
    # pick one and hand the user a guaranteed 409.
    catalog["agents"] = [
        agent for agent in catalog["agents"] if agent.get("direct_dispatchable", True)
    ]
    system = (
        "You are Bao's routing fallback. Pick exactly one destination from the "
        "catalog. Never invent agent_id or thread_id. Prefer continuing an "
        "existing session when the request clearly refers to it; otherwise "
        "choose an agent and create_thread=true. If you are not confident, "
        "return confidence below 0.6. Reply with JSON only: "
        '{"agent_id": str, "thread_id": str|null, "create_thread": bool, '
        '"confidence": number, "reason": str}'
    )
    human = (
        f"Catalog:\n{json.dumps(catalog, ensure_ascii=False)}\n\n"
        f"User request:\n{text}"
    )
    model_name = "unknown"
    try:
        config = getattr(runtime_agent, "config", None)
        model_ref = config.pick_default_model_ref() if config is not None else None
        model_name = str(getattr(model_ref, "model", None) or model_ref or "unknown")
        llm = runtime_agent.model_factory.get(model_ref)
        raw = await ainvoke_text(
            llm,
            [SystemMessage(content=system), HumanMessage(content=human)],
            timeout=8.0,
        )
    except Exception as exc:  # noqa: BLE001 - fallback must never break routing
        logger.warning("bao route model call failed: %s", exc)
        return None, {
            "tried": True,
            "code": "model_failed",
            "detail": str(exc)[:200],
        }

    parsed = _parse_model_json(raw)
    if parsed is None:
        return None, {
            "tried": True,
            "code": "model_failed",
            "detail": "model returned non-JSON output",
        }

    try:
        confidence = float(parsed.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    note = str(parsed.get("reason") or "")[:200]
    if confidence < 0.6:
        return None, {
            "tried": True,
            "code": "model_unsure",
            "detail": note or f"confidence {confidence:.2f} below 0.6",
        }

    agent_id = str(parsed.get("agent_id") or "").strip()
    project = next(
        (p for p in projects if any(a["agent_id"] == agent_id for a in p["agents"])),
        None,
    )
    if project is None:
        return None, {
            "tried": True,
            "code": "model_unsure",
            "detail": f"agent {agent_id or '<empty>'} is not in the candidate catalog",
        }
    agent = next(a for a in project["agents"] if a["agent_id"] == agent_id)
    if agent.get("direct_dispatchable") is False:
        return None, {
            "tried": True,
            "code": "model_unsure",
            "detail": f"agent {agent_id} is a team member and cannot be dispatched directly",
        }
    thread_id = str(parsed.get("thread_id") or "").strip()
    create_thread = bool(parsed.get("create_thread"))
    session: dict[str, Any] | None = None
    if thread_id:
        session = next(
            (
                item
                for item in project["sessions"]
                if item["thread_id"] == thread_id and item["agent_id"] == agent_id
            ),
            None,
        )
        if session is None:
            return None, {
                "tried": True,
                "code": "model_unsure",
                "detail": f"thread {thread_id} does not belong to agent {agent_id}",
            }
    elif not create_thread:
        return None, {
            "tried": True,
            "code": "model_unsure",
            "detail": "model chose neither an existing thread nor a new thread",
        }

    decision = _decision(
        project,
        agent,
        session,
        code="model_route",
        params={
            "model": model_name,
            "confidence": round(confidence, 2),
            "note": note or "model fallback",
        },
    )
    return decision, {
        "tried": True,
        "code": "model_route",
        "detail": f"{model_agent_id} -> {agent_id}",
    }


@router.post("/route", summary="Decide where Bao should dispatch a task")
async def route_task(
    body: BaoRouteBody,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Deterministic Router decision.

    Bao only decides *where* work goes; execution stays with the target
    conversation through ``/dispatch``. Matching order: explicit session title,
    expert name, project name, then the most recent (preferably active)
    conversation in scope. When the request is genuinely ambiguous we return
    ``needs_target`` with candidates instead of guessing. Only after the
    deterministic chain asks for a target do we spend one lightweight model call
    on a second opinion; if that is not confident either, ``needs_target`` stays.
    """
    text = body.text.strip()
    if not text:
        raise OctopError(ErrorCode.SLASH_BAD_ARGS, "task text is empty")

    overview = _overview_payload(server, user, DEFAULT_SESSION_LIMIT)
    projects: list[dict[str, Any]] = overview["projects"]
    if not projects:
        return _needs_target(
            "no_project",
            projects=[],
            attempt={
                "tried": False,
                "code": "no_candidates",
                "detail": "no visible project or session",
            },
        )

    candidates = projects
    if body.scope == "project":
        key = body.project_key or projects[0]["key"]
        candidates = [p for p in projects if p["key"] == key] or [projects[0]]
    text_cf = text.casefold()

    matched_project: dict[str, Any] | None = None
    project_hits = [p for p in candidates if _text_matches(text_cf, p["name"])]
    if project_hits:
        matched_project = project_hits[0]
        candidates = project_hits

    sessions = [s for p in candidates for s in p["sessions"]]
    session_hits = [s for s in sessions if _text_matches(text_cf, s["title"])]
    if session_hits:
        session = max(session_hits, key=lambda s: int(s["last_active"] or 0))
        project, agent = _project_of_session(candidates, session)
        return _decision(
            project,
            agent,
            session,
            code="session_title",
            params={"title": session["title"] or ""},
        )

    agent_hits: list[tuple[dict[str, Any], dict[str, Any]]] = [
        (project, agent)
        for project in candidates
        for agent in project["agents"]
        if _text_matches(text_cf, agent["name"])
    ]
    if agent_hits:
        project, agent = agent_hits[0]
        owned = [s for s in project["sessions"] if s["agent_id"] == agent["agent_id"]]
        if owned:
            session = max(owned, key=lambda s: int(s["last_active"] or 0))
            return _decision(
                project,
                agent,
                session,
                code="agent_name",
                params={"agent": agent["name"], "title": session["title"] or ""},
            )
        if agent["model_ready"]:
            return _decision(
                project,
                agent,
                None,
                code="agent_name_new_thread",
                params={"agent": agent["name"]},
            )

    if sessions:
        active = [s for s in sessions if s["turn_active"] or s["awaiting_user"]]
        pool = active or sessions
        session = max(pool, key=lambda s: int(s["last_active"] or 0))
        project, agent = _project_of_session(candidates, session)
        base = "project_name" if matched_project else "scope"
        code = f"{base}_{'active' if active else 'recent'}_session"
        return _decision(
            project,
            agent,
            session,
            code=code,
            params={"title": session["title"] or "", "project": project["name"] or ""},
        )

    # No conversation to continue: create one, but only if the destination is
    # unambiguous (a single scoped project, or the user named one).
    agent_pairs = [
        (project, agent) for project in candidates for agent in project["agents"]
    ]
    runnable = [pair for pair in agent_pairs if pair[1]["model_ready"]]
    if runnable:
        if body.scope == "global" and not matched_project and len(projects) > 1:
            decision, attempt = await _model_route(server, text=text, projects=projects)
            if decision is not None:
                return {**decision, "model_attempt": attempt}
            return _needs_target(
                "ambiguous_project",
                projects=projects,
                attempt=attempt,
            )
        runnable.sort(
            key=lambda pair: 0 if pair[1]["state"] in _BUSY_STATES else 1
        )
        project, agent = runnable[0]
        return _decision(
            project,
            agent,
            None,
            code="new_thread",
            params={"project": project["name"] or "", "agent": agent["name"]},
        )

    decision, attempt = await _model_route(server, text=text, projects=candidates)
    if decision is not None:
        return {**decision, "model_attempt": attempt}
    return _needs_target("no_agent", projects=candidates, attempt=attempt)


@router.get("/tasks", summary="Bao dispatch ledger")
async def list_tasks(
    limit: int = Query(50, ge=1, le=200),
    ack: bool = Query(True),
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Return persisted dispatch records; optionally acknowledge what the page saw.

    ``ack=false`` is used by the Home inbox, which must keep unread counts until
    the user explicitly acknowledges a task. Running tasks whose turn
    disappeared are first reconciled so a process restart converges to an
    explicit failure instead of a permanent spinner.
    """
    assert server.app_runtime is not None  # noqa: S101
    repo = server.services.bao_task_repo
    hub = server.app_runtime.gateway.ws_hub
    repo.reconcile_interrupted(
        user_id=user.id,
        active_thread_ids=hub.active_thread_ids,
    )
    rows = repo.list_for_user(user.id, limit=limit)
    if ack:
        terminal = [row.id for row in rows if row.status in ("done", "failed")]
        repo.acknowledge(user.id, terminal)
    return {
        "updated_at": int(time.time()),
        "tasks": [row.to_dict() for row in rows],
        "retention": {
            "max_per_user": 200,
            "max_age_days": 30,
        },
    }


class TaskAckBody(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=200)


@router.post("/tasks/ack", summary="Acknowledge finished Bao tasks")
async def acknowledge_tasks(
    body: TaskAckBody,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Mark explicit reads only — opening the inbox never acknowledges tasks."""
    repo = server.services.bao_task_repo
    acknowledged = repo.acknowledge(user.id, body.ids)
    return {"ok": True, "acknowledged": acknowledged}


@router.get("/chat", summary="Bao conversation history")
async def chat_history(
    limit: int = Query(100, ge=1, le=200),
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    rows = server.services.bao_message_repo.list_for_user(user.id, limit=limit)
    return {
        "updated_at": int(time.time()),
        "messages": [row.to_dict() for row in rows],
        "settings": _bao_settings(server, user),
    }


@router.get("/settings", summary="Bao notification settings")
async def get_settings(
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    return _bao_settings(server, user)


@router.patch("/settings", summary="Update Bao notification settings")
async def patch_settings(
    body: BaoSettingsBody,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    colour_fields = {
        field: getattr(body, field)
        for field in ("body_color", "eye_color")
        if field in body.model_fields_set
    }
    return _set_bao_settings(
        server,
        user,
        muted=body.proactive_muted,
        name=body.name,
        identity_set=body.identity_set,
        onboarding_done=body.onboarding_done,
        shape=body.shape,
        color=body.color,
        follow_theme=body.follow_theme,
        **colour_fields,
    )


@router.post("/chat", summary="Talk to Bao")
async def chat(
    body: BaoChatBody,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """One conversational turn: remember, resolve references, maybe dispatch.

    Deterministic phrase matching decides the intent. Bao only reads its own
    task/message ledgers and calls the existing route/dispatch path — it never
    touches a workspace or runs a command on the user's behalf.
    """
    assert server.app_runtime is not None  # noqa: S101
    text = body.text.strip()
    if not text:
        raise OctopError(ErrorCode.SLASH_BAD_ARGS, "message text is empty")

    msg_repo = server.services.bao_message_repo
    task_repo = server.services.bao_task_repo
    history = msg_repo.list_for_user(user.id, limit=CHAT_CONTEXT_MESSAGES)
    text_cf = text.casefold()
    referenced = _referenced_task(server, user, history)
    pending = _pending_clarify(history)

    if _match_any(text_cf, _CANCEL_MARKERS):
        intent = "cancel"
    elif _match_any(text_cf, _WAIT_MARKERS):
        intent = "wait"
    elif _match_any(text_cf, _STATUS_MARKERS):
        intent = "status"
    elif _match_any(text_cf, _ALSO_MARKERS):
        intent = "also"
    elif _match_any(text_cf, _RETRY_MARKERS):
        intent = "retry"
    elif _match_any(text_cf, _OVERVIEW_MARKERS):
        intent = "overview"
    elif pending is not None and (
        _match_any(text_cf, _TARGET_PREFIXES) or _agent_from_text(server, user, text_cf)
    ):
        intent = "target"
    else:
        intent = "new_task"

    user_msg = msg_repo.append(
        user_id=user.id,
        role="user",
        text=text,
        intent=intent,
        refs={"task_id": referenced["id"]} if referenced else None,
    )

    reply: dict[str, Any]
    extra: dict[str, Any] = {}
    task_payload: dict[str, Any] | None = None

    if intent == "cancel":
        if referenced is not None:
            task_repo.acknowledge(user.id, [referenced["id"]])
        reply = _reply("cancel")
    elif intent == "wait":
        reply = _reply("wait")
    elif intent == "status":
        rows = _chat_tasks(server, user, limit=3)
        extra["tasks"] = rows
        if not rows:
            reply = _reply("status_empty")
        else:
            summary = _task_summary(rows)
            reply = _reply("status", {"summary": summary, "count": len(rows)})
    elif intent == "overview":
        overview = _overview_payload(server, user, DEFAULT_SESSION_LIMIT)
        projects = overview["projects"]
        names = "、".join(
            str(project["name"] or "默认项目") for project in projects[:6]
        )
        reply = _reply(
            "overview",
            {
                "count": len(projects),
                "agents": overview["totals"]["agents"],
                "names": names,
            },
        )
        extra["projects"] = [_project_ref(project) for project in projects]
    elif intent in ("also", "retry"):
        if referenced is None:
            reply = _reply("no_task")
        else:
            try:
                dispatched = await _dispatch_core(
                    server,
                    user,
                    agent_id=str(referenced["agent_id"]),
                    thread_id=str(referenced["thread_id"]),
                    text=str(referenced["task_text"]),
                    route_reason={"code": intent, "params": {"task_id": referenced["id"]}},
                    source=f"bao-chat-{intent}",
                )
                task_payload = dispatched["task"]
                extra["dispatch"] = dispatched
                reply = _reply("dispatch", {"agent": dispatched["agent_name"]})
            except OctopError as exc:
                reply = _chat_dispatch_error(exc)
    elif intent == "target":
        target = _agent_from_text(server, user, text_cf)
        pending_text = str((pending or {}).get("pending_text") or "").strip()
        if target is None or not pending_text:
            reply = _reply("clarify", {"text": pending_text})
        else:
            reply, task_payload, extra = await _chat_dispatch(
                server,
                user,
                agent_id=target[0],
                thread_id=None,
                text=pending_text,
                source="bao-chat-target",
            )
    else:
        agent_id = (body.agent_id or "").strip()
        if agent_id:
            reply, task_payload, extra = await _chat_dispatch(
                server,
                user,
                agent_id=agent_id,
                thread_id=(body.thread_id or "").strip() or None,
                text=text,
                source="bao-chat-manual",
            )
        else:
            decision = await route_task(
                BaoRouteBody(text=text, scope=body.scope, project_key=body.project_key),
                user=user,
                server=server,
            )
            extra["decision"] = decision
            if decision.get("decided"):
                agent = decision["agent"]
                thread = decision.get("thread")
                reply, task_payload, dispatched = await _chat_dispatch(
                    server,
                    user,
                    agent_id=str(agent["agent_id"]),
                    thread_id=str(thread["thread_id"]) if thread else None,
                    text=text,
                    route_reason=decision.get("reason"),
                    source="bao-chat",
                )
                extra.update(dispatched)
            else:
                reason = decision.get("reason") or {}
                code = str(reason.get("code") or "")
                params = dict(reason.get("params") or {})
                if code == "team_member":
                    reply = _reply(
                        "team_member",
                        {"agent": params.get("agent", ""), "team": params.get("team", "")},
                    )
                else:
                    reply = _reply("clarify", {"text": text})
                extra["needs_target"] = True
                extra["candidates"] = decision.get("candidates")

    refs: dict[str, Any] = {}
    if task_payload is not None:
        refs.update(
            {
                "task_id": task_payload["id"],
                "agent_id": task_payload["agent_id"],
                "thread_id": task_payload["thread_id"],
            }
        )
    if intent == "clarify" or extra.get("needs_target"):
        refs["pending_text"] = text
        if extra.get("candidates"):
            refs["candidates"] = extra["candidates"]
    bao_msg = msg_repo.append(
        user_id=user.id,
        role="bao",
        text=str(reply["reply_text"]),
        intent=str(reply["reply_code"]),
        refs=refs or None,
        task_id=task_payload["id"] if task_payload else None,
    )
    return {
        "intent": intent,
        "messages": [user_msg.to_dict(), bao_msg.to_dict()],
        "task": task_payload,
        "settings": _bao_settings(server, user),
        **reply,
        **extra,
    }


def _chat_dispatch_error(exc: OctopError) -> dict[str, Any]:
    if exc.code == ErrorCode.TEAM_MEMBER_NOT_DIRECT:
        return _reply(
            "team_member",
            {
                "agent": str(exc.details.get("agent_id") or ""),
                "team": str(exc.details.get("team_name") or ""),
            },
        )
    if exc.code == ErrorCode.THREAD_TURN_ACTIVE:
        return _reply("busy")
    raise exc


async def _chat_dispatch(
    server: Any,
    user: Any,
    *,
    agent_id: str,
    thread_id: str | None,
    text: str,
    route_reason: dict[str, Any] | None = None,
    source: str,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any]]:
    try:
        dispatched = await _dispatch_core(
            server,
            user,
            agent_id=agent_id,
            thread_id=thread_id,
            text=text,
            route_reason=route_reason,
            source=source,
        )
    except OctopError as exc:
        return _chat_dispatch_error(exc), None, {}
    return (
        _reply("dispatch", {"agent": dispatched["agent_name"]}),
        dispatched["task"],
        {"dispatch": dispatched},
    )


@router.post("/tasks/import", summary="Import browser-local Bao tasks once")
async def import_tasks(
    body: BaoTaskImportBody,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Idempotently move pre-upgrade localStorage records into ``bao_tasks``."""
    repo = server.services.bao_task_repo
    imported, skipped = repo.import_legacy(user.id, body.tasks)
    return {
        "imported": imported,
        "skipped": skipped,
        "updated_at": int(time.time()),
    }


async def _dispatch_core(
    server: Any,
    user: Any,
    *,
    agent_id: str,
    thread_id: str | None,
    text: str,
    route_reason: dict[str, Any] | None = None,
    source: str = "bao",
) -> dict[str, Any]:
    """Shared dispatch path for ``/dispatch`` and ``/chat``.

    Persists the task before enqueue so the worker always finds a running row.
    Rejects busy / approval-paused threads and team members up front instead of
    reporting success or deferring to a later 409.
    """
    assert server.app_runtime is not None  # noqa: S101
    text = text.strip()
    if not text:
        raise OctopError(ErrorCode.SLASH_BAD_ARGS, "task text is empty")

    row = require_agent_row(agent_id, user=user, as_user=None, server=server)
    _reject_team_member(server, user, agent_id)
    gateway = server.app_runtime.gateway
    thread_registry = gateway.thread_registry
    created = thread_id is None
    if created:
        # Same dashboard thread factory the "new conversation" button uses;
        # ``rebind=False`` keeps the agent's current chat unchanged.
        thread_id = thread_registry.create_thread(
            agent_id=agent_id,
            user_id=user.id,
            channel_type=ThreadRegistry.CHANNEL_DASHBOARD,
            session_key=ThreadRegistry.dashboard_key(agent_id=agent_id, user_id=user.id),
        )
        thread = thread_registry.get_thread(thread_id)
        if thread is None:
            raise OctopError(ErrorCode.NOT_FOUND, "conversation not found")
    else:
        thread_id = thread_id or ""
        thread = thread_registry.get_thread(thread_id)
        if thread is None or thread.agent_id != agent_id:
            raise OctopError(ErrorCode.NOT_FOUND, "conversation not found")
        # Defense in depth: prepare_dashboard_turn re-checks visibility, but the
        # busy/approval probes below run before that and must not leak state of
        # conversations this user cannot see.
        if not thread_visible_to(thread, user.id):
            raise OctopError(ErrorCode.FORBIDDEN, "conversation not owned by user")

    hub = gateway.ws_hub
    if hub.is_turn_active(thread_id):
        raise OctopError(ErrorCode.THREAD_TURN_ACTIVE, "conversation is still replying")
    hitl_store = gateway.processor.hitl_coordinator.store
    pending = hitl_store.pending_thread_ids(
        agent_id=agent_id,
        user_id=user.id,
        any_user=bool(thread.contributed),
    )
    if thread_id in pending:
        raise OctopError(ErrorCode.THREAD_TURN_ACTIVE, "conversation is waiting for approval")

    turn = ChatTurnBody(
        text=text,
        messages=[{"role": "user", "content": text}],
        thread_id=thread_id,
        session_key=thread.session_key,
        conversation_mode=thread.conversation_mode or "craft",
    )
    if not turn_has_content(turn):
        raise OctopError(ErrorCode.SLASH_BAD_ARGS, "task text is empty")
    prepared = await prepare_dashboard_turn(
        server,
        agent_id=agent_id,
        user=user,
        turn=turn,
    )
    channel_manager = gateway.channel_manager
    if channel_manager is None:
        raise OctopError(ErrorCode.AGENT_NOT_RUNNING, "gateway is not ready")
    inbound = build_dashboard_inbound(
        agent_id=agent_id,
        user_id=user.id,
        prepared=prepared,
        turn=turn,
        # No socket belongs to this dispatch; results are written back by the
        # WS turn-completion hook. The synthetic id keeps HITL frames attributable.
        ws_connection_id=f"bao-dispatch:{thread_id}",
        user_is_admin=bool(getattr(user, "is_admin", False)),
    )
    default_root = host_path_text(server.paths.agents_dir)
    key, name, _is_default = project_identity(_agent_workspace(server, row), default_root)
    dispatched_at = int(time.time())
    session_title = thread.title if isinstance(thread.title, str) else ""
    task_repo = server.services.bao_task_repo
    # Persist before enqueue: a very fast worker must still find a running row
    # to write its result into.
    task = task_repo.create(
        user_id=user.id,
        agent_id=agent_id,
        agent_name=row.name,
        thread_id=prepared.thread_id,
        session_title=session_title,
        project_key=key,
        project_name=name,
        task_text=text,
        source=source,
        route_reason=route_reason,
        dispatched_at=dispatched_at,
    )
    try:
        channel_manager.enqueue(WS_CHANNEL_ID, inbound)
    except Exception:
        task_repo.complete_running(
            thread_id=prepared.thread_id,
            agent_id=agent_id,
            status="failed",
            error_text="dispatch enqueue failed",
        )
        raise
    return {
        "dispatched": True,
        "created": created,
        "agent_id": agent_id,
        "agent_name": row.name,
        "thread_id": prepared.thread_id,
        "session_title": session_title or None,
        "project_key": key,
        "project_name": name,
        "dispatched_at": dispatched_at,
        "task_id": task.id,
        "task": task.to_dict(),
    }


@router.post("/dispatch", summary="Dispatch a task into a conversation")
async def dispatch_task(
    body: BaoDispatchBody,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Submit a task to an existing thread through the normal chat pipeline.

    This deliberately refuses busy / approval-paused threads and team members
    instead of reporting success: Bao must not imply a task was queued when the
    running turn would swallow it.
    """
    return await _dispatch_core(
        server,
        user,
        agent_id=body.agent_id,
        thread_id=body.thread_id,
        text=body.text,
        route_reason=body.route_reason,
        source=body.source,
    )
