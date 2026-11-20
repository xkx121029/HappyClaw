"""S10: run a DSH bundle's built entry through the tool bridge.

The five harness bundles ship a Cordis plugin, not a data-returning function.
Invoking one therefore means starting the plugin inside a real ``Context`` and
reading back the service it publishes. That is a process execution, and this
module treats it as one:

* **Two opt-ins.** ``OCTOP_DSH_EXEC`` turns the stage on and
  ``OCTOP_DSH_EXEC_PLUGINS`` names the bundle ids the host grants. Neither the
  manifest nor the switch list can widen the other.
* **The sandbox runs the command.** The host passes ``exec`` to the plugin only
  as an explicit grant, the probe is built with the same permission set and a
  real ``SubprocessExecutor``, and the call itself goes through
  ``PluginSandbox.run_command`` so cwd, timeout and the output cap are the
  sandbox's, not this module's.
* **Failures are typed.** A missing package, a missing entry and an old Node
  each get their own error code; nothing is reported as a generic success.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from octop.infra.dsh.diagnostics import record_failure
from octop.infra.plugins.bridge.contract import ToolDefinition, ToolOutputSpec
from octop.infra.plugins.bridge.errors import DshToolError, DshToolErrorCode
from octop.infra.plugins.runtime.contract import (
    PluginEnvelope,
    PermissionKind,
    version_satisfies,
)
from octop.infra.plugins.sandbox import SandboxDeniedError
from octop.infra.plugins.sandbox.command import CommandRequest
from octop.infra.plugins.sandbox.gate import PluginSandbox

logger = logging.getLogger(__name__)

ENV_EXEC_PLUGINS = "OCTOP_DSH_EXEC_PLUGINS"
ENV_NODE = "OCTOP_DSH_NODE"
ENV_HARNESS_ROOT = "DSH_HARNESS_ROOT"

DEFAULT_ENGINE = ">=24.9.0"
RESULT_MARKER = "DSH_RUNTIME_RESULT:"
CAPABILITY = "startup"
TOOL_NAME = "startup"
MAX_OUTPUT_BYTES = 65_536
MAX_RESULT_BYTES = 65_536

# Runs inside ``node --input-type=module -e <source> <request-json>``. It only
# mounts the plugin and reads published services; it never evaluates host input
# beyond the entry path and the argv the model supplied.
RUNNER_SOURCE = r"""
import { readFileSync } from "node:fs";

const req = JSON.parse(process.argv[1]);
const result = (value) => {
  console.log("DSH_RUNTIME_RESULT:" + JSON.stringify(value));
  process.exit(0);
};

let mod;
try {
  mod = await import(req.entryUrl);
} catch (error) {
  result({ ok: false, code: "import_failed", message: String(error && error.message || error) });
}

let Context;
try {
  ({ Context } = await import(req.cordisUrl));
} catch (error) {
  result({ ok: false, code: "cordis_missing", message: String(error && error.message || error) });
}

// The launcher supplies the same three services the real stdio launcher does.
// ``inject`` is only the set the plugin declares it reads eagerly; ``appExit``
// and ``appReady`` are read later by helpers such as ``exitOnStdinEnd``, so
// providing just ``inject`` leaves those helpers throwing inside the plugin's
// action and the published service silently never appears.
const launcher = {
  cmdlineArgs: () => ({ get: () => req.arguments }),
  appExit: () => () => {},
  appReady: () => ({ onReady: (fn) => { fn(); return () => {}; } }),
};

const ctx = new Context();
const missing = [];
for (const name of mod.inject || []) {
  if (!launcher[name]) missing.push(name);
}
if (missing.length) result({ ok: false, code: "service_missing", missing, inject: mod.inject || [] });
for (const [name, factory] of Object.entries(launcher)) {
  try { ctx.provide(name, factory()); }
  catch (error) { result({ ok: false, code: "service_missing", missing: [name + ": " + String(error && error.message || error)] }); }
}

let failure = null;
try { ctx.plugin(mod); }
catch (error) { failure = String(error && error.stack || error); }
await new Promise((resolve) => setTimeout(resolve, req.settleMs));

const published = {};
for (const [key, value] of Object.entries(mod)) {
  if (!/^[A-Z0-9_]+_SERVICE$/.test(key) || typeof value !== "string") continue;
  try {
    const service = ctx.get(value);
    if (service !== undefined) published[value] = service;
  } catch (error) {
    published[value] = { error: String(error && error.message || error) };
  }
}

