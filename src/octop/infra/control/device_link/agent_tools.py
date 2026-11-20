"""把设备链路能力暴露为 Agent 可调用工具。

六个工具一一对应 ``protocol.json`` 里的命令，全部经由 :class:`DeviceLinkManager`
走既有的 ``/api/device-link/*`` 链路，不另起通道：

- 只读：``phone_screenshot`` / ``phone_ui_tree`` / ``phone_list_apps``
- 有副作用：``phone_tap`` / ``phone_swipe`` / ``phone_type_text``（强制一次性审批）

可用性约定：未配对时不挂载；离线时由 :class:`DeviceLinkToolGateMiddleware`
从模型可见工具列表中剔除；工具内部再做一次兜底校验（竞态场景），绝不凭空假装能控制。
"""

from __future__ import annotations

import asyncio
import json
import struct
import time
from pathlib import Path
from typing import Annotated, Any

from langchain_core.tools import StructuredTool
from langgraph.config import get_config
from pydantic import Field

from octop.infra.control.device_link.today.collector import DEFAULT_CONFIG
from octop.infra.control.device_link.today.items import sensitive_redact
from octop.infra.users.permissions import user_has_permission
from octop.infra.utils.ulid import new_short_id

PHONE_SCREENSHOT = "phone_screenshot"
PHONE_UI_TREE = "phone_ui_tree"
PHONE_LIST_APPS = "phone_list_apps"
PHONE_TAP = "phone_tap"
PHONE_SWIPE = "phone_swipe"
PHONE_TYPE_TEXT = "phone_type_text"
PHONE_NOTIFICATIONS = "phone_notifications"
PHONE_TIME_CONTEXT = "phone_time_context"

DEVICE_LINK_READONLY_TOOLS: frozenset[str] = frozenset(
    {PHONE_SCREENSHOT, PHONE_UI_TREE, PHONE_LIST_APPS, PHONE_NOTIFICATIONS, PHONE_TIME_CONTEXT}
)
DEVICE_LINK_SIDE_EFFECT_TOOLS: frozenset[str] = frozenset(
    {PHONE_TAP, PHONE_SWIPE, PHONE_TYPE_TEXT}
)
DEVICE_LINK_TOOL_NAMES: frozenset[str] = (
    DEVICE_LINK_READONLY_TOOLS | DEVICE_LINK_SIDE_EFFECT_TOOLS
)

_MAX_TREE_ELEMENTS = 40
_MAX_APPS = 200
_MAX_TEXT_PREVIEW = 40
_MAX_NOTIFICATION_TEXT = 200

_REMINDER_POLICY = (
    "提醒只在 HappyClaw 侧创建一次（用定时任务工具），设备上的日程/闹钟只读，"
    "用于查重与解析「明天九点」这类相对时间；不要两边各建一份。"
)



# ----------------------------------------------------------------------
# 结果整形
# ----------------------------------------------------------------------


def _dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _error(
    tool: str,
    code: str,
    message: str,
    *,
    command: str | None = None,
    retryable: bool = True,
    duration_ms: int = 0,
) -> str:
    return _dumps(
        {
            "ok": False,
            "tool": tool,
            "command": command,
            "code": code,
            "message": message,
            "retryable": retryable,
            "duration_ms": duration_ms,
        }
    )


def _failure(tool: str, command: str, reply: dict[str, Any]) -> str:
    err = reply.get("error") if isinstance(reply.get("error"), dict) else {}
    return _dumps(
        {
            "ok": False,
            "tool": tool,
            "command": command,
            "code": str(err.get("code") or "INTERNAL"),
            "message": str(err.get("message") or "设备未返回错误说明"),
            "retryable": bool(err.get("retryable", True)),
            "duration_ms": int(reply.get("duration_ms") or 0),
            "command_id": reply.get("command_id"),
        }
    )


def _parse_png_size(path: str | None) -> tuple[int | None, int | None]:
    """从已落盘 PNG 的 IHDR 读取宽高；失败不影响主结果。"""
    if not path:
        return None, None
    try:
        with Path(path).open("rb") as fh:
            head = fh.read(24)
        if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
            return None, None
        width, height = struct.unpack(">II", head[16:24])
        return int(width), int(height)
    except OSError:
        return None, None


