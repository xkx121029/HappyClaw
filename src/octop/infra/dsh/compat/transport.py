"""Line-oriented JSON RPC to a plugin's Node runner.

One :class:`NodeRpcClient` owns one child process. Requests are correlated by
id; runner-side requests (``{"rpc": true}``) are answered by a small handler so
a plugin can register tools while it is still mounting. A process exit is
visible immediately: pending calls fail with ``PROCESS_EXIT`` instead of
hanging the host.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from octop.infra.dsh.compat.errors import DshCompatCode, DshCompatError

logger = logging.getLogger(__name__)

HostRequestHandler = Callable[[str, Mapping[str, Any]], Any]
EventCallback = Callable[[Mapping[str, Any]], None]


class NodeRpcClient:
    """Own one ``runner.mjs`` process."""

    def __init__(
        self,
        *,
        node: str,
        runner: Path,
        plugin_id: str,
        cwd: str | Path,
        env: Mapping[str, str] | None = None,
        on_host_request: HostRequestHandler | None = None,
        on_event: EventCallback | None = None,
    ) -> None:
        self.node = node
        self.runner = Path(runner)
        self.plugin_id = plugin_id
        self.cwd = str(cwd)
        self._env = dict(os.environ if env is None else env)
        self._on_host_request = on_host_request or (lambda _method, _params: {})
        self._on_event = on_event
        self._process: subprocess.Popen[str] | None = None
        self._pending: dict[int, tuple[threading.Event, list[Any]]] = {}
        self._pending_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._next_id = 1
        self._stderr: deque[str] = deque(maxlen=200)
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self._closed = False

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._process is not None:
            return
        self._process = subprocess.Popen(
            [self.node, str(self.runner), self.plugin_id],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=self.cwd,
            env=self._env,
        )
        self._reader = threading.Thread(target=self._read_stdout, name=f"dsh-rpc-{self.plugin_id}", daemon=True)
        self._reader.start()
        self._stderr_reader = threading.Thread(target=self._read_stderr, name=f"dsh-err-{self.plugin_id}", daemon=True)
        self._stderr_reader.start()

    @property
    def alive(self) -> bool:
        return self._process is not None and self._process.poll() is None and not self._closed

    @property
    def stderr_tail(self) -> str:
        return "\n".join(self._stderr)

    def close(self, *, graceful: bool = True) -> None:
        process = self._process
        if process is None:
            return
        if graceful and process.poll() is None:
            try:
                self.request("shutdown", {}, timeout=1.5)
            except DshCompatError:
                pass
        self._closed = True
        try:
            process.terminate()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass
        self._process = None
        with self._pending_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for event, holder in pending:
            holder.append(
                DshCompatError(
                    DshCompatCode.PROCESS_EXIT,
                    f"plugin {self.plugin_id} process stopped",
                )
            )
            event.set()

    # -- requests ----------------------------------------------------------
    def request(self, method: str, params: Mapping[str, Any] | None = None, *, timeout: float = 15.0) -> Any:
        process = self._process
        if process is None or process.poll() is not None or self._closed:
            raise DshCompatError(
                DshCompatCode.PROCESS_EXIT,
                f"plugin {self.plugin_id} runner is not running",
            )
        with self._pending_lock:
            request_id = self._next_id
            self._next_id += 1
            event = threading.Event()
            holder: list[Any] = []
            self._pending[request_id] = (event, holder)
        payload = json.dumps(
            {"id": request_id, "method": method, "params": dict(params or {})},
            ensure_ascii=False,
        )
        try:
            with self._write_lock:
                if process.stdin is None:
                    raise OSError("stdin closed")
                process.stdin.write(payload + "\n")
                process.stdin.flush()
        except (OSError, ValueError) as exc:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise DshCompatError(
                DshCompatCode.PROCESS_EXIT,
                f"plugin {self.plugin_id} runner pipe closed",
                details={"error": str(exc)},
            ) from exc

        if not event.wait(timeout):
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise DshCompatError(
                DshCompatCode.TIMEOUT,
                f"plugin {self.plugin_id} did not answer {method} within {timeout}s",
            )
        if not holder:
            raise DshCompatError(
                DshCompatCode.RUNTIME_THROW,
                f"plugin {self.plugin_id} produced no result for {method}",
            )
        value = holder[0]
        if isinstance(value, DshCompatError):
            raise value
        return value

    # -- internals ---------------------------------------------------------
    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for raw in process.stdout:
            line = raw.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("dsh runner %s non-json: %s", self.plugin_id, line[:200])
                continue
            if message.get("rpc"):
                self._answer_host_request(message)
                continue
            if "event" in message and "id" not in message:
                if self._on_event is not None:
                    try:
                        self._on_event(message)
                    except Exception:  # pragma: no cover - observer only
                        logger.debug("dsh event observer failed", exc_info=True)
                continue
            request_id = message.get("id")
            if request_id is None:
                continue
            with self._pending_lock:
                entry = self._pending.pop(int(request_id), None)
            if entry is None:
                continue
            event, holder = entry
            if message.get("ok", True):
                holder.append(message.get("result"))
            else:
                error = message.get("error") or {}
                raw_code = str(error.get("code") or DshCompatCode.RUNTIME_THROW.value)
                try:
                    code = DshCompatCode(raw_code)
                except ValueError:
                    # A runner-side code the host has no enum for (e.g. a
                    # plugin-thrown ``DSH_TOOL_THROW``) must still fail the
                    # call instead of killing the reader thread.
                    code = DshCompatCode.RUNTIME_THROW
                holder.append(
                    DshCompatError(
                        code,
                        str(error.get("message") or "runner reported failure"),
                        details={**error, "runner_code": raw_code},
                    )
                )
            event.set()
        # stdout closed: fail everything still waiting
        with self._pending_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for event, holder in pending:
            holder.append(
                DshCompatError(
                    DshCompatCode.PROCESS_EXIT,
                    f"plugin {self.plugin_id} runner exited",
                    details={"stderr": self.stderr_tail[-1200:]},
                )
            )
            event.set()

    def _answer_host_request(self, message: Mapping[str, Any]) -> None:
        request_id = message.get("id")
        method = str(message.get("method") or "")
        params = message.get("params") or {}
        try:
            result = self._on_host_request(method, params)
            response = {"id": request_id, "ok": True, "result": result}
        except Exception as exc:  # pragma: no cover - defensively answered
            response = {
                "id": request_id,
                "ok": False,
                "error": {"code": DshCompatCode.HOST_API_UNSUPPORTED.value, "message": str(exc)},
            }
        try:
            with self._write_lock:
                process = self._process
                if process is not None and process.stdin is not None:
                    process.stdin.write(json.dumps(response, ensure_ascii=False) + "\n")
                    process.stdin.flush()
        except (OSError, ValueError):
            pass

    def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        for raw in process.stderr:
            line = raw.rstrip()
            if not line:
                continue
            self._stderr.append(line)
            logger.debug("dsh[%s] %s", self.plugin_id, line[:400])

    def wait_ready(self, *, timeout: float = 1.0) -> None:
        """Give the child a moment to boot; the mount request is the real gate."""

        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.alive:
                raise DshCompatError(
                    DshCompatCode.PROCESS_EXIT,
                    f"plugin {self.plugin_id} runner exited during boot",
                    details={"stderr": self.stderr_tail[-1200:]},
                )
            return
