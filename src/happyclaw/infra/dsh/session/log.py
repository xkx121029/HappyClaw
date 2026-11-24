"""Append-only, generation-switched session log.

Layout under ``root``::

    manifest.json            # {"schema": 1, "generation": N, "file": "..."}
    session.g0.jsonl         # first generation, never rewritten in place
    session.g1.jsonl         # successor written completely, then switched to
    blobs/                   # offloaded bodies (owned by the compaction layer)

Crash rules:

* appends are ``write + fsync`` of one newline-terminated line;
* a load discards the final line when the file does not end with ``\\n``,
  because that line was interrupted mid-write;
* the next append truncates the discarded tail before writing, so a torn line
  can never be fused with a later record;
* a malformed or out-of-order record inside the committed prefix raises
  :class:`LogCorruptionError` instead of silently dropping history.

A generation file is immutable once published. Rewriting history (for example
after an external repair) creates ``session.g{N+1}.jsonl`` and only then
atomically replaces ``manifest.json``; old generations stay on disk untouched.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from happyclaw.infra.dsh.session.events import EventType, LogFormatError, LogRecord

__all__ = ["GENERATION_PREFIX", "MANIFEST_NAME", "LogCorruptionError", "SessionLog"]

MANIFEST_NAME = "manifest.json"
GENERATION_PREFIX = "session.g"
_GENERATION_RE = re.compile(r"^session\.g(?P<generation>\d+)\.jsonl$")


class LogCorruptionError(RuntimeError):
    """The committed prefix of a log is malformed or has seq gaps."""


class SessionLog:
    """One session's durable event log.

    The writer is single-process/single-handle; concurrent appenders are not
    coordinated. Readers are safe as long as they tolerate a torn final line,
    which :meth:`load` already does.
    """

    def __init__(
        self,
        root: Path | str,
        *,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self._root = Path(root)
        self._clock = clock or _utc_now
        self._generation = 0
        self._seq = -1
        self._prepared = False

    @property
    def root(self) -> Path:
        """Directory holding this session's log and blobs."""
        return self._root

    @property
    def generation(self) -> int:
        """Currently selected generation number."""
        if not self._prepared:
            self._generation = self._resolve_generation()
        return self._generation

    @property
    def current_path(self) -> Path:
        """Path of the currently selected generation file."""
        return self._generation_path(self.generation)

    def append(
        self,
        event_type: EventType | str,
        data: Mapping[str, Any] | None = None,
    ) -> LogRecord:
        """Append one record and return it after the line is fsynced."""
        self._prepare()
        seq = self._seq + 1
        record = LogRecord.make(seq, event_type, data, ts=self._clock())
        path = self._generation_path(self._generation)
        self._root.mkdir(parents=True, exist_ok=True)
        previous_size = path.stat().st_size if path.exists() else 0
        try:
            with path.open("ab") as handle:
                handle.write(record.to_json().encode("utf-8") + b"\n")
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            # Keep the committed prefix intact when the write or fsync fails.
            if path.exists():
                os.truncate(path, previous_size)
            raise
        self._seq = seq
        return record

    def load(self) -> list[LogRecord]:
        """Return every committed record, discarding a torn final line."""
        generation = self._resolve_generation()
        records, _valid_size = self._read_generation(generation)
        return records

    def rewrite(self, records: Sequence[LogRecord]) -> int:
        """Publish ``records`` as a fresh immutable generation.

        The complete successor is written and fsynced under a new generation
        number, then the manifest is atomically replaced. The previous
        generation file is never modified. Returns the new generation number.
        """
        expected = list(range(len(records)))
        if [record.seq for record in records] != expected:
            raise ValueError("rewritten records must have contiguous seqs starting at 0")

        self._root.mkdir(parents=True, exist_ok=True)
        generation = self._next_generation_number()
        path = self._generation_path(generation)
        payload = b"".join(record.to_json().encode("utf-8") + b"\n" for record in records)
        try:
            with path.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            # Generation numbers are never reused; retry with a fresh one.
            return self.rewrite(records)
        _fsync_dir(self._root)
        self._write_manifest(generation)
        self._generation = generation
        self._seq = records[-1].seq if records else -1
        self._prepared = True
        return generation

    def generations(self) -> list[Path]:
        """Return all generation files present on disk, oldest first."""
        if not self._root.exists():
            return []
        found: list[tuple[int, Path]] = []
        for path in self._root.iterdir():
            match = _GENERATION_RE.match(path.name)
            if match is not None and path.is_file():
                found.append((int(match.group("generation")), path))
        return [path for _number, path in sorted(found)]

    def _prepare(self) -> None:
        if self._prepared:
            return
        generation = self._resolve_generation()
        records, valid_size = self._read_generation(generation)
        path = self._generation_path(generation)
        if path.exists() and path.stat().st_size > valid_size:
            # Drop the interrupted tail before appending a new record.
            os.truncate(path, valid_size)
        self._generation = generation
        self._seq = records[-1].seq if records else -1
        self._prepared = True

    def _resolve_generation(self) -> int:
        manifest_generation = self._read_manifest_generation()
        existing = self._existing_generation_numbers()
        if manifest_generation is not None:
            if manifest_generation in existing or not existing:
                return manifest_generation
        if existing:
            return max(existing)
        return 0

    def _next_generation_number(self) -> int:
        candidate = max(self._resolve_generation(), self._generation) + 1
        existing = set(self._existing_generation_numbers())
        while candidate in existing:
            candidate += 1
        return candidate

    def _existing_generation_numbers(self) -> list[int]:
        numbers: list[int] = []
        if not self._root.exists():
            return numbers
        for path in self._root.iterdir():
            match = _GENERATION_RE.match(path.name)
            if match is not None and path.is_file():
                numbers.append(int(match.group("generation")))
        return sorted(numbers)

    def _generation_path(self, generation: int) -> Path:
        return self._root / f"{GENERATION_PREFIX}{generation}.jsonl"

    def _read_manifest_generation(self) -> int | None:
        path = self._root / MANIFEST_NAME
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LogCorruptionError(f"manifest is unreadable: {exc}") from exc
        if not isinstance(payload, dict):
            raise LogCorruptionError("manifest must be a JSON object")
        generation = payload.get("generation")
        if not isinstance(generation, int) or isinstance(generation, bool) or generation < 0:
            raise LogCorruptionError("manifest.generation must be a non-negative integer")
        return generation

    def _write_manifest(self, generation: int) -> None:
        payload = {
            "file": self._generation_path(generation).name,
            "generation": generation,
            "schema": 1,
        }
        target = self._root / MANIFEST_NAME
        temporary = self._root / f"{MANIFEST_NAME}.tmp"
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        _fsync_dir(self._root)

    def _read_generation(self, generation: int) -> tuple[list[LogRecord], int]:
        path = self._generation_path(generation)
        if not path.exists():
            return [], 0
        raw = path.read_bytes()
        if not raw:
            return [], 0
        last_newline = raw.rfind(b"\n")
        if last_newline < 0:
            # The whole file is one interrupted line; nothing is committed.
            return [], 0
        valid_size = last_newline + 1
        records: list[LogRecord] = []
        for piece in raw[:valid_size].split(b"\n")[:-1]:
            if not piece:
                raise LogCorruptionError("blank line inside the committed prefix")
            try:
                line = piece.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise LogCorruptionError("record line is not valid UTF-8") from exc
            try:
                record = LogRecord.from_json(line)
            except LogFormatError as exc:
                raise LogCorruptionError(f"record line is malformed: {exc}") from exc
            expected = records[-1].seq + 1 if records else 0
            if record.seq != expected:
                raise LogCorruptionError(
                    f"record seq {record.seq} does not follow {expected - 1}"
                )
            records.append(record)
        return records, valid_size


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _fsync_dir(path: Path) -> None:
    """Best-effort directory fsync; Windows has no directory handle."""
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