def _tree_summary(result: dict[str, Any] | None) -> dict[str, Any]:
    data = result or {}
    raw = data.get("elements")
    elements = raw if isinstance(raw, list) else []
    picked: list[dict[str, Any]] = []
    for item in elements[:_MAX_TREE_ELEMENTS]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        desc = str(item.get("contentDescription") or "").strip()
        view_id = str(item.get("viewId") or "").strip()
        bounds = str(item.get("bounds") or "").strip()
        if not (text or desc or view_id or bounds):
            continue
        picked.append(
            {
                "text": text or None,
                "desc": desc or None,
                "viewId": view_id or None,
                "bounds": bounds or None,
                "clickable": bool(item.get("clickable")),
            }
        )
    width = data.get("screenWidth")
    height = data.get("screenHeight")
    return {
        "package": data.get("packageName"),
        "screen": f"{width}x{height}" if width and height else None,
        "node_count": len(elements),
        "elements": picked,
        "truncated": len(elements) > _MAX_TREE_ELEMENTS,
    }


def _app_list(result: dict[str, Any] | None) -> tuple[int, list[dict[str, Any]]]:
    data = result or {}
    raw = data.get("apps")
    apps = raw if isinstance(raw, list) else []
    out: list[dict[str, Any]] = []
    for item in apps[:_MAX_APPS]:
        if isinstance(item, dict) and item.get("package"):
            out.append(
                {
                    "package": str(item["package"]),
                    "label": str(item.get("label") or ""),
                    "isSystem": bool(item.get("isSystem")),
                    "launchable": bool(item.get("launchable", True)),
                }
            )
    return len(apps), out


def _result_of(reply: dict[str, Any]) -> dict[str, Any]:
    result = reply.get("result")
    return result if isinstance(result, dict) else {}


