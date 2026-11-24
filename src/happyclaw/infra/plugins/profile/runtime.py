"""Atomic profile switching, lazy activation, and load timing.

Switching semantics
-------------------
A switch first resolves the target profile, then activates the missing eager
plugins. Only after every eager activation succeeds does it deactivate plugins
that left the composition. If any activation fails, the newly activated plugins
are torn down in reverse order and the previous composition (including its
handles, plan, and failure marks) is restored untouched. That is the atomicity
contract: the caller observes either the old composition or the new one, never
a half-applied one.

Lazy plugins are never touched during a switch. They load on the first
``ensure_loaded`` call; a failure there is recorded against that plugin only and
leaves the rest of the composition running.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from happyclaw.infra.plugins.profile.errors import ProfileNotFoundError
from happyclaw.infra.plugins.profile.model import LoadMode, Profile
from happyclaw.infra.plugins.profile.solver import ResolvedProfile, resolve_profile
from happyclaw.infra.plugins.profile.store import ActiveProfile, ProfileStore
from happyclaw.infra.plugins.runtime.contract import (
    ActivationContext,
    CapabilityKind,
    MissingDependencyError,
    PermissionKind,
    PluginEnvelope,
    PluginErrorCode,
    PluginHandle,
    PluginKind,
    PluginLoader,
    PluginLoadError,
    PluginRuntimeError,
)

__all__ = [
    "LoadTiming",
    "PluginFailure",
    "PluginState",
    "PluginStatus",
    "ProfileRuntime",
    "RefreshResult",
    "SwitchResult",
]

logger = logging.getLogger(__name__)

Clock = Callable[[], float]


class PluginStatus(StrEnum):
    """Observable state of one plugin in the current composition."""

    ACTIVE = "active"
    PENDING = "pending"
    FAILED = "failed"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class LoadTiming:
    """One measured activation, attributed to its triggering phase."""

    plugin_id: str
    phase: LoadMode
    elapsed_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "phase": self.phase.value,
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass(frozen=True, slots=True)
class PluginFailure:
    """A plugin that could not be activated, with its stable error code."""

    plugin_id: str
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"plugin_id": self.plugin_id, "code": self.code, "message": self.message}


@dataclass(frozen=True, slots=True)
class PluginState:
    """One row of ``ProfileRuntime.status()``."""

    plugin_id: str
    load: LoadMode
    status: PluginStatus
    version: str | None = None
    error: PluginFailure | None = None
    elapsed_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "load": self.load.value,
            "status": self.status.value,
            "version": self.version,
            "error": None if self.error is None else self.error.to_dict(),
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass(frozen=True, slots=True)
class SwitchResult:
    """Outcome of one ``switch`` call."""

    ok: bool
    profile: str
    revision: int
    activated: tuple[str, ...]
    deactivated: tuple[str, ...]
    failures: tuple[PluginFailure, ...]
    rolled_back: bool
    elapsed_ms: float
    persisted: bool
    replaced: tuple[str, ...] = ()
    capabilities: Mapping[str, tuple[CapabilityKind, ...]] = field(default_factory=dict)
    permissions: Mapping[str, tuple[PermissionKind, ...]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "profile": self.profile,
            "revision": self.revision,
            "activated": list(self.activated),
            "deactivated": list(self.deactivated),
            "replaced": list(self.replaced),
            "failures": [failure.to_dict() for failure in self.failures],
            "rolled_back": self.rolled_back,
            "elapsed_ms": self.elapsed_ms,
            "persisted": self.persisted,
            "capabilities": {
                plugin_id: [capability.value for capability in capabilities]
                for plugin_id, capabilities in self.capabilities.items()
            },
            "permissions": {
                plugin_id: [permission.value for permission in permissions]
                for plugin_id, permissions in self.permissions.items()
            },
        }


@dataclass(frozen=True, slots=True)
class RefreshResult:
    """Outcome of reconciling the active composition with a fresh discovery."""

    ok: bool
    degraded: bool
    missing: tuple[str, ...]
    replaced: tuple[str, ...]
    failures: tuple[PluginFailure, ...]
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "degraded": self.degraded,
            "missing": list(self.missing),
            "replaced": list(self.replaced),
            "failures": [failure.to_dict() for failure in self.failures],
            "reason": self.reason,
        }


@dataclass(slots=True)
class _Active:
    handle: PluginHandle
    mode: LoadMode
    version: str


def _failure_from(plugin_id: str, exc: Exception) -> PluginFailure:
    if isinstance(exc, PluginRuntimeError):
        return PluginFailure(plugin_id=plugin_id, code=exc.code.value, message=exc.message)
    return PluginFailure(
        plugin_id=plugin_id,
        code=PluginErrorCode.LOAD_FAILED.value,
        message=f"插件 {plugin_id} 装载失败：{exc}",
    )


class ProfileRuntime:
    """Owns the active composition and the switch/lazy-load state machine."""

    def __init__(
        self,
        *,
        loaders: Mapping[PluginKind, PluginLoader] | None = None,
        envelopes: Sequence[PluginEnvelope] | None = None,
        store: ProfileStore | None = None,
        clock: Clock | None = None,
        services: Mapping[str, Any] | None = None,
        envelope_provider: Callable[[], Mapping[str, PluginEnvelope]] | None = None,
    ) -> None:
        self._loaders: dict[PluginKind, PluginLoader] = dict(loaders or {})
        if envelopes is None:
            discovered: list[PluginEnvelope] = []
            for loader in self._loaders.values():
                discovered.extend(loader.discover())
            envelopes = discovered
        self._envelopes: dict[str, PluginEnvelope] = {}
        for envelope in envelopes:
            self._envelopes.setdefault(envelope.id, envelope)
        self._store = store
        self._clock: Clock = clock or time.perf_counter
        self._services: dict[str, Any] = dict(services or {})
        self._active: dict[str, _Active] = {}
        self._plan: ResolvedProfile | None = None
        self._failures: dict[str, PluginFailure] = {}
        self._timings: list[LoadTiming] = []
        self._profile_name: str | None = None
        self._previous_name: str | None = None
        self._revision = 0
        self._provider = envelope_provider
        self._degraded = False
        self._missing: tuple[str, ...] = ()
        self._degradation_reason: str | None = None

    @property
    def active_profile(self) -> str | None:
        return self._profile_name

    @property
    def previous_profile(self) -> str | None:
        return self._previous_name

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def degraded(self) -> bool:
        """True when a refresh found a plugin gone or a constraint broken."""

        return self._degraded

    @property
    def missing_plugins(self) -> tuple[str, ...]:
        """Plugins that are part of the composition but no longer installed."""

        return self._missing

    @property
    def degradation_reason(self) -> str | None:
        return self._degradation_reason

    @property
    def envelopes(self) -> Mapping[str, PluginEnvelope]:
        return dict(self._envelopes)

    def switch(self, profile: str | Profile, *, persist: bool = True) -> SwitchResult:
        """Atomically make ``profile`` the active composition."""

        target = self._resolve_profile(profile)
        started = self._clock()
        self._sync_envelopes()
        try:
            plan = resolve_profile(target, self._envelopes)
        except PluginRuntimeError as exc:
            # The switch is refused, not silently shrunk; record why.
            self._note_degraded(exc)
            raise

        previous_plan = self._plan
        previous_active = dict(self._active)
        previous_failures = dict(self._failures)
        previous_name = self._profile_name
        previous_previous_name = self._previous_name
        previous_degraded = self._degraded
        previous_missing = self._missing
        previous_reason = self._degradation_reason

        activated: list[str] = []
        replaced: list[str] = []
        newly: list[tuple[str, PluginHandle]] = []
        superseded: list[tuple[str, PluginHandle]] = []
        failure: PluginFailure | None = None
        timing_mark = len(self._timings)

        for plugin_id in plan.order:
            envelope = self._envelopes[plugin_id]
            existing = self._active.get(plugin_id)
            version_changed = existing is not None and existing.version != envelope.version
            if existing is not None and not version_changed:
                continue
            if existing is None and plan.modes[plugin_id] is LoadMode.LAZY:
                continue
            if version_changed and plan.modes[plugin_id] is LoadMode.LAZY:
                # Drop the stale version; the new one loads on first use.
                self._deactivate(plugin_id)
                replaced.append(plugin_id)
                continue
            loader = self._loaders.get(envelope.kind)
            if loader is None:
                failure = PluginFailure(
                    plugin_id=plugin_id,
                    code=PluginErrorCode.LOAD_FAILED.value,
                    message=f"没有可用于 {envelope.kind.value} 插件的加载器，无法装载 {plugin_id}",
                )
                break
            begin = self._clock()
            try:
                handle = loader.activate(
                    envelope,
                    ActivationContext(
                        config=plan.configs.get(plugin_id, {}),
                        services=self._services,
                    ),
                )
            except Exception as exc:
                # Plugin code is an untrusted boundary: record, then roll back.
                failure = _failure_from(plugin_id, exc)
                break
            self._timings.append(
                LoadTiming(
                    plugin_id=plugin_id,
                    phase=LoadMode.EAGER,
                    elapsed_ms=(self._clock() - begin) * 1000.0,
                )
            )
            self._active[plugin_id] = _Active(
                handle=handle,
                mode=LoadMode.EAGER,
                version=envelope.version,
            )
            newly.append((plugin_id, handle))
            if existing is not None:
                # Keep the old version running until the new one is committed.
                superseded.append((plugin_id, existing.handle))
                replaced.append(plugin_id)
            else:
                activated.append(plugin_id)

        if failure is not None:
            for plugin_id, handle in reversed(newly):
                self._deactivate_handle(plugin_id, handle)
            # The failed attempt never became the composition; drop its timings
            # so ``timing_report`` only aggregates committed loads.
            del self._timings[timing_mark:]
            self._active = previous_active
            self._plan = previous_plan
            self._failures = previous_failures
            self._profile_name = previous_name
            self._previous_name = previous_previous_name
            self._degraded = previous_degraded
            self._missing = previous_missing
            self._degradation_reason = previous_reason
            return SwitchResult(
                ok=False,
                profile=target.name,
                revision=self._revision,
                activated=tuple(activated),
                deactivated=(),
                failures=(failure,),
                rolled_back=True,
                elapsed_ms=(self._clock() - started) * 1000.0,
                persisted=False,
            )

        deactivated: list[str] = []
        stale: list[str] = []
        if previous_plan is not None:
            stale.extend(
                plugin_id
                for plugin_id in reversed(previous_plan.order)
                if plugin_id in self._active and plugin_id not in plan.order
            )
        stale.extend(
            plugin_id
            for plugin_id in self._active
            if plugin_id not in plan.order and plugin_id not in stale
        )
        for plugin_id in stale:
            self._deactivate(plugin_id)
            deactivated.append(plugin_id)
        for plugin_id, handle in superseded:
            self._deactivate_handle(plugin_id, handle)

        self._plan = plan
        self._failures = {}
        self._previous_name = previous_name
        self._profile_name = target.name
        self._revision += 1
        self._degraded = False
        self._missing = ()
        self._degradation_reason = None

        persisted = False
        if persist and self._store is not None:
            try:
                self._store.save_active(
                    ActiveProfile(
                        name=target.name,
                        previous=previous_name,
                        revision=self._revision,
                        switched_at=datetime.now(UTC).isoformat(timespec="seconds"),
                    )
                )
                persisted = True
            except OSError as exc:
                logger.warning("组合状态写入失败：%s", exc)

        return SwitchResult(
            ok=True,
            profile=target.name,
            revision=self._revision,
            activated=tuple(activated),
            deactivated=tuple(deactivated),
            failures=(),
            rolled_back=False,
            elapsed_ms=(self._clock() - started) * 1000.0,
            persisted=persisted,
            replaced=tuple(replaced),
            capabilities=plan.capabilities,
            permissions=plan.permissions,
        )

    def refresh(self) -> RefreshResult:
        """Reconcile the active composition with a fresh discovery.

        Semantics: upgraded versions that still satisfy every constraint are
        swapped in; plugins that disappeared (or whose new version breaks a
        constraint) are stopped and the composition is marked ``degraded`` with
        the affected ids. The remaining plugins keep running.
        """

        provider = self._provider
        if provider is None:
            raise PluginLoadError("没有配置插件发现来源，无法刷新组合")
        self._sync_envelopes()
        plan = self._plan
        if plan is None:
            return RefreshResult(
                ok=True,
                degraded=False,
                missing=(),
                replaced=(),
                failures=(),
            )

        try:
            new_plan = resolve_profile(plan.profile, self._envelopes)
        except PluginRuntimeError as exc:
            stopped = self._stop_unusable()
            self._note_degraded(exc, stopped=stopped, plan=plan)
            failure = PluginFailure(
                plugin_id=self._missing[0] if self._missing else "",
                code=exc.code.value,
                message=exc.message,
            )
            return RefreshResult(
                ok=False,
                degraded=True,
                missing=self._missing,
                replaced=(),
                failures=(failure,),
                reason=self._degradation_reason,
            )

        replaced: list[str] = []
        for plugin_id, record in list(self._active.items()):
            envelope = self._envelopes.get(plugin_id)
            if envelope is None or envelope.version == record.version:
                continue
            self._deactivate(plugin_id)
            replaced.append(plugin_id)

        failures: list[PluginFailure] = []
        for plugin_id in new_plan.order:
            if new_plan.modes[plugin_id] is LoadMode.LAZY or plugin_id in self._active:
                continue
            envelope = self._envelopes[plugin_id]
            loader = self._loaders.get(envelope.kind)
            if loader is None:
                failures.append(
                    PluginFailure(
                        plugin_id=plugin_id,
                        code=PluginErrorCode.LOAD_FAILED.value,
                        message=f"没有可用于 {envelope.kind.value} 插件的加载器，无法装载 {plugin_id}",
                    )
                )
                continue
            begin = self._clock()
            try:
                handle = loader.activate(
                    envelope,
                    ActivationContext(
                        config=new_plan.configs.get(plugin_id, {}),
                        services=self._services,
                    ),
                )
            except Exception as exc:
                failures.append(_failure_from(plugin_id, exc))
                continue
            self._timings.append(
                LoadTiming(
                    plugin_id=plugin_id,
                    phase=LoadMode.EAGER,
                    elapsed_ms=(self._clock() - begin) * 1000.0,
                )
            )
            self._active[plugin_id] = _Active(
                handle=handle,
                mode=LoadMode.EAGER,
                version=envelope.version,
            )

        self._plan = new_plan
        self._failures = {failure.plugin_id: failure for failure in failures}
        self._revision += 1
        self._degraded = bool(failures)
        self._missing = ()
        self._degradation_reason = (
            f"{failures[0].code}: {failures[0].message}" if failures else None
        )
        return RefreshResult(
            ok=not failures,
            degraded=bool(failures),
            missing=(),
            replaced=tuple(replaced),
            failures=tuple(failures),
            reason=self._degradation_reason,
        )

    def rollback(self, *, persist: bool = True) -> SwitchResult:
        """Switch back to the profile that was active before the last switch."""

        if self._previous_name is None:
            raise PluginLoadError(
                "没有可回滚的组合",
                details={"profile": self._profile_name},
            )
        return self.switch(self._previous_name, persist=persist)

    def ensure_loaded(self, plugin_id: str) -> PluginHandle:
        """Load a plugin on first use; failures stay local to that plugin."""

        plan = self._plan
        if plan is None:
            raise PluginLoadError("尚未切换到任何组合，无法装载插件")
        if plugin_id not in plan.modes:
            raise PluginLoadError(
                f"插件 {plugin_id} 不在当前组合中",
                details={"plugin_id": plugin_id, "profile": self._profile_name},
            )
        self._sync_envelopes()
        envelope = self._envelopes.get(plugin_id)
        if envelope is None:
            failure = PluginFailure(
                plugin_id=plugin_id,
                code=PluginErrorCode.DEPENDENCY_MISSING.value,
                message=f"插件 {plugin_id} 已不在安装目录中（可能被卸载）",
            )
            self._failures[plugin_id] = failure
            raise MissingDependencyError(
                failure.message,
                details={"plugin_id": plugin_id, "profile": self._profile_name},
            )
        record = self._active.get(plugin_id)
        if record is not None and record.version == envelope.version:
            return record.handle
        if record is not None:
            # An upgrade landed while this lazy plugin was idle.
            self._deactivate(plugin_id)
        loader = self._loaders.get(envelope.kind)
        if loader is None:
            raise PluginLoadError(
                f"没有可用于 {envelope.kind.value} 插件的加载器，无法装载 {plugin_id}",
                details={"plugin_id": plugin_id},
            )

        begin = self._clock()
        try:
            handle = loader.activate(
                envelope,
                ActivationContext(
                    config=plan.configs.get(plugin_id, {}),
                    services=self._services,
                ),
            )
        except Exception as exc:
            self._failures[plugin_id] = _failure_from(plugin_id, exc)
            if isinstance(exc, PluginRuntimeError):
                raise
            raise PluginLoadError(
                f"插件 {plugin_id} 装载失败：{exc}",
                details={"plugin_id": plugin_id},
            ) from exc

        self._timings.append(
            LoadTiming(
                plugin_id=plugin_id,
                phase=LoadMode.LAZY,
                elapsed_ms=(self._clock() - begin) * 1000.0,
            )
        )
        self._active[plugin_id] = _Active(
            handle=handle,
            mode=LoadMode.LAZY,
            version=envelope.version,
        )
        self._failures.pop(plugin_id, None)
        return handle

    def status(self) -> tuple[PluginState, ...]:
        """Return every plugin the current composition knows about."""

        plan = self._plan
        if plan is None:
            return ()
        timings = {timing.plugin_id: timing for timing in self._timings}
        states: list[PluginState] = []
        for entry in plan.profile.entries:
            if entry.enabled:
                continue
            states.append(
                PluginState(
                    plugin_id=entry.plugin_id,
                    load=entry.load,
                    status=PluginStatus.DISABLED,
                )
            )
        for plugin_id in plan.order:
            mode = plan.modes[plugin_id]
            failure = self._failures.get(plugin_id)
            if plugin_id in self._active:
                status = PluginStatus.ACTIVE
            elif failure is not None:
                status = PluginStatus.FAILED
            else:
                status = PluginStatus.PENDING
            timing = timings.get(plugin_id)
            envelope = self._envelopes.get(plugin_id)
            states.append(
                PluginState(
                    plugin_id=plugin_id,
                    load=mode,
                    status=status,
                    version=None if envelope is None else envelope.version,
                    error=failure,
                    elapsed_ms=None if timing is None else timing.elapsed_ms,
                )
            )
        return tuple(states)

    def capabilities_for(self, plugin_id: str) -> tuple[CapabilityKind, ...]:
        """Effective capability switch for one plugin in the current plan."""

        plan = self._plan
        if plan is None or plugin_id not in plan.capabilities:
            raise PluginLoadError(
                f"插件 {plugin_id} 不在当前组合中",
                details={"plugin_id": plugin_id, "profile": self._profile_name},
            )
        return plan.capabilities[plugin_id]

    def permissions_for(self, plugin_id: str) -> tuple[PermissionKind, ...]:
        """Effective permissions for one plugin; empty means least privilege."""

        plan = self._plan
        if plan is None or plugin_id not in plan.permissions:
            raise PluginLoadError(
                f"插件 {plugin_id} 不在当前组合中",
                details={"plugin_id": plugin_id, "profile": self._profile_name},
            )
        return plan.permissions[plugin_id]

    def permission_report(self) -> dict[str, Any]:
        """Export effective permissions per plugin plus the composition union.

        Undeclared manifests appear with ``declared=false`` and an empty item
        list: the least-privilege default, never "everything allowed".
        """

        plan = self._plan
        if plan is None:
            raise PluginLoadError("尚未切换到任何组合，无法导出权限")
        plugins: list[dict[str, Any]] = []
        union: set[PermissionKind] = set()
        undeclared: list[str] = []
        for plugin_id in plan.order:
            envelope = self._envelopes[plugin_id]
            granted = plan.permissions[plugin_id]
            declared = bool(envelope.permissions)
            union.update(granted)
            if not declared:
                undeclared.append(plugin_id)
            plugins.append(
                {
                    "plugin_id": plugin_id,
                    "declared": declared,
                    "items": [
                        permission.value
                        for permission in PermissionKind
                        if permission in set(granted)
                    ],
                    "policy": "declared" if declared else "least_privilege",
                }
            )
        return {
            "profile": self._profile_name,
            "plugins": plugins,
            "union": [
                permission.value
                for permission in PermissionKind
                if permission in union
            ],
            "undeclared": undeclared,
        }

    def timings(self) -> tuple[LoadTiming, ...]:
        return tuple(self._timings)

    def timing_report(self) -> dict[str, Any]:
        """Aggregate load time by phase, so lazy savings are measurable.

        ``eager_ms`` is what a switch paid; ``lazy_ms`` is what first use paid
        later. Both are summed from the same per-plugin measurements, so the
        report cannot show the same cost twice.
        """

        eager = round(
            sum(t.elapsed_ms for t in self._timings if t.phase is LoadMode.EAGER),
            3,
        )
        lazy = round(
            sum(t.elapsed_ms for t in self._timings if t.phase is LoadMode.LAZY),
            3,
        )
        return {
            "eager_ms": eager,
            "lazy_ms": lazy,
            "total_ms": round(eager + lazy, 3),
            "plugins": [timing.to_dict() for timing in self._timings],
        }

    def _resolve_profile(self, profile: str | Profile) -> Profile:
        if isinstance(profile, Profile):
            return profile
        if self._store is None:
            raise ProfileNotFoundError(
                "没有配置组合存储目录，无法按名称切换组合",
                details={"profile": profile},
            )
        return self._store.get(profile)

    def _sync_envelopes(self) -> None:
        """Pull a fresh discovery snapshot before resolving a profile.

        Without a provider this is a no-op, so explicitly injected envelopes
        keep working for tests and hosts that own discovery themselves.
        """

        provider = self._provider
        if provider is None:
            return
        try:
            discovered = provider()
        except Exception as exc:
            raise PluginLoadError(
                f"插件发现失败：{exc}",
                details={"profile": self._profile_name},
            ) from exc
        self._envelopes = dict(discovered)

    def _note_degraded(
        self,
        exc: PluginRuntimeError,
        *,
        stopped: Sequence[str] = (),
        plan: ResolvedProfile | None = None,
    ) -> None:
        missing = set(stopped)
        missing.update(plugin_id for plugin_id in self._active if plugin_id not in self._envelopes)
        reference = plan or self._plan
        if reference is not None:
            missing.update(
                plugin_id
                for plugin_id in reference.order
                if plugin_id not in self._envelopes
            )
        self._missing = tuple(sorted(missing))
        self._degraded = True
        self._degradation_reason = f"{exc.code.value}: {exc.message}"
        for plugin_id in self._missing:
            self._failures[plugin_id] = PluginFailure(
                plugin_id=plugin_id,
                code=exc.code.value,
                message=exc.message,
            )

    def _stop_unusable(self) -> list[str]:
        """Stop active plugins whose slot disappeared or changed version."""

        stopped: list[str] = []
        for plugin_id in list(self._active):
            envelope = self._envelopes.get(plugin_id)
            record = self._active[plugin_id]
            if envelope is None or envelope.version != record.version:
                self._deactivate(plugin_id)
                stopped.append(plugin_id)
        return stopped

    def _deactivate(self, plugin_id: str) -> None:
        record = self._active.pop(plugin_id, None)
        if record is None:
            return
        self._deactivate_handle(plugin_id, record.handle)

    def _deactivate_handle(self, plugin_id: str, handle: PluginHandle) -> None:
        loader = self._loaders.get(handle.kind)
        if loader is None:
            return
        try:
            loader.deactivate(handle)
        except Exception as exc:
            # Teardown errors do not change composition semantics.
            logger.warning("插件 %s 卸载失败：%s", plugin_id, exc)
