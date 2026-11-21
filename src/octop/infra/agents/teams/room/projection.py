"""Message and history projection helpers operating on plain message objects."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import fields
from typing import Any

from octop_harness.teams.util import (
    PeerSession,
)

from octop.infra.agents.teams.room.constants import (
    _EDIT_CARD_TOOL_BASES,
    _HISTORY_TOOL_RESULT_MAX_CHARS,
    _HISTORY_TOOL_RESULT_SUFFIX,
    _STREAM_SPEAKER_TYPES,
)
from octop.infra.agents.threads.artifact import artifact_path_allowed, extract_artifact_paths
from octop.infra.gateway.media.tool_media import tool_name_base
from octop.infra.utils.ulid import new_ulid


def _chunk_speaker_id(chunk: dict[str, Any]) -> str:
    """Read a live-frame speaker. Ignore LangGraph's ``agent`` node name."""
    for key in ("agent_id", "agent", "speaker_agent_id"):
        raw = chunk.get(key)
        if not isinstance(raw, str):
            continue
        value = raw.strip()
        if not value:
            continue
        if key == "agent" and value == "agent":
            continue
        return value
    return ""


def stamp_stream_speaker(
    chunk: dict[str, Any],
    speaker_id: str,
    *,
    include_done: bool = False,
) -> dict[str, Any]:
    """Copy a stream frame and set ``agent`` / ``agent_id`` to the speaker."""
    if not isinstance(chunk, dict) or not speaker_id:
        return chunk
    kind = str(chunk.get("type") or "")
    if kind == "done" and not include_done:
        return chunk
    if kind not in _STREAM_SPEAKER_TYPES:
        return chunk
    if chunk.get("agent_id") == speaker_id and chunk.get("agent") == speaker_id:
        return chunk
    out = dict(chunk)
    out["agent_id"] = speaker_id
    out["agent"] = speaker_id
    return out


def stamp_team_host_chunk(
    chunk: dict[str, Any],
    agent_id: str,
    team_host: bool,
) -> dict[str, Any]:
    if not team_host:
        return chunk
    existing = _chunk_speaker_id(chunk)
    if existing and existing != agent_id:
        return chunk
    return stamp_stream_speaker(chunk, agent_id, include_done=True)


def _with_room_turn_id(frame: dict[str, Any], turn_id: str) -> dict[str, Any]:
    """Keep a team room frame on the host turn that dispatched it."""
    token = turn_id.strip()
    if not token or frame.get("turn_id"):
        return frame
    return {**frame, "turn_id": token}


def _is_decision_custom(chunk: dict[str, Any]) -> bool:
    data = chunk.get("data")
    return isinstance(data, dict) and data.get("kind") == "decision"


def _peer_user_message_id(thread_id: str, turn_id: str | None = None) -> str:
    suffix = (turn_id or "").strip() or new_ulid()
    return f"team-peer:{thread_id}:{suffix}:human"


def _is_team_system_prompt(text: str) -> bool:
    head = text.lstrip()
    return head.startswith(
        (
            "[团队成员",
            "[系统唤醒",
            "[团队派工",
            "[主持人调度",
            "[team member",
            "[system wake-up",
            "[background task",
            "[Team assignment",
            "[Host dispatch",
            "以下是当前群聊记录",
            "Here is the current group-chat transcript",
        )
    )


def _projected_row_text(row: Any) -> str:
    raw = getattr(row, "message_json", "") or ""
    try:
        wire = json.loads(raw)
    except json.JSONDecodeError:
        return str(raw).strip()
    data = wire.get("data") if isinstance(wire, dict) else None
    content = data.get("content") if isinstance(data, dict) else None
    if content is None and isinstance(wire, dict):
        content = wire.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(str(block.get("text") or ""))
        return "".join(parts).strip()
    return str(content or "").strip()


def _projected_kwargs(row: Any) -> dict[str, Any]:
    raw = getattr(row, "message_json", "") or ""
    try:
        wire = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(wire, dict):
        return {}
    data = wire.get("data")
    kwargs = data.get("additional_kwargs") if isinstance(data, dict) else None
    if not isinstance(kwargs, dict):
        kwargs = wire.get("additional_kwargs")
    return kwargs if isinstance(kwargs, dict) else {}


def _projected_speaker(row: Any) -> str:
    speaker = _projected_kwargs(row).get("speaker_agent_id")
    return str(speaker).strip() if speaker else ""


def _make_peer_session(**kwargs: Any) -> PeerSession:
    allowed = {item.name for item in fields(PeerSession)}
    return PeerSession(**{key: value for key, value in kwargs.items() if key in allowed})


