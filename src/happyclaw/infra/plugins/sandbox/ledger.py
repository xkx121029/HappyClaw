"""Durable JSONL ledgers and read-only summaries.

Two separate streams keep facts apart:

* ``denials.jsonl`` — one line per denial, written by
  :class:`JsonlSandboxLedger`;
* ``checks.jsonl`` — aggregated traces of *allowed* probes, written by
  :class:`JsonlCheckLedger` through :class:`CheckAggregator`.

The active files live in ``<HAPPYCLAW_HOME>/dsh-sandbox/`` (falling back to
``~/.octop/dsh-sandbox/``). When a file would exceed ``max_bytes`` it rotates to
``.1``, older files shift up to ``max_files``, and the oldest is deleted, so
neither stream grows without bound.

Denials are per-event. Allowed checks are bucketed in memory by
``(tool, stage, coverage, checked)`` and flushed every ``flush_every`` notes, so
a thousand calls do not produce a thousand lines. Neither sink failure changes
the security decision.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from happyclaw.infra.plugins.sandbox.audit import (
    SandboxAuditRecord,
    SandboxCheckLedger,
    SandboxCheckRecord,
    new_check_record,
)
from happyclaw.infra.plugins.sandbox.errors import describe_exception
from happyclaw.infra.utils.paths import PathLayout

__all__ = [
    "DEFAULT_CHECK_FILENAME",
    "DEFAULT_LEDGER_DIRNAME",
    "DEFAULT_LEDGER_FILENAME",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_FILES",
    "CheckAggregator",
    "CheckBucketSummary",
    "CheckSummary",
    "DenialSummary",
    "JsonlCheckLedger",
    "JsonlSandboxLedger",
    "PluginDenialSummary",
    "default_check_ledger_path",
    "default_ledger_path",
    "format_check_summary",
    "format_denial_summary",
    "load_check_records",
    "load_denial_records",
    "summarize_check_file",
    "summarize_checks",
    "summarize_denial_file",
    "summarize_denials",
]

LOGGER = logging.getLogger(__name__)

DEFAULT_LEDGER_DIRNAME = "dsh-sandbox"
DEFAULT_LEDGER_FILENAME = "denials.jsonl"
DEFAULT_CHECK_FILENAME = "checks.jsonl"
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_FILES = 5


def default_ledger_path(home: str | Path | None = None) -> Path:
    """Return the default denial ledger path, honoring ``HAPPYCLAW_HOME``."""

    root = Path(home) if home is not None else PathLayout.from_env().root
    return root / DEFAULT_LEDGER_DIRNAME / DEFAULT_LEDGER_FILENAME


def default_check_ledger_path(home: str | Path | None = None) -> Path:
    """Return the default allowed-check ledger path, honoring ``HAPPYCLAW_HOME``."""

    root = Path(home) if home is not None else PathLayout.from_env().root
    return root / DEFAULT_LEDGER_DIRNAME / DEFAULT_CHECK_FILENAME


class _RotatingJsonlWriter:
    """Append-only JSONL writer with bounded size via rotation."""

    def __init__(
        self,
        path: str | Path,
        *,
        max_bytes: int,
        max_files: int,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes 必须是正整数")
        if max_files < 0:
            raise ValueError("max_files 不能为负数")
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.max_files = max_files

    def append(self, payload: Mapping[str, Any]) -> None:
        line = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
        data = line.encode("utf-8")
        self._rotate_if_needed(len(data))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("ab") as handle:
            handle.write(data)

    def _rotate_if_needed(self, incoming: int) -> None:
        if not self.path.exists():
            return
        if self.path.stat().st_size + incoming <= self.max_bytes:
            return
        if self.max_files == 0:
            self.path.unlink()
            return
        oldest = Path(f"{self.path}.{self.max_files}")
        if oldest.exists():
            oldest.unlink()
        for index in range(self.max_files - 1, 0, -1):
            source = Path(f"{self.path}.{index}")
            if source.exists():
                source.replace(Path(f"{self.path}.{index + 1}"))
        self.path.replace(Path(f"{self.path}.1"))


class JsonlSandboxLedger:
    """Denial sink. A failed write raises; the caller keeps the denial."""

    def __init__(
        self,
        path: str | Path,
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_files: int = DEFAULT_MAX_FILES,
    ) -> None:
        self._writer = _RotatingJsonlWriter(
            path,
            max_bytes=max_bytes,
            max_files=max_files,
        )

    @property
    def path(self) -> Path:
        return self._writer.path

    def append(self, record: SandboxAuditRecord) -> None:
        self._writer.append(record.to_dict())


class JsonlCheckLedger:
    """Allowed-check sink, kept in a file separate from denials."""

    def __init__(
        self,
        path: str | Path,
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_files: int = DEFAULT_MAX_FILES,
    ) -> None:
        self._writer = _RotatingJsonlWriter(
            path,
            max_bytes=max_bytes,
            max_files=max_files,
        )

    @property
    def path(self) -> Path:
        return self._writer.path

    def append(self, record: SandboxCheckRecord) -> None:
        self._writer.append(record.to_dict())


class _CheckBucket:
    __slots__ = ("count", "first_seen", "last_seen")

    def __init__(self, now: str) -> None:
        self.count = 0
        self.first_seen = now
        self.last_seen = now


class CheckAggregator:
    """Buckets allowed probes and flushes aggregate records.

    ``flush_every`` bounds how many lines a high-frequency tool can add: one
    bucket produces one record per flush, so ``N`` calls yield at most
    ``ceil(N / flush_every)`` records per bucket. The in-memory bucket count is
    bounded by the plugin's declared tools and inspection plans.
    """

    def __init__(
        self,
        sink: SandboxCheckLedger,
        *,
        plugin_id: str,
        flush_every: int = 100,
    ) -> None:
        if flush_every <= 0:
            raise ValueError("flush_every 必须是正整数")
        self._sink = sink
        self._plugin_id = plugin_id
        self._flush_every = flush_every
        self._buckets: dict[tuple[str, str, str, tuple[str, ...]], _CheckBucket] = {}
        self._pending = 0

    def note(
        self,
        *,
        tool_name: str,
        stage: str,
        coverage: str,
        checked: tuple[str, ...],
    ) -> None:
        key = (tool_name, stage, coverage, tuple(checked))
        now = datetime.now(UTC).isoformat()
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _CheckBucket(now)
            self._buckets[key] = bucket
        bucket.count += 1
        bucket.last_seen = now
        self._pending += 1
        if self._pending >= self._flush_every:
            self.flush()

    def flush(self) -> None:
        pending = list(self._buckets.items())
        self._buckets.clear()
        self._pending = 0
        for (tool_name, stage, coverage, checked), bucket in pending:
            record = new_check_record(
                plugin_id=self._plugin_id,
                tool_name=tool_name,
                stage=stage,
                coverage=coverage,
                checked=checked,
                count=bucket.count,
                window_start=bucket.first_seen,
                window_end=bucket.last_seen,
            )
            try:
                self._sink.append(record)
            except Exception as exc:
                # Same rule as denials: observability must never change
                # behavior. Drop the batch so a broken sink cannot grow memory
                # without bound, and log once per failed flush.
                LOGGER.warning(
                    "沙箱检查台账写入失败，执行不受影响（plugin=%s tool=%s）：%s",
                    self._plugin_id,
                    tool_name,
                    describe_exception(exc),
                )
                break


def load_denial_records(
    path: str | Path,
    *,
    include_rotated: bool = True,
) -> list[SandboxAuditRecord]:
    """Read denials back, oldest first; corrupt lines are skipped."""

    return _load_records(
        path,
        record_type=SandboxAuditRecord,
        include_rotated=include_rotated,
        sort_key=lambda record: record.timestamp,
    )


def load_check_records(
    path: str | Path,
    *,
    include_rotated: bool = True,
) -> list[SandboxCheckRecord]:
    """Read allowed-check aggregates back, oldest window end first."""

    return _load_records(
        path,
        record_type=SandboxCheckRecord,
        include_rotated=include_rotated,
        sort_key=lambda record: record.window_end,
    )


def summarize_denials(
    records: Iterable[SandboxAuditRecord],
    *,
    since: datetime | str | None = None,
    until: datetime | str | None = None,
) -> DenialSummary:
    """Aggregate denials by plugin, error code, and stage within a window."""

    since_at = _parse_bound(since)
    until_at = _parse_bound(until)

    code_counts: Counter[str] = Counter()
    stage_counts: Counter[str] = Counter()
    per_plugin: dict[str, _PluginAccumulator] = {}
    total = 0

    for record in records:
        if not _in_window(record.timestamp, since_at, until_at):
            continue
        total += 1
        code_counts[record.error_code] += 1
        stage_counts[record.stage] += 1
        accumulator = per_plugin.setdefault(record.plugin_id, _PluginAccumulator())
        accumulator.add(record)

    plugins = tuple(
        PluginDenialSummary(
            plugin_id=plugin_id,
            total=accumulator.total,
            by_error_code=_sorted_counts(accumulator.by_error_code),
            by_stage=_sorted_counts(accumulator.by_stage),
            first_seen=accumulator.first_seen,
            last_seen=accumulator.last_seen,
        )
        for plugin_id, accumulator in sorted(
            per_plugin.items(),
            key=lambda item: (-item[1].total, item[0]),
        )
    )
    return DenialSummary(
        total=total,
        since=_bound_text(since_at),
        until=_bound_text(until_at),
        by_plugin=plugins,
        by_error_code=_sorted_counts(code_counts),
        by_stage=_sorted_counts(stage_counts),
    )


def summarize_denial_file(
    path: str | Path,
    *,
    since: datetime | str | None = None,
    until: datetime | str | None = None,
) -> DenialSummary:
    """Read a denial ledger plus rotated siblings and summarize it."""

    return summarize_denials(
        load_denial_records(path),
        since=since,
        until=until,
    )


def summarize_checks(
    records: Iterable[SandboxCheckRecord],
    *,
    since: datetime | str | None = None,
    until: datetime | str | None = None,
) -> CheckSummary:
    """Aggregate allowed-check traces by plugin, coverage, and bucket."""

    since_at = _parse_bound(since)
    until_at = _parse_bound(until)

    plugin_counts: Counter[str] = Counter()
    coverage_counts: Counter[str] = Counter()
    stage_counts: Counter[str] = Counter()
    merged: dict[tuple[str, str, str, str, tuple[str, ...]], _CheckMerge] = {}
    total = 0

    for record in records:
        if not _in_window(record.window_end, since_at, until_at):
            continue
        total += record.count
        plugin_counts[record.plugin_id] += record.count
        coverage_counts[record.coverage] += record.count
        stage_counts[record.stage] += record.count
        key = (
            record.plugin_id,
            record.tool_name,
            record.stage,
            record.coverage,
            record.checked,
        )
        entry = merged.get(key)
        if entry is None:
            merged[key] = _CheckMerge(
                count=record.count,
                first_seen=record.window_start,
                last_seen=record.window_end,
            )
            continue
        entry.count += record.count
        entry.first_seen = min(entry.first_seen, record.window_start)
        entry.last_seen = max(entry.last_seen, record.window_end)

    buckets = tuple(
        CheckBucketSummary(
            plugin_id=plugin_id,
            tool_name=tool_name,
            stage=stage,
            coverage=coverage,
            checked=checked,
            count=entry.count,
            first_seen=entry.first_seen,
            last_seen=entry.last_seen,
        )
        for (plugin_id, tool_name, stage, coverage, checked), entry in sorted(
            merged.items(),
            key=lambda item: (-item[1].count, item[0]),
        )
    )
    return CheckSummary(
        total=total,
        since=_bound_text(since_at),
        until=_bound_text(until_at),
        by_plugin=_sorted_counts(plugin_counts),
        by_coverage=_sorted_counts(coverage_counts),
        by_stage=_sorted_counts(stage_counts),
        buckets=buckets,
    )


def summarize_check_file(
    path: str | Path,
    *,
    since: datetime | str | None = None,
    until: datetime | str | None = None,
) -> CheckSummary:
    """Read a check ledger plus rotated siblings and summarize it."""

    return summarize_checks(
        load_check_records(path),
        since=since,
        until=until,
    )


def format_denial_summary(summary: DenialSummary) -> str:
    """Render a denial summary as readable Chinese for a terminal or log."""

    if summary.is_empty:
        return "沙箱拒绝汇总：没有记录。"
    lines = [f"沙箱拒绝汇总：共 {summary.total} 条"]
    if summary.since is not None or summary.until is not None:
        lines[0] += (
            f"（时间范围 {summary.since or '不限'} ~ {summary.until or '不限'}）"
        )
    lines.append("按插件：")
    for item in summary.by_plugin:
        lines.append(
            f"  {item.plugin_id}：{item.total} 次（{item.first_seen} ~ {item.last_seen}）"
        )
        lines.append(f"    阶段：{_format_counts(item.by_stage)}")
        lines.append(f"    错误码：{_format_counts(item.by_error_code)}")
    lines.append(f"按错误码：{_format_counts(summary.by_error_code)}")
    lines.append(f"按阶段：{_format_counts(summary.by_stage)}")
    return "\n".join(lines)


def format_check_summary(summary: CheckSummary) -> str:
    """Render an allowed-check summary as readable Chinese."""

    if summary.is_empty:
        return "沙箱检查汇总：没有记录。"
    lines = [f"沙箱检查汇总：共 {summary.total} 次"]
    if summary.since is not None or summary.until is not None:
        lines[0] += (
            f"（时间范围 {summary.since or '不限'} ~ {summary.until or '不限'}）"
        )
    lines.append(f"按插件：{_format_counts(summary.by_plugin)}")
    lines.append(f"按覆盖：{_format_counts(summary.by_coverage)}")
    lines.append(f"按阶段：{_format_counts(summary.by_stage)}")
    lines.append("明细：")
    for item in summary.buckets:
        checked = "、".join(item.checked) if item.checked else "（无）"
        lines.append(
            f"  {item.plugin_id} / {item.tool_name} / {item.stage}："
            f"{item.coverage}，检查项 {checked}，{item.count} 次"
            f"（{item.first_seen} ~ {item.last_seen}）"
        )
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class PluginDenialSummary:
    """Per-plugin denial counts, including where each denial happened."""

    plugin_id: str
    total: int
    by_error_code: dict[str, int]
    by_stage: dict[str, int]
    first_seen: str
    last_seen: str


@dataclass(frozen=True, slots=True)
class DenialSummary:
    """Read-only view over denials for one time window."""

    total: int
    since: str | None
    until: str | None
    by_plugin: tuple[PluginDenialSummary, ...]
    by_error_code: dict[str, int]
    by_stage: dict[str, int]

    @property
    def is_empty(self) -> bool:
        return self.total == 0


@dataclass(frozen=True, slots=True)
class CheckBucketSummary:
    """One merged allowed-check bucket."""

    plugin_id: str
    tool_name: str
    stage: str
    coverage: str
    checked: tuple[str, ...]
    count: int
    first_seen: str
    last_seen: str


@dataclass(frozen=True, slots=True)
class CheckSummary:
    """Read-only view over allowed checks for one time window."""

    total: int
    since: str | None
    until: str | None
    by_plugin: dict[str, int]
    by_coverage: dict[str, int]
    by_stage: dict[str, int]
    buckets: tuple[CheckBucketSummary, ...]

    @property
    def is_empty(self) -> bool:
        return self.total == 0


class _PluginAccumulator:
    def __init__(self) -> None:
        self.total = 0
        self.by_error_code: Counter[str] = Counter()
        self.by_stage: Counter[str] = Counter()
        self.first_seen = ""
        self.last_seen = ""

    def add(self, record: SandboxAuditRecord) -> None:
        self.total += 1
        self.by_error_code[record.error_code] += 1
        self.by_stage[record.stage] += 1
        if not self.first_seen or record.timestamp < self.first_seen:
            self.first_seen = record.timestamp
        if not self.last_seen or record.timestamp > self.last_seen:
            self.last_seen = record.timestamp


@dataclass(slots=True)
class _CheckMerge:
    count: int
    first_seen: str
    last_seen: str


_RECORD_FIELDS: dict[type[Any], set[str]] = {
    SandboxAuditRecord: {field.name for field in fields(SandboxAuditRecord)},
    SandboxCheckRecord: {field.name for field in fields(SandboxCheckRecord)},
}
_REQUIRED_FIELDS: dict[type[Any], set[str]] = {
    SandboxAuditRecord: {
        "record_id",
        "timestamp",
        "plugin_id",
        "tool_name",
        "operation",
        "stage",
        "error_code",
        "reason",
    },
    SandboxCheckRecord: {
        "record_id",
        "window_start",
        "window_end",
        "plugin_id",
        "tool_name",
        "stage",
        "coverage",
        "count",
    },
}


def _ledger_files(path: Path, include_rotated: bool) -> list[Path]:
    files: list[Path] = []
    if include_rotated:
        index = 1
        while True:
            rotated = Path(f"{path}.{index}")
            if not rotated.exists():
                break
            files.append(rotated)
            index += 1
        files.reverse()
    if path.exists():
        files.append(path)
    return files


def _load_records(
    path: str | Path,
    *,
    record_type: type[Any],
    include_rotated: bool,
    sort_key: Callable[[Any], str],
) -> list[Any]:
    target = Path(path)
    records: dict[str, Any] = {}
    for file in _ledger_files(target, include_rotated):
        for payload in _read_payloads(file):
            record = _record_from_mapping(payload, record_type)
            if record is not None:
                records.setdefault(record.record_id, record)
    return sorted(records.values(), key=sort_key)


def _read_payloads(path: Path) -> Iterator[Mapping[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            yield payload


def _record_from_mapping(
    payload: Mapping[str, Any],
    record_type: type[Any],
) -> Any:
    if not _REQUIRED_FIELDS[record_type].issubset(payload):
        return None
    values = {
        name: payload[name]
        for name in _RECORD_FIELDS[record_type]
        if name in payload
    }
    if record_type is SandboxCheckRecord and "checked" in values:
        raw = values["checked"]
        if isinstance(raw, (list, tuple)):
            values["checked"] = tuple(str(item) for item in raw)
    try:
        return record_type(**values)
    except (TypeError, ValueError):
        return None


def _parse_bound(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value).strip())
        except ValueError:
            raise ValueError(f"无法解析时间边界：{value!r}") from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def _bound_text(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _in_window(
    timestamp: str,
    since: datetime | None,
    until: datetime | None,
) -> bool:
    try:
        moment = datetime.fromisoformat(timestamp)
    except ValueError:
        # An unreadable timestamp cannot be placed in a window; keep it only
        # when no window was requested, so totals never silently drop records.
        return since is None and until is None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    if since is not None and moment < since:
        return False
    return until is None or moment <= until


def _sorted_counts(counts: Mapping[str, int]) -> dict[str, int]:
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _format_counts(counts: Mapping[str, int]) -> str:
    if not counts:
        return "（无）"
    return "、".join(f"{key} {value} 次" for key, value in counts.items())
