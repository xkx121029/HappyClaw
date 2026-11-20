"""设备侧信息的统一条目模型。

手机侧来源（应用通知、日程、闹钟、HappyClaw 定时任务、用户口述）各不相同，
这里先归一化成同一结构 :class:`TodayItem`，再做去重合并与时间线排序，
供采集器落盘、写记忆、下发 Today 首屏与生成主动提醒。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

KIND_SCHEDULE = "schedule"
KIND_REMINDER = "reminder"
KIND_TODO = "todo"
KIND_NOTIFICATION = "notification"
KIND_MESSAGE = "message"
KIND_CARE = "care"

KINDS = (
    KIND_SCHEDULE,
    KIND_REMINDER,
    KIND_TODO,
    KIND_NOTIFICATION,
    KIND_MESSAGE,
    KIND_CARE,
)

# 合并分组：日程/提醒/待办互相可能描述同一件事；通知/消息同理。
_SCHEDULE_GROUP = frozenset({KIND_SCHEDULE, KIND_REMINDER, KIND_TODO})
_MESSAGE_GROUP = frozenset({KIND_NOTIFICATION, KIND_MESSAGE})

_MESSAGE_CATEGORIES = frozenset({"msg", "email", "social"})
_CALL_CATEGORIES = frozenset({"call", "alarm"})
_URGENT_WORDS = ("紧急", "逾期", "审批", "立即", "逾期未", "urgent", "asap")
_ACTION_WORDS = (
    "回复",
    "确认",
    "审批",
    "付款",
    "支付",
    "待办",
    "截止",
    "签到",
    "提交",
    "报名",
    "reply",
    "confirm",
)

# 敏感内容：命中验证码/密码形态时，正文一律不落盘。
_SENSITIVE_RE = re.compile(
    r"((验证码|校验码|动态码|口令|密码|verification\s+code|one[-\s]?time\s+code|otp|password)"
    r"\s*[:：为是]?\s*)([0-9A-Za-z]{4,12})",
    re.IGNORECASE,
)
_PERSON_PREFIX_RE = re.compile(r"^([\u4e00-\u9fa5A-Za-z0-9_\-\.]{2,16})\s*[:：]")

REDACTED = "[内容已隐藏]"


def normalize_text(value: str) -> str:
    """归一化文本用于相似度比较：小写、去掉空白与标点。"""
    return re.sub(r"[\s\W_]+", "", (value or "").lower())


def sensitive_redact(
    text: str,
    package: str,
    sensitive_packages: Iterable[str],
) -> tuple[str, bool]:
    """按敏感包与验证码形态脱敏；返回 (脱敏后文本, 是否命中)。"""
    pkg = (package or "").strip()
    for item in sensitive_packages:
        prefix = str(item or "").strip()
        if prefix and (pkg == prefix or pkg.startswith(prefix)):
            return (REDACTED if text else "", True)
    if not text:
        return ("", False)
    if _SENSITIVE_RE.search(text):
        return (_SENSITIVE_RE.sub(lambda m: f"{m.group(1)}{REDACTED}", text), True)
    return (text, False)


def _ms(value: Any) -> int | None:
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    # 兼容秒与毫秒
    return number * 1000 if number < 100_000_000_000 else number


def _stable_id(kind: str, title: str, at: int | None, bucket_ms: int = 300_000) -> str:
    stamp = int((at or 0) // bucket_ms)
    raw = f"{kind}|{normalize_text(title)}|{stamp}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _truncate(value: str, limit: int = 300) -> str:
    clean = (value or "").strip()
    return clean if len(clean) <= limit else clean[:limit] + "…"


def _needs_action(text: str, category: str = "") -> bool:
    lowered = (text or "").lower()
    if category in _MESSAGE_CATEGORIES | _CALL_CATEGORIES:
        return True
    return any(word in lowered for word in _ACTION_WORDS)


def _importance(text: str, category: str = "") -> int:
    level = 1
    if _needs_action(text, category):
        level = 2
    lowered = (text or "").lower()
    if category in _CALL_CATEGORIES or any(word in lowered for word in _URGENT_WORDS):
        level = 3
    return level


@dataclass
class TodayItem:
    id: str
    kind: str
    source: str
    title: str
    text: str = ""
    at: int | None = None
    end_at: int | None = None
    people: list[str] = field(default_factory=list)
    needs_action: bool = False
    importance: int = 1
    sources: list[str] = field(default_factory=list)
    refs: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.sources:
            self.sources = [self.source]
        if self.source not in self.sources:
            self.sources.insert(0, self.source)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "source": self.source,
            "sources": list(self.sources),
            "title": self.title,
            "text": self.text,
            "at": self.at,
            "endAt": self.end_at,
            "people": list(self.people),
            "needsAction": self.needs_action,
            "importance": self.importance,
            "refs": dict(self.refs),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TodayItem | None:
        if not isinstance(raw, dict) or not raw.get("id") or not raw.get("kind"):
            return None
        return cls(
            id=str(raw["id"]),
            kind=str(raw["kind"]),
            source=str(raw.get("source") or ""),
            title=str(raw.get("title") or ""),
            text=str(raw.get("text") or ""),
            at=_ms(raw.get("at")),
            end_at=_ms(raw.get("endAt")),
            people=[str(p) for p in raw.get("people") or [] if str(p).strip()],
            needs_action=bool(raw.get("needsAction")),
            importance=int(raw.get("importance") or 1),
            sources=[str(s) for s in raw.get("sources") or [] if str(s).strip()],
            refs=dict(raw.get("refs") or {}),
        )


# ----------------------------------------------------------------------
# 各来源的归一化
# ----------------------------------------------------------------------


def item_from_notification(
    raw: dict[str, Any],
    *,
    allow: Iterable[str] = (),
    deny: Iterable[str] = (),
    sensitive: Iterable[str] = (),
) -> TodayItem | None:
    package = str(raw.get("package") or "").strip()
    if not package:
        return None
    allow_set = {str(p).strip() for p in allow if str(p).strip()}
    deny_set = {str(p).strip() for p in deny if str(p).strip()}
    if package in deny_set:
        return None
    if allow_set and package not in allow_set:
        return None

    title = _truncate(str(raw.get("title") or ""), 120)
    body = _truncate(str(raw.get("text") or ""), 300)
    if not title and not body:
        # 分组摘要/占位通知没有内容，收进来只会污染当天时间线
        return None
    title, title_hit = sensitive_redact(title, package, sensitive)
    body, body_hit = sensitive_redact(body, package, sensitive)
    if title_hit:
        # 标题本身带敏感信息（常见于验证码通知），整条只留来源
        title = REDACTED
        body = REDACTED

    category = str(raw.get("category") or "").strip().lower()
    kind = KIND_MESSAGE if category in _MESSAGE_CATEGORIES else KIND_NOTIFICATION
    label = str(raw.get("appLabel") or package)

    people: list[str] = []
    match = _PERSON_PREFIX_RE.match(title)
    if match and kind == KIND_MESSAGE:
        people = [match.group(1)]
    elif kind == KIND_MESSAGE and re.fullmatch(r"[\u4e00-\u9fa5A-Za-z0-9_\-\.]{2,16}", title):
        # 消息类通知的标题常常就是联系人/群名（如「张三」），正文才是内容
        people = [title]

    combined = f"{title} {body}".strip()
    posted_at = _ms(raw.get("postedAt"))
    return TodayItem(
        id=_stable_id(kind, title or label, posted_at),
        kind=kind,
        source=f"notification:{package}",
        title=title or label,
        text=body,
        at=posted_at,
        people=people,
        needs_action=_needs_action(combined, category),
        importance=_importance(combined, category),
        refs={
            "package": package,
            "notificationKey": raw.get("key"),
            "appLabel": label,
            "redacted": bool(title_hit or body_hit),
        },
    )


def item_from_calendar(raw: dict[str, Any]) -> TodayItem | None:
    title = _truncate(str(raw.get("title") or ""), 120)
    if not title:
        return None
    start_at = _ms(raw.get("startAt"))
    description = _truncate(str(raw.get("description") or ""), 300)
    location = _truncate(str(raw.get("location") or ""), 120)
    text = "；".join(part for part in (description, f"地点：{location}" if location else "") if part)
    attendees = [str(a) for a in raw.get("attendees") or [] if str(a).strip()][:10]
    return TodayItem(
        id=_stable_id(KIND_SCHEDULE, title, start_at, bucket_ms=3_600_000),
        kind=KIND_SCHEDULE,
        source="calendar",
        title=title,
        text=text,
        at=start_at,
        end_at=_ms(raw.get("endAt")),
        people=attendees,
        needs_action=False,
        importance=2,
        refs={
            "eventId": raw.get("eventId"),
            "calendarId": raw.get("calendarId"),
            "allDay": bool(raw.get("allDay")),
        },
    )


_ALARM_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*(AM|PM)?", re.IGNORECASE)
_CN_WEEKDAYS = "一二三四五六日"


def _alarm_at(text: str, now: datetime) -> datetime | None:
    """把系统闹钟文案（"Sun 9:00 PM" / "周日 21:00"）落成当天的时间点。"""
    match = _ALARM_TIME_RE.search(text)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    meridiem = (match.group(3) or "").upper()
    if meridiem == "PM" and hour < 12:
        hour += 12
    elif meridiem == "AM" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    prefix = text[: match.start()].strip()
    if prefix:
        # 只在「今天响」时落到今天的时间线；跨天闹钟保持无时间点
        today_names = {
            now.strftime("%a"),
            "周" + _CN_WEEKDAYS[now.weekday()],
            "周" + _CN_WEEKDAYS[now.weekday()] + "天",
            "星期" + _CN_WEEKDAYS[now.weekday()],
            "今天",
            "Today",
        }
        if prefix not in today_names:
            return None
    return int(now.replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp() * 1000)


def item_from_alarm(raw: dict[str, Any], now: datetime) -> TodayItem | None:
    """系统闹钟：只取下一个响铃，作为当天的提醒条目。"""
    next_alarm = str(raw.get("nextAlarm") or "").strip()
    if next_alarm in {"无", "无闹钟", "None", "null", "-"}:
        next_alarm = ""
    if raw.get("hasAlarm") is False:
        next_alarm = ""
    alarms = raw.get("alarms") if isinstance(raw.get("alarms"), list) else []
    # 设备给了绝对时间戳就用它，格式化文案只作兜底与展示
    explicit_at = raw.get("nextAlarmAt")
    if not isinstance(explicit_at, (int, float)) or explicit_at <= 0:
        explicit_at = None
    if next_alarm:
        return TodayItem(
            id=_stable_id(KIND_REMINDER, f"闹钟 {next_alarm}", None, bucket_ms=3_600_000),
            kind=KIND_REMINDER,
            source="alarm",
            title=f"闹钟 {next_alarm}",
            at=int(explicit_at) if explicit_at is not None else _alarm_at(next_alarm, now),
            importance=2,
            refs={"nextAlarm": next_alarm},
        )
    first = next((a for a in alarms if isinstance(a, dict)), None)
    if not first:
        return None
    try:
        hour = int(first.get("hour"))
        minute = int(first.get("minute"))
    except (TypeError, ValueError):
        return None
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate < now:
        candidate += timedelta(days=1)
    label = str(first.get("label") or "").strip() or "闹钟"
    return TodayItem(
        id=_stable_id(KIND_REMINDER, label, int(candidate.timestamp() * 1000), bucket_ms=3_600_000),
        kind=KIND_REMINDER,
        source="alarm",
        title=f"{label} {hour:02d}:{minute:02d}",
        at=int(candidate.timestamp() * 1000),
        importance=2,
        refs={"hour": hour, "minute": minute},
    )


def item_from_cron(row: Any, now: datetime, tz_name: str = "Asia/Shanghai") -> TodayItem | None:
    """HappyClaw 自己的定时任务：与设备日程同框展示，但不重复创建。"""
    name = str(getattr(row, "name", "") or getattr(row, "title", "") or "").strip()
    # 优先稳定的 cron_id：行对象的自增 id 会随重建变化，不适合放进 refs
    cron_id = str(getattr(row, "cron_id", "") or getattr(row, "id", "") or "").strip()
    if not name or not cron_id:
        return None
    if str(getattr(row, "enabled", 1)) in {"0", "False", "false"}:
        return None
    at = _ms(getattr(row, "next_run_at", None))
    if at is not None and not _same_local_day(at, now, tz_name):
        return None
    return TodayItem(
        id=_stable_id(KIND_TODO, name, at, bucket_ms=3_600_000),
        kind=KIND_TODO,
        source="happyclaw",
        title=name,
        at=at,
        needs_action=True,
        importance=2,
        refs={"cronId": cron_id},
    )


def item_from_capture(text: str, captured_at: int | None) -> TodayItem | None:
    clean = _truncate(text, 300)
    if not clean:
        return None
    at = _ms(captured_at)
    return TodayItem(
        id=_stable_id(KIND_TODO, clean, at),
        kind=KIND_TODO,
        source="device-capture",
        title=clean,
        at=at,
        needs_action=True,
        importance=2,
        refs={"capturedAt": at},
    )


def item_from_care(text: str, created_at: int | None) -> TodayItem | None:
    clean = _truncate(text, 300)
    if not clean:
        return None
    at = _ms(created_at)
    return TodayItem(
        id=_stable_id(KIND_CARE, clean, at, bucket_ms=3_600_000),
        kind=KIND_CARE,
        source="happyclaw",
        title=clean,
        at=at,
        needs_action=False,
        importance=1,
        refs={"createdAt": at},
    )


def _same_local_day(at_ms: int, now: datetime, tz_name: str) -> bool:
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz = UTC
    return (
        datetime.fromtimestamp(at_ms / 1000, tz).date()
        == now.astimezone(tz).date()
    )


# ----------------------------------------------------------------------
# 去重合并
# ----------------------------------------------------------------------


def _group_of(kind: str) -> frozenset[str]:
    if kind in _SCHEDULE_GROUP:
        return _SCHEDULE_GROUP
    if kind in _MESSAGE_GROUP:
        return _MESSAGE_GROUP
    return frozenset({kind})


_DAY_TOKEN_RE = re.compile(r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun|周[一二三四五六日天])", re.IGNORECASE)


def _alarm_signature(item: TodayItem) -> str | None:
    """闹钟的「哪天几点」签名。

    时钟应用会为同一个闹钟再发一条「Upcoming alarm」通知，它和系统闹钟文案
    属于同一件事，但两者文本差异大、时间点也不同，需要靠签名而非相似度合并。
    """
    if item.kind not in {KIND_REMINDER, KIND_NOTIFICATION}:
        return None
    text = f"{item.title} {item.text}"
    time_match = _ALARM_TIME_RE.search(text)
    day_match = _DAY_TOKEN_RE.search(text)
    if not time_match or not day_match:
        return None
    hour, minute = int(time_match.group(1)), int(time_match.group(2))
    meridiem = (time_match.group(3) or "").upper()
    if meridiem == "PM" and hour < 12:
        hour += 12
    elif meridiem == "AM" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return f"{day_match.group(1).lower()}{hour:02d}{minute:02d}"


def _mergeable(left: TodayItem, right: TodayItem) -> bool:
    same_alarm = bool(
        _alarm_signature(left) is not None and _alarm_signature(left) == _alarm_signature(right)
    )
    if not same_alarm:
        if _group_of(left.kind) is not _group_of(right.kind):
            return False
        window = 30 * 60 * 1000 if _group_of(left.kind) is _MESSAGE_GROUP else 24 * 60 * 60 * 1000
        if left.at is not None and right.at is not None:
            if abs(left.at - right.at) > window:
                return False
        elif left.at is not None or right.at is not None:
            # 一侧没有时间（如系统闹钟文案）时不参与自动合并，避免误并
            return False

    left_text = normalize_text(f"{left.title}{left.text}")
    right_text = normalize_text(f"{right.title}{right.text}")
    if not left_text or not right_text:
        return same_alarm
    if same_alarm:
        # 同一个闹钟在不同来源里的文案差别很大，签名一致就并
        return True
    threshold = 0.72
    shared_people = set(left.people) & set(right.people)
    if shared_people and left.at is not None and right.at is not None:
        if abs(left.at - right.at) <= 10 * 60 * 1000:
            threshold = 0.6
    return SequenceMatcher(None, left_text, right_text).ratio() >= threshold


def _absorb(target: TodayItem, extra: TodayItem) -> None:
    if target.at is None or (extra.at is not None and extra.at < target.at):
        target.at = extra.at
    if len(extra.text) > len(target.text):
        target.text = extra.text
    if len(extra.title) > len(target.title) and target.title != REDACTED:
        target.title = extra.title
    for source in extra.sources:
        if source not in target.sources:
            target.sources.append(source)
    for person in extra.people:
        if person not in target.people:
            target.people.append(person)
    target.needs_action = target.needs_action or extra.needs_action
    target.importance = max(target.importance, extra.importance)
    if extra.end_at is not None and target.end_at is None:
        target.end_at = extra.end_at
    for key, value in extra.refs.items():
        target.refs.setdefault(key, value)


def merge_items(items: Iterable[TodayItem]) -> list[TodayItem]:
    """同一件事从多个来源出现时只留一条，并标出来源集合。"""
    ordered = sorted(
        (item for item in items if item is not None),
        key=lambda it: (it.at is None, it.at or 0, -it.importance),
    )
    merged: list[TodayItem] = []
    for item in ordered:
        found = next(
            ((idx, existing) for idx, existing in enumerate(merged) if _mergeable(existing, item)),
            None,
        )
        if found is None:
            merged.append(item)
            continue
        index, target = found
        if item.kind == KIND_REMINDER and target.kind != KIND_REMINDER:
            # 闹钟事件以系统闹钟为骨架：保留闹钟时间，通知只补文本与来源
            keep_at = item.at
            _absorb(item, target)
            item.at = keep_at
            merged[index] = item
        else:
            _absorb(target, item)
    return merged


# ----------------------------------------------------------------------
# 当天时间线
# ----------------------------------------------------------------------


def day_bounds(now: datetime, tz_name: str = "Asia/Shanghai") -> tuple[int, int]:
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz = UTC
    local = now.astimezone(tz)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def build_timeline(
    items: Iterable[TodayItem],
    *,
    day_start_ms: int,
    day_end_ms: int,
) -> list[TodayItem]:
    picked = [
        item
        for item in items
        if item.at is None or day_start_ms <= item.at < day_end_ms
    ]
    return sorted(picked, key=lambda it: (it.at is None, it.at or 0, -it.importance))


def format_clock(at_ms: int | None, tz_name: str = "Asia/Shanghai") -> str:
    if at_ms is None:
        return "今天"
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz = UTC
    return datetime.fromtimestamp(at_ms / 1000, tz).strftime("%H:%M")


def source_label(sources: Iterable[str]) -> str:
    labels: list[str] = []
    for source in sources:
        if source.startswith("notification:"):
            labels.append("通知")
        elif source == "calendar":
            labels.append("日历")
        elif source == "alarm":
            labels.append("闹钟")
        elif source == "happyclaw":
            labels.append("HappyClaw")
        elif source == "device-capture":
            labels.append("随手记")
        else:
            labels.append(source)
    unique: list[str] = []
    for label in labels:
        if label not in unique:
            unique.append(label)
    return "、".join(unique)


def describe_item(item: TodayItem, tz_name: str = "Asia/Shanghai") -> str:
    clock = format_clock(item.at, tz_name)
    return f"{clock}「{item.title}」（{source_label(item.sources)}）"
