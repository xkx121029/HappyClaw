"""Today 聚合结果的本地持久化。

只存整理后的条目与去重键：``today.json`` 位于 ``<octop root>/device-link/``。
通知正文在进入本模块前已完成敏感脱敏（见 ``items.sensitive_redact``），
``seenKeys`` / ``pushLog`` 只记 id 与时间戳，不存原文。
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from .items import TodayItem, merge_items

_MAX_ITEMS = 400
_MAX_SEEN = 500
_RETENTION_MS = 3 * 24 * 3600 * 1000


class TodayStore:
    def __init__(self, root: Path, *, filename: str = "today.json") -> None:
        self._root = Path(root)
        self._path = self._root / filename
        self._lock = threading.Lock()
        self._state: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # 读写
    # ------------------------------------------------------------------

    @property
    def path(self) -> Path:
        return self._path

    def _default(self) -> dict[str, Any]:
        return {
            "updatedAt": 0,
            "day": "",
            "items": [],
            "seenKeys": [],
            "pushLog": [],
            "cursorMs": 0,
            "permissions": {},
        }

    def _load(self) -> dict[str, Any]:
        if self._state is not None:
            return self._state
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        state = self._default()
        if isinstance(raw, dict):
            state.update(
                {
                    "updatedAt": int(raw.get("updatedAt") or 0),
                    "day": str(raw.get("day") or ""),
                    "items": list(raw.get("items") or []),
                    "seenKeys": [str(k) for k in raw.get("seenKeys") or []],
                    "pushLog": list(raw.get("pushLog") or []),
                    "cursorMs": int(raw.get("cursorMs") or 0),
                    "permissions": dict(raw.get("permissions") or {}),
                }
            )
        self._state = state
        return state

    def _flush(self) -> None:
        state = self._state or self._default()
        self._root.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, self._path)

    # ------------------------------------------------------------------
    # 条目
    # ------------------------------------------------------------------

    def items(self) -> list[TodayItem]:
        with self._lock:
            state = self._load()
            parsed = [TodayItem.from_dict(raw) for raw in state.get("items") or []]
            return [item for item in parsed if item is not None]

    def merge(
        self,
        new_items: Iterable[TodayItem],
        *,
        now_ms: int | None = None,
        day: str = "",
    ) -> tuple[list[TodayItem], list[TodayItem]]:
        """并入新条目并落盘，返回 (当天时间线全量, 本次新增条目)。"""
        now = int(now_ms or time.time() * 1000)
        with self._lock:
            state = self._load()
            existing = [
                item
                for item in (TodayItem.from_dict(raw) for raw in state.get("items") or [])
                if item is not None
            ]
            existing_ids = {item.id for item in existing}
            merged = merge_items([*existing, *new_items])
            # 保留窗口：有时间的留 3 天，无时间的（如闹钟文案）随每日刷新重建
            merged = [
                item
                for item in merged
                if item.at is None or item.at >= now - _RETENTION_MS
            ]
            merged.sort(key=lambda it: (it.at is None, it.at or 0, -it.importance))
            merged = merged[:_MAX_ITEMS]
            state["items"] = [item.to_dict() for item in merged]
            state["updatedAt"] = now
            if day:
                state["day"] = day
            self._flush()
            added = [item for item in merged if item.id not in existing_ids]
            return merged, added

    def prune_undated(self) -> None:
        """清掉没有时间的旧条目（闹钟类），避免跨天重复展示。"""
        with self._lock:
            state = self._load()
            parsed = [
                item
                for item in (TodayItem.from_dict(raw) for raw in state.get("items") or [])
                if item is not None
            ]
            kept = [item for item in parsed if item.at is not None]
            if len(kept) != len(parsed):
                state["items"] = [item.to_dict() for item in kept]
                self._flush()

    # ------------------------------------------------------------------
    # 去重键
    # ------------------------------------------------------------------

    def seen(self, item_id: str) -> bool:
        with self._lock:
            return item_id in set(self._load().get("seenKeys") or [])

    def mark_seen(self, item_ids: Iterable[str]) -> None:
        ids = [str(i) for i in item_ids if str(i).strip()]
        if not ids:
            return
        with self._lock:
            state = self._load()
            seen = list(dict.fromkeys([*(state.get("seenKeys") or []), *ids]))
            state["seenKeys"] = seen[-_MAX_SEEN:]
            self._flush()

    # ------------------------------------------------------------------
    # 推送限频
    # ------------------------------------------------------------------

    def record_push(self, item_ids: Iterable[str], at_ms: int) -> None:
        ids = [str(i) for i in item_ids if str(i).strip()]
        with self._lock:
            state = self._load()
            log = [entry for entry in state.get("pushLog") or [] if isinstance(entry, dict)]
            log.append({"ids": ids, "at": int(at_ms)})
            state["pushLog"] = log[-200:]
            self._flush()

    def last_push_at(self) -> int | None:
        with self._lock:
            log = self._load().get("pushLog") or []
            stamps = [int(e.get("at") or 0) for e in log if isinstance(e, dict)]
            return max(stamps) if stamps else None

    def pushes_between(self, start_ms: int, end_ms: int) -> int:
        with self._lock:
            log = self._load().get("pushLog") or []
            return sum(
                1
                for entry in log
                if isinstance(entry, dict) and start_ms <= int(entry.get("at") or 0) < end_ms
            )

    def pushed_ids(self) -> set[str]:
        with self._lock:
            out: set[str] = set()
            for entry in self._load().get("pushLog") or []:
                if isinstance(entry, dict):
                    out.update(str(i) for i in entry.get("ids") or [])
            return out

    # ------------------------------------------------------------------
    # 游标与权限状态
    # ------------------------------------------------------------------

    def cursor(self) -> int:
        with self._lock:
            return int(self._load().get("cursorMs") or 0)

    def set_cursor(self, value: int) -> None:
        with self._lock:
            state = self._load()
            state["cursorMs"] = int(value)
            self._flush()

    def set_permissions(self, perms: dict[str, Any]) -> None:
        with self._lock:
            state = self._load()
            state["permissions"] = {**dict(state.get("permissions") or {}), **perms}
            self._flush()

    def permissions(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._load().get("permissions") or {})

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            state = self._load()
            return {
                "updatedAt": state.get("updatedAt"),
                "day": state.get("day"),
                "items": list(state.get("items") or []),
                "permissions": dict(state.get("permissions") or {}),
            }
