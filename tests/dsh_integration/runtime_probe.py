"""Locate and call the plugin runtime adapters, without assuming they exist.

The scaffold resolves a *facade*: any object exposing the ``PluginLoader``
protocol (``discover`` / ``activate`` / ``deactivate``) and, optionally, a
``load`` / ``register`` / ``install`` entry point used by the duplicate-load
smoke.

Resolution order:

1. ``DSH_SMOKE_RUNTIME`` environment variable, a comma-separated list of
   ``module:attribute`` targets. Use this to point the scaffold at an adapter
   that lives outside the default scan path.
2. Every importable module in ``happyclaw.infra.plugins.runtime``; classes that
   implement the protocol are instantiated with no arguments.

A missing facade raises :class:`NotAvailableError`, which callers translate to
"未实现" rather than a crash or a fake pass.
"""

from __future__ import annotations

import importlib
import inspect
import os
import pkgutil
from dataclasses import dataclass, field
from typing import Any

import happyclaw.infra.plugins.runtime as runtime_package
from happyclaw.infra.plugins.runtime import (
    ActivationContext,
    PluginEnvelope,
    PluginLoader,
)

ENV_OVERRIDE = "DSH_SMOKE_RUNTIME"
VERSION_CONFLICT_CODE = "PLUGIN_VERSION_CONFLICT"

_DISCOVER_ROOT_PARAMETERS = ("roots", "paths", "plugin_dirs", "directories")
_LOAD_ATTRIBUTES = (
    "load_plugin",
    "load",
    "register_plugin",
    "register",
    "install_plugin",
    "install",
    "activate",
)


class NotAvailableError(RuntimeError):
    """The runtime piece the scaffold needs is not implemented yet."""


@dataclass(frozen=True)
class FacadeHit:
    """One resolved loader plus the place it came from."""

    facade: Any
    origin: str


@dataclass(frozen=True)
class DiscoveryResult:
    """Aggregated ``discover()`` output across every resolved facade."""

    envelopes: list[PluginEnvelope] = field(default_factory=list)
    injected_roots: bool = False
    errors: list[str] = field(default_factory=list)
    producer: dict[str, FacadeHit] = field(default_factory=dict)


def resolve_facades() -> list[FacadeHit]:
    """Return the loaders exposed by the runtime package or the env override."""
    override = os.environ.get(ENV_OVERRIDE, "").strip()
    if override:
        return _facades_from_override(override)

    hits: list[FacadeHit] = []
    import_errors: list[str] = []
    for info in pkgutil.iter_modules(runtime_package.__path__, runtime_package.__name__ + "."):
        if info.name.rsplit(".", 1)[-1].startswith("_"):
            continue
        try:
            module = importlib.import_module(info.name)
        except ImportError as exc:
            import_errors.append(f"{info.name}: {type(exc).__name__}: {exc}")
            continue
        hits.extend(_facades_in_module(module, origin=info.name))
    hits = _dedupe(hits)
    if not hits:
        message = (
            f"{runtime_package.__name__} 下未找到实现 PluginLoader 的加载器；"
            f"适配器落地后可直接被扫描到，或用 {ENV_OVERRIDE}=模块:属性 指定"
        )
        if import_errors:
            message += "；导入失败: " + "; ".join(import_errors)
        raise NotAvailableError(message)
    return hits


def discover(facades: list[FacadeHit], roots: list[Any]) -> DiscoveryResult:
    """Call ``discover`` on every facade, injecting fixture roots when possible."""
    envelopes: list[PluginEnvelope] = []
    errors: list[str] = []
    producer: dict[str, FacadeHit] = {}
    injected = False

    for hit in facades:
        try:
            found, used_roots = _call_discover(hit.facade, roots)
        except NotImplementedError as exc:
            errors.append(f"{hit.origin}: discover 未实现 ({exc})")
            continue
        except Exception as exc:  # noqa: BLE001 - reported as evidence, never raised
            errors.append(f"{hit.origin}: discover 抛错 {type(exc).__name__}: {exc}")
            continue
        injected = injected or used_roots
        for item in found:
            if not isinstance(item, PluginEnvelope):
                errors.append(
                    f"{hit.origin}: discover 返回非 PluginEnvelope（{type(item).__name__}）"
                )
                continue
            envelopes.append(item)
            producer.setdefault(item.id, hit)

    return DiscoveryResult(
        envelopes=envelopes,
        injected_roots=injected,
        errors=errors,
        producer=producer,
    )


