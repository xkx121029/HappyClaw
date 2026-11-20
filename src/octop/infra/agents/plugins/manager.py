"""Install, load, and expose plugins under ``~/.octop/plugins/``."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from octop_harness.plugins import (
    LoadedPlugin,
    PluginManifest,
    PluginRegistry,
    discover_plugin_dirs,
    load_plugin_dir,
    unload_plugin,
)

from octop.infra.agents.plugins.bundled import default_bundled_plugins_root
from octop.infra.agents.plugins.legacy_imports import ensure_legacy_harness_agent_alias
from octop.infra.db.repos.control_files import ControlFileRepo
from octop.infra.db.repos.settings import SettingsRepo
from octop.infra.errors import ErrorCode, OctopError, corrupt_config_error
from octop.infra.market import (
    PortalMarketError,
    get_market_plugin,
    is_market_archive_url,
    list_market_plugins,
    pick_localized,
)
from octop.infra.market.errors import local_network_error
from octop.infra.plugins.market.source import Source
from octop.infra.utils.json_file import (
    JsonFileCorruptError,
    read_json_object,
    write_json_atomic,
)

logger = logging.getLogger(__name__)

PLUGINS_ENABLED = "plugins.enabled"
PLUGINS_REVISION = "plugins.revision"

#: Plugin UI surface contract. Keep in sync with
#: ``dashboard/src/plugins/surfaces/types.ts`` and ``docs/plugin-ui-surfaces.md``.
PLUGIN_UI_API_VERSION = 1
PLUGIN_UI_SLOTS: tuple[str, ...] = (
    "home.sidebar",
    "chat.messages.top",
    "conversation.view",
    "conversation.input.left",
    "conversation.input.overlay",
    "settings.section",
)
PLUGIN_UI_DATA_DOMAINS: tuple[str, ...] = (
    "runtime.activity",
    "sessions.running",
    "plugins.installed",
    "host.context",
)
PLUGIN_UI_EVENTS: tuple[str, ...] = (
    "session.started",
    "session.updated",
    "session.ended",
)

#: Host services the compatibility layer may resolve. ``supported=False`` rows
#: keep a stable reason code instead of disappearing or failing silently.
PLUGIN_UI_HOST_SERVICES: tuple[dict[str, Any], ...] = (
    {
        "id": "jobs",
        "supported": False,
        "reason_code": "HOST_JOBS_UNSUPPORTED",
        "reason": "插件定时任务需要宿主侧常驻调度器；v1 插件只存在于浏览器运行时，关闭面板即停止",
    },
    {
        "id": "agentDefaultModel",
        "supported": True,
        "reason_code": "HOST_AGENT_DEFAULT_MODEL_READONLY",
        "reason": "只读：默认模型由宿主设置页管理",
    },
    {
        "id": "attachments",
        "supported": True,
        "reason_code": "HOST_AGENT_CONTEXT_MISSING",
        "reason": "需要当前会话的 Agent 上下文才能上传",
    },
    {
        "id": "webServer.tapIndex",
        "supported": False,
        "reason_code": "HOST_SERVER_HOOK_UNSUPPORTED",
        "reason": "v1 插件是客户端 ESM，宿主不向插件开放服务端 index.html 注入",
    },
)
PLUGIN_UI_SURFACE_REASON_SLOT = "SURFACE_SLOT_UNKNOWN"
PLUGIN_UI_SURFACE_REASON_DUPLICATE = "SURFACE_DUPLICATE_ID"

#: DSH bundles never execute HappyClaw UI code. The reason is returned instead
#: of silently pretending the plugin has a panel.
DSH_UI_SURFACE_REASON_CODE = "DSH_UI_SURFACE_UNSUPPORTED"
DSH_UI_SURFACE_REASON = "DSH 插件没有 HappyClaw 界面扩展入口，仅参与运行时"

#: ``config.json`` section holding DSH index addresses.
DSH_SOURCES_LIMIT = 20

#: Indexes verified to be reachable and to serve DSH ``format 1``. They are
#: only a starting point: once the user writes ``plugin_market.dsh_sources``
#: (including an empty list) the stored value wins and defaults never return.
DSH_DEFAULT_SOURCES: tuple[str, ...] = (
    "https://cdn.dsh.so/market/index.json",
    "https://cdn.jsdelivr.net/npm/dsh-plugin-catalog/index.json",
    "https://dshopen.org/index.json",
)

DSH_MARKET_PAGE_SIZE = 50
DSH_MARKET_MAX_PAGE_SIZE = 200
DSH_MARKET_CACHE_TTL_SECONDS = 120.0
DSH_STATUS_SCHEMA_VERSION = 1
#: Default read budget for one public index; three indexes are fetched in
#: parallel so a slow operator only costs its own budget.
DSH_INDEX_FETCH_TIMEOUT_SECONDS = 20.0
#: A large index on a slow CDN is not a broken source. The jsDelivr copy weighs
#: several megabytes and regularly needs more than the default budget, so it
#: gets its own. Values are whole-read budgets, not socket timeouts.
DSH_SOURCE_BUDGET_SECONDS: dict[str, float] = {
    "https://cdn.jsdelivr.net/npm/dsh-plugin-catalog/index.json": 45.0,
}
DSH_SOURCE_ATTEMPTS = 2
DSH_SOURCE_RETRY_BACKOFF_SECONDS = 0.8
#: Background refreshes have no request to answer, so they may wait much
#: longer than the page load: this is how a slow mirror eventually gets cached.
DSH_SOURCE_BACKGROUND_BUDGET_SECONDS = 180.0
DSH_SOURCE_FETCH_WORKERS = 4
#: How long one catalog page waits for all sources. Readers that miss it keep
#: running in the background (and fill the disk cache); the page renders the
#: sources that are ready instead of blocking on the slowest mirror.
DSH_MARKET_SNAPSHOT_DEADLINE_SECONDS = 15.0
#: Successful index bodies on disk, keyed by address. They cover a slow source
#: on the next page load instead of dropping its entries from the catalog.
DSH_INDEX_CACHE_DIRNAME = ".dsh-index-cache"
#: Dependency closure install (npm/pnpm) and the entry probe that follows it.
DSH_DEP_INSTALL_TIMEOUT_SECONDS = 600.0
DSH_PROBE_TIMEOUT_SECONDS = 30.0
DSH_PROGRESS_HISTORY = 20

_MAX_PLUGIN_ARCHIVE_BYTES = 100 * 1024 * 1024
_MAX_PLUGIN_ZIP_ENTRIES = 2_000
_MAX_PLUGIN_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
_MAX_PLUGIN_MEMBER_BYTES = 64 * 1024 * 1024
_MAX_PLUGIN_COMPRESSION_RATIO = 100.0
_DOWNLOAD_CHUNK = 64 * 1024

_GITHUB_BLOB_RE = re.compile(
    r"^https?://(?:www\.)?github\.com/"
    r"(?P<owner>[^/]+)/(?P<repo>[^/]+)/(?:blob|raw)/"
    r"(?P<ref>[^/]+)/(?P<path>.+)$",
    re.IGNORECASE,
)


_CHANNEL_FINGERPRINTS: dict[str, str] = {}


def _channel_fingerprint(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or any(
            part in {"__pycache__", ".git"} for part in path.relative_to(directory).parts
        ):
            continue
        digest.update(str(path.relative_to(directory)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def normalize_plugin_download_url(url: str) -> str:
    """Rewrite GitHub ``/blob/`` (and ``/raw/``) page URLs to raw content URLs.

    ``https://github.com/org/repo/blob/main/plugin.zip`` returns HTML, not the
    archive — that is the common cause of ``BadZipFile`` during install.
    """
    cleaned = url.strip()
    match = _GITHUB_BLOB_RE.match(cleaned)
    if match is None:
        return cleaned
    owner = match.group("owner")
    repo = match.group("repo")
    ref = match.group("ref")
    path = match.group("path").lstrip("/")
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"


def _load_plugin_dir(plugin_dir: Path, *, install_deps: bool) -> LoadedPlugin:
    """Load one plugin, accepting the pre-rename ``harness_agent`` import."""
    ensure_legacy_harness_agent_alias()
    return load_plugin_dir(plugin_dir, install_deps=install_deps)


def _market_error_payload(exc: Exception) -> dict[str, Any]:
    """Structured market failure for the UI: stable code + original details."""

    from octop.infra.plugins.market.errors import IndexFormatError

    details = dict(getattr(exc, "details", {}) or {})
    if isinstance(exc, IndexFormatError):
        code = "PLUGIN_MANIFEST_INVALID"
    else:
        raw_code = getattr(exc, "code", None)
        code = getattr(raw_code, "value", raw_code)
    return {
        "code": str(details.get("market_code") or code or "PLUGIN_MARKET_UNAVAILABLE"),
        "message": str(exc),
        "details": details,
    }


def _market_octop_error(exc: Exception) -> OctopError:
    """Wrap a market exception without losing its code, path or dependents."""

    details = dict(getattr(exc, "details", {}) or {})
    raw_code = getattr(exc, "code", None)
    code = getattr(raw_code, "value", raw_code)
    if code:
        details.setdefault("market_code", str(code))
    reason = str(exc)
    path = details.get("path")
    if path and str(path) not in reason:
        reason = f"{reason}（{path}）"
    return OctopError(ErrorCode.PLUGIN_INSTALL_FAILED, reason, details=details)


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


def _dsh_entry_matches(entry: Any, needle: str) -> bool:
    """Case-insensitive substring match over name, description and id."""

    return any(
        needle in str(value or "").casefold()
        for value in (
            getattr(entry, "name", ""),
            getattr(entry, "description", ""),
            getattr(entry, "plugin_id", ""),
        )
    )


def dsh_source_budget(url: str) -> float:
    """Whole-read budget for one index; slow operators get more time."""

    return DSH_SOURCE_BUDGET_SECONDS.get(url, DSH_INDEX_FETCH_TIMEOUT_SECONDS)


def _fetch_index_bytes(url: str, *, budget: float) -> bytes:
    """Read one index, retrying transient failures with a short backoff.

    A read that exhausted its whole budget is not retried in the foreground:
    the next attempt costs the same again, so the caller falls back to the
    cached body and refreshes it in the background instead.
    """

    from octop.infra.plugins.market.download import MAX_INDEX_BYTES, fetch_bytes
    from octop.infra.plugins.market.errors import SourceUnreachableError

    delay = DSH_SOURCE_RETRY_BACKOFF_SECONDS
    last: Exception | None = None
    for attempt in range(max(1, DSH_SOURCE_ATTEMPTS)):
        try:
            return fetch_bytes(url, limit=MAX_INDEX_BYTES, total_timeout=budget)
        except SourceUnreachableError as exc:
            last = exc
            if "timeout" in str(exc):
                break
            if attempt + 1 < DSH_SOURCE_ATTEMPTS:
                time.sleep(delay)
                delay *= 2
    assert last is not None
    raise last


def _dsh_index_cache_path(cache_dir: Path, url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return cache_dir / f"{digest}.json"


def _read_dsh_index_cache(cache_dir: Path, url: str) -> bytes | None:
    path = _dsh_index_cache_path(cache_dir, url)
    try:
        return path.read_bytes()
    except OSError:
        return None


def _write_dsh_index_cache(cache_dir: Path, url: str, body: bytes) -> None:
    path = _dsh_index_cache_path(cache_dir, url)
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{threading.get_ident()}.tmp")
        tmp.write_bytes(body)
        os.replace(tmp, path)
    except OSError as exc:  # a cache miss must never fail the read
        logger.debug("could not write DSH index cache for %s: %s", url, exc)


def _cached_dsh_index_entries(url: str, body: bytes, *, language: str) -> list[Any]:
    """Rebuild catalog rows from a cached index body."""

    from octop.infra.plugins.market import DshSource

    return DshSource(url, language=language, transport=lambda _target: body).fetch_index()


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


def _dsh_source(
    url: str,
    *,
    language: str,
    cache_dir: Path | None = None,
    budget: float | None = None,
    allow_cache: bool = False,
) -> Any:
    """Build a ``DshSource``; the npm registry is overridable for fixtures.

    ``cache_dir`` stores the raw index body of a successful read. With
    ``allow_cache`` a failed read falls back to that body, which is what keeps
    install/upgrade working while a mirror is slow; the catalog listing asks for
    live reads instead so it can report the source as ``stale``.
    """

    from octop.infra.plugins.market import DshSource
    from octop.infra.plugins.market.download import fetch_bytes

    # ``DshSource`` treats a ``Path`` as an offline file and a string as a URL,
    # so an absolute path must not be passed through as a string.
    index: str | Path = url
    if urlparse(url).scheme not in {"http", "https"}:
        index = Path(url)

    def transport(target: str) -> bytes:
        # Only the index itself gets a total budget: a public index can weigh
        # several megabytes, and one slow host must not stall a page load.
        if target != url:
            return fetch_bytes(target)
        try:
            body = _fetch_index_bytes(url, budget=budget or dsh_source_budget(url))
        except Exception:
            if not allow_cache or cache_dir is None:
                raise
            # Installing from a cached catalog beats failing because a mirror
            # is slow right now; the background refresh updates the cache.
            cached = _read_dsh_index_cache(cache_dir, url)
            if cached is None:
                raise
            logger.warning("DSH index %s unreadable; serving cached body", url)
            return cached
        if cache_dir is not None:
            _write_dsh_index_cache(cache_dir, url, body)
        return body

    registry = os.environ.get("OCTOP_DSH_NPM_REGISTRY", "").strip()
    if registry:
        return DshSource(index, language=language, npm_registry=registry, transport=transport)
    return DshSource(index, language=language, transport=transport)


class _TolerantDshSource(Source):
    """A DSH source whose read failure means "no rows", not "abort".

    ``MarketplaceIndex.fetch`` already skips a source whose rows were all
    rejected, but a transport failure escapes and aborts install/upgrade. A
    slow mirror must not block installing from a healthy one, so the failure is
    recorded here and the source simply contributes nothing.
    """

    def __init__(self, source: Any, failures: list[Exception]) -> None:
        super().__init__()
        self._source = source
        self._failures = failures
        self.source_id = source.source_id
        self.index_label = source.index_label

    @property
    def manifest_names(self) -> tuple[str, ...]:
        return tuple(self._source.manifest_names)

    def fetch_index(self) -> list[Any]:
        try:
            return list(self._source.fetch_index())
        except Exception as exc:  # one slow mirror is not a broken mirror
            self._failures.append(exc)
            return []

    def _validate_manifest(
        self,
        entry: Any,
        release: Any,
        manifest: Any,
        content_root: Path,
    ) -> str | None:
        result = self._source._validate_manifest(entry, release, manifest, content_root)
        return None if result is None else str(result)

    def install(self, entry: Any, dest: Path, *, release: Any = None) -> Any:
        return self._source.install(entry, dest, release=release)

    def verify(self, entry: Any, payload: Any, *, release: Any = None) -> None:
        self._source.verify(entry, payload, release=release)


def _read_dsh_sources(config_path: Path) -> list[str] | None:
    """Read ``plugin_market.dsh_sources`` without dropping unrelated keys.

    ``None`` means the user never configured the section, which is what lets
    :meth:`PluginManager.dsh_source_urls` fall back to the built-in indexes. An
    explicitly stored list (including ``[]``) is authoritative.
    """

    try:
        data = read_json_object(config_path)
    except JsonFileCorruptError as exc:
        raise corrupt_config_error(exc.path, exc.detail) from exc
    if not isinstance(data, dict):
        return None
    section = data.get("plugin_market")
    raw = section.get("dsh_sources") if isinstance(section, dict) else None
    if not isinstance(raw, list):
        return None
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip() and item.strip() not in out:
            out.append(item.strip())
    return out[:DSH_SOURCES_LIMIT]


def _write_dsh_sources(config_path: Path, urls: list[str]) -> None:
    """Merge ``plugin_market.dsh_sources`` into ``config.json`` atomically."""

    try:
        data = read_json_object(config_path)
    except JsonFileCorruptError as exc:
        raise corrupt_config_error(exc.path, exc.detail) from exc
    payload = dict(data or {})
    section = payload.get("plugin_market")
    merged = dict(section) if isinstance(section, dict) else {}
    merged["dsh_sources"] = list(urls)
    payload["plugin_market"] = merged
    write_json_atomic(config_path, payload)


def normalize_dsh_source(raw: str) -> str:
    """Validate one user-supplied DSH index address.

    Accepts ``http(s)://`` URLs and existing absolute local paths (offline
    fixtures). Everything else is refused with a typed error instead of being
    stored and failing later during a background refresh.
    """

    value = str(raw or "").strip()
    if not value:
        raise OctopError(
            ErrorCode.PLUGIN_MARKET_SOURCE_INVALID,
            "DSH 索引地址不能为空",
            details={"url": value},
        )
    parsed = urlparse(value)
    if parsed.scheme in ("http", "https"):
        if not parsed.netloc:
            raise OctopError(
                ErrorCode.PLUGIN_MARKET_SOURCE_INVALID,
                f"DSH 索引地址缺少主机名：{value}",
                details={"url": value},
            )
        return value
    path = Path(value).expanduser()
    if not path.is_absolute() or not path.is_file():
        raise OctopError(
            ErrorCode.PLUGIN_MARKET_SOURCE_INVALID,
            "DSH 索引地址必须是 http(s) URL 或存在的绝对文件路径",
            details={"url": value},
        )
    return str(path)


def _read_global_plugins(config_path: Path) -> dict[str, bool]:
    if not config_path.is_file():
        return {}
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    plugins = raw.get("plugins")
    if not isinstance(plugins, dict):
        return {}
    out: dict[str, bool] = {}
    for plugin_id, entry in plugins.items():
        if isinstance(entry, dict):
            out[str(plugin_id)] = bool(entry.get("enabled", True))
        else:
            out[str(plugin_id)] = True
    return out


def _write_global_plugin_enabled(config_path: Path, plugin_id: str, enabled: bool) -> None:
    """Merge ``plugins.<id>.enabled`` into ``config.json`` without dropping other keys.

    A corrupt config.json raises instead of being treated as empty: merging into
    ``{}`` and writing back destroys every other setting, including the
    ``database`` section (issue #730).
    """
    try:
        data = read_json_object(config_path)
    except JsonFileCorruptError as exc:
        raise corrupt_config_error(exc.path, exc.detail) from exc
    if data is None:
        data = {}
    plugins = data.get("plugins")
    if not isinstance(plugins, dict):
        plugins = {}
        data["plugins"] = plugins
    entry = plugins.get(plugin_id)
    if not isinstance(entry, dict):
        entry = {}
    entry["enabled"] = bool(enabled)
    plugins[plugin_id] = entry
    write_json_atomic(config_path, data)


def _assert_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise OctopError(
            ErrorCode.PLUGIN_INVALID_ARCHIVE,
            "plugin URL must be an http(s) address to a ZIP archive",
        )


def _assert_zip_magic(archive: Path) -> None:
    with archive.open("rb") as source:
        head = source.read(4)
    if len(head) < 2 or head[:2] != b"PK":
        raise OctopError(
            ErrorCode.PLUGIN_INVALID_ARCHIVE,
            "file is not a valid ZIP archive",
        )


def _archive_error(message: str) -> OctopError:
    return OctopError(ErrorCode.PLUGIN_INVALID_ARCHIVE, message)


def _validate_plugin_zip(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = zf.infolist()
    if len(infos) > _MAX_PLUGIN_ZIP_ENTRIES:
        raise _archive_error("plugin ZIP contains too many entries")

    total_uncompressed = 0
    for member in infos:
        if member.file_size < 0 or member.file_size > _MAX_PLUGIN_MEMBER_BYTES:
            raise _archive_error(f"plugin ZIP member is too large: {member.filename}")
        total_uncompressed += member.file_size
        if total_uncompressed > _MAX_PLUGIN_UNCOMPRESSED_BYTES:
            raise _archive_error("plugin ZIP expands beyond 64 MiB")
        compressed = member.compress_size or 0
        if (
            compressed > 0
            and member.file_size > 1024 * 1024
            and member.file_size / compressed > _MAX_PLUGIN_COMPRESSION_RATIO
        ):
            raise _archive_error(f"plugin ZIP compression ratio is too high: {member.filename}")
    return infos


def _download_plugin_archive(url: str, archive: Path) -> None:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
            content_length = response.headers.get("Content-Length")
            if content_length is not None:
                try:
                    if int(content_length) > _MAX_PLUGIN_ARCHIVE_BYTES:
                        raise _archive_error("plugin ZIP download exceeds the configured limit")
                except ValueError:
                    pass
            total = 0
            with archive.open("wb") as target:
                while True:
                    chunk = response.read(_DOWNLOAD_CHUNK)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > _MAX_PLUGIN_ARCHIVE_BYTES:
                        raise _archive_error("plugin ZIP download exceeds the configured limit")
                    target.write(chunk)
    except OctopError:
        raise
    except urllib.error.HTTPError as exc:
        raise OctopError(
            ErrorCode.PLUGIN_INSTALL_FAILED,
            f"download failed with HTTP {exc.code}",
            details={"reason": f"HTTP {exc.code}"},
        ) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None) or str(exc)
        raise OctopError(
            ErrorCode.PLUGIN_INSTALL_FAILED,
            f"download failed: {reason}",
            details={"reason": str(reason)},
        ) from exc
    except OSError as exc:
        raise OctopError(
            ErrorCode.PLUGIN_INSTALL_FAILED, f"download failed: {exc}", details={"reason": str(exc)}
        ) from exc


def _read_plugin_yaml(plugin_dir: Path) -> dict[str, Any]:
    raw = yaml.safe_load((plugin_dir / "plugin.yaml").read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def parse_plugin_ui_meta(plugin_dir: Path) -> dict[str, Any] | None:
    """Return ``{entry, manifest, surfaces}`` when ``plugin.yaml`` declares ``ui``.

    Missing entry file → ``None`` (treat as backend-only). Harness ignores the
    ``ui`` key; Octop surfaces it for Dashboard dynamic loading.

    ``surfaces`` is additive: legacy plugins that only declare ``entry`` keep
    working, and a bad slot is reported instead of silently mounting nowhere.
    """
    try:
        data = _read_plugin_yaml(plugin_dir)
    except Exception:
        return None
    ui = data.get("ui")
    if not isinstance(ui, dict):
        return None
    entry = str(ui.get("entry") or "ui/dist/index.js").strip()
    manifest = str(ui.get("manifest") or "ui/dist/manifest.json").strip()
    if not entry or ".." in entry.replace("\\", "/").split("/"):
        return None
    if ".." in manifest.replace("\\", "/").split("/"):
        return None
    if not (plugin_dir / entry).is_file():
        logger.warning(
            "plugin %s declares ui.entry=%s but file is missing",
            plugin_dir.name,
            entry,
        )
        return None
    return {
        "entry": entry,
        "manifest": manifest,
        "surfaces": _parse_ui_surfaces(ui.get("surfaces")),
    }


def _parse_ui_surfaces(raw: Any) -> list[dict[str, Any]]:
    """Normalize the declarative surface list; never raises."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        surface_id = str(item.get("id") or "").strip()
        if not surface_id or re.fullmatch(r"[A-Za-z0-9._-]+", surface_id) is None:
            continue
        slot = str(item.get("slot") or "").strip()
        title = str(item.get("title") or "").strip() or surface_id
        duplicate = surface_id in seen
        if not duplicate:
            seen.add(surface_id)
        supported = slot in PLUGIN_UI_SLOTS and not duplicate
        reason_code = None
        if duplicate:
            reason_code = PLUGIN_UI_SURFACE_REASON_DUPLICATE
        elif slot not in PLUGIN_UI_SLOTS:
            reason_code = PLUGIN_UI_SURFACE_REASON_SLOT
        out.append(
            {
                "id": surface_id,
                "slot": slot,
                "title": title,
                "supported": supported,
                "reason_code": reason_code,
            }
        )
    return out


_ICON_FILE_SUFFIXES = {".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif"}

# Stable catalog slugs for Dashboard grouping. Unknown values still pass through.
PLUGIN_GROUPS: frozenset[str] = frozenset(
    {
        "lifestyle",
        "news",
        "finance",
        "media",
        "fun",
        "games",
        "tools",
        "ops",
    },
)


def parse_plugin_group(plugin_dir: Path) -> str | None:
    """Optional ``group`` slug from ``plugin.yaml`` (e.g. ``lifestyle``, ``games``)."""
    try:
        data = _read_plugin_yaml(plugin_dir)
    except Exception:
        return None
    raw = data.get("group")
    if raw is None:
        return None
    group = str(raw).strip().lower().replace("_", "-")
    if not group or len(group) > 64:
        return None
    if not all(ch.isalnum() or ch == "-" for ch in group):
        return None
    return group


def parse_plugin_icon(
    plugin_dir: Path,
    *,
    asset_prefix: str | None = None,
) -> str | None:
    """Optional ``icon`` from ``plugin.yaml`` for Dashboard cards.

    Accepts emoji text, absolute ``http(s)://`` / ``/api/...`` URLs, or a
    plugin-relative image path (e.g. ``icon.svg``) resolved to
    ``/api/plugins/{id}/ui/...`` (or ``asset_prefix`` when listing the market).
    """
    try:
        data = _read_plugin_yaml(plugin_dir)
    except Exception:
        return None
    raw = data.get("icon")
    if raw is None:
        return None
    icon = str(raw).strip()
    if not icon or len(icon) > 2048:
        return None
    if icon.startswith(("http://", "https://", "/api/", "data:image/")) or icon.startswith("//"):
        return icon
    # Relative image file shipped with the plugin package.
    cleaned = icon.lstrip("/").replace("\\", "/")
    if (
        cleaned
        and ".." not in cleaned.split("/")
        and Path(cleaned).suffix.lower() in _ICON_FILE_SUFFIXES
    ):
        target = (plugin_dir / cleaned).resolve()
        try:
            target.relative_to(plugin_dir.resolve())
        except ValueError:
            return icon
        if target.is_file():
            plugin_id = str(data.get("id") or plugin_dir.name).strip() or plugin_dir.name
            prefix = (asset_prefix or f"/api/plugins/{plugin_id}/ui").rstrip("/")
            return f"{prefix}/{cleaned}"
    return icon


def parse_plugin_requires(plugin_dir: Path) -> list[str]:
    try:
        data = _read_plugin_yaml(plugin_dir)
    except Exception:
        return []
    raw = data.get("requires") or []
    if not isinstance(raw, list):
        return []
    return [str(r).strip() for r in raw if str(r).strip()]


def _read_installed_version(plugin_dir: Path) -> str | None:
    try:
        data = _read_plugin_yaml(plugin_dir)
    except Exception:
        return None
    ver = data.get("version")
    if ver is None:
        return None
    text = str(ver).strip()
    return text or None


def _read_tree(root: Path) -> list[tuple[str, bytes]]:
    payloads: list[tuple[str, bytes]] = []
    if not root.is_dir():
        return payloads
    for dirpath, _dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        for filename in filenames:
            path = current / filename
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                payloads.append((path.relative_to(root).as_posix(), path.read_bytes()))
            except OSError:
                continue
    return payloads


def _version_tuple(version: str | None) -> tuple[int, ...]:
    ver = str(version or "0").strip() or "0"
    parts: list[int] = []
    for bit in ver.split("."):
        try:
            parts.append(int(bit))
        except ValueError:
            parts.append(0)
    return tuple(parts) or (0,)


_MARKET_ASSET_SUFFIXES = frozenset({".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif"})


class PluginManager:
    def __init__(self, *, plugins_dir: Path, config_path: Path) -> None:
        self._plugins_dir = plugins_dir
        self._config_path = config_path
        self._control_files: ControlFileRepo | None = None
        self._plugin_settings: SettingsRepo | None = None
        self._plugins_dir.mkdir(parents=True, exist_ok=True)
        # Last-known tool metadata so Admin / Experts can still list tools after
        # a global disable unloads the plugin from the process registry.
        self._tool_catalog: dict[str, list[dict[str, Any]]] = {}
        self._skill_catalog: dict[str, set[str]] = {}
        # Aggregated DSH index cache: rebuilding it re-downloads every source.
        self._dsh_market_cache: dict[str, Any] | None = None
        self._dsh_market_cache_key: tuple[tuple[str, ...], str] | None = None
        self._dsh_market_cache_at = 0.0
        self._dsh_market_lock = threading.Lock()
        self._dsh_source_health: dict[str, dict[str, Any]] = {}
        self._dsh_sources_checked_at: str | None = None
        # Install progress per plugin, polled by the DSH page while a load runs.
        self._dsh_progress: dict[str, dict[str, Any]] = {}
        self._dsh_progress_lock = threading.Lock()
        self._dsh_refresh_lock = threading.Lock()
        self._dsh_refresh_inflight: set[str] = set()

    @property
    def plugins_dir(self) -> Path:
        return self._plugins_dir

    def global_enabled_map(self) -> dict[str, bool]:
        settings = self._plugin_settings
        if settings is not None:
            raw = settings.get(PLUGINS_ENABLED)
            if raw:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    data = None
                if isinstance(data, dict):
                    return {str(key): bool(value) for key, value in data.items()}
            return {}
        return _read_global_plugins(self._config_path)

    def attach_control_plane(self, files: ControlFileRepo, settings: SettingsRepo) -> None:
        """Use the shared file table as the plugin source of truth."""
        self._control_files = files
        self._plugin_settings = settings
        self._adopt_local_plugins()
        self._ensure_plugin_cache()

    def _adopt_local_plugins(self) -> None:
        """Copy this machine's plugin trees once, before the revision marker exists."""
        files = self._control_files
        settings = self._plugin_settings
        if files is None or settings is None:
            return
        if settings.get(PLUGINS_REVISION) is not None:
            return
        for child in self._plugins_dir.iterdir():
            if not child.is_dir() or child.name.startswith(".") or child.is_symlink():
                continue
            if not (child / "plugin.yaml").is_file():
                continue
            if files.has_owner(ControlFileRepo.PLUGIN, child.name):
                continue
            payloads = _read_tree(child)
            if payloads:
                files.replace_tree(ControlFileRepo.PLUGIN, child.name, payloads)
        if settings.get(PLUGINS_ENABLED) is None:
            flags = _read_global_plugins(self._config_path)
            settings.set(PLUGINS_ENABLED, json.dumps(flags, sort_keys=True))
        owners = files.owners(ControlFileRepo.PLUGIN)
        settings.set(PLUGINS_REVISION, "1" if owners else "0")

    def _set_enabled_flag(self, plugin_id: str, enabled: bool) -> None:
        settings = self._plugin_settings
        if settings is None:
            _write_global_plugin_enabled(self._config_path, plugin_id, enabled)
            return
        current = self.global_enabled_map()
        current[plugin_id] = bool(enabled)
        settings.set(PLUGINS_ENABLED, json.dumps(current, sort_keys=True))

    def _revision_marker(self) -> Path:
        return self._plugins_dir / ".control-revision"

    def _ensure_plugin_cache(self) -> None:
        files = self._control_files
        settings = self._plugin_settings
        if files is None or settings is None:
            return
        revision = settings.get(PLUGINS_REVISION) or "0"
        marker = self._revision_marker()
        try:
            current = marker.read_text(encoding="utf-8") if marker.is_file() else None
        except OSError:
            current = None
        if current == revision:
            return
        self._plugins_dir.mkdir(parents=True, exist_ok=True)
        owners = set(files.owners(ControlFileRepo.PLUGIN))
        if not owners and revision == "0":
            marker.write_text(revision, encoding="utf-8")
            return
        for child in list(self._plugins_dir.iterdir()):
            if child.name == ".control-revision" or not child.is_dir():
                continue
            if child.name not in owners:
                shutil.rmtree(child, ignore_errors=True)
        for owner in owners:
            dest = self._plugins_dir / owner
            if dest.exists():
                shutil.rmtree(dest)
            dest.mkdir(parents=True)
            for relative, content in files.list_files(ControlFileRepo.PLUGIN, owner):
                target = dest / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        marker.write_text(revision, encoding="utf-8")

    def _bump_plugin_revision(self) -> None:
        settings = self._plugin_settings
        if settings is None:
            return
        raw = settings.get(PLUGINS_REVISION) or "0"
        try:
            revision = str(int(raw) + 1)
        except ValueError:
            revision = "1"
        settings.set(PLUGINS_REVISION, revision)
        try:
            self._revision_marker().write_text(revision, encoding="utf-8")
        except OSError:
            logger.warning("failed to record plugin cache revision")

    def _persist_plugin_tree(self, plugin_id: str) -> None:
        files = self._control_files
        if files is None:
            return
        files.replace_tree(
            ControlFileRepo.PLUGIN,
            plugin_id,
            _read_tree(self._plugins_dir / plugin_id),
        )
        self._bump_plugin_revision()

    def seed_bundled(self) -> list[str]:
        """Upgrade already-installed bundled plugins when catalog versions are newer."""
        from octop.infra.agents.plugins.bundled import default_bundled_plugins_root
        from octop.infra.agents.plugins.seed import seed_bundled_plugins

        copied = seed_bundled_plugins(
            bundled_root=default_bundled_plugins_root(),
            plugins_dir=self._plugins_dir,
            config_path=self._config_path,
        )
        for plugin_id in copied:
            self._persist_plugin_tree(plugin_id)
        return copied

    def market_root(self) -> Path:
        from octop.infra.agents.plugins.bundled import default_bundled_plugins_root

        return default_bundled_plugins_root()

    def market_plugin_dir(self, plugin_id: str) -> Path | None:
        """Return a catalog plugin directory when it exists under the market root."""
        cleaned = plugin_id.strip()
        if not cleaned or ".." in cleaned or "/" in cleaned or "\\" in cleaned:
            return None
        dest = self.market_root() / cleaned
        if dest.is_dir() and (dest / "plugin.yaml").is_file():
            return dest
        return None

    # -- DSH catalog ------------------------------------------------------

    def dsh_source_urls(self) -> list[str]:
        """Configured DSH index addresses, in user order.

        Until the user saves ``plugin_market.dsh_sources`` the built-in indexes
        are used. An explicit list replaces them entirely, so removing every
        built-in source sticks across restarts.
        """

        stored = _read_dsh_sources(self._config_path)
        if stored is None:
            return list(DSH_DEFAULT_SOURCES)
        return stored

    def add_dsh_source(self, url: str) -> list[str]:
        """Persist one DSH index address; idempotent for duplicates."""

        value = normalize_dsh_source(url)
        urls = self.dsh_source_urls()
        if value in urls:
            return urls
        if len(urls) >= DSH_SOURCES_LIMIT:
            raise OctopError(
                ErrorCode.PLUGIN_MARKET_SOURCE_INVALID,
                f"最多可添加 {DSH_SOURCES_LIMIT} 条 DSH 索引源",
                details={"url": value, "limit": DSH_SOURCES_LIMIT},
            )
        urls.append(value)
        _write_dsh_sources(self._config_path, urls)
        self._invalidate_dsh_market_cache()
        return urls

    def remove_dsh_source(self, url: str) -> list[str]:
        """Drop one DSH index address; unknown values are a no-op."""

        value = str(url or "").strip()
        current = self.dsh_source_urls()
        urls = [item for item in current if item != value]
        if urls != current:
            _write_dsh_sources(self._config_path, urls)
            self._invalidate_dsh_market_cache()
        return urls

    def _invalidate_dsh_market_cache(self) -> None:
        """Forget the aggregated index after a source or install change."""

        with self._dsh_market_lock:
            self._dsh_market_cache = None
            self._dsh_market_cache_key = None
            self._dsh_market_cache_at = 0.0

    def dsh_market_root(self) -> Path:
        """Catalog install root for DSH plugins."""

        from octop.infra.plugins.market import default_market_root

        return default_market_root()

    def _dsh_index(self, *, language: str = "zh") -> tuple[Any, list[Exception]]:
        """Marketplace index over every configured source, plus read failures.

        Sources are wrapped so a slow or broken mirror contributes no rows
        instead of aborting install/upgrade. The failures come back to the
        caller, which explains a total miss in terms of the source error.
        """
        from octop.infra.plugins.market import MarketplaceIndex

        urls = self.dsh_source_urls()
        if not urls:
            raise OctopError(
                ErrorCode.PLUGIN_MARKET_SOURCE_INVALID,
                "尚未配置 DSH 索引源，请先添加一个静态 JSON 索引地址",
                details={"sources": []},
            )
        cache_dir = self._dsh_index_cache_dir()
        failures: list[Exception] = []
        index = MarketplaceIndex(
            [
                _TolerantDshSource(
                    _dsh_source(
                        url,
                        language=language,
                        cache_dir=cache_dir,
                        allow_cache=True,
                    ),
                    failures,
                )
                for url in urls
            ]
        )
        return index, failures

    def _dsh_index_cache_dir(self) -> Path:
        return self.dsh_market_root() / DSH_INDEX_CACHE_DIRNAME

    def _fetch_dsh_source(
        self, url: str, *, language: str, fetched_at: str
    ) -> tuple[list[Any] | None, dict[str, Any]]:
        """Fetch one index; failures stay on that source instead of raising.

        A timeout is not the same as a broken source: when the body was cached
        from an earlier successful read, those rows are served (``status:
        "stale"``) and a background thread refreshes the cache. Only a source
        with no usable copy at all reports ``error`` and drops its entries.
        """

        cache_dir = self._dsh_index_cache_dir()
        source = _dsh_source(url, language=language, cache_dir=cache_dir)
        started = time.monotonic()
        try:
            rows = source.fetch_index()
        except Exception as exc:  # one source must not hide the others
            elapsed_ms = round((time.monotonic() - started) * 1000, 1)
            cached_body = _read_dsh_index_cache(cache_dir, url)
            error = _market_error_payload(exc)
            slow = "timeout" in str(exc).lower()
            if cached_body is not None:
                try:
                    rows = _cached_dsh_index_entries(url, cached_body, language=language)
                except Exception:
                    rows = None
                if rows is not None:
                    self._schedule_dsh_source_refresh(url, language=language)
                    return rows, {
                        "url": url,
                        "status": "stale",
                        "error": error,
                        "entry_count": len(rows),
                        "diagnostics": "",
                        "fetched_at": fetched_at,
                        "stale": True,
                        "budget_seconds": dsh_source_budget(url),
                        "elapsed_ms": elapsed_ms,
                    }
            if slow:
                # No cache yet and the read ran out of budget: the source is
                # slow today, not broken. Warm its cache off the request path
                # and keep every other source in the catalog.
                self._schedule_dsh_source_refresh(url, language=language)
            return None, {
                "url": url,
                "status": "slow" if slow else "error",
                "error": error,
                "entry_count": 0,
                "diagnostics": "",
                "fetched_at": fetched_at,
                "stale": False,
                "budget_seconds": dsh_source_budget(url),
                "elapsed_ms": elapsed_ms,
            }
        return rows, {
            "url": url,
            "status": "ok",
            "error": None,
            "entry_count": len(rows),
            "diagnostics": source.diagnostics(),
            "fetched_at": fetched_at,
            "stale": False,
            "budget_seconds": dsh_source_budget(url),
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
        }

    def _schedule_dsh_source_refresh(self, url: str, *, language: str) -> None:
        """Refresh a slow source off the request path; never raises."""

        with self._dsh_refresh_lock:
            if url in self._dsh_refresh_inflight:
                return
            self._dsh_refresh_inflight.add(url)

        def run() -> None:
            try:
                _dsh_source(
                    url,
                    language=language,
                    cache_dir=self._dsh_index_cache_dir(),
                    budget=DSH_SOURCE_BACKGROUND_BUDGET_SECONDS,
                ).fetch_index()
            except Exception as exc:  # the visible status already carries the error
                logger.info("background DSH source refresh failed for %s: %s", url, exc)
            finally:
                with self._dsh_refresh_lock:
                    self._dsh_refresh_inflight.discard(url)

        threading.Thread(target=run, daemon=True, name="dsh-source-refresh").start()

    def _dsh_snapshot(
        self, urls: list[str], *, language: str, refresh: bool
    ) -> tuple[dict[str, Any], bool]:
        """Aggregated index (one winning entry per plugin id) plus source health.

        The snapshot is cached for a short window: three public indexes weigh
        several megabytes, and paging/searching must not re-download them on
        every keystroke. ``refresh`` forces a rebuild; source and install
        changes invalidate the cache explicitly.
        """

        from datetime import datetime, timezone

        from octop.infra.plugins.market.versions import compare_versions

        key = (tuple(urls), language)
        with self._dsh_market_lock:
            started = time.monotonic()
            if (
                not refresh
                and self._dsh_market_cache is not None
                and self._dsh_market_cache_key == key
                and started - self._dsh_market_cache_at < DSH_MARKET_CACHE_TTL_SECONDS
            ):
                return self._dsh_market_cache, True

            fetched_at = datetime.now(timezone.utc).isoformat()
            source_rows: list[dict[str, Any]] = []
            winners: dict[str, Any] = {}
            pending_urls: list[str] = []
            # Sources are independent; fetching them in parallel keeps the
            # first page bounded by the slowest operator, not their sum.
            if urls:
                from concurrent.futures import ThreadPoolExecutor, as_completed

                pool = ThreadPoolExecutor(max_workers=min(DSH_SOURCE_FETCH_WORKERS, len(urls)))
                futures = {
                    pool.submit(
                        self._fetch_dsh_source,
                        url,
                        language=language,
                        fetched_at=fetched_at,
                    ): url
                    for url in urls
                }
                results: list[tuple[list[Any] | None, dict[str, Any]]] = []
                try:
                    for future in as_completed(
                        futures, timeout=DSH_MARKET_SNAPSHOT_DEADLINE_SECONDS
                    ):
                        try:
                            results.append(future.result())
                        except Exception as exc:  # never expected; stay honest
                            url = futures[future]
                            results.append(
                                (
                                    None,
                                    {
                                        "url": url,
                                        "status": "error",
                                        "error": _market_error_payload(exc),
                                        "entry_count": 0,
                                        "diagnostics": "",
                                        "fetched_at": fetched_at,
                                        "stale": False,
                                        "budget_seconds": dsh_source_budget(url),
                                        "elapsed_ms": None,
                                    },
                                )
                            )
                except TimeoutError:
                    # A slow source must not hold the whole catalog hostage:
                    # render what is ready and let the reader finish in the
                    # background, where it fills the disk cache.
                    pending_urls = [url for future, url in futures.items() if not future.done()]
                finally:
                    pool.shutdown(wait=False)
                for url in pending_urls:
                    results.append(
                        (
                            None,
                            {
                                "url": url,
                                "status": "slow",
                                "error": {
                                    "code": "PLUGIN_SOURCE_PENDING",
                                    "message": "索引仍在读取，已转入后台并会缓存",
                                    "details": {},
                                },
                                "entry_count": 0,
                                "diagnostics": "",
                                "fetched_at": fetched_at,
                                "stale": False,
                                "budget_seconds": dsh_source_budget(url),
                                "elapsed_ms": None,
                            },
                        )
                    )
            else:
                results = []
            # ``as_completed`` yields in completion order. Health rows are
            # reported in the configured order so callers can index by
            # position instead of matching URLs.
            order = {url: index for index, url in enumerate(urls)}
            results.sort(key=lambda item: order.get(item[1]["url"], len(order)))
            for rows, health in results:
                source_rows.append(health)
                self._dsh_source_health[health["url"]] = health
                for entry in rows or []:
                    current = winners.get(entry.plugin_id)
                    if current is None:
                        winners[entry.plugin_id] = entry
                        continue
                    comparison = compare_versions(entry.version, current.version)
                    if comparison is not None and comparison > 0:
                        winners[entry.plugin_id] = entry

            self._dsh_sources_checked_at = fetched_at
            snapshot = {
                "sources": source_rows,
                "winners": winners,
                "fetched_at": fetched_at,
            }
            self._dsh_market_cache = snapshot
            self._dsh_market_cache_key = key
            self._dsh_market_cache_at = started
            return snapshot, False

    def list_dsh_market(
        self,
        language: str = "zh",
        *,
        query: str = "",
        page: int = 1,
        page_size: int = DSH_MARKET_PAGE_SIZE,
        refresh: bool = False,
    ) -> dict[str, Any]:
        """Return one page of the DSH catalog, with source health and paging.

        Filtering is a case-insensitive substring match over the plugin name,
        description and canonical id. Paging happens after filtering, so
        ``total`` always describes the query. The full index stays on the
        server: the UI only receives the rows it renders.
        """

        urls = self.dsh_source_urls()
        root = self.dsh_market_root()
        snapshot, cached = self._dsh_snapshot(urls, language=language, refresh=refresh)
        needle = str(query or "").strip().casefold()

        winners = snapshot["winners"]
        matched = [
            entry
            for _plugin_id, entry in sorted(winners.items())
            if not needle or _dsh_entry_matches(entry, needle)
        ]
        total = len(matched)
        size = max(1, min(int(page_size or DSH_MARKET_PAGE_SIZE), DSH_MARKET_MAX_PAGE_SIZE))
        current = max(1, int(page or 1))
        start = (current - 1) * size
        entries = [self._dsh_entry_row(entry, root=root) for entry in matched[start : start + size]]
        builtin = set(DSH_DEFAULT_SOURCES)
        return {
            "market_root": str(root),
            "sources": [{**row, "builtin": row["url"] in builtin} for row in snapshot["sources"]],
            "entries": entries,
            "total": total,
            "page": current,
            "page_size": size,
            "total_pages": (total + size - 1) // size,
            "query": str(query or "").strip(),
            "fetched_at": snapshot["fetched_at"],
            "cached": cached,
        }

    def _dsh_entry_row(self, entry: Any, *, root: Path) -> dict[str, Any]:
        from functools import cmp_to_key

        from octop.infra.plugins.market.versions import compare_versions

        releases = sorted(
            entry.releases,
            key=cmp_to_key(lambda left, right: compare_versions(right.version, left.version) or 0),
        )
        installed, installed_version = self._dsh_install_state(entry.plugin_id)
        runtime = self._dsh_runtime_status(entry.plugin_id)
        return {
            "plugin_id": entry.plugin_id,
            "package_name": entry.extra.get("package_name"),
            "name": entry.name,
            "description": entry.description,
            "icon": entry.icon,
            "homepage": entry.homepage,
            "tags": list(entry.tags),
            "source_url": entry.extra.get("index_url"),
            "versions": [release.version for release in releases],
            "recommended_version": entry.version,
            "installed": installed,
            "installed_version": installed_version,
            "update_available": bool(
                installed
                and installed_version
                and (compare_versions(entry.version, installed_version) or 0) > 0
            ),
            "runtime": runtime,
        }

    def _dsh_install_state(self, plugin_id: str) -> tuple[bool, str | None]:
        """Read the ledger's ``current`` version without trusting the slot."""

        native = plugin_id.split(":", 1)[1] if ":" in plugin_id else plugin_id
        ledger_path = self.dsh_market_root() / "dsh" / native / "index.json"
        try:
            ledger = read_json_object(ledger_path)
        except JsonFileCorruptError:
            return True, None
        if not isinstance(ledger, dict):
            return False, None
        current = ledger.get("current")
        if not isinstance(current, dict):
            return True, None
        return True, str(current.get("version") or "") or None

    def list_dsh_installed(self) -> dict[str, Any]:
        """Return DSH bundles installed from the market, read from disk only.

        ``list_installed`` scans ``~/.octop/plugins`` (host plugin directories),
        while DSH market installs live under ``<market_root>/dsh`` and are
        tracked by their own ledger. The installed tab therefore has to read
        that ledger directly; resolving it through the remote index would make
        an offline catalog look like an uninstalled plugin. Nothing is imported
        or executed here, and no network request is made.
        """

        from octop.infra.plugins.market import ENVELOPE_FILENAME

        root = self.dsh_market_root()
        dsh_root = root / "dsh"
        rows: list[dict[str, Any]] = []
        if not dsh_root.is_dir():
            return {"market_root": str(root), "plugins": rows}

        for plugin_root in sorted(path for path in dsh_root.iterdir() if path.is_dir()):
            plugin_id = f"dsh:{plugin_root.name}"
            row: dict[str, Any] = {
                "plugin_id": plugin_id,
                "name": plugin_root.name,
                "description": "",
                "version": None,
                "versions": [],
                "installed_at": None,
                "install_dir": None,
                "entry": None,
                "source_url": None,
                "runtime": self._dsh_runtime_status(plugin_id),
                "error": None,
            }
            try:
                ledger = read_json_object(plugin_root / "index.json")
            except JsonFileCorruptError as exc:
                row["error"] = f"安装账本无法解析：{exc.detail}"
                rows.append(row)
                continue
            if not isinstance(ledger, dict):
                row["error"] = "未找到安装账本"
                rows.append(row)
                continue

            plugin_id = str(ledger.get("plugin_id") or plugin_id)
            row["plugin_id"] = plugin_id
            records = [item for item in ledger.get("installs", []) if isinstance(item, dict)]
            row["versions"] = [
                str(item.get("version") or "") for item in records if item.get("version")
            ]
            current = ledger.get("current")
            record = current if isinstance(current, dict) else (records[-1] if records else None)
            if record is None:
                row["error"] = "安装账本没有可读的版本记录"
                rows.append(row)
                continue

            row["version"] = str(record.get("version") or "") or None
            row["installed_at"] = record.get("installed_at")
            slot = plugin_root / str(record.get("slot") or "")
            row["install_dir"] = str(slot)
            try:
                envelope = read_json_object(slot / ENVELOPE_FILENAME)
            except JsonFileCorruptError:
                envelope = None
            if isinstance(envelope, dict):
                metadata = envelope.get("metadata")
                metadata = metadata if isinstance(metadata, dict) else {}
                package = metadata.get("package")
                package = package if isinstance(package, dict) else {}
                market = metadata.get("market")
                market = market if isinstance(market, dict) else {}
                source = envelope.get("source")
                source = source if isinstance(source, dict) else {}
                row["name"] = str(
                    package.get("package_name") or metadata.get("native_id") or row["name"]
                )
                row["description"] = str(metadata.get("description") or "")
                row["entry"] = envelope.get("entry")
                row["source_url"] = (
                    str(market.get("index") or source.get("reference") or "") or None
                )
            row["runtime"] = self._dsh_runtime_status(plugin_id)
            rows.append(row)

        return {"market_root": str(root), "plugins": rows}

    def dsh_status(
        self,
        *,
        language: str = "zh",
        probe: bool = False,
        agent_manager: Any = None,
    ) -> dict[str, Any]:
        """DSH-specific status: readiness, stage switches, sources, failures.

        Stable shape (``schema_version`` 1):

        * ``runtime`` — master switch, readiness and the reason it is not
          ready. ``reason_code`` is one of ``DSH_RUNTIME_DISABLED``,
          ``DSH_NO_STAGE_ENABLED``, ``DSH_NODE_MISSING`` or null when ready.
        * ``stages`` — every DSH switch with the env var that drives it,
          whether it is configured, and whether it is effective (the master
          switch wins, except for ``skills_prompts`` which is independent).
        * ``sources`` — per-source health. ``status`` is ``ok``, ``error`` or
          ``unknown`` (never fetched); ``checked_at`` is null for unknown.
          ``probe=true`` re-fetches every index and also warms the catalog.
        * ``installed`` — market installs with the static runtime report:
          ``visible_to_agents``, ``executable``, ``error_code`` and ``reason``.
        * ``tools`` / ``llm`` — the S2 assembly and S8 wiring reports, or null
          when that stage is off (querying them would import disabled modules).
        * ``last_failure`` / ``recent_failures`` — typed load/execute failures
          observed by this process, newest first.

        Every sub-read is guarded: a broken ledger or adapter reports its own
        error field instead of failing the whole status call.
        """

        from datetime import datetime, timezone

        from octop.infra.dsh.diagnostics import latest_failure, recent_failures
        from octop.infra.dsh.integration import (
            DSH_SKILLS_PROMPTS_ENV,
            dsh_skills_prompts_enabled,
        )
        from octop.infra.dsh.switches import (
            llm_enabled,
            runtime_enabled,
            shadow_enabled,
            stage_enabled,
        )

        truthy = {"1", "true", "yes", "on"}

        def configured(env: str) -> bool:
            return os.environ.get(env, "").strip().lower() in truthy

        master = runtime_enabled()
        stage_defs = (
            ("tools", "OCTOP_DSH_TOOLS", stage_enabled("tools")),
            ("hitl", "OCTOP_DSH_HITL", stage_enabled("hitl")),
            ("exec", "OCTOP_DSH_EXEC", stage_enabled("exec")),
            ("shadow", "OCTOP_DSH_SHADOW", shadow_enabled()),
            ("llm", "OCTOP_DSH_LLM", llm_enabled()),
            ("skills_prompts", DSH_SKILLS_PROMPTS_ENV, dsh_skills_prompts_enabled()),
        )
        stages = [
            {
                "name": name,
                "env": env,
                "configured": configured(env),
                "effective": bool(effective),
                "gated_by_master": name != "skills_prompts",
            }
            for name, env, effective in stage_defs
        ]

        exec_on = stage_enabled("exec")
        node: dict[str, Any] = {
            "required": exec_on,
            "available": None,
            "version": None,
        }
        if exec_on:
            from octop.infra.dsh.tools.runtime import host_node_version  # noqa: PLC0415

            version = host_node_version()
            node = {
                "required": True,
                "available": bool(version),
                "version": version,
            }

        ready = master and any(
            stage["effective"] and stage["name"] != "skills_prompts" for stage in stages
        )
        reason_code: str | None = None
        reason = ""
        if not master:
            reason_code = "DSH_RUNTIME_DISABLED"
            reason = "未开启 OCTOP_DSH_RUNTIME，DSH 运行时整体关闭"
        elif not ready:
            reason_code = "DSH_NO_STAGE_ENABLED"
            reason = "未开启任何 DSH 阶段开关（tools / hitl / exec / shadow / llm）"
        elif node["required"] and not node["available"]:
            ready = False
            reason_code = "DSH_NODE_MISSING"
            reason = "OCTOP_DSH_EXEC 已开启，但找不到可用的 Node 可执行文件"

        urls = self.dsh_source_urls()
        if probe:
            snapshot, _ = self._dsh_snapshot(urls, language=language, refresh=True)
            source_rows = snapshot["sources"]
        else:
            source_rows = []
            for url in urls:
                cached_row = self._dsh_source_health.get(url)
                source_rows.append(
                    cached_row
                    if cached_row is not None
                    else {
                        "url": url,
                        "status": "unknown",
                        "error": None,
                        "entry_count": 0,
                        "diagnostics": "",
                        "fetched_at": None,
                    }
                )
        builtin = set(DSH_DEFAULT_SOURCES)
        source_items = [
            {
                "url": row["url"],
                "builtin": row["url"] in builtin,
                "status": row["status"],
                "entry_count": int(row.get("entry_count") or 0),
                "error": row.get("error"),
                "diagnostics": str(row.get("diagnostics") or ""),
                "checked_at": row.get("fetched_at"),
                "stale": bool(row.get("stale")),
                "budget_seconds": row.get("budget_seconds"),
                "elapsed_ms": row.get("elapsed_ms"),
            }
            for row in source_rows
        ]

        installed: list[dict[str, Any]] = []
        install_error: str | None = None
        try:
            for row in self.list_dsh_installed()["plugins"]:
                runtime = row.get("runtime") or {}
                installed.append(
                    {
                        "plugin_id": row["plugin_id"],
                        "version": row.get("version"),
                        "install_dir": row.get("install_dir"),
                        "status": runtime.get("status", "missing"),
                        "visible_to_agents": bool(runtime.get("visible_to_agents")),
                        "executable": bool(runtime.get("executable")),
                        "error_code": runtime.get("error_code"),
                        "reason": str(runtime.get("reason") or ""),
                        "notes": list(runtime.get("notes") or []),
                        "probe": runtime.get("probe"),
                        "ledger_error": row.get("error"),
                    }
                )
        except Exception as exc:  # status must survive one broken install root
            install_error = str(exc)

        tools_on = stage_enabled("tools")
        tools_report: dict[str, Any] | None = None
        tools_error: str | None = None
        if agent_manager is not None and tools_on:
            try:
                tools_report = agent_manager.dsh_tools_status()
            except Exception as exc:
                tools_error = str(exc)

        llm_on = llm_enabled()
        llm_installation: dict[str, Any] | None = None
        llm_error: str | None = None
        if agent_manager is not None and llm_on:
            try:
                llm_installation = agent_manager.dsh_llm_status()
            except Exception as exc:
                llm_error = str(exc)

        return {
            "schema_version": DSH_STATUS_SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "runtime": {
                "enabled": master,
                "ready": ready,
                "reason_code": reason_code,
                "reason": reason,
                "node": node,
            },
            "stages": stages,
            "sources": {
                "checked_at": self._dsh_sources_checked_at,
                "probed": bool(probe),
                "items": source_items,
            },
            "installed": installed,
            "installed_error": install_error,
            "tools": {
                "stage_enabled": tools_on,
                "report": tools_report,
                "error": tools_error,
            },
            "llm": {
                "stage_enabled": llm_on,
                "installation": llm_installation,
                "error": llm_error,
            },
            "last_failure": latest_failure(),
            "recent_failures": recent_failures(10),
        }

    def _dsh_runtime_status(self, plugin_id: str, *, probe: bool = False) -> dict[str, Any]:
        """Readiness report for one installed DSH bundle.

        Static checks mirror the failures the S10 runtime would raise. With
        ``probe=True`` the entry is additionally loaded in a Node child
        process, which is the only way to prove the dependency closure and the
        build actually work; page rendering keeps ``probe=False`` so listing
        the catalog stays local.
        """

        native = plugin_id.split(":", 1)[1] if ":" in plugin_id else plugin_id
        root = self.dsh_market_root()
        plugin_root = root / "dsh" / native
        status: dict[str, Any] = {
            "status": "missing",
            "visible_to_agents": False,
            "executable": False,
            "error_code": None,
            "reason": "",
            "notes": [],
            "probe": {"attempted": False, "ok": False, "code": None, "message": ""},
            # DSH has no HappyClaw UI surface contract; say so explicitly so
            # the UI can distinguish "not supported" from "broken".
            "surface_supported": False,
            "surface_reason_code": DSH_UI_SURFACE_REASON_CODE,
            "surface_reason": DSH_UI_SURFACE_REASON,
        }
        ledger_path = plugin_root / "index.json"
        if not ledger_path.is_file():
            return status
        try:
            ledger = read_json_object(ledger_path)
        except JsonFileCorruptError as exc:
            status.update(
                status="broken",
                error_code="TOOL_RUNTIME_PLUGIN_NOT_LOADED",
                reason=f"安装账本无法解析：{ledger_path}（{exc.detail}）",
            )
            return status
        if isinstance(ledger, dict) and isinstance(ledger.get("current"), dict):
            current = ledger["current"]
        else:
            status.update(
                status="broken",
                error_code="TOOL_RUNTIME_PLUGIN_NOT_LOADED",
                reason=f"未找到可读的当前版本记录：{ledger_path}",
            )
            return status

        slot_name = str(current.get("slot") or "")
        slot = plugin_root / slot_name
        if not slot_name or not slot.is_dir():
            status.update(
                status="broken",
                error_code="TOOL_RUNTIME_PLUGIN_NOT_LOADED",
                reason=f"账本指向的安装目录不存在：{slot}",
            )
            return status

        try:
            package = read_json_object(slot / "package.json") or {}
        except JsonFileCorruptError as exc:
            status.update(
                status="broken",
                error_code="TOOL_RUNTIME_PLUGIN_NOT_LOADED",
                reason=f"package.json 无法解析：{slot / 'package.json'}（{exc.detail}）",
            )
            return status

        missing = _node_dependency_gaps(slot, package)
        if missing:
            status.update(
                status="not_loaded",
                error_code="DSH_DEP_MISSING",
                reason=(
                    "缺少 npm 依赖闭包："
                    + "、".join(missing)
                    + "；在 DSH 页重新装载会执行 pnpm/npm install 补齐"
                ),
                notes=["静态检查仅覆盖 package.json 中的直接 dependencies"],
            )
            return status

        entry_path = str(package.get("main") or "index.js").strip() or "index.js"
        if not (slot / entry_path).is_file():
            status.update(
                status="not_loaded",
                error_code="TOOL_RUNTIME_ENTRY_MISSING",
                reason=f"入口文件不存在：{entry_path}",
            )
            return status

        engine_error = _node_engine_problem(package)
        if engine_error:
            status.update(
                status="not_loaded",
                error_code="TOOL_RUNTIME_ENGINE_UNSATISFIED",
                reason=engine_error,
            )
            return status

        from octop.infra.dsh.tools.discovery import discover_dsh_plugins
        from octop.infra.dsh.tools.runtime import resolve_exec_plugins

        grants = {pid: "host exec grant" for pid in resolve_exec_plugins()}
        candidates, skipped = discover_dsh_plugins(
            market_root=root,
            local_roots=(),
            granted=grants,
        )
        if any(candidate.plugin_id == plugin_id for candidate in candidates):
            status.update(
                status="visible",
                visible_to_agents=True,
                executable=True,
                reason="已对 Agent 可见；未做运行时探针",
            )
            if probe:
                result = _probe_dsh_entry(slot, entry_path)
                status["probe"] = result
                if result["ok"]:
                    status.update(reason="已对 Agent 可见，且入口已在 Node 中实测加载成功")
                else:
                    status.update(
                        status="not_loaded",
                        executable=False,
                        error_code=result.get("code") or "TOOL_RUNTIME_PLUGIN_NOT_LOADED",
                        reason=str(result.get("message") or "入口探针失败"),
                    )
            return status

        record = next((item for item in skipped if item.plugin_id == plugin_id), None)
        if record is None:
            status.update(
                status="not_visible",
                error_code="TOOL_CAPABILITY_UNAVAILABLE",
                reason="宿主未授予 exec（OCTOP_DSH_EXEC_PLUGINS 不含该插件）",
            )
            return status
        code = (
            "TOOL_CAPABILITY_UNAVAILABLE"
            if record.reason
            in {
                "unsafe_permission",
                "not_tool_capability",
                "duplicate_plugin_id",
            }
            else "TOOL_RUNTIME_PLUGIN_NOT_LOADED"
        )
        status.update(
            status="not_visible",
            error_code=code,
            reason=record.detail or record.reason,
            notes=[f"skip_reason={record.reason}"],
        )
        return status

    # -- install progress --------------------------------------------------

    def _dsh_progress_start(self, plugin_id: str, *, action: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._dsh_progress_lock:
            self._dsh_progress[plugin_id] = {
                "plugin_id": plugin_id,
                "action": action,
                "phase": "download",
                "status": "running",
                "progress": 0.05,
                "message": "正在下载并解包发布包",
                "detail": "",
                "error_code": None,
                "started_at": now,
                "updated_at": now,
                "finished_at": None,
            }
            self._prune_dsh_progress_locked()

    def _prune_dsh_progress_locked(self) -> None:
        overflow = len(self._dsh_progress) - DSH_PROGRESS_HISTORY
        if overflow <= 0:
            return
        finished = sorted(
            (
                (key, record["finished_at"])
                for key, record in self._dsh_progress.items()
                if record.get("finished_at")
            ),
            key=lambda item: item[1],
        )
        for key, _finished_at in finished[:overflow]:
            self._dsh_progress.pop(key, None)

    def _dsh_progress_update(self, plugin_id: str, **fields: Any) -> None:
        with self._dsh_progress_lock:
            record = self._dsh_progress.get(plugin_id)
            if record is None:
                return
            record.update(fields)
            record["updated_at"] = datetime.now(timezone.utc).isoformat()

    def _dsh_progress_finish(
        self, plugin_id: str, *, status: str, error_code: str | None = None
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._dsh_progress_lock:
            record = self._dsh_progress.get(plugin_id)
            if record is None:
                return
            record.update(
                phase="done",
                status=status,
                progress=1.0,
                error_code=error_code,
                updated_at=now,
                finished_at=now,
            )

    def dsh_install_progress(self, plugin_id: str) -> dict[str, Any]:
        """Last known load progress for one plugin (``__missing__`` is null).

        Returned separately from the install response so the page can show a
        phase while the install request itself is still running.
        """

        with self._dsh_progress_lock:
            record = self._dsh_progress.get(plugin_id)
            return {
                "plugin_id": plugin_id,
                "progress": dict(record) if record is not None else None,
            }

    def _dsh_install_dependencies(self, plugin_id: str, install_dir: Path) -> dict[str, Any]:
        """Run the dependency install for one slot and stream its progress."""

        try:
            package = read_json_object(install_dir / "package.json") or {}
        except JsonFileCorruptError as exc:
            return {
                "status": "failed",
                "manager": None,
                "missing": [],
                "code": "DSH_DEP_RESOLVE",
                "cause": "resolve",
                "message": f"package.json 无法解析：{exc.detail}",
                "output_tail": "",
                "duration_ms": 0,
            }
        self._dsh_progress_update(
            plugin_id,
            phase="dependencies",
            progress=0.45,
            message="正在安装依赖闭包（pnpm/npm）",
        )

        def on_output(line: str) -> None:
            self._dsh_progress_update(plugin_id, detail=line[:300], progress=0.6)

        report = _install_dsh_dependencies(install_dir, package, on_output=on_output)
        self._dsh_progress_update(
            plugin_id,
            detail=report["message"],
            progress=0.8,
            error_code=report.get("code"),
        )
        return report

    def install_dsh_market(
        self,
        plugin_id: str,
        *,
        version: str | None = None,
        force: bool = False,
        language: str = "zh",
    ) -> dict[str, Any]:
        """Install one DSH release, then its dependency closure and a probe.

        The market pipeline only unpacks the tarball. A bundle that declares
        npm dependencies is therefore loaded-but-broken unless the closure is
        installed here. Dependency failure is reported, not raised: the files
        did install, and the UI distinguishes "依赖装不上" from "装上了但运行时
        不可用".
        """

        self._dsh_progress_start(plugin_id, action="install")
        index, source_failures = self._dsh_index(language=language)
        if not index.fetch() and source_failures:
            self._dsh_progress_finish(
                plugin_id,
                status="failed",
                error_code=_market_error_payload(source_failures[0])["code"],
            )
            raise _market_octop_error(source_failures[0]) from source_failures[0]
        try:
            result = index.install(
                plugin_id,
                self.dsh_market_root(),
                version=version,
                force=force,
            )
        except Exception as exc:
            # "not listed" is misleading when a source was simply unreachable:
            # report the read failure so the UI can say the source is down
            # instead of claiming the plugin does not exist.
            failure = exc
            if source_failures and "is not listed" in str(exc):
                failure = source_failures[0]
            self._dsh_progress_finish(
                plugin_id,
                status="failed",
                error_code=_market_error_payload(failure)["code"],
            )
            self._dsh_progress_update(plugin_id, detail=str(failure)[:400])
            raise _market_octop_error(failure) from failure

        dependency = self._dsh_install_dependencies(plugin_id, result.install_dir)
        self._dsh_progress_update(
            plugin_id, phase="probe", progress=0.9, message="正在做运行时能力探针"
        )
        runtime = self._dsh_runtime_status(plugin_id, probe=True)
        if dependency["status"] == "failed":
            status = "installed_dependency_failed"
        elif runtime["status"] == "visible":
            status = "installed"
        else:
            status = "installed_not_ready"
        self._dsh_progress_finish(
            plugin_id,
            status="ok" if status == "installed" else "not_ready",
            error_code=dependency.get("code") or runtime.get("error_code"),
        )
        return {
            "plugin_id": result.plugin_id,
            "version": result.version,
            "source": result.source,
            "install_dir": str(result.install_dir),
            "status": status,
            "dependency": dependency,
            "runtime": runtime,
        }

    def upgrade_dsh_market(
        self,
        plugin_id: str,
        *,
        version: str | None = None,
        allow_capability_expansion: bool = False,
        language: str = "zh",
    ) -> dict[str, Any]:
        """Move an installed DSH plugin to another catalog version."""

        self._dsh_progress_start(plugin_id, action="upgrade")
        index, source_failures = self._dsh_index(language=language)
        if not index.fetch() and source_failures:
            self._dsh_progress_finish(
                plugin_id,
                status="failed",
                error_code=_market_error_payload(source_failures[0])["code"],
            )
            raise _market_octop_error(source_failures[0]) from source_failures[0]
        try:
            result = index.upgrade(
                plugin_id,
                self.dsh_market_root(),
                version=version,
                allow_capability_expansion=allow_capability_expansion,
            )
        except Exception as exc:
            failure = exc
            if source_failures and "is not listed" in str(exc):
                failure = source_failures[0]
            self._dsh_progress_finish(
                plugin_id,
                status="failed",
                error_code=_market_error_payload(failure)["code"],
            )
            self._dsh_progress_update(plugin_id, detail=str(failure)[:400])
            raise _market_octop_error(failure) from failure

        dependency = self._dsh_install_dependencies(plugin_id, result.install_dir)
        self._dsh_progress_update(
            plugin_id, phase="probe", progress=0.9, message="正在做运行时能力探针"
        )
        runtime = self._dsh_runtime_status(plugin_id, probe=True)
        if dependency["status"] == "failed":
            status = "upgraded_dependency_failed"
        elif runtime["status"] == "visible":
            status = "upgraded"
        else:
            status = "upgraded_not_ready"
        self._dsh_progress_finish(
            plugin_id,
            status="ok" if status == "upgraded" else "not_ready",
            error_code=dependency.get("code") or runtime.get("error_code"),
        )
        return {
            "plugin_id": result.plugin_id,
            "version": result.version,
            "previous_version": result.previous_version,
            "source": result.source,
            "install_dir": str(result.install_dir),
            "status": status,
            "dependency": dependency,
            "runtime": runtime,
        }

    def uninstall_dsh_market(
        self,
        plugin_id: str,
        *,
        version: str | None = None,
    ) -> dict[str, Any]:
        """Uninstall one DSH slot and report whether the tree is gone."""

        from octop.infra.plugins.market import uninstall as uninstall_entry

        root = self.dsh_market_root()
        try:
            result = uninstall_entry(plugin_id, root, version=version)
        except Exception as exc:
            raise _market_octop_error(exc) from exc
        native = plugin_id.split(":", 1)[1] if ":" in plugin_id else plugin_id
        plugin_root = root / "dsh" / native
        return {
            "plugin_id": result.plugin_id,
            "version": result.version,
            "install_dir": str(result.install_dir),
            "cleaned": not plugin_root.exists(),
            "remaining_versions": list(result.remaining_versions),
        }

    def list_market(self, language: str = "zh") -> list[dict[str, Any]]:
        """List marketplace plugins from the bundled catalog and the portal.

        Bundled plugins ship with the product, so they stay browsable even when
        the portal is unreachable. ``source`` tells the Dashboard which install
        endpoint to call; the remote shape keeps its old fields.
        """
        bundled = self._bundled_plugin_rows(language)
        try:
            remote = list_market_plugins()
        except PortalMarketError as exc:
            logger.warning("remote plugin market unavailable: %s", exc)
            if bundled:
                return bundled
            network_error = local_network_error(exc)
            if network_error is not None:
                raise network_error from exc
            raise OctopError(
                ErrorCode.PLUGIN_MARKET_FAILED,
                "plugin market failed: upstream request failed",
                details={"reason": "upstream request failed"},
            ) from exc
        return bundled + [self._remote_plugin_row(item, language) for item in remote]

    def _bundled_plugin_rows(self, language: str) -> list[dict[str, Any]]:
        """Describe every in-package catalog plugin, installed or not."""
        root = default_bundled_plugins_root()
        if not root.is_dir():
            return []
        rows: list[dict[str, Any]] = []
        for plugin_dir in sorted(root.iterdir(), key=lambda item: item.name):
            if not plugin_dir.is_dir() or not (plugin_dir / "plugin.yaml").is_file():
                continue
            try:
                manifest = _read_plugin_yaml(plugin_dir)
            except Exception as exc:
                logger.warning("skip bundled plugin %s: %s", plugin_dir.name, exc)
                continue
            plugin_id = str(manifest.get("id") or plugin_dir.name).strip()
            if not plugin_id:
                continue
            version = str(manifest.get("version") or "")
            installed_dir = self.plugin_dir(plugin_id)
            installed_version = (
                None if installed_dir is None else _read_installed_version(installed_dir)
            )
            ui = parse_plugin_ui_meta(plugin_dir)
            icon = manifest.get("icon")
            group = manifest.get("group")
            rows.append(
                {
                    "id": plugin_id,
                    "version": version,
                    "name": pick_localized(manifest.get("name"), language) or plugin_id,
                    "kind": str(manifest.get("kind") or "tool"),
                    "description": pick_localized(manifest.get("description"), language),
                    "icon": icon.strip() if isinstance(icon, str) and icon.strip() else None,
                    "group": (group.strip() if isinstance(group, str) and group.strip() else None),
                    "requires": [],
                    "installed": installed_dir is not None,
                    "installed_version": installed_version,
                    "update_available": (
                        installed_dir is not None
                        and _version_tuple(version) > _version_tuple(installed_version)
                    ),
                    "source": "bundled",
                    "install_kind": "bundled",
                    "ui": ui,
                }
            )
        return rows

    def install_bundled(self, plugin_id: str, *, force: bool = False) -> LoadedPlugin:
        """Install one in-package catalog plugin without touching the network."""
        cleaned = plugin_id.strip()
        if not cleaned or cleaned in {".", ".."} or "/" in cleaned or "\\" in cleaned:
            raise OctopError(ErrorCode.NOT_FOUND, f"bundled plugin {plugin_id!r} not found")
        source = default_bundled_plugins_root() / cleaned
        if not source.is_dir() or not (source / "plugin.yaml").is_file():
            raise OctopError(ErrorCode.NOT_FOUND, f"bundled plugin {plugin_id!r} not found")
        return self.install_path(source, force=force, expect_id=cleaned)

    def _remote_plugin_row(self, item: dict[str, Any], language: str) -> dict[str, Any]:
        plugin_id = str(item.get("id") or "").strip()
        version = str(item.get("version") or "")
        installed_dir = self.plugin_dir(plugin_id) if plugin_id else None
        installed_version = (
            None if installed_dir is None else _read_installed_version(installed_dir)
        )
        icon = item.get("icon")
        group = item.get("group")
        raw_requires = item.get("requires")
        requires = raw_requires if isinstance(raw_requires, list) else []
        return {
            "id": plugin_id,
            "version": version,
            "name": pick_localized(item.get("name"), language) or plugin_id,
            "kind": str(item.get("kind") or "tool"),
            "description": pick_localized(item.get("description"), language),
            "icon": icon.strip() if isinstance(icon, str) and icon.strip() else None,
            "group": group.strip() if isinstance(group, str) and group.strip() else None,
            "requires": [
                str(item_name).strip() for item_name in requires if str(item_name).strip()
            ],
            "installed": installed_dir is not None,
            "installed_version": installed_version,
            "update_available": (
                installed_dir is not None
                and _version_tuple(version) > _version_tuple(installed_version)
            ),
            "source": "portal",
            "install_kind": "archive",
        }

    def install_from_market(
        self,
        plugin_id: str,
        *,
        version: str | None = None,
        force: bool = False,
    ) -> LoadedPlugin:
        """Install one marketplace release from its CDN archive.

        ``version`` selects the catalog release. ``latest`` means the release
        currently listed for that id. A different release already on disk is
        replaced. ``force`` replaces the same release.
        """
        requested = version.strip() if version else None
        if requested == "latest":
            requested = None
        try:
            remote = get_market_plugin(plugin_id)
        except PortalMarketError as exc:
            logger.warning("remote plugin market unavailable: %s", exc)
            network_error = local_network_error(exc)
            if network_error is not None:
                raise network_error from exc
            raise OctopError(
                ErrorCode.PLUGIN_MARKET_FAILED,
                "plugin market failed: upstream request failed",
                details={"reason": "upstream request failed"},
            ) from exc
        if remote is None:
            raise OctopError(
                ErrorCode.NOT_FOUND,
                f"marketplace plugin {plugin_id!r} not found",
            )
        catalog_version = str(remote.get("version") or "")
        if requested and catalog_version != requested:
            raise OctopError(
                ErrorCode.NOT_FOUND,
                f"marketplace plugin {plugin_id!r} version {requested!r} not found",
            )
        url = remote.get("download_url")
        if not isinstance(url, str) or not is_market_archive_url(url):
            raise OctopError(
                ErrorCode.PLUGIN_INSTALL_FAILED,
                f"marketplace plugin {plugin_id!r} has no archive",
            )
        loaded = self.install_url(
            url,
            force=self._replace_market_release(
                plugin_id,
                requested or catalog_version,
                force=force,
            ),
            expect_id=plugin_id,
            expect_version=catalog_version or None,
        )
        self._set_enabled_flag(loaded.manifest.id, True)
        return loaded

    def _replace_market_release(self, plugin_id: str, version: str, *, force: bool) -> bool:
        """Replace disk contents when installing a different catalog release."""
        if force:
            return True
        installed_dir = self.plugin_dir(plugin_id)
        if installed_dir is None or not version:
            return False
        return _read_installed_version(installed_dir) != version

    def resolve_market_ui_file(self, plugin_id: str, rel_path: str) -> Path:
        """Resolve a marketplace catalog asset (icons only)."""
        plugin_dir = self.market_plugin_dir(plugin_id)
        if plugin_dir is None:
            raise OctopError(
                ErrorCode.NOT_FOUND,
                f"marketplace plugin {plugin_id!r} not found",
            )
        cleaned = rel_path.strip().lstrip("/").replace("\\", "/")
        suffix = Path(cleaned).suffix.lower()
        if suffix not in _MARKET_ASSET_SUFFIXES:
            raise OctopError(ErrorCode.NOT_FOUND, "invalid marketplace asset path")
        return self._resolve_plugin_asset(plugin_dir, cleaned)

    def load_installed(self, *, install_deps: bool = True) -> list[LoadedPlugin]:
        self._ensure_plugin_cache()
        enabled = self.global_enabled_map()
        previous = {plugin.manifest.id: plugin for plugin in PluginRegistry().all_loaded()}
        PluginRegistry().clear()
        loaded: list[LoadedPlugin] = []
        for plugin_dir in discover_plugin_dirs(self._plugins_dir):
            try:
                manifest = PluginManifest.load(plugin_dir / "plugin.yaml")
            except Exception as exc:
                logger.error("skip plugin dir %s: %s", plugin_dir, exc)
                continue
            if enabled.get(manifest.id, True) is False:
                continue
            try:
                fingerprint = (
                    _channel_fingerprint(plugin_dir) if str(manifest.kind) == "channel" else ""
                )
                old = previous.get(manifest.id)
                if (
                    str(manifest.kind) == "channel"
                    and old is not None
                    and _CHANNEL_FINGERPRINTS.get(manifest.id) == fingerprint
                ):
                    PluginRegistry().register(old)
                    loaded.append(old)
                else:
                    loaded.append(_load_plugin_dir(plugin_dir, install_deps=install_deps))
                if str(manifest.kind) == "channel":
                    _CHANNEL_FINGERPRINTS[manifest.id] = fingerprint
            except Exception as exc:
                logger.error(
                    "failed to load plugin from %s: %s",
                    plugin_dir,
                    exc,
                    exc_info=True,
                )
        for plugin_id, is_on in enabled.items():
            if not is_on:
                unload_plugin(plugin_id)
        return [p for p in loaded if enabled.get(p.manifest.id, True) is not False]

    def load_missing(self, *, install_deps: bool = False) -> list[LoadedPlugin]:
        """Load any on-disk plugins that are not yet in the process registry.

        Used after CLI ``octop plugin install`` while ``octop run`` is already
        up — unlike ``load_installed``, this does not clear already-loaded
        plugins.
        """
        self._ensure_plugin_cache()
        enabled = self.global_enabled_map()
        newly: list[LoadedPlugin] = []
        for plugin_dir in discover_plugin_dirs(self._plugins_dir):
            try:
                manifest = PluginManifest.load(plugin_dir / "plugin.yaml")
            except Exception as exc:
                logger.error("skip plugin dir %s: %s", plugin_dir, exc)
                continue
            if enabled.get(manifest.id) is False:
                continue
            if PluginRegistry().get(manifest.id) is not None:
                continue
            try:
                newly.append(_load_plugin_dir(plugin_dir, install_deps=install_deps))
                logger.info(
                    "loaded missing plugin %s v%s",
                    manifest.id,
                    manifest.version,
                )
            except Exception as exc:
                logger.error(
                    "failed to load plugin from %s: %s",
                    plugin_dir,
                    exc,
                    exc_info=True,
                )
        return newly

    @staticmethod
    def _channel_registration_error(plugin_id: str) -> str | None:
        from octop.infra.gateway.plugin_channels import registration_errors

        return registration_errors().get(plugin_id)

    def list_installed(self) -> list[dict[str, Any]]:
        self._ensure_plugin_cache()
        out: list[dict[str, Any]] = []
        enabled_map = self.global_enabled_map()
        for plugin_dir in discover_plugin_dirs(self._plugins_dir):
            try:
                manifest = PluginManifest.load(plugin_dir / "plugin.yaml")
            except Exception as exc:
                out.append(
                    {
                        "id": plugin_dir.name,
                        "error": str(exc),
                        "path": str(plugin_dir),
                        "enabled": enabled_map.get(plugin_dir.name, True),
                    },
                )
                continue
            loaded = PluginRegistry().get(manifest.id)
            ui_meta = parse_plugin_ui_meta(plugin_dir)
            if loaded is not None:
                tools_meta = [
                    {
                        "name": t.name,
                        "description": t.description,
                        "config_fields": t.config_fields,
                    }
                    for t in loaded.tools
                ]
                self._tool_catalog[manifest.id] = tools_meta
                if loaded.skills_dir is not None:
                    self._skill_catalog[manifest.id] = {
                        path.name
                        for path in loaded.skills_dir.iterdir()
                        if path.is_dir() and (path / "SKILL.md").is_file()
                    }
            else:
                tools_meta = list(self._tool_catalog.get(manifest.id) or [])
            out.append(
                {
                    "id": manifest.id,
                    "version": manifest.version,
                    "name": manifest.name,
                    "kind": manifest.kind,
                    "description": manifest.description,
                    "icon": parse_plugin_icon(plugin_dir),
                    "group": parse_plugin_group(plugin_dir),
                    "requires": parse_plugin_requires(plugin_dir),
                    "path": str(plugin_dir),
                    "loaded": loaded is not None,
                    "registration_error": self._channel_registration_error(manifest.id),
                    "enabled": enabled_map.get(manifest.id, True),
                    "ui": ui_meta,
                    "tools": tools_meta,
                },
            )
        return out

    def set_enabled(self, plugin_id: str, enabled: bool) -> dict[str, Any]:
        """Toggle global plugin enablement in ``config.json`` and load/unload registry."""
        plugin_dir = self.plugin_dir(plugin_id)
        if plugin_dir is None:
            raise OctopError(ErrorCode.NOT_FOUND, f"plugin {plugin_id!r} not found")
        try:
            PluginManifest.load(plugin_dir / "plugin.yaml")
        except Exception as exc:
            raise OctopError(
                ErrorCode.PLUGIN_INVALID_ARCHIVE,
                f"invalid plugin manifest: {exc}",
            ) from exc

        self._set_enabled_flag(plugin_id, enabled)
        if enabled:
            if PluginRegistry().get(plugin_id) is None:
                try:
                    _load_plugin_dir(plugin_dir, install_deps=False)
                except Exception as exc:
                    raise OctopError(
                        ErrorCode.PLUGIN_INSTALL_FAILED,
                        f"failed to load plugin: {exc}",
                        details={"reason": str(exc)},
                    ) from exc
        else:
            loaded = PluginRegistry().get(plugin_id)
            if loaded is not None:
                self._tool_catalog[plugin_id] = [
                    {
                        "name": t.name,
                        "description": t.description,
                        "config_fields": t.config_fields,
                    }
                    for t in loaded.tools
                ]
                if loaded.skills_dir is not None:
                    self._skill_catalog[plugin_id] = {
                        path.name
                        for path in loaded.skills_dir.iterdir()
                        if path.is_dir() and (path / "SKILL.md").is_file()
                    }
            unload_plugin(plugin_id)

        for item in self.list_installed():
            if item.get("id") == plugin_id:
                return item
        return {"id": plugin_id, "enabled": enabled}

    def plugin_dir(self, plugin_id: str) -> Path | None:
        """Return the on-disk plugin directory when it exists."""
        self._ensure_plugin_cache()
        dest = self._plugins_dir / plugin_id
        if dest.is_dir() and (dest / "plugin.yaml").is_file():
            return dest
        return None

    def resolve_ui_file(self, plugin_id: str, rel_path: str) -> Path:
        """Resolve a UI asset under the plugin tree with path-traversal checks.

        ``rel_path`` is typically relative to ``<plugin>/ui/`` (e.g. ``dist/index.js``)
        as served by ``GET /api/plugins/{id}/ui/{path}``. Full paths from the
        plugin root (``ui/dist/index.js``) are also accepted.
        """
        plugin_dir = self.plugin_dir(plugin_id)
        if plugin_dir is None:
            raise OctopError(
                ErrorCode.NOT_FOUND,
                f"plugin {plugin_id!r} not found",
            )
        return self._resolve_plugin_asset(plugin_dir, rel_path)

    @staticmethod
    def _resolve_plugin_asset(plugin_dir: Path, rel_path: str) -> Path:
        cleaned = rel_path.strip().lstrip("/").replace("\\", "/")
        if not cleaned or any(part == ".." for part in cleaned.split("/")):
            raise OctopError(ErrorCode.NOT_FOUND, "invalid plugin UI path")
        candidates = [
            plugin_dir / "ui" / cleaned,
            plugin_dir / cleaned,
        ]
        if not cleaned.startswith("ui/") and not cleaned.startswith("dist/"):
            candidates.append(plugin_dir / "ui" / "dist" / cleaned)
        for target in candidates:
            resolved = target.resolve()
            try:
                resolved.relative_to(plugin_dir.resolve())
            except ValueError as exc:
                raise OctopError(ErrorCode.NOT_FOUND, "invalid plugin UI path") from exc
            if resolved.is_file():
                return resolved
        raise OctopError(
            ErrorCode.NOT_FOUND,
            f"plugin UI file not found: {cleaned}",
        )

    def install_path(
        self,
        source: Path,
        *,
        force: bool = False,
        expect_id: str | None = None,
        expect_version: str | None = None,
    ) -> LoadedPlugin:
        self._ensure_plugin_cache()
        source = source.resolve()
        if not source.is_dir():
            raise OctopError(
                ErrorCode.PLUGIN_INVALID_ARCHIVE,
                f"plugin directory not found: {source}",
            )
        try:
            manifest = PluginManifest.load(source / "plugin.yaml")
        except Exception as exc:
            raise OctopError(
                ErrorCode.PLUGIN_INVALID_ARCHIVE,
                f"invalid plugin manifest: {exc}",
            ) from exc
        if expect_id is not None and manifest.id != expect_id:
            raise OctopError(
                ErrorCode.PLUGIN_INVALID_ARCHIVE,
                f"plugin id {manifest.id!r} does not match {expect_id!r}",
            )
        if expect_version is not None and manifest.version != expect_version:
            raise OctopError(
                ErrorCode.PLUGIN_INVALID_ARCHIVE,
                f"plugin version {manifest.version!r} does not match {expect_version!r}",
            )
        dest = self._plugins_dir / manifest.id
        if dest.exists():
            if not force:
                raise OctopError(
                    ErrorCode.PLUGIN_ALREADY_EXISTS,
                    f"plugin already installed: {manifest.id}",
                    details={"id": manifest.id},
                )
            shutil.rmtree(dest)
        shutil.copytree(source, dest)
        self._persist_plugin_tree(manifest.id)
        unload_plugin(manifest.id)
        try:
            return _load_plugin_dir(dest, install_deps=True)
        except Exception as exc:
            raise OctopError(
                ErrorCode.PLUGIN_INSTALL_FAILED,
                f"failed to load plugin: {exc}",
                details={"reason": str(exc)},
            ) from exc

    def install_archive(
        self,
        archive: Path,
        *,
        force: bool = False,
        expect_id: str | None = None,
        expect_version: str | None = None,
    ) -> LoadedPlugin:
        """Install a plugin from a local ZIP archive.

        The archive must contain exactly one plugin directory (at the zip root
        or in a single top-level folder) with a ``plugin.yaml`` manifest.
        """
        _assert_zip_magic(archive)
        try:
            if archive.stat().st_size > _MAX_PLUGIN_ARCHIVE_BYTES:
                raise _archive_error("plugin ZIP exceeds 100 MiB")
        except OSError as exc:
            raise _archive_error(f"cannot inspect plugin ZIP: {exc}") from exc
        with tempfile.TemporaryDirectory() as tmp:
            extract_to = Path(tmp) / "extract"
            extract_to.mkdir()
            try:
                with zipfile.ZipFile(archive) as zf:
                    infos = _validate_plugin_zip(zf)
                    extract_root = extract_to.resolve()
                    for member in infos:
                        target = (extract_to / member.filename).resolve()
                        try:
                            target.relative_to(extract_root)
                        except ValueError as exc:
                            raise _archive_error("zip path traversal detected") from exc
                    total_written = 0
                    for member in infos:
                        target = (extract_to / member.filename).resolve()
                        if member.is_dir():
                            target.mkdir(parents=True, exist_ok=True)
                            continue
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(member) as source, target.open("wb") as destination:
                            while True:
                                chunk = source.read(1024 * 1024)
                                if not chunk:
                                    break
                                total_written += len(chunk)
                                if total_written > _MAX_PLUGIN_UNCOMPRESSED_BYTES:
                                    raise _archive_error("plugin ZIP expands beyond 64 MiB")
                                destination.write(chunk)
            except OctopError:
                raise
            except zipfile.BadZipFile as exc:
                raise OctopError(
                    ErrorCode.PLUGIN_INVALID_ARCHIVE,
                    "file is not a valid ZIP archive",
                ) from exc

            # Support zip root being the plugin dir or containing one subdir
            candidates = [p for p in extract_to.iterdir() if (p / "plugin.yaml").is_file()]
            if not candidates and (extract_to / "plugin.yaml").is_file():
                candidates = [extract_to]
            if len(candidates) != 1:
                raise OctopError(
                    ErrorCode.PLUGIN_INVALID_ARCHIVE,
                    "zip must contain exactly one plugin directory with plugin.yaml",
                )
            return self.install_path(
                candidates[0],
                force=force,
                expect_id=expect_id,
                expect_version=expect_version,
            )

    def install_url(
        self,
        url: str,
        *,
        force: bool = False,
        expect_id: str | None = None,
        expect_version: str | None = None,
    ) -> LoadedPlugin:
        resolved = normalize_plugin_download_url(url)
        _assert_http_url(resolved)
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "plugin.zip"
            _download_plugin_archive(resolved, archive)
            try:
                return self.install_archive(
                    archive,
                    force=force,
                    expect_id=expect_id,
                    expect_version=expect_version,
                )
            except OctopError as exc:
                if exc.code is not ErrorCode.PLUGIN_INVALID_ARCHIVE:
                    raise
                raise OctopError(
                    ErrorCode.PLUGIN_INVALID_ARCHIVE,
                    f"{exc.message} (GitHub /blob/ pages return HTML — use a raw .zip URL)",
                    details=exc.details,
                ) from exc

    def uninstall(self, plugin_id: str) -> None:
        unload_plugin(plugin_id)
        self._tool_catalog.pop(plugin_id, None)
        self._skill_catalog.pop(plugin_id, None)
        dest = self._plugins_dir / plugin_id
        if dest.is_dir():
            shutil.rmtree(dest)
        if self._control_files is not None:
            self._control_files.delete_owner(ControlFileRepo.PLUGIN, plugin_id)
            self._bump_plugin_revision()

    def plugin_skill_names(self, plugin_id: str) -> set[str]:
        """Return skill directory names registered by one loaded plugin."""
        plugin = PluginRegistry().get(plugin_id)
        if plugin is None or plugin.skills_dir is None:
            return set(self._skill_catalog.get(plugin_id) or ())
        names = {
            path.name
            for path in plugin.skills_dir.iterdir()
            if path.is_dir() and (path / "SKILL.md").is_file()
        }
        self._skill_catalog[plugin_id] = names
        return set(names)

    def sync_skills_to_workspace(
        self,
        workspace: Any,
        *,
        agent_plugins: object = None,
    ) -> None:
        from octop_harness.backends.workspace import BackendWorkspace

        from octop.infra.agents.plugins.plugin_tool_defaults import agent_plugin_enabled

        if not isinstance(workspace, BackendWorkspace):
            return
        enabled = self.global_enabled_map()
        pairs: list[tuple[str, bytes]] = []
        for plugin in PluginRegistry().list_plugins():
            if enabled.get(plugin.manifest.id) is False:
                continue
            if not agent_plugin_enabled(agent_plugins, plugin.manifest.id):
                continue
            if plugin.skills_dir is None:
                continue
            for skill_dir in plugin.skills_dir.iterdir():
                if not skill_dir.is_dir():
                    continue
                if not (skill_dir / "SKILL.md").is_file():
                    continue
                dest = f"skills/{skill_dir.name}"
                if workspace.exists(f"{dest}/SKILL.md"):
                    continue
                for path in skill_dir.rglob("*"):
                    if not path.is_file():
                        continue
                    rel = path.relative_to(skill_dir).as_posix()
                    pairs.append((f"{dest}/{rel}", path.read_bytes()))
        if pairs:
            workspace.upload_many(pairs)
