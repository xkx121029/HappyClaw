"""Smoke 3: duplicate loading of one plugin id must be decidable.

Accepted outcomes:

* a ``PluginRuntimeError`` whose code is ``PLUGIN_VERSION_CONFLICT``;
* an idempotent second load that returns the same activation handle.

Anything else (silent second activation, an unrelated error, an empty result)
is a failure, and a runtime without a load/register/activate entry is reported
as unimplemented.
"""

from __future__ import annotations

from typing import Any

from . import fixture_specs, runtime_probe
from .report import CheckResult, Status

_NAME = "冒烟③ 重复装载同一插件 id 的冲突处理"


def run() -> CheckResult:
    try:
        specs = fixture_specs.load_fixture_specs()
    except Exception as exc:  # noqa: BLE001 - fixture defects are check failures
        return CheckResult(
            _NAME,
            Status.FAIL,
            f"fixture 清单不符合契约: {type(exc).__name__}: {exc}",
        )

    try:
        facades = runtime_probe.resolve_facades()
    except runtime_probe.NotAvailableError as exc:
        return CheckResult(_NAME, Status.UNIMPLEMENTED, str(exc))

    discovery = runtime_probe.discover(facades, [spec.root for spec in specs])
    target = specs[0]
    envelope = next(
        (item for item in discovery.envelopes if item.id == target.envelope.id),
        target.envelope,
    )
    evidence = [f"目标插件: {envelope.id} v{envelope.version}"]
    if envelope is target.envelope:
        evidence.append("运行时未发现该 fixture，改用 fixture 自建 envelope 直接装载")
    evidence.extend(discovery.errors)

    hit = discovery.producer.get(envelope.id) or _preferred_facade(facades)
    entry = runtime_probe.find_load_entry(hit.facade)
    if entry is None:
        return CheckResult(
            _NAME,
            Status.UNIMPLEMENTED,
            f"{hit.origin} 没有 load/register/install/activate 入口",
            tuple(evidence),
        )

    load, entry_name = entry
    evidence.append(f"装载入口: {hit.origin}.{entry_name}")

    try:
        first = runtime_probe.invoke_load(load, envelope)
    except Exception as exc:  # noqa: BLE001 - first load failure is reported
        if runtime_probe.is_not_implemented(exc):
            return CheckResult(
                _NAME,
                Status.UNIMPLEMENTED,
                f"首次装载未实现: {type(exc).__name__}: {exc}",
                tuple(evidence),
            )
        return CheckResult(
            _NAME,
            Status.FAIL,
            f"首次装载失败: {_describe_error(exc)}",
            tuple(evidence),
        )

    evidence.append(f"首次装载结果: {_describe_value(first)}")

    try:
        second = runtime_probe.invoke_load(load, envelope)
    except Exception as exc:  # noqa: BLE001 - judged below
        if runtime_probe.is_not_implemented(exc):
            return CheckResult(
                _NAME,
                Status.UNIMPLEMENTED,
                f"重复装载未实现: {type(exc).__name__}: {exc}",
                tuple(evidence),
            )
        if runtime_probe.is_version_conflict(exc):
            return CheckResult(
                _NAME,
                Status.PASS,
                f"重复装载按契约返回 {runtime_probe.VERSION_CONFLICT_CODE}",
                tuple(evidence),
            )
        code = runtime_probe.error_code(exc)
        if code:
            return CheckResult(
                _NAME,
                Status.FAIL,
                f"重复装载返回错误码 {code}，期望 {runtime_probe.VERSION_CONFLICT_CODE}",
                tuple(evidence),
            )
        return CheckResult(
            _NAME,
            Status.FAIL,
            f"重复装载抛出非契约异常: {_describe_error(exc)}",
            tuple(evidence),
        )

    evidence.append(f"第二次装载结果: {_describe_value(second)}")
    _release(hit.facade, first, second)

    first_id = _activation_id(first)
    second_id = _activation_id(second)
    if first_id and first_id == second_id:
        return CheckResult(
            _NAME,
            Status.PASS,
            f"重复装载复用同一激活句柄（activation_id={first_id}）",
            tuple(evidence),
        )
    if first is not None and first is second:
        return CheckResult(_NAME, Status.PASS, "重复装载返回同一对象（幂等）", tuple(evidence))
    if first is None and second is None:
        return CheckResult(
            _NAME,
            Status.FAIL,
            "两次装载均无返回值，既未报冲突也未给出可判定的幂等结果",
            tuple(evidence),
        )
    return CheckResult(
        _NAME,
        Status.FAIL,
        "重复装载产生了两个不同激活，且未返回 PLUGIN_VERSION_CONFLICT",
        tuple(evidence),
    )


def _preferred_facade(facades: list[runtime_probe.FacadeHit]) -> runtime_probe.FacadeHit:
    for hit in facades:
        entry = runtime_probe.find_load_entry(hit.facade)
        if entry is not None and entry[1] != "activate":
            return hit
    return facades[0]


def _activation_id(value: Any) -> str:
    raw = getattr(value, "activation_id", None)
    return str(raw) if raw else ""


def _describe_value(value: Any) -> str:
    if value is None:
        return "None"
    activation_id = _activation_id(value)
    if activation_id:
        return f"{type(value).__name__}(activation_id={activation_id})"
    return f"{type(value).__name__}({value!r})"


def _describe_error(exc: BaseException) -> str:
    code = runtime_probe.error_code(exc)
    prefix = f"[{code}] " if code else ""
    return f"{prefix}{type(exc).__name__}: {exc}"


def _release(facade: Any, *handles: Any) -> None:
    deactivate = getattr(facade, "deactivate", None)
    if not callable(deactivate):
        return
    for handle in handles:
        if not _activation_id(handle):
            continue
        try:
            deactivate(handle)
        except Exception:  # noqa: BLE001 - cleanup must not mask the verdict
            pass
