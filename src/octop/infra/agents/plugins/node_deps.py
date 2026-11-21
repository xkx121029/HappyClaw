"""Node version checks, dependency install and entry probing."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from octop.infra.agents.plugins.constants import (
    DSH_DEP_INSTALL_TIMEOUT_SECONDS,
    DSH_PROBE_TIMEOUT_SECONDS,
)
from octop.infra.utils.json_file import (
    JsonFileCorruptError,
    read_json_object,
)

_DEP_NETWORK_RE = re.compile(
    r"EAI_AGAIN|ENOTFOUND|ETIMEDOUT|ECONNRESET|ECONNREFUSED|ENETUNREACH|"
    r"socket hang up|network|proxy|request failed|fetch failed",
    re.IGNORECASE,
)

_DEP_PERMISSION_RE = re.compile(
    r"EACCES|EPERM|permission denied|operation not permitted|access is denied",
    re.IGNORECASE,
)

_DEP_RESOLVE_RE = re.compile(
    r"ERESOLVE|ETARGET|notarget|404 Not Found|No matching version|"
    r"peer dep|Could not resolve",
    re.IGNORECASE,
)

_MODULE_NOT_FOUND_RE = re.compile(r"Cannot find package '([^']+)'|Cannot find module '([^']+)'")

_PROBE_SOURCE = r"""
const req = JSON.parse(process.argv[1]);
const done = (value) => {
  console.log("DSH_PROBE_RESULT:" + JSON.stringify(value));
  process.exit(0);
};
let mod;
try {
  mod = await import(req.entryUrl);
} catch (error) {
  done({ ok: false, code: "import_failed", message: String(error && error.stack || error) });
}
done({
  ok: true,
  name: mod.name || (mod.default && mod.default.name) || null,
  exports: Object.keys(mod).slice(0, 24),
});
"""


def _node_dependency_gaps(slot: Path, package: dict[str, Any]) -> list[str]:
    """Direct npm dependencies that have no ``node_modules`` entry.

    Deliberately shallow: the market only unpacks tarballs and never runs
    ``npm install``, so a missing direct dependency is already enough to say
    the bundle will not load. Transitive gaps are out of scope and reported as
    such by the caller.
    """

    dependencies = package.get("dependencies")
    if not isinstance(dependencies, dict) or not dependencies:
        return []
    node_modules = slot / "node_modules"
    missing: list[str] = []
    for name in sorted(dependencies):
        if not isinstance(name, str) or not name:
            continue
        if not (node_modules / name).exists():
            missing.append(name)
    return missing


def _node_version_tuple(raw: str) -> tuple[int, ...] | None:
    text = raw.strip().lstrip("v")
    parts: list[int] = []
    for chunk in text.split("."):
        digits = ""
        for char in chunk:
            if not char.isdigit():
                break
            digits += char
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts) if parts else None


def _node_range_satisfied(host: str, constraint: str) -> bool | None:
    """Minimal ``engines.node`` check; ``None`` means "cannot tell".

    Supports space-separated comparators joined by ``||``. Unparseable ranges
    return ``None`` so the UI reports "unknown" instead of inventing a failure.
    """

    host_parts = _node_version_tuple(host)
    if host_parts is None:
        return None
    saw_clause = False
    for alternative in constraint.split("||"):
        clauses = alternative.strip().split()
        if not clauses:
            continue
        ok = True
        parsed_any = False
        for clause in clauses:
            for operator in (">=", "<=", ">", "<", "="):
                if clause.startswith(operator):
                    target = _node_version_tuple(clause[len(operator) :])
                    if target is None:
                        return None
                    parsed_any = True
                    width = max(len(host_parts), len(target))
                    left = host_parts + (0,) * (width - len(host_parts))
                    right = target + (0,) * (width - len(target))
                    if operator == ">=":
                        ok = ok and left >= right
                    elif operator == "<=":
                        ok = ok and left <= right
                    elif operator == ">":
                        ok = ok and left > right
                    elif operator == "<":
                        ok = ok and left < right
                    else:
                        ok = ok and left == right
                    break
            else:
                target = _node_version_tuple(clause)
                if target is None:
                    return None
                parsed_any = True
                width = max(len(host_parts), len(target))
                left = host_parts + (0,) * (width - len(host_parts))
                right = target + (0,) * (width - len(target))
                ok = ok and left == right
        if not parsed_any:
            return None
        saw_clause = True
        if ok:
            return True
    return False if saw_clause else None


def _node_engine_problem(package: dict[str, Any]) -> str | None:
    engines = package.get("engines")
    if not isinstance(engines, dict):
        return None
    constraint = engines.get("node")
    if not isinstance(constraint, str) or not constraint.strip():
        return None
    from octop.infra.dsh.tools.runtime import host_node_version

    host = host_node_version()
    if not host:
        return None
    satisfied = _node_range_satisfied(host, constraint)
    if satisfied is False:
        return f"宿主 Node {host} 不满足 engines.node {constraint.strip()}"
    return None


def _classify_dependency_failure(output: str) -> tuple[str, str]:
    """Map package-manager output to a stable code and a coarse cause."""

    if _DEP_PERMISSION_RE.search(output):
        return "DSH_DEP_PERMISSION", "permission"
    if _DEP_NETWORK_RE.search(output):
        return "DSH_DEP_NETWORK", "network"
    if _DEP_RESOLVE_RE.search(output):
        return "DSH_DEP_RESOLVE", "resolve"
    return "DSH_DEP_INSTALL_FAILED", "unknown"


def _install_dsh_dependencies(
    slot: Path,
    package: dict[str, Any],
    *,
    on_output: Any = None,
) -> dict[str, Any]:
    """Install the bundle's npm dependency closure inside its slot.

    The market pipeline only unpacks a tarball, so a bundle that declares
    ``dependencies`` fails at import time until those packages exist. This runs
    the real package manager in the slot so the closure lands next to the code.

    Failure is a report, not an exception: the files are installed either way,
    and the caller needs to tell "依赖装不上" from "装上了但运行时不可用".
    """

    dependencies = package.get("dependencies") if isinstance(package, dict) else None
    if not isinstance(dependencies, dict) or not dependencies:
        return {
            "status": "skipped",
            "manager": None,
            "missing": [],
            "code": None,
            "cause": None,
            "message": "package.json 未声明 dependencies",
            "output_tail": "",
            "duration_ms": 0,
        }

    missing = _node_dependency_gaps(slot, package)
    if (slot / "node_modules").is_dir() and not missing:
        return {
            "status": "present",
            "manager": None,
            "missing": [],
            "code": None,
            "cause": None,
            "message": "依赖闭包已存在",
            "output_tail": "",
            "duration_ms": 0,
        }

    manager_path = shutil.which("pnpm") or shutil.which("npm")
    if not manager_path:
        return {
            "status": "failed",
            "manager": None,
            "missing": missing,
            "code": "DSH_DEP_TOOL_MISSING",
            "cause": "tool",
            "message": "找不到 pnpm 或 npm，无法安装依赖闭包",
            "output_tail": "",
            "duration_ms": 0,
        }
    manager = "pnpm" if Path(manager_path).name.lower().startswith("pnpm") else "npm"
    if manager == "pnpm":
        argv = [manager_path, "install", "--prod", "--reporter=append-only"]
    else:
        argv = [
            manager_path,
            "install",
            "--omit=dev",
            "--no-audit",
            "--no-fund",
            "--loglevel=error",
        ]
    if os.name == "nt" and manager_path.lower().endswith((".cmd", ".bat")):
        argv = ["cmd.exe", "/c", *argv]

    environment = os.environ.copy()
    environment.update({"NO_COLOR": "1", "npm_config_audit": "false"})
    # The catalog may point at an npm mirror; the closure must come from the
    # same place, otherwise a fixture or an air-gapped mirror silently reaches
    # the public registry.
    registry = os.environ.get("OCTOP_DSH_NPM_REGISTRY", "").strip()
    if registry:
        environment["npm_config_registry"] = registry
    started = time.monotonic()
    output: list[str] = []
    timed_out = False
    try:
        process = subprocess.Popen(  # noqa: S603 - fixed argv, user-initiated install
            argv,
            cwd=str(slot),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
        )
    except OSError as exc:
        return {
            "status": "failed",
            "manager": manager,
            "missing": missing,
            "code": "DSH_DEP_TOOL_MISSING",
            "cause": "tool",
            "message": f"无法启动 {manager}：{exc}",
            "output_tail": "",
            "duration_ms": round((time.monotonic() - started) * 1000, 1),
        }

    def pump() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            text = line.strip()
            if not text:
                continue
            output.append(text[-400:])
            del output[:-40]
            if on_output is not None:
                on_output(text)

    reader = threading.Thread(target=pump, daemon=True, name="dsh-deps-output")
    reader.start()
    try:
        returncode = process.wait(timeout=DSH_DEP_INSTALL_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        returncode = -1
    reader.join(timeout=5)
    duration_ms = round((time.monotonic() - started) * 1000, 1)
    tail = "\n".join(output[-10:])

    if timed_out:
        return {
            "status": "failed",
            "manager": manager,
            "missing": missing,
            "code": "DSH_DEP_NETWORK",
            "cause": "network",
            "message": f"依赖安装在 {DSH_DEP_INSTALL_TIMEOUT_SECONDS:.0f}s 内未完成",
            "output_tail": tail,
            "duration_ms": duration_ms,
        }
    if returncode != 0:
        code, cause = _classify_dependency_failure("\n".join(output))
        return {
            "status": "failed",
            "manager": manager,
            "missing": missing,
            "code": code,
            "cause": cause,
            "message": f"{manager} install 失败（退出码 {returncode}）",
            "output_tail": tail,
            "duration_ms": duration_ms,
        }

    try:
        updated = read_json_object(slot / "package.json") or package
    except JsonFileCorruptError:
        updated = package
    still_missing = _node_dependency_gaps(slot, updated)
    if still_missing:
        return {
            "status": "failed",
            "manager": manager,
            "missing": still_missing,
            "code": "DSH_DEP_MISSING",
            "cause": "resolve",
            "message": "依赖安装完成，但 node_modules 仍缺少声明的包",
            "output_tail": tail,
            "duration_ms": duration_ms,
        }
    return {
        "status": "installed",
        "manager": manager,
        "missing": [],
        "code": None,
        "cause": None,
        "message": "依赖闭包已安装",
        "output_tail": tail,
        "duration_ms": duration_ms,
    }


def _probe_dsh_entry(slot: Path, entry: str) -> dict[str, Any]:
    """Load the bundle's entry in a Node child process.

    Static checks cannot prove the code runs: a missing transitive package or a
    broken build only shows up when Node resolves the module. This probe is
    what turns "文件装好了" into "运行时真的能加载".
    """

    started = time.monotonic()
    node = shutil.which("node")
    if not node:
        return {
            "attempted": True,
            "ok": False,
            "code": "TOOL_RUNTIME_ENGINE_UNSATISFIED",
            "message": "找不到 node 可执行文件",
            "missing": [],
            "duration_ms": 0,
        }
    entry_path = (slot / entry).resolve()
    request = json.dumps({"entryUrl": entry_path.as_uri()})
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, user-initiated install
            [node, "--input-type=module", "-e", _PROBE_SOURCE, request],
            cwd=str(slot),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=DSH_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "attempted": True,
            "ok": False,
            "code": "TOOL_RUNTIME_FAILED",
            "message": f"入口探针在 {DSH_PROBE_TIMEOUT_SECONDS:.0f}s 内未完成",
            "missing": [],
            "duration_ms": round((time.monotonic() - started) * 1000, 1),
        }
    except OSError as exc:
        return {
            "attempted": True,
            "ok": False,
            "code": "TOOL_RUNTIME_ENGINE_UNSATISFIED",
            "message": f"无法启动 node：{exc}",
            "missing": [],
            "duration_ms": round((time.monotonic() - started) * 1000, 1),
        }
    duration_ms = round((time.monotonic() - started) * 1000, 1)
    payload: dict[str, Any] | None = None
    for line in reversed(completed.stdout.splitlines()):
        if line.startswith("DSH_PROBE_RESULT:"):
            try:
                decoded = json.loads(line[len("DSH_PROBE_RESULT:") :])
            except json.JSONDecodeError:
                decoded = None
            if isinstance(decoded, dict):
                payload = decoded
                break
    if payload is None:
        detail = (completed.stderr or completed.stdout).strip()[:400]
        return {
            "attempted": True,
            "ok": False,
            "code": "TOOL_RUNTIME_FAILED",
            "message": "探针没有返回结果" + (f"：{detail}" if detail else ""),
            "missing": [],
            "duration_ms": duration_ms,
        }
    if payload.get("ok"):
        return {
            "attempted": True,
            "ok": True,
            "code": None,
            "message": "入口已在 Node 中实测加载成功",
            "missing": [],
            "exports": list(payload.get("exports") or []),
            "duration_ms": duration_ms,
        }
    message = str(payload.get("message") or "入口加载失败")
    match = _MODULE_NOT_FOUND_RE.search(message)
    if match:
        package = match.group(1) or match.group(2) or ""
        return {
            "attempted": True,
            "ok": False,
            "code": "DSH_DEP_MISSING",
            "message": f"入口加载失败，缺少包 {package}",
            "missing": [package] if package else [],
            "duration_ms": duration_ms,
        }
    return {
        "attempted": True,
        "ok": False,
        "code": "TOOL_RUNTIME_PLUGIN_NOT_LOADED",
        "message": message[:600],
        "missing": [],
        "duration_ms": duration_ms,
    }
