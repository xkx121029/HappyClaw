"""Rerunnable acceptance entry point for the DSH integration scaffold.

Run from the repository root::

    .venv\\Scripts\\python.exe -m tests.dsh_integration.run_smoke

Exit codes: ``0`` all checks passed, ``1`` at least one check failed, ``2`` no
failures but at least one piece is not implemented yet.
"""

from __future__ import annotations

import argparse
import os
import platform
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    __package__ = "tests.dsh_integration"

from . import runtime_probe, smoke_conflict, smoke_plugins, smoke_tool
from .report import CheckResult, Report, Status

_SMOKES = (smoke_plugins, smoke_tool, smoke_conflict)
_EXIT_LABELS = {
    0: "全部通过",
    1: "存在失败项",
    2: "无失败项，但存在未实现项（未计为通过）",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="DSH 整合验收脚手架：三态输出，未实现不视为通过。",
    )
    parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[2]
    _print_header(repo_root)

    report = Report()
    for module in _SMOKES:
        report.add(_run_smoke(module))

    print("-" * 72)
    for result in report.results:
        for line in result.render():
            print(line)

    counts = report.counts()
    exit_code = report.exit_code()
    print("-" * 72)
    print(
        "汇总: 通过 {pass} / 失败 {fail} / 未实现 {todo}".format(
            **{
                "pass": counts[Status.PASS],
                "fail": counts[Status.FAIL],
                "todo": counts[Status.UNIMPLEMENTED],
            }
        )
    )
    print(f"结论: {_EXIT_LABELS[exit_code]}")
    return exit_code


def _run_smoke(module: Any) -> CheckResult:
    try:
        return module.run()
    except Exception as exc:  # noqa: BLE001 - a broken scaffold must not crash the run
        return CheckResult(
            getattr(module, "_NAME", module.__name__),
            Status.FAIL,
            f"脚手架自身异常: {type(exc).__name__}: {exc}",
        )


def _print_header(repo_root: Path) -> None:
    override = os.environ.get(runtime_probe.ENV_OVERRIDE, "").strip()
    print("DSH 整合验收脚手架（只调用运行时，不修补模块）")
    print(f"仓库: {repo_root}")
    print(f"解释器: {sys.executable} ({platform.python_version()})")
    print(f"运行时覆盖: {override or '未设置（扫描 happyclaw.infra.plugins.runtime）'}")
    print("-" * 72)


if __name__ == "__main__":
    raise SystemExit(main())
