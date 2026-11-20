"""设备侧信息采集与整合（Today）。

一条固定流水线：采集（通知 / 日程 / 闹钟 / HappyClaw 定时任务）
→ 归一化 → 去重合并 → 落盘当天时间线 → 去重写记忆 → 下发设备首屏
→ 按限频规则主动提醒。

它不走对话，不会因为用户没开口就停止；离线时静默跳过，重连后由事件触发立即补一轮。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from octop.infra.utils.paths import PathLayout
from octop.infra.utils.ulid import new_short_id

from . import items as I
from .store import TodayStore

logger = logging.getLogger(__name__)

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "intervalSeconds": 300,
    "memoryAgentId": None,
    "activeHours": {"start": "08:00", "end": "22:00"},
    "minPushGapMinutes": 60,
    "maxPushesPerDay": 6,
    "minImportanceToPush": 2,
    # 通知默认不采集：必须由用户明确授权（PUT /api/device-link/today）后才开启
    "notificationConsent": False,
    # 通知默认不落盘：none=只在内存里聚合；digest=允许脱敏摘要写入 today.json；
    # memory=摘要可沉淀为记忆
    "notificationStorage": "none",
    "sensitivePackages": [
        "com.android.mms",
        "com.google.android.apps.messaging",
        "com.android.vending",
        "com.google.android.apps.authenticator2",
        "com.android.settings",
    ],
    "denyPackages": [],
    "allowPackages": [],
}

_UNSUPPORTED_CODES = frozenset({"INVALID_COMMAND", "UNSUPPORTED", "NOT_IMPLEMENTED", "UNKNOWN_COMMAND"})
_MAX_MEMORY_PER_ROUND = 10
_MAX_SYNC_ITEMS = 20
_PUSH_TEXT_LIMIT = 200
_QUIET_WINDOW = timedelta(minutes=15)


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "Asia/Shanghai")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _hhmm(value: str, fallback: tuple[int, int]) -> tuple[int, int]:
    try:
        hour, minute = (int(part) for part in str(value).split(":", 1))
        return hour, minute
    except (TypeError, ValueError):
        return fallback


def _in_active_hours(local: datetime, start: tuple[int, int], end: tuple[int, int]) -> bool:
    current = local.hour * 60 + local.minute
    begin = start[0] * 60 + start[1]
    finish = end[0] * 60 + end[1]
    if begin == finish:
        return False
    if begin < finish:
        return begin <= current < finish
    return current >= begin or current < finish


class TodayCollector:
    def __init__(
        self,
        *,
        manager: Any,
        server: Any,
        gateway: Any,
        cron_manager: Any = None,
        agent_repo: Any = None,
        session_repo: Any = None,
        thread_repo: Any = None,
        timezone: str = "Asia/Shanghai",
        config_path: Path | None = None,
        clock: Callable[[], int] | None = None,
    ) -> None:
        self._manager = manager
        self._server = server
        self._gateway = gateway
        self._cron_manager = cron_manager
        self._agent_repo = agent_repo
        self._session_repo = session_repo
        self._thread_repo = thread_repo
        self._timezone = timezone or "Asia/Shanghai"
        self._clock = clock or (lambda: int(time.time() * 1000))

        root = (config_path.parent if config_path else PathLayout.from_env().root / "device-link")
        # 配置与聚合状态分文件：同名会让 update_config 把当天条目整段覆盖掉
        self._config_path = config_path or (root / "today-config.json")
        self._store = TodayStore(root)

        self._tasks: list[asyncio.Task[Any]] = []
        self._run_lock = asyncio.Lock()
        self._queue: asyncio.Queue[dict[str, Any]] | None = None
        self._unsupported: set[str] = set()
        self._started = False

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def config(self) -> dict[str, Any]:
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        try:
            raw = json.loads(self._config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        if isinstance(raw, dict):
            for key, value in raw.items():
                if key == "activeHours" and isinstance(value, dict):
                    cfg["activeHours"] = {**cfg["activeHours"], **value}
                elif key in cfg:
                    cfg[key] = value
        if str(cfg.get("notificationStorage") or "none") not in {"none", "digest", "memory"}:
            cfg["notificationStorage"] = "none"
        return cfg

    def update_config(self, patch: dict[str, Any]) -> dict[str, Any]:
        """部分更新配置并落盘；返回更新后的完整配置。"""
        try:
            current = json.loads(self._config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            current = {}
        if not isinstance(current, dict):
            current = {}
        for key, value in (patch or {}).items():
            if key not in DEFAULT_CONFIG:
                continue
            if key == "activeHours" and isinstance(value, dict):
                current["activeHours"] = {
                    **{k: v for k, v in (current.get("activeHours") or {}).items() if isinstance(v, str)},
                    **{str(k): str(v) for k, v in value.items()},
                }
            else:
                current[key] = value
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._config_path.with_suffix(self._config_path.suffix + ".tmp")
        tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._config_path)
        return self.config()

    def snapshot(self) -> dict[str, Any]:
        return {
            "config": self.config(),
            "snapshot": self._store.snapshot(),
        }

    async def start(self) -> None:
        if self._started:
            return
        cfg = self.config()
        if not cfg.get("enabled", True):
            logger.info("TodayCollector: disabled by config")
            return
        self._started = True
        try:
            self._queue = self._manager.subscribe()
        except Exception:  # noqa: BLE001
            logger.warning("TodayCollector: subscribe device events failed", exc_info=True)
        self._tasks = [
            asyncio.create_task(self._periodic_loop(), name="today-collector-periodic"),
            asyncio.create_task(self._event_loop(), name="today-collector-events"),
        ]
        logger.info("TodayCollector: started (interval=%ss)", cfg.get("intervalSeconds"))

    async def stop(self) -> None:
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if self._queue is not None:
            try:
                self._manager.unsubscribe(self._queue)
            except Exception:  # noqa: BLE001
                pass
            self._queue = None
        self._started = False

    @property
    def store(self) -> TodayStore:
        return self._store

    async def _periodic_loop(self) -> None:
        while True:
            interval = max(60, int(self.config().get("intervalSeconds") or 300))
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.warning("TodayCollector: periodic round failed", exc_info=True)
            await asyncio.sleep(interval)

    async def _event_loop(self) -> None:
        queue = self._queue
        if queue is None:
            return
        while True:
            event = await queue.get()
            if not isinstance(event, dict):
                continue
            kind = str(event.get("kind") or "")
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            try:
                if kind in {"client.connected", "link.paired", "link.connected"}:
                    await self.run_once()
                elif kind == "today.capture":
                    await self.handle_capture(data)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.warning("TodayCollector: event %s failed", kind, exc_info=True)

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------

    async def run_once(self) -> None:
        if not self._manager.is_online():
            logger.debug("TodayCollector: device offline, skip")
            return
        if self._run_lock.locked():
            return
        async with self._run_lock:
            cfg = self.config()
            now = datetime.now(UTC)
            now_ms = self._clock()
            day_start, day_end = I.day_bounds(now, self._timezone)

            collected: list[I.TodayItem] = []
            ephemeral: list[I.TodayItem] = []
            storage = str(cfg.get("notificationStorage") or "none")
            if bool(cfg.get("notificationConsent")):
                notes = await self._collect_notifications(cfg, now_ms)
                if storage in {"digest", "memory"}:
                    collected.extend(notes)
                else:
                    # 默认策略：通知只在内存里参与当天聚合，不写 today.json
                    ephemeral.extend(notes)
            else:
                self._store.set_permissions(
                    {"notification": False, "notificationConsent": False}
                )
            collected.extend(await self._collect_calendar(day_end - day_start))
            collected.extend(await self._collect_alarms(now, day_start, day_end))
            collected.extend(self._collect_cron(now))

            merged, added = self._store.merge(
                collected,
                now_ms=now_ms,
                day=now.astimezone(_zone(self._timezone)).strftime("%Y-%m-%d"),
            )
            if added:
                logger.info("TodayCollector: merged %d new items", len(added))

            timeline = I.build_timeline(
                I.merge_items([*merged, *ephemeral]),
                day_start_ms=day_start,
                day_end_ms=day_end,
            )
            await self._write_memory(timeline, cfg, now)
            # 先推送再同步：本轮新产生的「想告诉你」条目才能立刻下发到首屏
            await self._maybe_push(timeline, cfg, now, day_start, day_end)
            await self._sync_device(timeline, now_ms, day_start, day_end)

    async def handle_capture(self, body: dict[str, Any]) -> None:
        """设备端「说一句就记下来」：立即并入今天并写记忆。"""
        text = str(body.get("text") or "").strip()
        if not text:
            return
        captured_at = body.get("capturedAt") or self._clock()
        item = I.item_from_capture(text, int(captured_at) if isinstance(captured_at, (int, float)) else None)
        if item is None:
            return
        cfg = self.config()
        now = datetime.now(UTC)
        day_start, day_end = I.day_bounds(now, self._timezone)
        merged, _ = self._store.merge([item], now_ms=self._clock())
        timeline = I.build_timeline(merged, day_start_ms=day_start, day_end_ms=day_end)
        await self._write_memory([item], cfg, now)
        await self._sync_device(timeline, self._clock(), day_start, day_end)
        logger.info("TodayCollector: captured note %r", text[:40])

    # ------------------------------------------------------------------
    # 采集
    # ------------------------------------------------------------------

    async def _cmd(self, name: str, params: dict[str, Any]) -> dict[str, Any] | None:
        if name in self._unsupported:
            return None
        try:
            reply = await self._manager.run_command(
                name, params, command_id=new_short_id(12), timeout_ms=12_000
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("TodayCollector: %s failed: %s", name, exc)
            return None
        if not isinstance(reply, dict):
            return None
        if not reply.get("ok"):
            code = str((reply.get("error") or {}).get("code") or "")
            if code in _UNSUPPORTED_CODES:
                self._unsupported.add(name)
                logger.info("TodayCollector: device does not support %s yet", name)
            else:
                logger.debug("TodayCollector: %s error %s", name, code)
            return None
        result = reply.get("result")
        return result if isinstance(result, dict) else {}

    async def _collect_notifications(self, cfg: dict[str, Any], now_ms: int) -> list[I.TodayItem]:
        status = await self._cmd("notification.status", {})
        granted = bool(status and status.get("granted"))
        self._store.set_permissions({"notification": granted, "notificationConsent": True})
        if not granted:
            logger.info("TodayCollector: notification listener not granted, skip notifications")
            return []

        cursor = self._store.cursor() or (now_ms - 24 * 3600 * 1000)
        result = await self._cmd(
            "notification.list",
            {
                "limit": 100,
                "sinceMs": cursor,
                "allowPackages": ",".join(str(p) for p in cfg.get("allowPackages") or []),
                "denyPackages": ",".join(str(p) for p in cfg.get("denyPackages") or []),
            },
        )
        if result is None:
            return []
        raw_items = result.get("items")
        if not isinstance(raw_items, list):
            raw_items = result.get("notifications")
        raw_items = raw_items if isinstance(raw_items, list) else []
        newest = cursor
        out: list[I.TodayItem] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            item = I.item_from_notification(
                raw,
                allow=cfg.get("allowPackages") or [],
                deny=cfg.get("denyPackages") or [],
                sensitive=cfg.get("sensitivePackages") or [],
            )
            if item is not None:
                out.append(item)
            posted = raw.get("postedAt")
            if isinstance(posted, (int, float)):
                newest = max(newest, int(posted))
        self._store.set_cursor(newest)
        return out

    async def _collect_calendar(self, window_ms: int) -> list[I.TodayItem]:
        days = max(1, min(7, int(window_ms // (24 * 3600 * 1000)) or 1))
        result = await self._cmd("calendar.list", {"days": days, "limit": 50})
        if result is None:
            return []
        self._store.set_permissions({"calendar": bool(result.get("granted"))})
        if not result.get("granted"):
            return []
        raw_items = result.get("items")
        if not isinstance(raw_items, list):
            raw_items = result.get("events")
        out: list[I.TodayItem] = []
        for raw in raw_items if isinstance(raw_items, list) else []:
            if isinstance(raw, dict):
                item = I.item_from_calendar(raw)
                if item is not None:
                    out.append(item)
        return out

    async def _collect_alarms(
        self, now: datetime, day_start: int, day_end: int
    ) -> list[I.TodayItem]:
        result = await self._cmd("alarm.list", {})
        if not result:
            return []
        item = I.item_from_alarm(result, now)
        if item is None:
            return []
        if item.at is not None and not (day_start <= item.at < day_end):
            return []
        return [item]

    def _collect_cron(self, now: datetime) -> list[I.TodayItem]:
        if self._cron_manager is None:
            return []
        try:
            rows = self._cron_manager.list_all(include_disabled=False)
        except TypeError:
            try:
                rows = self._cron_manager.list_all()
            except Exception:  # noqa: BLE001
                return []
        except Exception:  # noqa: BLE001
            return []
        out: list[I.TodayItem] = []
        for row in rows:
            item = I.item_from_cron(row, now, self._timezone)
            if item is not None:
                out.append(item)
        return out

    # ------------------------------------------------------------------
    # 记忆
    # ------------------------------------------------------------------

    def _resolve_agent(self, cfg: dict[str, Any]) -> str | None:
        override = cfg.get("memoryAgentId")
        if isinstance(override, str) and override.strip():
            return override.strip()
        if self._agent_repo is None:
            return None
        try:
            rows = self._agent_repo.list_all()
        except Exception:  # noqa: BLE001
            return None
        # agent 记录同时有自增 id 与字符串 agent_id，对外一律用后者
        ids = sorted(
            str(getattr(row, "agent_id", "") or getattr(row, "id", "") or "") for row in rows
        )
        # 优先挑真的有过会话的 agent：id 最小的那个可能只是个空壳，
        # 主动提醒会因为没有会话键而静默丢失。
        if self._session_repo is not None:
            for agent_id in ids:
                if not agent_id:
                    continue
                try:
                    if self._session_repo.list_by_agent(agent_id, limit=1):
                        return agent_id
                except Exception:  # noqa: BLE001
                    continue
        return next((agent_id for agent_id in ids if agent_id), None)

    async def _write_memory(
        self,
        timeline: list[I.TodayItem],
        cfg: dict[str, Any],
        now: datetime,
    ) -> None:
        agent_id = self._resolve_agent(cfg)
        if not agent_id:
            return
        allow_notification_memory = str(cfg.get("notificationStorage") or "none") == "memory"
        candidates = [
            item
            for item in timeline
            if (item.needs_action or item.importance >= 2)
            and not self._store.seen(item.id)
            and not item.refs.get("redacted")
            and (
                allow_notification_memory
                or not item.source.startswith("notification:")
            )
        ][:_MAX_MEMORY_PER_ROUND]
        if not candidates:
            return
        try:
            from octop.api.common.memory_client import _open_memory_for_agent  # noqa: PLC0415
        except Exception:  # noqa: BLE001
            return
        try:
            _memory, bridge = _open_memory_for_agent(self._server, agent_id)
        except Exception:  # noqa: BLE001
            logger.warning("TodayCollector: open memory failed agent=%s", agent_id, exc_info=True)
            return

        written: list[str] = []
        for index, item in enumerate(candidates, start=1):
            params = {
                "assertion": self._assertion(item),
                "entity_name": item.people[0] if item.people else "今日事项",
                "entity_type": "Fact",
                "kind": "Task" if item.needs_action else "Fact",
                "importance": "high" if item.importance >= 3 else "medium",
                "confidence": "medium",
                "reason": "device-today-collector",
            }
            try:
                response = bridge.handle(
                    {
                        "jsonrpc": "2.0",
                        "id": index,
                        "method": "create_atom",
                        "params": params,
                    }
                )
            except Exception:  # noqa: BLE001
                logger.warning("TodayCollector: create_atom failed", exc_info=True)
                continue
            if isinstance(response, dict) and response.get("error"):
                logger.warning("TodayCollector: create_atom rejected: %s", response.get("error"))
                continue
            written.append(item.id)
        if written:
            self._store.mark_seen(written)
            logger.info("TodayCollector: wrote %d memory atoms", len(written))

    def _assertion(self, item: I.TodayItem) -> str:
        clock = I.format_clock(item.at, self._timezone)
        head = f"{clock} {item.title}" if item.at else item.title
        body = item.text.strip()
        if body and body != I.REDACTED:
            head = f"{head}：{body[:120]}"
        return f"{head}（来源：{I.source_label(item.sources)}）"

    # ------------------------------------------------------------------
    # 下发设备 / 主动提醒
    # ------------------------------------------------------------------

    async def _sync_device(
        self,
        timeline: list[I.TodayItem],
        now_ms: int,
        day_start: int,
        day_end: int,
    ) -> None:
        if "today.sync" in self._unsupported:
            return
        todos: list[dict[str, Any]] = []
        reminders: list[dict[str, Any]] = []
        proactive: list[dict[str, Any]] = []
        merged_keys: list[str] = []
        for item in timeline:
            if item.kind == I.KIND_CARE:
                proactive.append(
                    {"id": item.id, "text": item.title, "createdAt": item.at or now_ms}
                )
            elif item.kind == I.KIND_TODO:
                todos.append({"id": item.id, "text": item.title, "done": False})
            elif item.kind in (I.KIND_SCHEDULE, I.KIND_REMINDER):
                reminders.append(
                    {"id": item.id, "text": item.title, "dueAt": item.at or day_start}
                )
            if item.kind != I.KIND_NOTIFICATION:
                key = str(item.refs.get("notificationKey") or "").strip()
                if key:
                    merged_keys.append(key)
        payload = {
            "todos": todos[: _MAX_SYNC_ITEMS],
            "reminders": reminders[: _MAX_SYNC_ITEMS],
            "proactive": proactive[: _MAX_SYNC_ITEMS],
            # 已被并入日程/提醒/待办的通知，设备侧不要再单列一条，避免同一件事出现两次
            "mergedNotificationKeys": merged_keys,
            "updatedAt": now_ms,
        }
        try:
            reply = await self._manager.run_command(
                "today.sync", payload, command_id=new_short_id(12), timeout_ms=8_000
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("TodayCollector: today.sync failed: %s", exc)
            return
        if isinstance(reply, dict) and not reply.get("ok"):
            code = str((reply.get("error") or {}).get("code") or "")
            if code in _UNSUPPORTED_CODES:
                self._unsupported.add("today.sync")
                logger.info("TodayCollector: device does not support today.sync yet")
            else:
                logger.debug("TodayCollector: today.sync error %s", code)

    async def _maybe_push(
        self,
        timeline: list[I.TodayItem],
        cfg: dict[str, Any],
        now: datetime,
        day_start: int,
        day_end: int,
    ) -> None:
        local = now.astimezone(_zone(self._timezone))
        hours = cfg.get("activeHours") or {}
        if not _in_active_hours(
            local,
            _hhmm(str(hours.get("start") or "08:00"), (8, 0)),
            _hhmm(str(hours.get("end") or "22:00"), (22, 0)),
        ):
            logger.debug("TodayCollector: push skipped, outside active hours (%s)", local)
            return

        now_ms = self._clock()
        gap_ms = int(cfg.get("minPushGapMinutes") or 60) * 60 * 1000
        last = self._store.last_push_at()
        if last is not None and now_ms - last < gap_ms:
            logger.debug("TodayCollector: push skipped, within min gap")
            return
        if self._store.pushes_between(day_start, day_end) >= int(cfg.get("maxPushesPerDay") or 6):
            logger.debug("TodayCollector: push skipped, daily cap reached")
            return

        min_importance = int(cfg.get("minImportanceToPush") or 2)
        pushed = self._store.pushed_ids()
        candidates = [
            item
            for item in timeline
            if item.kind != I.KIND_CARE
            and item.id not in pushed
            and (item.needs_action or item.importance >= min_importance)
            and not item.refs.get("redacted")
        ]
        if not candidates:
            logger.debug("TodayCollector: push skipped, no candidate items")
            return

        agent_id = self._resolve_agent(cfg)
        if not agent_id:
            logger.debug("TodayCollector: push skipped, no agent")
            return
        if self._recent_user_activity(agent_id, now_ms):
            logger.debug("TodayCollector: push skipped, user active within quiet window")
            return
        session_key = self._pick_session(agent_id)
        if not session_key:
            logger.debug("TodayCollector: push skipped, no session for %s", agent_id)
            return

        picked = sorted(
            candidates,
            key=lambda it: (-it.importance, it.at is None, it.at or 0),
        )[:3]
        text = self._push_text(picked)
        try:
            await self._gateway.push_text_from_session(agent_id, session_key, text)
        except Exception:  # noqa: BLE001
            logger.warning("TodayCollector: proactive push failed", exc_info=True)
            return
        self._store.record_push([item.id for item in picked], now_ms)
        if str(cfg.get("notificationStorage") or "none") != "none":
            # storage=none 时连「已推送摘要」也不落盘，避免留下通知痕迹
            care_item = I.item_from_care(text, now_ms)
            if care_item is not None:
                self._store.merge([care_item], now_ms=now_ms)
        logger.info("TodayCollector: pushed today summary (%d items)", len(picked))

    def _push_text(self, picked: list[I.TodayItem]) -> str:
        parts = [I.describe_item(item, self._timezone) for item in picked[:2]]
        head = "、".join(parts)
        rest = len(picked) - len(parts)
        text = f"今天 {head}" if head else "今天"
        if rest > 0:
            text += f"，另外 {rest} 条需要关注"
        return text[:_PUSH_TEXT_LIMIT]

    def _recent_user_activity(self, agent_id: str, now_ms: int) -> bool:
        if self._thread_repo is None:
            return False
        try:
            latest = self._thread_repo.latest_user_activity(agent_id)
        except Exception:  # noqa: BLE001
            return False
        if latest is None:
            return False
        stamp = int(latest)
        if stamp < 100_000_000_000:
            stamp *= 1000
        return now_ms - stamp < int(_QUIET_WINDOW.total_seconds() * 1000)

    def _pick_session(self, agent_id: str) -> str | None:
        if self._session_repo is not None:
            try:
                rows = self._session_repo.list_by_agent(agent_id, limit=10)
            except Exception:  # noqa: BLE001
                rows = []
            if rows:
                target = next((s for s in rows if getattr(s, "channel_id", None)), rows[0])
                key = getattr(target, "session_key", None)
                if key:
                    return str(key)
        # 退化路径：沿用默认会话键
        fallback = getattr(self._gateway, "default_session_key", None)
        return str(fallback) if fallback else None


_collector: TodayCollector | None = None


def set_today_collector(collector: TodayCollector | None) -> None:
    global _collector
    _collector = collector


def get_today_collector() -> TodayCollector | None:
    return _collector


__all__ = ["DEFAULT_CONFIG", "TodayCollector", "get_today_collector", "set_today_collector"]