def _as_dict(value: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {"ok": False, "code": "INTERNAL", "message": str(value)}
    return parsed if isinstance(parsed, dict) else {"ok": False, "code": "INTERNAL", "message": str(value)}


def _cron_snapshot(cron_manager: Any, limit: int = 20) -> list[dict[str, Any]]:
    if cron_manager is None:
        return []
    try:
        rows = cron_manager.list_all(include_disabled=False)
    except TypeError:
        try:
            rows = cron_manager.list_all()
        except Exception:  # noqa: BLE001
            return []
    except Exception:  # noqa: BLE001
        return []
    out: list[dict[str, Any]] = []
    for row in rows[:limit]:
        out.append(
            {
                "id": str(getattr(row, "id", "") or getattr(row, "cron_id", "") or ""),
                "name": str(getattr(row, "name", "") or getattr(row, "title", "") or ""),
                "nextRunAt": getattr(row, "next_run_at", None),
                "enabled": bool(getattr(row, "enabled", 1)),
            }
        )
    return out



def _text_preview(text: str) -> str:
    clean = text.replace("\n", " ").strip()
    if len(clean) <= _MAX_TEXT_PREVIEW:
        return clean
    return clean[:_MAX_TEXT_PREVIEW] + "…"


# ----------------------------------------------------------------------
# 审批文案：必须写清要操作哪个坐标 / 哪个输入框
# ----------------------------------------------------------------------


def _args_of(tool_call: Any) -> dict[str, Any]:
    raw = tool_call.get("args") if isinstance(tool_call, dict) else None
    return raw if isinstance(raw, dict) else {}


def describe_device_action(tool_call: Any, state: Any = None, runtime: Any = None) -> str:
    """给审批卡用的中文说明：做什么、影响哪里。"""
    name = str(tool_call.get("name") or "") if isinstance(tool_call, dict) else ""
    args = _args_of(tool_call)
    if name == PHONE_TAP:
        return (
            f"即将在手机屏幕上点击坐标 ({args.get('x')}, {args.get('y')})（设备像素），"
            "会触发该位置的控件，可能跳转页面或提交表单。"
        )
    if name == PHONE_SWIPE:
        duration = args.get("duration_ms", 300)
        return (
            f"即将在手机屏幕上从 ({args.get('x1')}, {args.get('y1')}) 滑动到 "
            f"({args.get('x2')}, {args.get('y2')})，耗时 {duration}ms，"
            "会滚动列表或触发手势。"
        )
    if name == PHONE_TYPE_TEXT:
        preview = _text_preview(str(args.get("text") or ""))
        x, y = args.get("x"), args.get("y")
        if x is not None and y is not None:
            where = f"坐标 ({x}, {y}) 的输入框"
        else:
            where = "当前焦点输入框"
        return f"即将向{where}覆写文本「{preview}」，原内容会被替换。"
    return f"即将向手机下发有副作用的动作：{name}。"


def device_link_interrupt_on() -> dict[str, Any]:
    """副作用工具的一次性审批配置（approve / reject，逐次确认）。"""
    entry = {
        "allowed_decisions": ["approve", "reject"],
        "description": describe_device_action,
    }
    return {name: dict(entry) for name in sorted(DEVICE_LINK_SIDE_EFFECT_TOOLS)}


# ----------------------------------------------------------------------
# 权限与执行
# ----------------------------------------------------------------------


def _denied(tool: str, command: str, message: str) -> str:
    return _error(tool, "DENIED", message, command=command, retryable=False)


def _check_access(config: Any, user_repo: Any) -> str | None:
    """返回 None 表示允许，否则返回拒绝原因。

    设备直连走 pairing + token，与旧的 ADB 手机能力开关无关，因此这里只校验
    用户权限，不再读取 ``capabilities.mobile``。
    """
    _ = config
    ctx = get_config().get("configurable") or {}
    user_raw = ctx.get("user")
    if user_raw is None:
        return "当前对话缺少用户身份，无法校验 mobile 权限"
    if ctx.get("user_is_admin"):
        return None
    try:
        row = user_repo.get(int(user_raw))
    except (TypeError, ValueError):
        return "当前对话的用户身份无效"
    if row is None or not user_has_permission(row, "mobile"):
        return "需要 mobile 权限才能控制手机"
    return None


async def _run(
    tool: str,
    command: str,
    params: dict[str, Any],
    *,
    config: Any,
    user_repo: Any,
    timeout_ms: int | None = None,
) -> dict[str, Any] | str:
    """执行一条设备命令；返回原始 reply（dict）或已序列化的错误/离线 JSON。"""
    denied = _check_access(config, user_repo)
    if denied:
        return _denied(tool, command, denied)

    from octop.infra.control.device_link.manager import get_device_link_manager

    manager = get_device_link_manager()
    if not manager.is_online():
        # 竞态兜底：中间件本应已把工具从列表剔除，正常不会走到这里
        return _error(
            tool,
            "DEVICE_OFFLINE",
            "设备链路未连接（离线），本次未执行任何动作。请在「远程桌面 → 设备直连」面板确认设备在线。",
            command=command,
        )
    try:
        return await manager.run_command(
            command,
            params,
            command_id=new_short_id(16),
            timeout_ms=timeout_ms,
        )
    except Exception as exc:  # noqa: BLE001
        return _error(tool, "INTERNAL", f"设备命令执行异常: {exc}", command=command)


def build_device_link_tools(
    config: Any, *, user_repo: Any, cron_manager: Any = None
) -> list[StructuredTool]:
    """构建 8 个设备工具。调用方负责在未配对时不要挂载。"""

    async def phone_screenshot() -> str:
        reply = await _run(
            PHONE_SCREENSHOT, "screen.screenshot", {}, config=config, user_repo=user_repo
        )
        if isinstance(reply, str):
            return reply
        if not reply.get("ok"):
            return _failure(PHONE_SCREENSHOT, "screen.screenshot", reply)
        result = reply.get("result") if isinstance(reply.get("result"), dict) else {}
        artifact = reply.get("artifact")
        width, height = _parse_png_size(artifact)
        return _dumps(
            {
                "ok": True,
                "tool": PHONE_SCREENSHOT,
                "command": "screen.screenshot",
                "duration_ms": int(reply.get("duration_ms") or 0),
                "artifact": artifact,
                "size_bytes": result.get("sizeBytes"),
                "width": width,
                "height": height,
                "command_id": reply.get("command_id"),
            }
        )

    async def phone_ui_tree(
        display_id: Annotated[
            int | None, Field(description="显示屏 id；省略或 -1 表示主屏。")
        ] = None,
    ) -> str:
        params: dict[str, Any] = {}
        if display_id is not None:
            params["displayId"] = display_id
        reply = await _run(
            PHONE_UI_TREE, "screen.tree", params, config=config, user_repo=user_repo
        )
        if isinstance(reply, str):
            return reply
        if not reply.get("ok"):
            return _failure(PHONE_UI_TREE, "screen.tree", reply)
        result = reply.get("result") if isinstance(reply.get("result"), dict) else {}
        return _dumps(
            {
                "ok": True,
                "tool": PHONE_UI_TREE,
                "command": "screen.tree",
                "duration_ms": int(reply.get("duration_ms") or 0),
                "summary": _tree_summary(result),
                "command_id": reply.get("command_id"),
            }
        )

    async def phone_list_apps(
        include_system: Annotated[
            bool, Field(description="是否包含系统应用（默认不包含）")
        ] = False,
        launchable_only: Annotated[
            bool, Field(description="是否只列可启动的应用（默认是）")
        ] = True,
        limit: Annotated[
            int, Field(description="最多返回多少条（1-200）", ge=1, le=200)
        ] = 200,
    ) -> str:
        reply = await _run(
            PHONE_LIST_APPS,
            "app.list",
            {
                "includeSystem": include_system,
                "launchableOnly": launchable_only,
                "limit": limit,
            },
            config=config,
            user_repo=user_repo,
        )
        if isinstance(reply, str):
            return reply
        if not reply.get("ok"):
            return _failure(PHONE_LIST_APPS, "app.list", reply)
        result = _result_of(reply)
        total, apps = _app_list(result)
        return _dumps(
            {
                "ok": True,
                "tool": PHONE_LIST_APPS,
                "command": "app.list",
                "duration_ms": int(reply.get("duration_ms") or 0),
                "count": total,
                "apps": apps,
                "truncated": total > len(apps) or bool(result.get("truncated")),
                "command_id": reply.get("command_id"),
            }
        )

    async def phone_notifications(
        limit: Annotated[int, Field(description="最多返回多少条通知（1-100）", ge=1, le=100)] = 20,
        since_minutes: Annotated[
            int, Field(description="只看最近多少分钟内的通知（0 表示不限）", ge=0, le=1440)
        ] = 60,
        allow_packages: Annotated[
            list[str] | None, Field(description="只保留这些包名的通知（可选）")
        ] = None,
        deny_packages: Annotated[
            list[str] | None, Field(description="排除这些包名的通知（可选，优先级最高）")
        ] = None,
    ) -> str:
        status = await _run(
            PHONE_NOTIFICATIONS, "notification.status", {}, config=config, user_repo=user_repo
        )
        if isinstance(status, str):
            return status
        if not status.get("ok"):
            return _failure(PHONE_NOTIFICATIONS, "notification.status", status)
        if not _result_of(status).get("granted"):
            return _dumps(
                {
                    "ok": True,
                    "tool": PHONE_NOTIFICATIONS,
                    "granted": False,
                    "hint": (
                        "手机尚未授予通知使用权，读不到任何通知。"
                        "请在手机 App 的权限页或系统设置里为本应用开启「通知使用权」，"
                        "授权后重新调用即可；在此之前不要猜测通知内容。"
                    ),
                    "settingsAction": "notification-listener",
                }
            )

        params: dict[str, Any] = {"limit": limit}
        if since_minutes > 0:
            params["sinceMs"] = int(time.time() * 1000) - since_minutes * 60 * 1000
        if allow_packages:
            params["allowPackages"] = ",".join(str(p) for p in allow_packages)
        if deny_packages:
            params["denyPackages"] = ",".join(str(p) for p in deny_packages)
        reply = await _run(
            PHONE_NOTIFICATIONS, "notification.list", params, config=config, user_repo=user_repo
        )
        if isinstance(reply, str):
            return reply
        if not reply.get("ok"):
            return _failure(PHONE_NOTIFICATIONS, "notification.list", reply)
        result = _result_of(reply)
        if result.get("granted") is False:
            return _dumps(
                {
                    "ok": True,
                    "tool": PHONE_NOTIFICATIONS,
                    "granted": False,
                    "hint": str(
                        result.get("hint")
                        or "手机尚未授予通知使用权，读不到任何通知。请在系统设置里开启后重试。"
                    ),
                    "settingsAction": str(result.get("settingsAction") or "notification-listener"),
                }
            )

        sensitive = list(DEFAULT_CONFIG.get("sensitivePackages") or [])
        raw_items = result.get("items")
        if not isinstance(raw_items, list):
            raw_items = result.get("notifications")
        out: list[dict[str, Any]] = []
        redacted_count = 0
        for raw in raw_items if isinstance(raw_items, list) else []:
            if not isinstance(raw, dict):
                continue
            package = str(raw.get("package") or "")
            if deny_packages and package in deny_packages:
                continue
            if allow_packages and package not in allow_packages:
                continue
            title, title_hit = sensitive_redact(str(raw.get("title") or ""), package, sensitive)
            text, text_hit = sensitive_redact(str(raw.get("text") or ""), package, sensitive)
            if title_hit:
                title, text = "[内容已隐藏]", "[内容已隐藏]"
            if title_hit or text_hit:
                redacted_count += 1
            out.append(
                {
                    "package": package,
                    "appLabel": str(raw.get("appLabel") or package),
                    "title": title[:120],
                    "text": text[:_MAX_NOTIFICATION_TEXT],
                    "postedAt": raw.get("postedAt"),
                    "category": raw.get("category"),
                    "key": raw.get("key"),
                    "redacted": bool(title_hit or text_hit),
                }
            )
        return _dumps(
            {
                "ok": True,
                "tool": PHONE_NOTIFICATIONS,
                "command": "notification.list",
                "granted": True,
                "duration_ms": int(reply.get("duration_ms") or 0),
                "count": len(out),
                "items": out,
                "redacted": redacted_count,
                "truncated": bool(result.get("truncated")),
                "command_id": reply.get("command_id"),
            }
        )

    async def phone_time_context(
        days: Annotated[int, Field(description="日程向前看几天（1-7）", ge=1, le=7)] = 1,
    ) -> str:
        calendar_reply, alarm_reply = await asyncio.gather(
            _run(
                PHONE_TIME_CONTEXT,
                "calendar.list",
                {"days": days, "limit": 50},
                config=config,
                user_repo=user_repo,
            ),
            _run(
                PHONE_TIME_CONTEXT, "alarm.list", {}, config=config, user_repo=user_repo
            ),
        )
        calendar = _as_dict(calendar_reply)  # type: ignore[arg-type]
        alarm = _as_dict(alarm_reply)  # type: ignore[arg-type]
        for name, payload in (("calendar.list", calendar), ("alarm.list", alarm)):
            if not payload.get("ok", False) and payload.get("code") == "DEVICE_OFFLINE":
                return _dumps(
                    {
                        "ok": False,
                        "tool": PHONE_TIME_CONTEXT,
                        "command": name,
                        "code": "DEVICE_OFFLINE",
                        "message": str(payload.get("message") or "设备离线，无法读取设备时间信息"),
                        "retryable": True,
                    }
                )

        calendar_result = calendar.get("result") if isinstance(calendar.get("result"), dict) else {}
        alarm_result = alarm.get("result") if isinstance(alarm.get("result"), dict) else {}
        cron_jobs = _cron_snapshot(cron_manager)

        calendar_events = calendar_result.get("items")
        if not isinstance(calendar_events, list):
            calendar_events = calendar_result.get("events")
        events = [
            {
                "title": str(item.get("title") or ""),
                "startAt": item.get("startAt"),
                "endAt": item.get("endAt"),
                "location": str(item.get("location") or ""),
                "allDay": bool(item.get("allDay")),
            }
            for item in (calendar_events if isinstance(calendar_events, list) else [])
            if isinstance(item, dict)
        ]
        cron_names = {
            str(job.get("name") or "").strip() for job in cron_jobs if job.get("name")
        }
        duplicates = [
            event["title"]
            for event in events
            if event["title"] and event["title"] in cron_names
        ]
        return _dumps(
            {
                "ok": True,
                "tool": PHONE_TIME_CONTEXT,
                "calendar": {
                    "granted": bool(calendar_result.get("granted")),
                    "hint": calendar_result.get("hint"),
                    "settingsAction": calendar_result.get("settingsAction") or "calendar",
                    "items": events,
                },
                "alarm": {
                    "nextAlarm": alarm_result.get("nextAlarm"),
                    "items": alarm_result.get("alarms") or [],
                },
                "cronjobs": cron_jobs,
                "duplicates": duplicates,
                "reminder_policy": _REMINDER_POLICY,
            }
        )


    def _action_payload(tool: str, command: str, reply: dict[str, Any]) -> str:
        if not reply.get("ok"):
            return _failure(tool, command, reply)
        return _dumps(
            {
                "ok": True,
                "tool": tool,
                "command": command,
                "duration_ms": int(reply.get("duration_ms") or 0),
                "result": reply.get("result"),
                "command_id": reply.get("command_id"),
            }
        )

    async def phone_tap(
        x: Annotated[int, Field(description="点击横坐标（设备像素）")],
        y: Annotated[int, Field(description="点击纵坐标（设备像素）")],
    ) -> str:
        reply = await _run(
            PHONE_TAP, "ui.click", {"x": x, "y": y}, config=config, user_repo=user_repo
        )
        if isinstance(reply, str):
            return reply
        return _action_payload(PHONE_TAP, "ui.click", reply)

    async def phone_swipe(
        x1: Annotated[int, Field(description="起点横坐标")],
        y1: Annotated[int, Field(description="起点纵坐标")],
        x2: Annotated[int, Field(description="终点横坐标")],
        y2: Annotated[int, Field(description="终点纵坐标")],
        duration_ms: Annotated[
            int, Field(description="滑动耗时（毫秒）", ge=50, le=5000)
        ] = 300,
    ) -> str:
        reply = await _run(
            PHONE_SWIPE,
            "ui.swipe",
            {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "durationMs": duration_ms},
            config=config,
            user_repo=user_repo,
        )
        if isinstance(reply, str):
            return reply
        return _action_payload(PHONE_SWIPE, "ui.swipe", reply)

    async def phone_type_text(
        text: Annotated[str, Field(description="要覆写进输入框的文本")],
        x: Annotated[int | None, Field(description="目标输入框横坐标（可选）")] = None,
        y: Annotated[int | None, Field(description="目标输入框纵坐标（可选）")] = None,
    ) -> str:
        params: dict[str, Any] = {"text": text}
        if x is not None and y is not None:
            params["x"] = x
            params["y"] = y
        reply = await _run(
            PHONE_TYPE_TEXT, "ui.typeText", params, config=config, user_repo=user_repo
        )
        if isinstance(reply, str):
            return reply
        return _action_payload(PHONE_TYPE_TEXT, "ui.typeText", reply)

    return [
        StructuredTool.from_function(
            coroutine=phone_screenshot,
            name=PHONE_SCREENSHOT,
            description=(
                "截取当前配对手机的屏幕，返回 PNG 落盘的绝对路径与宽高。只读，无副作用。"
            ),
        ),
        StructuredTool.from_function(
            coroutine=phone_ui_tree,
            name=PHONE_UI_TREE,
            description=(
                "读取当前手机界面的无障碍元素树，返回包名、屏幕尺寸与元素摘要（文本/控件 id/边界/可点击）。"
            ),
        ),
        StructuredTool.from_function(
            coroutine=phone_list_apps,
            name=PHONE_LIST_APPS,
            description=(
                "列出手机上的应用（包名、名称、是否系统应用、是否可启动）。"
                "默认不含系统应用；只读，无副作用。"
            ),
        ),
        StructuredTool.from_function(
            coroutine=phone_notifications,
            name=PHONE_NOTIFICATIONS,
            description=(
                "读取手机通知（应用、标题、正文、时间），支持按应用白名单/黑名单过滤；"
                "验证码等敏感内容会被隐藏。未授予通知使用权时返回 granted=false 与说明，不报错。"
            ),
        ),
        StructuredTool.from_function(
            coroutine=phone_time_context,
            name=PHONE_TIME_CONTEXT,
            description=(
                "汇总时间信息：手机日程、下一个闹钟、HappyClaw 自己的定时任务。"
                "提醒应只在 HappyClaw 侧创建一次；先用本工具查重与解析相对时间。"
            ),
        ),
        StructuredTool.from_function(
            coroutine=phone_tap,
            name=PHONE_TAP,
            description=(
                "在手机屏幕上点击指定坐标（设备像素）。有副作用，需要用户逐次审批。"
                "坐标参考 phone_screenshot 的宽高或 phone_ui_tree 的 bounds。"
            ),
        ),
        StructuredTool.from_function(
            coroutine=phone_swipe,
            name=PHONE_SWIPE,
            description="在手机屏幕上从起点滑动到终点。有副作用，需要用户逐次审批。",
        ),
        StructuredTool.from_function(
            coroutine=phone_type_text,
            name=PHONE_TYPE_TEXT,
            description=(
                "向当前焦点输入框（或指定坐标的输入框）覆写文本。有副作用，"
                "会替换原有内容，需要用户逐次审批。"
            ),
        ),
    ]


__all__ = [
    "DEVICE_LINK_READONLY_TOOLS",
    "DEVICE_LINK_SIDE_EFFECT_TOOLS",
    "DEVICE_LINK_TOOL_NAMES",
    "PHONE_LIST_APPS",
    "PHONE_NOTIFICATIONS",
    "PHONE_SCREENSHOT",
    "PHONE_SWIPE",
    "PHONE_TAP",
    "PHONE_TIME_CONTEXT",
    "PHONE_TYPE_TEXT",
    "PHONE_UI_TREE",
    "build_device_link_tools",
    "describe_device_action",
    "device_link_interrupt_on",
]
