"""DSH bundle compatibility inventory.

Static facts come from the manifest and the entry sources only. The optional
dynamic pass imports the host entry inside a Node child process with a
Cordis-compatible context, so a plugin's own ``apply`` really runs while the
host stays clean.

The two passes answer different questions and are reported separately:

* static: can this bundle even be *shaped* into a HappyClaw plugin?
* dynamic: when mounted, which service does it need, which does it publish,
  and where does it stop?
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from octop.infra.dsh.compat.errors import DshCompatCode

NODE_ENTRY = Path(__file__).resolve().parent / "node" / "probe.mjs"
MAX_SCAN_BYTES = 8 * 1024 * 1024
SETTLE_MS = 400
PROBE_TIMEOUT_S = 30.0

# Slots the Dashboard really renders (see dashboard/src/plugins/surfaces/types.ts).
HOST_SLOTS = ("home.sidebar", "chat.messages.top")

_SKIP_DIRS = {
    ".git",
    "node_modules",
    "dist",
    "coverage",
    "__pycache__",
}

_NATIVE_HINTS = (
    "bindings",
    "ffi-napi",
    "node-gyp-build",
    "sharp",
    "canvas",
    "better-sqlite3",
    "lmdb",
    "node-pty",
    "usb",
    "serialport",
)

_CREDENTIAL_RE = re.compile(
    r"(api[_-]?key|access[_-]?token|client[_-]?secret|password\s*[:=])",
    re.IGNORECASE,
)
_NETWORK_RE = re.compile(r"https?://(?!localhost|127\.0\.0\.1)[a-z0-9.-]+", re.IGNORECASE)
_SLOT_RE = re.compile(
    r"slots?\.(?:inject|register)\(\s*(?:[\"']([^\"']+)[\"']|\{[^}]{0,240}?name\s*:\s*[\"']([^\"']+)[\"'])",
    re.DOTALL,
)
_CTX_MEMBER_RE = re.compile(r"\bctx\.([A-Za-z_$][A-Za-z0-9_$]*)")
_REQUIRE_RE = re.compile(r"require\(\s*[\"']([^\"']+)[\"']\s*\)")
_IMPORT_RE = re.compile(
    r"(?:^|\n)\s*(?:import|export)\s[^;\n]*?from\s*[\"']([^\"']+)[\"']"
)
_INJECT_RE = re.compile(r"export\s+(?:const|let|var)\s+inject\s*=\s*\[([^\]]*)\]")


@dataclass
class StaticFacts:
    plugin_id: str
    package_name: str
    version: str
    package_dir: str
    title: str
    category: str
    main_rel: str | None = None
    main_exists: bool = False
    client_rel: str | None = None
    client_exists: bool = False
    client_declared: bool = False
    host_exports: tuple[str, ...] = ()
    host_ctx: tuple[str, ...] = ()
    host_inject: tuple[str, ...] = ()
    host_bare_imports: tuple[str, ...] = ()
    client_requires: tuple[str, ...] = ()
    client_ctx: tuple[str, ...] = ()
    ui_slots: tuple[str, ...] = ()
    mapped_slots: tuple[str, ...] = ()
    unsupported_slots: tuple[str, ...] = ()
    native_modules: tuple[str, ...] = ()
    network_hosts: tuple[str, ...] = ()
    credential_signals: tuple[str, ...] = ()
    entry_shape: str = "unknown"
    needs_build: bool = False
    code: str = DshCompatCode.OK.value
    reasons: tuple[str, ...] = ()


@dataclass
class PluginReport:
    plugin_id: str
    package_name: str
    version: str
    title: str
    category: str
    package_dir: str
    host: dict[str, Any] = field(default_factory=dict)
    client: dict[str, Any] = field(default_factory=dict)
    can_run: bool = False
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def map_slot(dsh_slot: str) -> str | None:
    """Map one DSH slot id onto a HappyClaw surface slot.

    ``None`` means the Dashboard has no honest place to render it; the caller
    must record it as unsupported instead of silently dropping the plugin.
    """

    slot = dsh_slot.strip()
    if not slot:
        return None
    # Composer slots before the generic ``conversation.*`` prefixes.
    if slot.startswith(("conversation.input.overlay", "conversation.input.float")):
        return "conversation.input.overlay"
    if slot == "conversation.input" or slot.startswith("conversation.input.left"):
        return "conversation.input.left"
    if slot == "conversation.view" or slot.startswith("conversation.view."):
        return "conversation.view"
    if (
        slot == "settings.section"
        or slot.startswith("settings.section.")
        or slot == "plugins.bundle.config"
        or slot.startswith("plugins.bundle.config.")
    ):
        return "settings.section"
    if slot == "shell.overlay" or slot.startswith(("overlay.", "modal.", "toast.")):
        return "chat.messages.top"  # rendered through a body portal
    if slot.startswith(("sidebar.", "home.")):
        return "home.sidebar"
    if slot.startswith(("conversation.header", "chat.")) or slot == "conversation.header.leading":
        return "chat.messages.top"
    return None


def _read_text(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_SCAN_BYTES:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                return handle.read(MAX_SCAN_BYTES)
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _bare_imports(source: str) -> tuple[str, ...]:
    found: list[str] = []
    for match in _IMPORT_RE.finditer(source):
        spec = match.group(1)
        if not spec.startswith((".", "/", "node:")):
            found.append(spec)
    for match in _REQUIRE_RE.finditer(source):
        spec = match.group(1)
        if spec.startswith((".", "/", "node:")):
            continue
        if spec not in found:
            found.append(spec)
    return tuple(dict.fromkeys(found))


def _ctx_members(source: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_CTX_MEMBER_RE.findall(source)))


def _resolve_export(data: Mapping[str, Any], key: str) -> str | None:
    exports = data.get("exports")
    if isinstance(exports, str):
        return exports if key == "." else None
    if not isinstance(exports, Mapping):
        return None
    value = exports.get(key)
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        default = value.get("default") or value.get("import") or value.get("require")
        return default if isinstance(default, str) else None
    return None


def _pick_client_entry(data: Mapping[str, Any], root: Path) -> tuple[str | None, bool]:
    dsh = data.get("dsh") if isinstance(data.get("dsh"), Mapping) else {}
    client = dsh.get("client") if isinstance(dsh.get("client"), Mapping) else {}
    declared = bool(client)
    candidates: list[str] = []
    entry = client.get("entry")
    if isinstance(entry, str):
        candidates.append(entry)
    exported = _resolve_export(data, "./client")
    if exported:
        candidates.append(exported)
    main = data.get("main")
    if isinstance(main, str):
        candidates.append(str(Path(main).parent / "client.js"))
    candidates.extend(("client.js", "lib/client.js", "client/client.js"))
    for rel in candidates:
        candidate = (root / rel).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            continue
        if candidate.is_file():
            return str(candidate.relative_to(root.resolve())).replace("\\", "/"), declared
    return (candidates[0] if candidates else None), declared


def _entry_shape(source: str) -> str:
    if "__ModuleLoader__" in source:
        return "module-loader"
    if re.search(r"^\s*export\s+(?:default|const|function|async|class|\{)", source, re.MULTILINE):
        return "esm"
    if "module.exports" in source or re.search(r"^\s*exports\.", source, re.MULTILINE):
        return "cjs"
    return "script"


def classify_static(package_dir: str | Path, *, category: str = "") -> StaticFacts:
    root = Path(package_dir).expanduser().resolve()
    manifest_path = root / "package.json"
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    name = str(data.get("name") or root.name)
    version = str(data.get("version") or "0.0.0")
    native_id = re.sub(r"[^A-Za-z0-9._-]", "-", name.rsplit("/", 1)[-1]).lstrip("._-") or "unnamed"
    title = name
    title_block = data.get("title")
    if isinstance(title_block, Mapping):
        title = str(title_block.get("en") or title_block.get("zh") or name)

    main_rel = _resolve_export(data, ".") or (
        data.get("main") if isinstance(data.get("main"), str) else None
    )
    main_path = (root / main_rel).resolve() if main_rel else None
    main_exists = bool(main_path and main_path.is_file())
    client_rel, client_declared = _pick_client_entry(data, root)
    client_path = (root / client_rel).resolve() if client_rel else None
    client_exists = bool(client_path and client_path.is_file())

    host_source = _read_text(main_path) if main_exists and main_path else ""
    host_ctx = _ctx_members(host_source)
    inject_match = _INJECT_RE.search(host_source)
    host_inject = (
        tuple(re.findall(r"[\"']([^\"']+)[\"']", inject_match.group(1)))
        if inject_match
        else ()
    )
    host_bare = _bare_imports(host_source)

    client_source = _read_text(client_path) if client_exists and client_path else ""
    client_requires = tuple(dict.fromkeys(_REQUIRE_RE.findall(client_source)))
    client_ctx = _ctx_members(client_source)
    ui_slots = tuple(
        dict.fromkeys(match.group(1) or match.group(2) for match in _SLOT_RE.finditer(client_source))
    )
    mapped = tuple(dict.fromkeys(slot for slot in (map_slot(item) for item in ui_slots) if slot))
    unsupported = tuple(item for item in ui_slots if map_slot(item) is None)

    native: list[str] = []
    for spec in (*host_bare, *client_requires):
        if any(hint in spec for hint in _NATIVE_HINTS):
            native.append(spec)
    if any(path.suffix == ".node" for path in root.rglob("*.node")):
        native.append("*.node")
    native_modules = tuple(dict.fromkeys(native))

    network_hosts = tuple(dict.fromkeys(_NETWORK_RE.findall(host_source + client_source)))[:8]
    credential_signals = tuple(dict.fromkeys(_CREDENTIAL_RE.findall(host_source + client_source)))[:8]

    ts_files = list(root.rglob("*.ts")) + list(root.rglob("*.tsx"))
    needs_build = not main_exists and bool(ts_files)

    reasons: list[str] = []
    code = DshCompatCode.OK.value
    if not main_exists:
        code = (
            DshCompatCode.NEEDS_BUILD.value
            if needs_build
            else DshCompatCode.ENTRY_SHAPE.value
        )
        reasons.append(code)
    if native_modules:
        reasons.append(DshCompatCode.NATIVE_MODULE.value)
    if client_declared and not client_exists:
        reasons.append(DshCompatCode.ENTRY_SHAPE.value)
    if unsupported:
        reasons.append(DshCompatCode.SLOT_UNSUPPORTED.value)
    if not client_declared and not client_exists:
        reasons.append(DshCompatCode.CLIENT_MISSING.value)

    return StaticFacts(
        plugin_id=f"dsh:{native_id}",
        package_name=name,
        version=version,
        package_dir=str(root),
        title=title,
        category=category,
        main_rel=main_rel,
        main_exists=main_exists,
        client_rel=client_rel,
        client_exists=client_exists,
        client_declared=client_declared,
        host_exports=_exports_of(host_source),
        host_ctx=host_ctx,
        host_inject=host_inject,
        host_bare_imports=host_bare,
        client_requires=client_requires,
        client_ctx=client_ctx,
        ui_slots=ui_slots,
        mapped_slots=mapped,
        unsupported_slots=unsupported,
        native_modules=native_modules,
        network_hosts=network_hosts,
        credential_signals=credential_signals,
        entry_shape=_entry_shape(host_source),
        needs_build=needs_build,
        code=code,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def _exports_of(source: str) -> tuple[str, ...]:
    names = re.findall(
        r"export\s+(?:const|let|var|function|async function|class)\s+([A-Za-z_$][A-Za-z0-9_$]*)",
        source,
    )
    if re.search(r"export\s+default", source):
        names.append("default")
    return tuple(dict.fromkeys(names))


def _node_executable() -> str | None:
    return shutil.which("node") or shutil.which("node.exe")


def probe_dynamic(facts: StaticFacts, *, timeout_s: float = PROBE_TIMEOUT_S) -> dict[str, Any]:
    """Mount the host entry in an isolated Node child process."""

    node = _node_executable()
    if node is None:
        return {
            "class": "FAILED",
            "code": DshCompatCode.ENGINE_UNSATISFIED.value,
            "error": "node executable not found",
        }
    if not facts.main_exists:
        return {
            "class": "SKIPPED",
            "code": facts.code,
            "error": "entry file is missing",
        }
    with tempfile.TemporaryDirectory(prefix="dsh-probe-") as sandbox:
        request = {
            "entry": str(Path(facts.package_dir) / (facts.main_rel or "")),
            "inject": list(facts.host_inject),
            "settleMs": SETTLE_MS,
            "cwd": facts.package_dir,
        }
        env = dict(os.environ)
        env.update(
            {
                "HOME": sandbox,
                "USERPROFILE": sandbox,
                "DSH_HOME": str(Path(sandbox) / "dsh-home"),
                "XDG_CONFIG_HOME": str(Path(sandbox) / "config"),
                "XDG_DATA_HOME": str(Path(sandbox) / "data"),
                "OCTOP_DSH_PROBE": "1",
            }
        )
        try:
            completed = subprocess.run(
                [node, str(NODE_ENTRY), json.dumps(request, ensure_ascii=False)],
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
                cwd=facts.package_dir,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return {
                "class": "FAILED",
                "code": DshCompatCode.TIMEOUT.value,
                "error": f"probe exceeded {timeout_s}s",
            }
        except OSError as exc:
            return {
                "class": "FAILED",
                "code": DshCompatCode.ENGINE_UNSATISFIED.value,
                "error": str(exc),
            }
    payload = _last_json(completed.stdout)
    if payload is None:
        return {
            "class": "FAILED",
            "code": DshCompatCode.IMPORT_FAILED.value,
            "error": (completed.stderr or completed.stdout or "probe produced no result").strip()[-1200:],
        }
    payload["stderr"] = completed.stderr.strip()[-800:] if completed.stderr else ""
    return payload


def _last_json(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def build_report(facts: StaticFacts, *, dynamic: bool = True) -> PluginReport:
    report = PluginReport(
        plugin_id=facts.plugin_id,
        package_name=facts.package_name,
        version=facts.version,
        title=facts.title,
        category=facts.category,
        package_dir=facts.package_dir,
    )
    reasons = list(facts.reasons)

    host = {
        "class": "STATIC_ONLY",
        "code": facts.code,
        "entry": facts.main_rel,
        "entry_shape": facts.entry_shape,
        "inject": list(facts.host_inject),
        "ctx": list(facts.host_ctx),
        "native_modules": list(facts.native_modules),
    }
    if dynamic:
        probe = probe_dynamic(facts)
        host.update(
            {
                "class": probe.get("class", "FAILED"),
                "code": probe.get("code", DshCompatCode.RUNTIME_THROW.value),
            }
        )
        for key in (
            "published",
            "missing",
            "missing_packages",
            "accessed",
            "unsupported",
            "routes",
            "tools",
            "sections",
            "error",
            "stderr",
        ):
            if key in probe:
                host[key] = probe[key]
        if host["code"] != DshCompatCode.OK.value:
            reasons.append(str(host["code"]))

    client = {
        "class": "NONE",
        "code": DshCompatCode.CLIENT_MISSING.value,
        "entry": facts.client_rel,
        "requires": list(facts.client_requires),
        "ctx": list(facts.client_ctx),
        "slots": list(facts.ui_slots),
        "mapped_slots": list(facts.mapped_slots),
        "unsupported_slots": list(facts.unsupported_slots),
    }
    if facts.client_exists:
        client["class"] = (
            "READY"
            if not facts.unsupported_slots
            else "PARTIAL"
        )
        client["code"] = (
            DshCompatCode.OK.value
            if not facts.unsupported_slots
            else DshCompatCode.SLOT_UNSUPPORTED.value
        )
    elif facts.client_declared:
        client["class"] = "FAILED"
        client["code"] = DshCompatCode.ENTRY_SHAPE.value

    if facts.native_modules:
        reasons.append(DshCompatCode.NATIVE_MODULE.value)

    report.host = host
    report.client = client
    report.reasons = list(dict.fromkeys(reasons))
    report.can_run = (
        host["class"] in {"OK", "PARTIAL", "STATIC_ONLY"}
        and host["code"]
        in {
            DshCompatCode.OK.value,
            DshCompatCode.MISSING_API.value,
            DshCompatCode.SLOT_UNSUPPORTED.value,
        }
        and DshCompatCode.NATIVE_MODULE.value not in report.reasons
    )
    return report


def _category_of(package_dir: Path, fallback: str) -> str:
    meta = package_dir / ".market.json"
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback
    category = data.get("category") or data.get("plugin_category")
    return str(category) if category else fallback


def discover_samples(root: Path) -> list[Path]:
    """Every directory under ``root`` that carries a package.json, version dirs first."""

    found: list[Path] = []
    if not root.is_dir():
        return found
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if name not in _SKIP_DIRS)
        if "package.json" in filenames:
            found.append(Path(dirpath))
    return sorted(found, key=str)


def run_inventory(
    roots: Iterable[str | Path],
    *,
    dynamic: bool = True,
    category_map: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    categories = dict(category_map or {})
    reports: list[PluginReport] = []
    for raw in roots:
        root = Path(raw).expanduser()
        for package_dir in discover_samples(root):
            facts = classify_static(package_dir)
            facts.category = (
                _category_of(package_dir, "")
                or categories.get(facts.package_name, "")
                or categories.get(str(package_dir), "")
            )
            if not facts.package_name or facts.package_name == package_dir.name:
                continue
            reports.append(build_report(facts, dynamic=dynamic))

    by_class: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for report in reports:
        by_class[report.host["class"]] = by_class.get(report.host["class"], 0) + 1
        key = report.category or "unknown"
        by_category[key] = by_category.get(key, 0) + 1

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "node": _node_version(),
        "host_slots": list(HOST_SLOTS),
        "summary": {
            "total": len(reports),
            "by_host_class": by_class,
            "by_category": by_category,
            "runnable": sum(1 for item in reports if item.can_run),
            "with_client": sum(1 for item in reports if item.client["class"] != "NONE"),
            "slot_unsupported": sum(
                1 for item in reports if DshCompatCode.SLOT_UNSUPPORTED.value in item.reasons
            ),
        },
        "plugins": [item.to_dict() for item in reports],
    }


def _node_version() -> str | None:
    node = _node_executable()
    if node is None:
        return None
    try:
        completed = subprocess.run(
            [node, "--version"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inventory DSH bundles for HappyClaw")
    parser.add_argument("--root", action="append", default=[], help="directory to scan")
    parser.add_argument("--out", required=True, help="JSON report path")
    parser.add_argument("--categories", help="JSON object: package name -> category")
    parser.add_argument("--no-dynamic", action="store_true", help="static pass only")
    args = parser.parse_args(argv)
    roots = args.root or [str(Path.home() / ".octop" / "market" / "dsh")]
    categories: dict[str, str] = {}
    if args.categories:
        try:
            loaded = json.loads(Path(args.categories).expanduser().read_text(encoding="utf-8"))
            if isinstance(loaded, Mapping):
                categories = {str(key): str(value) for key, value in loaded.items()}
        except (OSError, json.JSONDecodeError):
            categories = {}
    report = run_inventory(roots, dynamic=not args.no_dynamic, category_map=categories)
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