def _chat_request_payload(request: Any, speaker_id: str) -> dict[str, Any]:
    if isinstance(request, dict):
        payload = dict(request)
    else:
        payload = {
            "messages": getattr(request, "messages", ""),
            "thread_id": getattr(request, "thread_id", None),
            "user": getattr(request, "user", None),
            "source": getattr(request, "source", None),
            "agent_id": getattr(request, "agent_id", None),
            "model": getattr(request, "model", None),
            "configurable": getattr(request, "configurable", None),
            "mcp_servers": getattr(request, "mcp_servers", None),
            "mcp_use_default": bool(getattr(request, "mcp_use_default", False)),
        }
        payload = {
            key: value for key, value in payload.items() if value is not None and value is not False
        }
        if getattr(request, "mcp_use_default", False):
            payload["mcp_use_default"] = True
        if "messages" not in payload:
            payload["messages"] = ""
    if not payload.get("agent_id"):
        payload["agent_id"] = speaker_id
    return payload


def _octop_user_id(user_id: str | int) -> int | None:
    if isinstance(user_id, int):
        return user_id if user_id > 0 else None
    if isinstance(user_id, str) and user_id.isdigit():
        uid = int(user_id)
        return uid if uid > 0 else None
    return None


def _message_role(msg: Any) -> str:
    if isinstance(msg, dict):
        return str(msg.get("role") or msg.get("type") or "").lower()
    return str(getattr(msg, "type", None) or getattr(msg, "role", "") or "").lower()


def _message_is_assistant(msg: Any) -> bool:
    return _message_role(msg) in {"ai", "assistant"}


def _decision_from_messages(messages: Sequence[Any]) -> dict[str, Any] | None:
    for msg in reversed(messages):
        if not _message_is_assistant(msg):
            continue
        kwargs = (
            msg.get("additional_kwargs")
            if isinstance(msg, dict)
            else getattr(msg, "additional_kwargs", None)
        )
        if not isinstance(kwargs, dict):
            continue
        decision = kwargs.get("octop_decision")
        if isinstance(decision, dict):
            return dict(decision)
    return None


def _message_tool_calls(msg: Any) -> Any:
    if isinstance(msg, dict):
        return msg.get("tool_calls")
    return getattr(msg, "tool_calls", None)


def _final_room_assistant(messages: list[Any]) -> Any | None:
    for msg in reversed(messages):
        if not _message_is_assistant(msg) or _message_tool_calls(msg):
            continue
        if _assistant_text(msg):
            return msg
    return None


def _apply_edited_files_stamp(
    messages: list[Any],
    edited: list[str],
) -> tuple[list[Any], Any | None]:
    """Stamp ``edited_files`` on the final text bubble, or last AI if tools-only."""
    final = _final_room_assistant(messages)
    if not edited:
        return messages, final
    target = final
    if target is None:
        for msg in reversed(messages):
            if _message_is_assistant(msg):
                target = msg
                break
    if target is None:
        return messages, final
    stamped_target = _with_edited_files(target, edited)
    out = [stamped_target if msg is target else msg for msg in messages]
    if final is None:
        return out, None
    return out, stamped_target if final is target else final


def _truncate_tool_result_text(
    text: str,
    *,
    max_chars: int = _HISTORY_TOOL_RESULT_MAX_CHARS,
) -> str:
    if len(text) <= max_chars:
        return text
    keep = max(max_chars - len(_HISTORY_TOOL_RESULT_SUFFIX), 0)
    return text[:keep] + _HISTORY_TOOL_RESULT_SUFFIX


def _truncate_tool_content(content: Any) -> Any:
    if isinstance(content, str):
        return _truncate_tool_result_text(content)
    if isinstance(content, list):
        out: list[Any] = []
        changed = False
        for block in content:
            if isinstance(block, str):
                new_block = _truncate_tool_result_text(block)
                out.append(new_block)
                changed = changed or new_block != block
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                text = str(block["text"])
                new_text = _truncate_tool_result_text(text)
                if new_text != text:
                    out.append({**block, "text": new_text})
                    changed = True
                else:
                    out.append(block)
            else:
                out.append(block)
        return out if changed else content
    return content


def _replace_message_content(msg: Any, content: Any) -> Any:
    if isinstance(msg, dict):
        out = dict(msg)
        out["content"] = content
        return out
    copy = getattr(msg, "model_copy", None)
    if callable(copy):
        try:
            return copy(update={"content": content})
        except Exception:
            pass
    try:
        object.__setattr__(msg, "content", content)
    except Exception:
        msg.content = content
    return msg


def _history_projection_messages(messages: list[Any]) -> list[Any]:
    """Truncate bulky ToolMessage bodies before writing team projections."""
    out: list[Any] = []
    for msg in messages:
        if _message_role(msg) != "tool":
            out.append(msg)
            continue
        content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "")
        truncated = _truncate_tool_content(content)
        if truncated is content:
            out.append(msg)
            continue
        out.append(_replace_message_content(msg, truncated))
    return out


