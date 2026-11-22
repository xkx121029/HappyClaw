"""Shared idempotent activation bookkeeping for the ecosystem loaders.

This module is private (leading underscore) so the smoke scaffold never treats
its helper class as a loader facade.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from happyclaw.infra.plugins.runtime.contract import (
    ActivationContext,
    PluginEnvelope,
    PluginHandle,
    PluginKind,
    PluginLoadError,
    VersionConflictError,
)


def ensure_entry_available(envelope: PluginEnvelope) -> None:
    """Fail loudly when the manifest entry does not exist on disk.

    Activation must not report success for a plugin whose entry is missing: the
    caller would otherwise treat it as loaded while nothing can ever run.
    """

    entry_path = Path(envelope.source.reference).parent / envelope.entry
    if entry_path.is_file():
        return
    directory = entry_path.parent
    try:
        preview = sorted(item.name for item in directory.iterdir())[:12]
    except OSError:
        preview = []
    raise PluginLoadError(
        "plugin entry does not exist",
        details={
            "plugin_id": envelope.id,
            "reason": "entry_missing",
            "entry": str(entry_path),
            "directory": str(directory),
            "directory_preview": preview,
        },
    )


@dataclass(frozen=True, slots=True)
class _ActiveRecord:
    handle: PluginHandle
    version: str


class ActivationStore:
    """Tracks active envelopes and makes duplicate activation idempotent.

    Activating the same id twice with the same version returns the original
    handle; activating it with a different version raises
    ``PLUGIN_VERSION_CONFLICT``. ``deactivate`` is safe to call twice.
    """

    def __init__(self, kind: PluginKind) -> None:
        self._kind = kind
        self._active: dict[str, _ActiveRecord] = {}

    def activate(self, envelope: PluginEnvelope, ctx: ActivationContext) -> PluginHandle:
        del ctx  # loaders that execute plugins override this method
        if envelope.kind is not self._kind:
            raise PluginLoadError(
                "envelope kind does not match this loader",
                details={"loader": self._kind.value, "plugin": envelope.id},
            )

        record = self._active.get(envelope.id)
        if record is not None:
            if record.version != envelope.version:
                raise VersionConflictError(
                    "plugin is already active with a different version",
                    details={
                        "plugin_id": envelope.id,
                        "active_version": record.version,
                        "requested_version": envelope.version,
                    },
                )
            return record.handle

        handle = PluginHandle(
            plugin_id=envelope.id,
            kind=envelope.kind,
            activation_id=f"{envelope.kind.value}-{uuid.uuid4().hex}",
        )
        self._active[envelope.id] = _ActiveRecord(handle=handle, version=envelope.version)
        return handle

    def deactivate(self, handle: PluginHandle) -> None:
        record = self._active.get(handle.plugin_id)
        if record is None:
            return
        if record.handle.activation_id == handle.activation_id:
            self._active.pop(handle.plugin_id, None)

    def is_active(self, plugin_id: str) -> bool:
        return plugin_id in self._active
