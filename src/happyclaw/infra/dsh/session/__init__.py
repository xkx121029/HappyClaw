"""DSH session log, surface projection, and compaction.

The package is standalone: it owns its JSONL generations and blob directory and
never mutates the product's existing chat-history tables or routers.
"""

from __future__ import annotations

from happyclaw.infra.dsh.session.budget import (
    UnitWeights,
    WeightedBudget,
    measure_units,
    trim_head,
    trim_tail,
)
from happyclaw.infra.dsh.session.compaction import (
    L1_MARKER,
    BlobStore,
    CompactionConfig,
    CompactionEngine,
    CompactionReport,
    CompactionStep,
)
from happyclaw.infra.dsh.session.events import (
    COMPACTION_EVENT_TYPES,
    SCHEMA_VERSION,
    EventType,
    LogFormatError,
    LogRecord,
)
from happyclaw.infra.dsh.session.log import (
    GENERATION_PREFIX,
    MANIFEST_NAME,
    LogCorruptionError,
    SessionLog,
)
from happyclaw.infra.dsh.session.surface import (
    SurfaceNode,
    content_text,
    content_units,
    project,
    surface_json,
    surface_units,
)

__all__ = [
    "COMPACTION_EVENT_TYPES",
    "GENERATION_PREFIX",
    "L1_MARKER",
    "MANIFEST_NAME",
    "SCHEMA_VERSION",
    "BlobStore",
    "CompactionConfig",
    "CompactionEngine",
    "CompactionReport",
    "CompactionStep",
    "EventType",
    "LogCorruptionError",
    "LogFormatError",
    "LogRecord",
    "SessionLog",
    "SurfaceNode",
    "UnitWeights",
    "WeightedBudget",
    "content_text",
    "content_units",
    "measure_units",
    "project",
    "surface_json",
    "surface_units",
    "trim_head",
    "trim_tail",
]