def _edited_files_from_messages(messages: list[Any]) -> list[str]:
    """Workspace paths from write/edit/send tool_calls in a peer turn."""
    out: list[str] = []
    seen: set[str] = set()
    for msg in messages:
        tool_calls = _message_tool_calls(msg)
        if not isinstance(tool_calls, list):
            continue
        for call in tool_calls:
            if isinstance(call, dict):
                name = str(call.get("name") or "")
                args = call.get("args")
            else:
                name = str(getattr(call, "name", "") or "")
                args = getattr(call, "args", None)
            base = tool_name_base(name).lower()
            if base not in _EDIT_CARD_TOOL_BASES:
                continue
            for path in extract_artifact_paths(tool_name=name, args=args):
                key = path.replace("\\", "/").strip()
                if not key or not artifact_path_allowed(key) or key in seen:
                    continue
                seen.add(key)
                out.append(key)
    return out


def _patch_additional_kwargs(msg: Any, updates: dict[str, Any]) -> Any:
    if not updates:
        return msg
    if isinstance(msg, dict):
        kwargs = dict(msg.get("additional_kwargs") or {})
        kwargs.update(updates)
        out = dict(msg)
        out["additional_kwargs"] = kwargs
        return out
    kwargs = dict(getattr(msg, "additional_kwargs", None) or {})
    kwargs.update(updates)
    copy = getattr(msg, "model_copy", None)
    if callable(copy):
        try:
            return copy(update={"additional_kwargs": kwargs})
        except Exception:
            pass
    try:
        object.__setattr__(msg, "additional_kwargs", kwargs)
    except Exception:
        msg.additional_kwargs = kwargs
    return msg


def _with_speaker(msg: Any, agent_id: str) -> Any:
    if isinstance(msg, dict):
        kwargs = dict(msg.get("additional_kwargs") or {})
        if kwargs.get("speaker_agent_id") == agent_id:
            return msg
    else:
        kwargs = dict(getattr(msg, "additional_kwargs", None) or {})
        if kwargs.get("speaker_agent_id") == agent_id:
            return msg
    return _patch_additional_kwargs(msg, {"speaker_agent_id": agent_id})


def _with_edited_files(msg: Any, paths: list[str]) -> Any:
    if not paths:
        return msg
    return _patch_additional_kwargs(msg, {"edited_files": list(paths)})


def _ensure_reasoning(msg: Any, reasoning: str) -> None:
    if not reasoning:
        return
    if isinstance(msg, dict):
        kwargs = dict(msg.get("additional_kwargs") or {})
        if not str(kwargs.get("reasoning_content") or "").strip():
            kwargs["reasoning_content"] = reasoning
            msg["additional_kwargs"] = kwargs
        return
    kwargs = dict(getattr(msg, "additional_kwargs", None) or {})
    if str(kwargs.get("reasoning_content") or "").strip():
        return
    kwargs["reasoning_content"] = reasoning
    try:
        object.__setattr__(msg, "additional_kwargs", kwargs)
    except Exception:
        msg.additional_kwargs = kwargs


def _room_peer_messages(messages: list[Any]) -> list[Any]:
    last_user = -1
    for index, msg in enumerate(messages):
        if _message_role(msg) in {"human", "user"}:
            last_user = index
    tail = messages[last_user + 1 :] if last_user >= 0 else list(messages)
    skip = {"system", "human", "user"}
    return [msg for msg in tail if _message_role(msg) not in skip]


def _assistant_text(msg: Any) -> str:
    content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "\n".join(p for p in parts if p).strip()
    return str(content or "").strip()


def _peer_turn_messages(messages: list[Any]) -> list[Any]:
    """Last user turn for the member page: trigger + full assistant/tool trail.

    Historically this kept only the final AI text, which dropped tool_calls
    from both the member projection and (via fan-in) the room wall.
    """
    last_user = -1
    for index, msg in enumerate(messages):
        if _message_role(msg) in {"human", "user"}:
            last_user = index
    if last_user >= 0:
        trigger = messages[last_user]
        tail = messages[last_user + 1 :]
    else:
        trigger = None
        tail = list(messages)
    skip = {"system", "human", "user"}
    trail = [msg for msg in tail if _message_role(msg) not in skip]
    out: list[Any] = []
    if trigger is not None:
        out.append(trigger)
    out.extend(trail)
    return out


__all__ = [
    "_chunk_speaker_id",
    "stamp_stream_speaker",
    "stamp_team_host_chunk",
    "_with_room_turn_id",
    "_is_decision_custom",
    "_peer_user_message_id",
    "_is_team_system_prompt",
    "_projected_row_text",
    "_projected_kwargs",
    "_projected_speaker",
    "_make_peer_session",
    "_chat_request_payload",
    "_octop_user_id",
    "_message_role",
    "_message_is_assistant",
    "_decision_from_messages",
    "_message_tool_calls",
    "_final_room_assistant",
    "_apply_edited_files_stamp",
    "_truncate_tool_result_text",
    "_truncate_tool_content",
    "_replace_message_content",
    "_history_projection_messages",
    "_edited_files_from_messages",
    "_patch_additional_kwargs",
    "_with_speaker",
    "_with_edited_files",
    "_ensure_reasoning",
    "_room_peer_messages",
    "_assistant_text",
    "_peer_turn_messages",
]
