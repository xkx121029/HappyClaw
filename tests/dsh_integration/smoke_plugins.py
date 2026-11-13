"""Smoke 1: load the fixture plugins through the runtime and list capabilities.

Expected capabilities are read from each fixture's own manifest by
``fixture_specs``; this module never pins a capability value. A fixture that
declares no capability must load with ``capabilities == ()`` and stay on the
least-privilege path: the runtime must mark it as undeclared and must not turn
the empty set into "everything is allowed".
"""

from __future__ import annotations

from octop.infra.plugins.runtime import PluginEnvelope

from . import fixture_specs, runtime_probe
from .report import CheckResult, Status

_NAME = "冒烟① 装载 fixture 插件并列出能力（期望取自各 fixture 清单）"


def run() -> CheckResult:
    try:
        specs = fixture_specs.load_fixture_specs()
    except Exception as exc:  # noqa: BLE001 - fixture defects are check failures
        return CheckResult(
            _NAME,
            Status.FAIL,
            f"fixture 清单不符合契约: {type(exc).__name__}: {exc}",
        )

    evidence = [_describe_spec(spec) for spec in specs]
    for spec in specs:
        if not spec.entry_path.is_file():
            return CheckResult(
                _NAME,
                Status.FAIL,
                f"fixture 入口文件缺失: {spec.entry_path}",
                tuple(evidence),
            )

    try:
        facades = runtime_probe.resolve_facades()
    except runtime_probe.NotAvailableError as exc:
        return CheckResult(_NAME, Status.UNIMPLEMENTED, str(exc), tuple(evidence))

    discovery = runtime_probe.discover(facades, [spec.root for spec in specs])
    evidence.append(
        f"运行时发现 {len(discovery.envelopes)} 个 envelope"
        f"（注入 fixture 扫描根: {'是' if discovery.injected_roots else '否'}）"
    )
    evidence.extend(discovery.errors)

    found = {envelope.id: envelope for envelope in discovery.envelopes}
    missing = [plugin_id for plugin_id in fixture_specs.EXPECTED_IDS if plugin_id not in found]
    if missing:
        if not discovery.injected_roots and not discovery.envelopes:
            return CheckResult(
                _NAME,
                Status.UNIMPLEMENTED,
                "运行时加载器既不接受外部扫描根，也未返回任何 envelope，无法注入 fixture",
                tuple(evidence),
            )
        return CheckResult(
            _NAME,
            Status.FAIL,
            f"运行时未发现 fixture: {', '.join(missing)}",
            tuple(evidence),
        )

    for spec in specs:
        envelope = found[spec.envelope.id]
        expected = tuple(capability.value for capability in spec.envelope.capabilities)
        actual = tuple(capability.value for capability in envelope.capabilities)
        declared = bool(spec.envelope.metadata.get("capabilities_declared", expected))
        evidence.append(
            f"{envelope.id} v{envelope.version} 能力=[{', '.join(actual) or '无'}]"
            f"（{'清单已声明' if declared else '清单未声明'}）"
        )
        if actual != expected:
            return CheckResult(
                _NAME,
                Status.FAIL,
                f"{envelope.id} 能力不匹配: 期望 {expected}，实际 {actual}",
                tuple(evidence),
            )
        if envelope.version != spec.envelope.version:
            return CheckResult(
                _NAME,
                Status.FAIL,
                f"{envelope.id} 版本不匹配: 期望 {spec.envelope.version}，实际 {envelope.version}",
                tuple(evidence),
            )
        if not declared:
            problem = _least_privilege_problem(envelope)
            if problem:
                return CheckResult(_NAME, Status.FAIL, problem, tuple(evidence))
            evidence.append(
                f"{envelope.id} 未声明能力 → 下游授权集合=[]（最小权限，而非全允许）"
            )

    return CheckResult(
        _NAME,
        Status.PASS,
        f"{len(specs)} 个 fixture 均由运行时发现并列出能力"
        f"（{len(discovery.envelopes)} 个 envelope）",
        tuple(evidence),
    )


def _least_privilege_problem(envelope: PluginEnvelope) -> str:
    """Return why an undeclared-capability envelope is not least privilege."""

    if envelope.capabilities:
        values = [capability.value for capability in envelope.capabilities]
        return f"{envelope.id} 清单未声明能力，但 envelope 出现了能力 {values}"
    if envelope.metadata.get("capabilities_declared") is not False:
        return f"{envelope.id} 清单未声明能力，但 envelope 未标记 capabilities_declared=False"
    granted = {capability.value for capability in envelope.capabilities}
    inferred = {str(item) for item in (envelope.metadata.get("inferred_capabilities") or [])}
    leaked = sorted(granted & inferred)
    if leaked:
        return f"{envelope.id} 推断能力 {leaked} 被当成已授予能力"
    return ""


def _describe_spec(spec: fixture_specs.FixtureSpec) -> str:
    capabilities = ", ".join(capability.value for capability in spec.envelope.capabilities)
    declared = bool(spec.envelope.metadata.get("capabilities_declared", capabilities))
    return (
        f"fixture {spec.envelope.id} v{spec.envelope.version} "
        f"清单={spec.manifest_path.name} 能力=[{capabilities}] "
        f"（{'已声明' if declared else '未声明'}）"
    )