result({
  ok: failure === null,
  name: mod.name || null,
  inject: mod.inject || [],
  pluginConfig: mod.Config ? "declared" : null,
  published,
  registrySize: ctx.registry.size,
  error: failure,
});
"""


@dataclass(frozen=True, slots=True)
class ExecGrant:
    """One host-granted bundle the exec stage may invoke."""

    plugin_id: str
    workspace_root: Path | None
    cordis_entry: Path | None = None
    node_executable: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "workspace_root": str(self.workspace_root) if self.workspace_root else None,
            "cordis_entry": str(self.cordis_entry) if self.cordis_entry else None,
            "node": self.node_executable or None,
        }


def resolve_exec_plugins(raw: str | None = None) -> frozenset[str]:
    """Parse ``OCTOP_DSH_EXEC_PLUGINS``: comma-separated plugin ids."""

    value = os.environ.get(ENV_EXEC_PLUGINS, "") if raw is None else raw
    return frozenset(part.strip() for part in value.split(",") if part.strip())


def exec_permissions(envelope: PluginEnvelope) -> tuple[PermissionKind, ...]:
    """Manifest permissions plus the host's explicit ``exec`` grant.

    The grant is added here instead of on the envelope so no other stage (and
    no manifest reader) ever sees a widened plugin.
    """

    merged: list[PermissionKind] = []
    for kind in (*envelope.permissions, PermissionKind.EXEC):
        if kind not in merged:
            merged.append(kind)
    return tuple(merged)


def exec_declarations(
    envelope: PluginEnvelope,
    tool_names: Sequence[str],
) -> dict[str, tuple[str, ...]]:
    """Tools of a granted bundle declare exactly ``exec``."""

    permissions = {kind.value for kind in exec_permissions(envelope)}
    declared = tuple(
        kind.value for kind in (PermissionKind.EXEC,) if kind.value in permissions
    )
    return {name: declared for name in tool_names}


def exec_reason(plugin_id: str) -> str:
    return (
        f"plugin {plugin_id} tool {TOOL_NAME}: host granted exec, so the bundle's "
        "built entry runs in a Node child process"
    )


def find_cordis_entry(package_dir: Path) -> Path | None:
    """Locate the vendored Cordis runtime the bundle expects, walking upwards."""

    for base in (package_dir, *package_dir.parents):
        candidate = base / "vendor" / "cordis" / "lib" / "index.js"
        if candidate.is_file():
            return candidate
    root = os.environ.get(ENV_HARNESS_ROOT, "").strip()
    if root:
        candidate = Path(root) / "vendor" / "cordis" / "lib" / "index.js"
        if candidate.is_file():
            return candidate
    return None


_node_version: list[str | None] = []


def host_node_version(executable: str = "") -> str | None:
    """Ask the Node binary for its version; ``None`` when it cannot run."""

    if not executable:
        if _node_version:
            return _node_version[0]
        completed: subprocess.CompletedProcess[str] | None
        try:
            completed = subprocess.run(
                ["node", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            completed = None
        version = None
        if completed is not None and completed.returncode == 0:
            version = completed.stdout.strip().lstrip("v") or None
        _node_version.append(version)
        return version
    try:
        completed = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip().lstrip("v") or None


@dataclass
class RuntimeTools:
    """Tool definitions that mount one granted bundle's startup plugin."""

    grant: ExecGrant
    node_executable: str = ""
    timeout_s: float = 20.0
    settle_ms: int = 350
    _exposed: dict[str, str] = field(default_factory=dict)
    _sandbox: PluginSandbox | None = None

    @property
    def plugin_id(self) -> str:
        return self.grant.plugin_id

    def bind(self, exposed: Mapping[str, str], sandbox: PluginSandbox | None) -> None:
        """Attach the registry's exposed names and the probe's sandbox."""

        self._exposed = {str(k): str(v) for k, v in exposed.items()}
        self._sandbox = sandbox

    def definitions(self, envelope: PluginEnvelope) -> list[ToolDefinition]:
        return [self._definition(envelope)]

    def _definition(self, envelope: PluginEnvelope) -> ToolDefinition:
        return ToolDefinition(
            name=TOOL_NAME,
            description=(
                f"Run the DSH bundle {envelope.id} ({envelope.version}) startup plugin "
                "in a Node child process and return the services it publishes. "
                "The call is host-granted exec: the bundle's own code runs."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "arguments": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "argv exposed to the plugin through cmdlineArgs",
                    },
                    "timeout_s": {
                        "type": "number",
                        "minimum": 1,
                        "maximum": 30,
                        "description": "wall-clock budget for the child process",
                    },
                },
                "additionalProperties": False,
            },
            output=ToolOutputSpec(
                schema={
                    "type": "object",
                    "properties": {
                        "plugin": {"type": "string"},
                        "capability": {"type": "string"},
                        "entry": {"type": "string"},
                        "arguments": {"type": "array", "items": {"type": "string"}},
                        "duration_ms": {"type": "number"},
                        "published": {"type": "object"},
                        "registry_size": {"type": "integer"},
                    },
                    "required": [
                        "plugin",
                        "capability",
                        "entry",
                        "arguments",
                        "duration_ms",
                        "published",
                        "registry_size",
                    ],
                },
                render=_render,
            ),
            execute=lambda arguments, _ctx: asyncio.to_thread(
                self._run, envelope, arguments
            ),
            timeout_ms=40_000,
            max_result_bytes=MAX_RESULT_BYTES,
        )

    # ------------------------------------------------------------------
    # Invocation
    # ------------------------------------------------------------------
    def _run(
        self, envelope: PluginEnvelope, arguments: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Invoke the bundle and keep the last typed failure for diagnostics."""

        try:
            return self._invoke(envelope, arguments)
        except DshToolError as exc:
            record_failure(
                kind="execute",
                plugin_id=self.plugin_id,
                code=exc.code.value,
                reason=exc.message,
            )
            raise

    def _invoke(
        self, envelope: PluginEnvelope, arguments: Mapping[str, Any]
    ) -> dict[str, Any]:
        package = Path(envelope.source.reference)
        if not package.is_file():
            raise _fail(
                DshToolErrorCode.TOOL_RUNTIME_PLUGIN_NOT_LOADED,
                f"bundle {self.plugin_id} is not installed: {package} does not exist",
            )
        entry = package.parent / envelope.entry
        if not entry.is_file():
            raise _fail(
                DshToolErrorCode.TOOL_RUNTIME_ENTRY_MISSING,
                f"bundle {self.plugin_id} entry {entry} does not exist; build lib/ first",
            )

        required = str(
            (envelope.metadata.get("required_engines") or {}).get("node") or DEFAULT_ENGINE
        )
        executable = self.node_executable or self.grant.node_executable or "node"
        version = host_node_version(executable)
        if version is None:
            raise _fail(
                DshToolErrorCode.TOOL_RUNTIME_ENGINE_UNSATISFIED,
                f"node executable {executable!r} is not available on PATH",
            )
        if not version_satisfies(version, required):
            raise _fail(
                DshToolErrorCode.TOOL_RUNTIME_ENGINE_UNSATISFIED,
                f"host node {version} does not satisfy {required} required by {self.plugin_id}",
            )

        sandbox = self._sandbox
        if sandbox is None or self.grant.workspace_root is None:
            raise _fail(
                DshToolErrorCode.TOOL_CAPABILITY_UNAVAILABLE,
                "no sandbox is assembled for this workspace, so exec is refused",
            )
        cordis = self.grant.cordis_entry or find_cordis_entry(entry.parent)
        if cordis is None or not cordis.is_file():
            raise _fail(
                DshToolErrorCode.TOOL_RUNTIME_FAILED,
                f"cordis runtime for {self.plugin_id} was not found next to the bundle "
                "(expected vendor/cordis/lib/index.js)",
            )

        argv = _argv(arguments, self.timeout_s)
        request = {
            "entryUrl": entry.resolve().as_uri(),
            "cordisUrl": cordis.resolve().as_uri(),
            "arguments": argv,
            "settleMs": self.settle_ms,
        }
        tool_name = self._exposed.get(TOOL_NAME, TOOL_NAME)
        started = time.perf_counter()
        try:
            outcome = sandbox.run_command(
                tool_name,
                CommandRequest(
                    argv=(
                        _resolve_node(executable),
                        "--input-type=module",
                        "-e",
                        RUNNER_SOURCE,
                        json.dumps(request),
                    ),
                    cwd=str(self.grant.workspace_root),
                    timeout_s=_timeout(arguments, self.timeout_s),
                    max_output_bytes=MAX_OUTPUT_BYTES,
                ),
            )
        except SandboxDeniedError as exc:
            raise _fail(DshToolErrorCode.TOOL_RUNTIME_FAILED, exc.message) from None
        duration = round((time.perf_counter() - started) * 1000, 1)

        payload = _parse(outcome.stdout, outcome.stderr, self.plugin_id)
        code = str(payload.get("code") or "")
        if code == "import_failed":
            raise _fail(
                DshToolErrorCode.TOOL_RUNTIME_PLUGIN_NOT_LOADED,
                f"bundle {self.plugin_id} entry could not be imported: "
                f"{payload.get('message', '')}",
            )
        if code == "service_missing":
            missing = ", ".join(str(item) for item in payload.get("missing") or [])
            raise _fail(
                DshToolErrorCode.TOOL_RUNTIME_SERVICE_MISSING,
                f"bundle {self.plugin_id} injects services the host launcher does not "
                f"provide: {missing}",
            )
        if code == "cordis_missing":
            raise _fail(
                DshToolErrorCode.TOOL_RUNTIME_FAILED,
                f"cordis runtime failed to load: {payload.get('message', '')}",
            )
        if not payload.get("ok"):
            raise _fail(
                DshToolErrorCode.TOOL_RUNTIME_FAILED,
                f"bundle {self.plugin_id} plugin threw: {payload.get('error', '')}",
            )

        return {
            "plugin": self.plugin_id,
            "capability": CAPABILITY,
            "entry": envelope.entry,
            "arguments": argv,
            "duration_ms": duration,
            "published": dict(payload.get("published") or {}),
            "registry_size": int(payload.get("registrySize") or 0),
        }


def _argv(arguments: Mapping[str, Any], default_timeout: float) -> list[str]:
    raw = arguments.get("arguments")
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raise _fail(
            DshToolErrorCode.TOOL_INVALID_ARGUMENTS,
            "'arguments' must be a list of strings",
        )
    values: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise _fail(
                DshToolErrorCode.TOOL_INVALID_ARGUMENTS,
                "'arguments' must contain only strings",
            )
        values.append(item)
    return values


def _timeout(arguments: Mapping[str, Any], default: float) -> float:
    raw = arguments.get("timeout_s")
    if raw is None:
        return default
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise _fail(
            DshToolErrorCode.TOOL_INVALID_ARGUMENTS,
            "'timeout_s' must be a number",
        )
    return float(raw)


def _resolve_node(executable: str) -> str:
    if os.path.isabs(executable) and Path(executable).exists():
        return executable
    found = shutil.which(executable)
    return found or executable


def _parse(stdout: bytes, stderr: bytes, plugin_id: str) -> dict[str, Any]:
    text = stdout.decode("utf-8", errors="replace")
    for line in reversed(text.splitlines()):
        if line.startswith(RESULT_MARKER):
            try:
                payload = json.loads(line[len(RESULT_MARKER) :])
            except json.JSONDecodeError as exc:
                raise _fail(
                    DshToolErrorCode.TOOL_RUNTIME_FAILED,
                    f"bundle {plugin_id} returned unreadable JSON: {exc}",
                ) from None
            if isinstance(payload, dict):
                return payload
    detail = stderr.decode("utf-8", errors="replace").strip()[:400]
    raise _fail(
        DshToolErrorCode.TOOL_RUNTIME_FAILED,
        f"bundle {plugin_id} produced no runtime result"
        + (f"; stderr: {detail}" if detail else ""),
    )


def _render(arguments: Mapping[str, Any], value: Any) -> str:
    payload = value if isinstance(value, Mapping) else {}
    published = json.dumps(payload.get("published") or {}, ensure_ascii=False)
    return (
        "DSH 插件调用\n"
        f"plugin: {payload.get('plugin', '')}\n"
        f"capability: {payload.get('capability', CAPABILITY)}\n"
        f"entry: {payload.get('entry', '')}\n"
        f"arguments: {json.dumps(list(payload.get('arguments') or []), ensure_ascii=False)}\n"
        f"duration_ms: {payload.get('duration_ms', '')}\n"
        f"published: {published}"
    )


def _fail(code: DshToolErrorCode, message: str) -> DshToolError:
    """Carry the code both on the error and in its text.

    The pipeline renders failures as ``Error: <message>``; putting the code in
    the message is what makes it visible in the transcript, not just in the
    event stream and the ledger.
    """

    return DshToolError(code, f"[{code.value}] {message}")


__all__ = [
    "ENV_EXEC_PLUGINS",
    "ENV_NODE",
    "ExecGrant",
    "RuntimeTools",
    "exec_declarations",
    "exec_permissions",
    "exec_reason",
    "find_cordis_entry",
    "host_node_version",
    "resolve_exec_plugins",
]
