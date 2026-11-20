"""Today 条目归一化 / 去重合并 / 时间线单测（不依赖真机）。"""

from __future__ import annotations

from datetime import UTC, datetime

from octop.infra.control.device_link.today import items as I

NOW = datetime(2026, 11, 15, 10, 0, tzinfo=UTC)
TODAY = int(datetime(2026, 11, 15, 12, 0, tzinfo=UTC).timestamp() * 1000)


def test_normalize_text_drops_spacing_and_punctuation() -> None:
    assert I.normalize_text("评审 会：15:00!") == I.normalize_text("评审会15:00")
    assert I.normalize_text("Hello World") == "helloworld"


def test_sensitive_package_is_fully_hidden() -> None:
    text, hit = I.sensitive_redact("您的余额 100 元", "com.android.mms", ["com.android.mms"])
    assert hit is True
    assert text == I.REDACTED


def test_verification_code_is_masked_in_place() -> None:
    text, hit = I.sensitive_redact("登录验证码：123456，5 分钟内有效", "com.demo", [])
    assert hit is True
    assert "123456" not in text
    assert I.REDACTED in text


def test_verification_code_with_shi_is_masked() -> None:
    # 真机通知常见写法「您的验证码是 839201」，没有冒号也必须命中
    text, hit = I.sensitive_redact("您的验证码是 839201，5 分钟内有效", "com.demo", [])
    assert hit is True
    assert "839201" not in text
    assert I.REDACTED in text


def test_normal_text_is_untouched() -> None:
    text, hit = I.sensitive_redact("评审改到 15:00", "com.demo", ["com.android.mms"])
    assert (text, hit) == ("评审改到 15:00", False)


def test_notification_filters_by_allow_and_deny() -> None:
    raw = {"package": "com.demo", "title": "消息", "text": "hi", "postedAt": TODAY}
    assert I.item_from_notification(raw, allow=["com.other"]) is None
    assert I.item_from_notification(raw, deny=["com.demo"]) is None
    assert I.item_from_notification(raw, allow=["com.demo"]) is not None


def test_empty_group_summary_notification_is_dropped() -> None:
    # 系统分组摘要常常只有 key 没有标题/正文，收进时间线只会变成噪声
    raw = {"package": "com.android.shell", "title": "", "text": "", "postedAt": TODAY}
    assert I.item_from_notification(raw) is None


def test_same_event_from_two_apps_is_merged_with_sources() -> None:
    left = I.item_from_notification(
        {"package": "com.a", "title": "张三", "text": "评审改到 15:00", "postedAt": TODAY, "category": "msg"}
    )
    right = I.item_from_notification(
        {"package": "com.b", "title": "张三", "text": "评审改到 15:00", "postedAt": TODAY + 60_000, "category": "msg"}
    )
    assert left is not None and right is not None

    merged = I.merge_items([left, right])

    assert len(merged) == 1
    assert set(merged[0].sources) == {"notification:com.a", "notification:com.b"}
    assert merged[0].people == ["张三"]


def test_different_events_stay_separate() -> None:
    left = I.item_from_notification(
        {"package": "com.a", "title": "张三", "text": "下午开会", "postedAt": TODAY}
    )
    right = I.item_from_notification(
        {"package": "com.a", "title": "李四", "text": "快递到了", "postedAt": TODAY + 3_600_000}
    )
    assert len(I.merge_items([left, right])) == 2  # type: ignore[list-item]


def test_stable_id_is_deterministic_for_same_minute_bucket() -> None:
    assert I._stable_id("notification", "消息", TODAY) == I._stable_id(
        "notification", "消息", TODAY + 1_000
    )
    assert I._stable_id("notification", "消息", TODAY) != I._stable_id(
        "notification", "消息", TODAY + 3_600_000
    )


def test_timeline_sorts_and_filters_by_day() -> None:
    today = I.TodayItem(id="a", kind="schedule", source="calendar", title="早会", at=TODAY)
    tomorrow = I.TodayItem(
        id="b", kind="schedule", source="calendar", title="明天", at=TODAY + 24 * 3600 * 1000
    )
    undated = I.TodayItem(id="c", kind="reminder", source="alarm", title="闹钟", at=None)
    urgent = I.TodayItem(
        id="d", kind="notification", source="notification:x", title="紧急", at=TODAY, importance=3
    )

    day_start, day_end = I.day_bounds(NOW, "UTC")
    timeline = I.build_timeline([tomorrow, undated, today, urgent], day_start_ms=day_start, day_end_ms=day_end)

    assert [item.id for item in timeline] == ["d", "a", "c"]
    assert I.describe_item(timeline[1], "UTC").startswith("12:00")


def test_calendar_item_keeps_people_and_time() -> None:
    item = I.item_from_calendar(
        {
            "eventId": "e1",
            "title": "评审会",
            "startAt": TODAY,
            "endAt": TODAY + 3_600_000,
            "location": "3F",
            "attendees": ["张三", "李四"],
        }
    )
    assert item is not None
    assert item.kind == I.KIND_SCHEDULE
    assert item.people == ["张三", "李四"]
    assert item.importance == 2


def test_alarm_without_alarm_returns_none() -> None:
    assert I.item_from_alarm({"nextAlarm": "无闹钟", "hasAlarm": False}, NOW) is None


def test_alarm_today_lands_on_todays_timeline() -> None:
    item = I.item_from_alarm({"nextAlarm": "Sun 9:00 PM"}, NOW)
    assert item is not None
    assert item.at is not None
    landed = datetime.fromtimestamp(item.at / 1000, tz=UTC)
    assert (landed.hour, landed.minute) == (21, 0)
    assert landed.date() == NOW.date()


def test_alarm_on_another_day_has_no_time_point() -> None:
    item = I.item_from_alarm({"nextAlarm": "Mon 7:00 AM"}, NOW)
    assert item is not None
    assert item.at is None


def test_alarm_prefers_device_timestamp() -> None:
    stamp = 1794760000000
    item = I.item_from_alarm({"nextAlarm": "Sun 9:00 PM", "nextAlarmAt": stamp}, NOW)
    assert item is not None
    assert item.at == stamp


def test_clock_notification_merges_into_same_alarm() -> None:
    # 时钟应用会为同一个闹钟再发一条通知：文本不同、时间点不同，但属于同一件事
    note = I.item_from_notification(
        {
            "package": "com.google.android.deskclock",
            "title": "Upcoming alarm",
            "text": "Sun 2:30 PM - 评审",
            "postedAt": TODAY,
        }
    )
    alarm = I.item_from_alarm(
        {"nextAlarm": "Sun 2:30 PM", "nextAlarmAt": 1794753000000}, NOW
    )
    assert note is not None and alarm is not None

    merged = I.merge_items([note, alarm])

    assert len(merged) == 1
    assert merged[0].kind == I.KIND_REMINDER
    assert merged[0].at == 1794753000000
    assert "notification:com.google.android.deskclock" in merged[0].sources
    assert "alarm" in merged[0].sources
