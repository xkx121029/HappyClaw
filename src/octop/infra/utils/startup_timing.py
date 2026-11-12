"""Millisecond timeline for the boot path (``octop run`` cold start).

Every phase logs one ``startup.segment name=<phase> ms=<float>`` line, so a slow
boot can be attributed from ``<home>/logs/octop.log`` without re-instrumenting:

    Select-String 'startup.segment' <home>/logs/octop.log

Timings are monotonic. The ``process`` phase additionally reports the age of the
OS process (via psutil when available) so "the interpreter took N seconds before
our code ran" is not mistaken for application work.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager

logger = logging.getLogger(__name__)

_marks: dict[str, float] = {}


def _origin_mono() -> float:
    """Monotonic value captured at ``octop`` package import."""
    import octop  # noqa: PLC0415 - lazy to avoid an import cycle

    origin = getattr(octop, "PROCESS_MONO_ORIGIN", None)
    return origin if origin is not None else time.perf_counter()


def mark(name: str) -> None:
    """Remember the current monotonic clock under ``name``."""
    _marks[name] = time.perf_counter()


def since_mark_ms(name: str) -> float | None:
    """Milliseconds since ``mark(name)``; ``None`` when the mark is missing."""
    started = _marks.get(name)
    if started is None:
        return None
    return (time.perf_counter() - started) * 1000.0


def process_age_ms() -> float | None:
    """Age of this OS process in milliseconds, or ``None`` if unknown."""
    try:
        import psutil  # noqa: PLC0415 - optional, only for diagnostics

        created = psutil.Process().create_time()
    except Exception:  # pragma: no cover - psutil absent or denied
        return None
    return (time.time() - created) * 1000.0


def emit(name: str, ms: float, **fields: object) -> None:
    """Log one completed phase."""
    extra = "".join(f" {key}={value}" for key, value in fields.items() if value is not None)
    logger.info("startup.segment name=%s ms=%.1f%s", name, ms, extra)


@contextmanager
def segment(name: str, **fields: object) -> Iterator[None]:
    """Time a block and log it as ``startup.segment``."""
    started = time.perf_counter()
    try:
        yield
    finally:
        emit(name, (time.perf_counter() - started) * 1000.0, **fields)


def since_process_ms() -> float:
    """Milliseconds since the ``octop`` package started importing."""
    return (time.perf_counter() - _origin_mono()) * 1000.0


def emit_process() -> None:
    """Report spawn → now, split into interpreter start-up and package imports."""
    since_spawn_ms = process_age_ms()
    since_import_ms = (time.perf_counter() - _origin_mono()) * 1000.0
    interpreter_ms = (
        None if since_spawn_ms is None else max(0.0, since_spawn_ms - since_import_ms)
    )
    emit(
        "process",
        since_spawn_ms if since_spawn_ms is not None else since_import_ms,
        since_spawn_ms=None if since_spawn_ms is None else round(since_spawn_ms, 1),
        interpreter_before_package_ms=None if interpreter_ms is None else round(interpreter_ms, 1),
    )
