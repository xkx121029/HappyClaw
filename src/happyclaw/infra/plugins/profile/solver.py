"""Dependency closure and version checks for a profile.

The solver walks ``PluginEnvelope.requires`` from the profile's enabled rows,
auto-includes undiscovered-but-needed dependencies under their default
configuration, and refuses to proceed when something is missing or too old.
Nothing is skipped silently: every failure is a stable contract error code with
a Chinese message the local owner can act on.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from happyclaw.infra.plugins.profile.model import LoadMode, Profile
from happyclaw.infra.plugins.runtime.contract import (
    CapabilityKind,
    InvalidManifestError,
    MissingDependencyError,
    PermissionKind,
    PluginEnvelope,
    VersionConflictError,
)

__all__ = ["ResolvedProfile", "resolve_profile"]


@dataclass(frozen=True, slots=True)
class ResolvedProfile:
    """A profile plus the concrete activation plan derived from it."""

    profile: Profile
    order: tuple[str, ...]
    modes: Mapping[str, LoadMode]
    configs: Mapping[str, Mapping[str, object]]
    capabilities: Mapping[str, tuple[CapabilityKind, ...]]
    permissions: Mapping[str, tuple[PermissionKind, ...]]


def resolve_profile(
    profile: Profile,
    envelopes: Mapping[str, PluginEnvelope],
) -> ResolvedProfile:
    """Return the dependency closure of ``profile`` sorted dependencies-first.

    Eager rows propagate ``eager`` to their whole dependency closure; lazy rows
    keep their dependencies lazy unless something eager already pulled them in.
    A dependency missing from the profile is included with default config.
    """

    modes: dict[str, LoadMode] = {}
    configs: dict[str, Mapping[str, object]] = {}
    capabilities: dict[str, tuple[CapabilityKind, ...]] = {}
    permissions: dict[str, tuple[PermissionKind, ...]] = {}
    order: list[str] = []
    visiting: list[str] = []
    visited: set[str] = set()

    def entry_config(plugin_id: str) -> Mapping[str, object]:
        entry = profile.entry(plugin_id)
        return dict(entry.config) if entry is not None else {}

    def entry_capabilities(plugin_id: str, envelope: PluginEnvelope) -> tuple[CapabilityKind, ...]:
        entry = profile.entry(plugin_id)
        if entry is None or entry.capabilities is None:
            return tuple(envelope.capabilities)
        chosen = entry.capabilities
        missing = [capability for capability in chosen if capability not in envelope.capabilities]
        if missing:
            raise InvalidManifestError(
                f"插件 {plugin_id} 没有声明能力 "
                + "、".join(capability.value for capability in missing)
                + "，无法在组合里开启",
                details={
                    "plugin_id": plugin_id,
                    "capabilities": [capability.value for capability in missing],
                },
            )
        return tuple(chosen)

    def effective_permissions(
        plugin_id: str, envelope: PluginEnvelope
    ) -> tuple[PermissionKind, ...]:
        """Return the profile's permission switch, capped by the manifest.

        An undeclared manifest permission set stays empty (least privilege).
        A profile may narrow it, never widen it.
        """

        entry = profile.entry(plugin_id)
        if entry is None or entry.permissions is None:
            return tuple(envelope.permissions)
        chosen = entry.permissions
        extra = [permission for permission in chosen if permission not in envelope.permissions]
        if extra:
            raise InvalidManifestError(
                f"插件 {plugin_id} 没有声明权限 "
                + "、".join(permission.value for permission in extra)
                + "，无法在组合里开启",
                details={
                    "plugin_id": plugin_id,
                    "permissions": [permission.value for permission in extra],
                },
            )
        return tuple(chosen)

    def visit(plugin_id: str, requested: LoadMode) -> None:
        current = modes.get(plugin_id)
        effective = requested
        if current is LoadMode.EAGER or current is LoadMode.LAZY and requested is LoadMode.EAGER:
            effective = LoadMode.EAGER

        if plugin_id in visited:
            if effective is LoadMode.EAGER and modes[plugin_id] is LoadMode.LAZY:
                # An eager dependent arrives after the plugin was visited lazily:
                # upgrade it and its own closure.
                modes[plugin_id] = LoadMode.EAGER
                envelope = envelopes.get(plugin_id)
                if envelope is not None:
                    for requirement in envelope.requires:
                        visit(requirement.plugin_id, LoadMode.EAGER)
            return
        if plugin_id in visiting:
            chain = " → ".join([*visiting[visiting.index(plugin_id) :], plugin_id])
            raise InvalidManifestError(
                f"插件依赖存在循环：{chain}",
                details={"profile": profile.name, "cycle": chain},
            )

        entry = profile.entry(plugin_id)
        if entry is not None and not entry.enabled:
            raise MissingDependencyError(
                f"插件 {plugin_id} 在组合 {profile.name} 中被禁用，但其他插件依赖它",
                details={"profile": profile.name, "plugin_id": plugin_id},
            )
        envelope = envelopes.get(plugin_id)
        if envelope is None:
            raise MissingDependencyError(
                f"组合 {profile.name} 需要的插件 {plugin_id} 未被发现",
                details={"profile": profile.name, "plugin_id": plugin_id},
            )

        visiting.append(plugin_id)
        modes[plugin_id] = effective
        for requirement in envelope.requires:
            dependency = envelopes.get(requirement.plugin_id)
            if dependency is None:
                raise MissingDependencyError(
                    f"插件 {plugin_id} 依赖的 {requirement.plugin_id} 未被发现",
                    details={
                        "profile": profile.name,
                        "plugin_id": plugin_id,
                        "dependency": requirement.plugin_id,
                    },
                )
            if not requirement.matches(dependency.version):
                raise VersionConflictError(
                    f"插件 {plugin_id} 需要 {requirement.plugin_id}"
                    f"{requirement.constraint}，当前发现版本为 {dependency.version}",
                    details={
                        "profile": profile.name,
                        "plugin_id": plugin_id,
                        "dependency": requirement.plugin_id,
                        "constraint": requirement.constraint,
                        "version": dependency.version,
                    },
                )
            visit(requirement.plugin_id, effective)

        visiting.pop()
        visited.add(plugin_id)
        order.append(plugin_id)
        configs[plugin_id] = entry_config(plugin_id)
        capabilities[plugin_id] = entry_capabilities(plugin_id, envelope)
        permissions[plugin_id] = effective_permissions(plugin_id, envelope)

    for entry in profile.entries:
        if entry.enabled:
            visit(entry.plugin_id, entry.load)

    return ResolvedProfile(
        profile=profile,
        order=tuple(order),
        modes=dict(modes),
        configs=dict(configs),
        capabilities=dict(capabilities),
        permissions=dict(permissions),
    )
