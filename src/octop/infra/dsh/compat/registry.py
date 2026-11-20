"""Lifecycle for DSH bundles actually running inside HappyClaw.

A plugin's host half lives in its own Node child process; this registry owns
that process, its state machine and the thin Python view of what the plugin
published. Nothing here is on the import path of a normal request: the module
only acts once :func:`octop.infra.dsh.compat.switch.compat_enabled` is true.

Failure posture: discovery never raises, a start failure is recorded on that
plugin, and a crash marks only the plugin ``failed``. ``shutdown_all`` is called
on app exit.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from octop.infra.dsh.compat.client_asset import ClientAsset, client_asset
from octop.infra.dsh.compat.errors import DshCompatCode, DshCompatError
from octop.infra.dsh.compat.probe import StaticFacts, classify_static, discover_samples
from octop.infra.dsh.compat.switch import allowed_plugins, compat_enabled, plugin_allowed
from octop.infra.dsh.compat.transport import NodeRpcClient

logger = logging.getLogger(__name__)

RUNNER = Path(__file__).resolve().parent / "node" / "runner.mjs"
MAX_STARTS_PER_HOUR = 3
_REFRESH_TTL = 5.0


@dataclass
class PluginState:
    plugin_id: str
    native_id: str
    package_name: str
    version: str
    title: str
    category: str
    package_dir: Path
    facts: StaticFacts
    client: ClientAsset
    allowed: bool
    host_state: str = "idle"
    code: str = DshCompatCode.OK.value
    error: str = ""
    missing: tuple[str, ...] = ()
    published: dict[str, Any] = field(default_factory=dict)
    tools: list[dict[str, Any]] = field(default_factory=list)
    prompts: list[dict[str, Any]] = field(default_factory=list)
    routes: list[dict[str, Any]] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    ui_state: str = "unknown"
    ui_error: str = ""
    runtime: NodeRpcClient | None = None
    attempts: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.plugin_id,
            "native_id": self.native_id,
            "package_name": self.package_name,
            "version": self.version,
            "title": self.title,
            "category": self.category,
            "package_dir": str(self.package_dir),
            "allowed": self.allowed,
            "host": {
                "state": self.host_state,
                "code": self.code,
                "error": self.error,
                "missing": list(self.missing),
                "published": self.published,
                "tools": self.tools,
                "prompts": self.prompts,
                "routes": self.routes,
                "unsupported": self.unsupported,
                "entry_shape": self.facts.entry_shape,
                "ctx": list(self.facts.host_ctx),
            },
            "client": {
                **self.client.to_dict(),
                "url": f"/api/dsh-compat/ui/{self.native_id}/client.js",
            },
            "ui": {"state": self.ui_state, "error": self.ui_error},
        }


def _market_root() -> Path:
    raw = os.environ.get("OCTOP_DSH_MARKET_ROOT", "").strip()
    if raw:
        return Path(raw).expanduser()
    try:
        from octop.infra.plugins.market import default_market_root

        return default_market_root()
    except Exception:  # pragma: no cover - fallback for isolated tests
        return Path.home() / ".octop" / "market"


def _installed_dirs(root: Path) -> list[Path]:
    base = root / "dsh" if (root / "dsh").is_dir() else root
    found: list[Path] = []
    if not base.is_dir():
        return found
    try:
        natives = sorted(base.iterdir(), key=lambda item: item.name)
    except OSError:
        return found
    for native in natives:
        if not native.is_dir() or native.name.startswith("."):
            continue
        current = None
        ledger = native / "index.json"
        try:
            data = json.loads(ledger.read_text(encoding="utf-8"))
            version = (data.get("current") or {}).get("version")
            if isinstance(version, str):
                current = native / version
        except (OSError, json.JSONDecodeError):
            current = None
        if current is not None and (current / "package.json").is_file():
            found.append(current)
            continue
        candidates = sorted(
            (item for item in native.iterdir() if item.is_dir() and (item / "package.json").is_file()),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            found.append(candidates[0])
    return found


def _native_of(plugin_id: str) -> str:
    return plugin_id.split(":", 1)[1] if ":" in plugin_id else plugin_id


class DshCompatRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._plugins: dict[str, PluginState] = {}
        self._refreshed_at = 0.0
        self._node: str | None = None
        self._probed_node = False

    # -- discovery ---------------------------------------------------------
    def refresh(self, *, force: bool = False) -> list[PluginState]:
        with self._lock:
            now = time.time()
            if not force and self._plugins and now - self._refreshed_at < _REFRESH_TTL:
                return list(self._plugins.values())
            root = _market_root()
            states: dict[str, PluginState] = {}
            for package_dir in _installed_dirs(root):
                facts = classify_static(package_dir)
                if not facts.package_name:
                    continue
                existing = self._plugins.get(facts.plugin_id)
                if existing is not None and existing.package_dir == package_dir and existing.runtime is not None:
                    states[facts.plugin_id] = existing
                    continue
                asset = client_asset(facts)
                states[facts.plugin_id] = PluginState(
                    plugin_id=facts.plugin_id,
                    native_id=_native_of(facts.plugin_id),
                    package_name=facts.package_name,
                    version=facts.version,
                    title=facts.title,
                    category=facts.category or "unknown",
                    package_dir=package_dir,
                    facts=facts,
                    client=asset,
                    allowed=plugin_allowed(facts.plugin_id),
                )
            # Drop states whose install disappeared, closing their process.
            for plugin_id, state in self._plugins.items():
                if plugin_id not in states and state.runtime is not None:
                    state.runtime.close()
            self._plugins = states
            self._refreshed_at = now
            return list(states.values())

    def state(self, plugin_id: str) -> PluginState | None:
        self.refresh()
        return self._plugins.get(plugin_id) or self._plugins.get(f"dsh:{plugin_id}")

    # -- process -----------------------------------------------------------
    def _node_binary(self) -> str | None:
        if not self._probed_node:
            self._node = shutil.which("node") or shutil.which("node.exe")
            self._probed_node = True
        return self._node

    def _exhausted(self, state: PluginState) -> bool:
        cutoff = time.time() - 3600
        return len([item for item in state.attempts if item >= cutoff]) >= MAX_STARTS_PER_HOUR

    def start(self, plugin_id: str) -> PluginState:
        with self._lock:
            state = self.state(plugin_id)
            if state is None:
                raise DshCompatError(
                    DshCompatCode.ENTRY_SHAPE,
                    f"plugin {plugin_id} is not installed",
                )
            if not compat_enabled():
                state.host_state = "disabled"
                state.code = DshCompatCode.DISABLED.value
                return state
            if not state.allowed:
                state.host_state = "disabled"
                state.code = DshCompatCode.NOT_ALLOWED.value
                return state
            if state.host_state == "mounted" and state.runtime is not None and state.runtime.alive:
                return state
            if state.host_state == "starting":
                return state
            if self._exhausted(state):
                state.host_state = "failed"
                state.code = DshCompatCode.PROCESS_EXIT.value
                state.error = "start limit reached (3 per hour)"
                return state
            if not state.facts.main_exists:
                state.host_state = "failed"
                state.code = (
                    DshCompatCode.NEEDS_BUILD.value
                    if state.facts.needs_build
                    else DshCompatCode.ENTRY_SHAPE.value
                )
                state.error = "bundle entry is missing"
                return state
            node = self._node_binary()
            if node is None:
                state.host_state = "failed"
                state.code = DshCompatCode.ENGINE_UNSATISFIED.value
                state.error = "node executable not found"
                return state
            entry = (state.package_dir / (state.facts.main_rel or "")).resolve()
            runtime = NodeRpcClient(
                node=node,
                runner=RUNNER,
                plugin_id=state.plugin_id,
                cwd=state.package_dir,
            )
            state.attempts.append(time.time())
            state.host_state = "starting"
            state.error = ""
            try:
                runtime.start()
                result = runtime.request(
                    "mount",
                    {"entry": str(entry), "inject": list(state.facts.host_inject), "settleMs": 300},
                    timeout=25.0,
                )
            except DshCompatError as exc:
                runtime.close(graceful=False)
                state.host_state = "failed"
                state.code = exc.code.value
                state.error = exc.message
                return state
            except Exception as exc:  # pragma: no cover - defensive
                runtime.close(graceful=False)
                state.host_state = "failed"
                state.code = DshCompatCode.RUNTIME_THROW.value
                state.error = f"{type(exc).__name__}: {exc}"
                return state

            if not isinstance(result, Mapping) or not result.get("ok", False):
                runtime.close(graceful=False)
                state.host_state = "failed"
                state.code = str((result or {}).get("code") or DshCompatCode.RUNTIME_THROW.value)
                state.error = str((result or {}).get("error") or "mount failed")
                state.missing = tuple((result or {}).get("missing") or ())
                state.unsupported = list((result or {}).get("unsupported") or ())
                return state

            state.runtime = runtime
            state.host_state = "mounted"
            state.code = str(result.get("code") or DshCompatCode.OK.value)
            state.missing = tuple(result.get("missing") or ())
            state.published = dict(result.get("published") or {})
            state.tools = list(result.get("tools") or [])
            state.prompts = list(result.get("prompts") or [])
            state.routes = list(result.get("routes") or [])
            state.unsupported = list(result.get("unsupported") or ())
            logger.info(
                "DSH compat mounted %s: tools=%d prompts=%d routes=%d",
                state.plugin_id,
                len(state.tools),
                len(state.prompts),
                len(state.routes),
            )
            return state

    def stop(self, plugin_id: str) -> PluginState:
        with self._lock:
            state = self.state(plugin_id)
            if state is None:
                raise DshCompatError(DshCompatCode.ENTRY_SHAPE, f"plugin {plugin_id} is not installed")
            if state.runtime is not None:
                state.runtime.close()
                state.runtime = None
            state.host_state = "idle"
            state.code = DshCompatCode.OK.value
            return state

    def shutdown_all(self) -> None:
        with self._lock:
            for state in self._plugins.values():
                if state.runtime is not None:
                    state.runtime.close()
                    state.runtime = None
                if state.host_state == "mounted":
                    state.host_state = "idle"

    # -- service calls -----------------------------------------------------
    def ensure_started(self, plugin_ids: Iterable[str] | None = None) -> list[PluginState]:
        if not compat_enabled():
            return []
        states: list[PluginState] = []
        with self._lock:
            candidates = [
                state
                for state in self.refresh()
                if state.allowed and (plugin_ids is None or state.plugin_id in set(plugin_ids))
            ]
        for state in candidates:
            if state.host_state == "failed" and self._exhausted(state):
                states.append(state)
                continue
            try:
                states.append(self.start(state.plugin_id))
            except DshCompatError:
                states.append(state)
        return states

    def prompt_sections(self, *, limit: int = 12) -> list[str]:
        """Rendered prompt text from mounted plugins; never raises."""

        if not compat_enabled():
            return []
        texts: list[str] = []
        for state in self.ensure_started():
            if state.host_state != "mounted" or state.runtime is None:
                continue
            try:
                result = state.runtime.request(
                    "prompt.list",
                    {
                        "context": {
                            "cwd": os.getcwd(),
                            "locale": "zh",
                            "agent": {"id": "octop", "cwd": os.getcwd()},
                        }
                    },
                    timeout=1.5,
                )
            except DshCompatError as exc:
                state.ui_error = ""
                state.error = exc.message if state.host_state != "mounted" else state.error
                logger.debug("DSH prompt render failed for %s: %s", state.plugin_id, exc.message)
                continue
            if not isinstance(result, Mapping):
                continue
            for entry in result.get("entries") or []:
                text = str((entry or {}).get("text") or "").strip()
                if text:
                    texts.append(text)
                if len(texts) >= limit:
                    return texts
        return texts

    def call_tool(self, plugin_id: str, name: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        state = self.start(plugin_id)
        if state.host_state != "mounted" or state.runtime is None:
            raise DshCompatError(
                DshCompatCode(state.code) if state.code in DshCompatCode._value2member_map_ else DshCompatCode.RUNTIME_THROW,
                state.error or f"plugin {plugin_id} is not mounted",
            )
        result = state.runtime.request(
            "tools.call",
            {"name": name, "args": dict(arguments or {})},
            timeout=30.0,
        )
        return dict(result or {})

    def dispatch_http(
        self,
        plugin_id: str,
        *,
        method: str,
        path: str,
        headers: Mapping[str, str] | None = None,
        body: str = "",
    ) -> dict[str, Any]:
        state = self.start(plugin_id)
        if state.host_state != "mounted" or state.runtime is None:
            raise DshCompatError(
                DshCompatCode.RUNTIME_THROW,
                state.error or f"plugin {plugin_id} is not mounted",
            )
        result = state.runtime.request(
            "http.request",
            {"method": method, "path": path, "headers": dict(headers or {}), "body": body},
            timeout=20.0,
        )
        return dict(result or {})

    def emit(self, event: str, payload: Mapping[str, Any] | None = None) -> None:
        if not compat_enabled():
            return
        for state in self.refresh():
            if state.host_state != "mounted" or state.runtime is None:
                continue
            try:
                state.runtime.request("event.emit", {"name": event, "args": [dict(payload or {})]}, timeout=0.8)
            except DshCompatError:
                logger.debug("DSH event %s not delivered to %s", event, state.plugin_id)

    def report_ui(self, plugin_id: str, state_value: str, error: str = "") -> None:
        state = self.state(plugin_id)
        if state is None:
            return
        state.ui_state = str(state_value or "unknown")
        state.ui_error = str(error or "")

    # -- status ------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        enabled = compat_enabled()
        states = self.refresh(force=True) if enabled else list(self._plugins.values())
        return {
            "enabled": enabled,
            "allow": sorted(allowed_plugins()),
            "node": self._node_binary(),
            "host_slots": ["home.sidebar", "chat.messages.top"],
            "plugins": [state.to_dict() for state in states],
        }

    def ui_targets(self) -> list[dict[str, Any]]:
        targets: list[dict[str, Any]] = []
        for state in self.refresh():
            if not state.allowed or not state.client.exists:
                continue
            targets.append(
                {
                    "plugin_id": state.plugin_id,
                    "native_id": state.native_id,
                    "name": state.package_name,
                    "title": state.title,
                    "client_url": f"/api/dsh-compat/ui/{state.native_id}/client.js",
                    "slots": list(state.client.slots),
                    "mapped_slots": list(state.client.mapped_slots),
                    "unsupported_slots": list(state.client.unsupported_slots),
                    "code": state.client.code,
                    "ui_state": state.ui_state,
                    "ui_error": state.ui_error,
                }
            )
        return targets

    def mounted_ids(self) -> list[str]:
        return [state.plugin_id for state in self.refresh() if state.host_state == "mounted"]


_registry: DshCompatRegistry | None = None
_registry_lock = threading.Lock()


def get_registry() -> DshCompatRegistry:
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = DshCompatRegistry()
        return _registry


__all__ = ["DshCompatRegistry", "PluginState", "get_registry"]