def find_load_entry(facade: Any) -> tuple[Any, str] | None:
    """Return the first callable load/register/activate entry on ``facade``."""
    for attribute in _LOAD_ATTRIBUTES:
        method = getattr(facade, attribute, None)
        if callable(method):
            return method, attribute
    return None


def invoke_load(entry: Any, envelope: PluginEnvelope) -> Any:
    """Call a load entry with the envelope, adding a context when it wants one."""
    parameters = _positional_parameters(entry)
    required = [item for item in parameters if item.default is inspect.Parameter.empty]
    if len(required) >= 2:
        return entry(envelope, ActivationContext())
    return entry(envelope)


def error_code(exc: BaseException) -> str:
    """Read a stable plugin error code from exception-shaped failures."""
    code = getattr(exc, "code", None)
    if code is None:
        return ""
    return str(getattr(code, "value", code))


def is_version_conflict(exc: BaseException) -> bool:
    return error_code(exc) == VERSION_CONFLICT_CODE


def is_not_implemented(exc: BaseException) -> bool:
    return isinstance(exc, (NotImplementedError, NotAvailableError))


def _facades_from_override(override: str) -> list[FacadeHit]:
    hits: list[FacadeHit] = []
    for entry in override.split(","):
        entry = entry.strip()
        if not entry:
            continue
        module_name, _, attribute = entry.partition(":")
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001 - surfaced as "未实现"
            raise NotAvailableError(
                f"{ENV_OVERRIDE}={entry} 无法导入 {module_name}: {type(exc).__name__}: {exc}"
            ) from exc
        target = module if not attribute else getattr(module, attribute, None)
        if target is None:
            raise NotAvailableError(f"{ENV_OVERRIDE}={entry} 找不到属性 {attribute}")
        hits.extend(_facades_from_target(target, origin=entry))

    hits = _dedupe(hits)
    if not hits:
        raise NotAvailableError(f"{ENV_OVERRIDE}={override} 未解析出任何加载器")
    return hits


def _facades_from_target(target: Any, *, origin: str) -> list[FacadeHit]:
    if inspect.ismodule(target):
        return _facades_in_module(target, origin=origin)
    facade = _as_facade(target)
    if facade is not None:
        return [FacadeHit(facade, origin)]
    if callable(target):
        produced = target()
        if isinstance(produced, (list, tuple)):
            return [
                FacadeHit(item, origin)
                for item in produced
                if _as_facade(item) is not None
            ]
        facade = _as_facade(produced)
        if facade is not None:
            return [FacadeHit(facade, origin)]
    return []


def _facades_in_module(module: Any, *, origin: str) -> list[FacadeHit]:
    hits: list[FacadeHit] = []
    for name, value in vars(module).items():
        if name.startswith("_"):
            continue
        facade = _as_facade(value)
        if facade is not None:
            hits.append(FacadeHit(facade, f"{origin}.{name}"))
    return hits


def _as_facade(value: Any) -> Any | None:
    if inspect.isclass(value):
        if getattr(value, "_is_protocol", False):
            return None
        if not all(callable(getattr(value, name, None)) for name in _LOAD_ATTRIBUTES[-1:]):
            return None
        try:
            instance = value()
        except Exception:  # noqa: BLE001 - classes needing arguments are not facades
            return None
        return instance if _is_loader(instance) else None
    if _is_loader(value):
        return value
    return None


def _is_loader(value: Any) -> bool:
    return isinstance(value, PluginLoader)


def _call_discover(facade: Any, roots: list[Any]) -> tuple[list[Any], bool]:
    method = getattr(facade, "discover")
    try:
        parameters = inspect.signature(method).parameters
    except (TypeError, ValueError):
        parameters = {}
    for name in _DISCOVER_ROOT_PARAMETERS:
        if name in parameters:
            return list(method(**{name: list(roots)})), True
    return list(method()), False


def _positional_parameters(callable_: Any) -> list[inspect.Parameter]:
    try:
        signature = inspect.signature(callable_)
    except (TypeError, ValueError):
        return []
    return [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]


def _dedupe(hits: list[FacadeHit]) -> list[FacadeHit]:
    seen: set[int] = set()
    unique: list[FacadeHit] = []
    for hit in hits:
        marker = id(hit.facade)
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(hit)
    return unique


__all__ = [
    "ENV_OVERRIDE",
    "VERSION_CONFLICT_CODE",
    "DiscoveryResult",
    "FacadeHit",
    "NotAvailableError",
    "discover",
    "error_code",
    "find_load_entry",
    "invoke_load",
    "is_not_implemented",
    "is_version_conflict",
    "resolve_facades",
]
