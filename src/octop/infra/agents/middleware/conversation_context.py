"""Per-turn grounding block: what this conversation already knows.

HappyClaw should sound like it *remembers*, not like it was just told. The memory
middleware already recalls facts; this block adds the framing facts a user can
verify at a glance — the local clock, which expert / project / workspace this turn
runs in, which files changed recently, which conversations are warm, and what is
scheduled.

Every line is read from the database or the workspace on disk. Nothing is
inferred, so the model can point at a path, date or name instead of claiming to
remember something it never saw.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage
from langgraph.config import get_config

from octop.infra.agents.middleware.thread_artifacts import current_thread_id
from octop.infra.projects.session import QUICK_KIND, SESSION_KIND

__all__ = ["ConversationContextMiddleware", "render_context_block"]

# Workspace entries that belong to the product, not to the user's work.
_SYSTEM_FILES = frozenset(
    {
        "AGENTS.md",
        "BOOTSTRAP.md",
        "SOUL.md",
        "IDENTITY.md",
        "MEMORY.md",
        "USER.md",
        "PROACTIVE.md",
    }
)
_SYSTEM_DIRS = frozenset(
    {".octop", ".git", ".cache", "node_modules", "_builtin_skills", "inbound", "outbound", "skills"}
)
_MAX_SCAN_ENTRIES = 400
_MAX_RECENT_FILES = 6

_RULES_ZH = """<conversation-context-rules>
这份上下文只在本轮确实相关时使用：
- 提就提具体的：文件名或路径、日期、原话里的决定、会话标题。不要只说「我记得你的项目」这类空话。
- 一次最多自然带出一两条，其余留白；用户没问、也不影响当前动作时，不要罗列。
- 这里的 now / scope / workspace / recent files / scheduled 是每轮从磁盘和数据库真实读到的，可以直接当事实说，不必附加「我没有核实」之类的免责。
- 没出现在这里、对话历史和 <memory-context> 里也没有的，就直说「我这边没有记录」，不要补全细节。
- 引用「近期会话」时，标题只能证明聊过这个话题；结论要来自 memory 或你实际读到的内容，否则先确认再下结论。
</conversation-context-rules>"""

_RULES_EN = """<conversation-context-rules>
Use this context only when it is genuinely relevant to this turn:
- Be specific: file name or path, date, the decision as it was worded, conversation title. Never open with vague lines like "I remember your project".
- Surface at most one or two items naturally; leave the rest out. Do not list anything the user did not ask about and that does not affect the current action.
- now / scope / workspace / recent files / scheduled below were read from disk and the database this turn; state them as facts without adding "I haven't verified" disclaimers.
- Anything absent here and from the conversation history and <memory-context> gets "I don't have that on record" instead of a filled-in guess.
- A title under "recent conversations" only proves the topic was discussed; conclusions must come from memory or from content you actually read. Confirm before asserting.
</conversation-context-rules>"""


class _ThreadLookup(Protocol):
    def get(self, thread_id: str) -> Any | None: ...

    def list_by_agent(self, *, agent_id: str, limit: int = 50) -> list[Any]: ...


class _ProjectLookup(Protocol):
    def get(self, project_id: str) -> Any | None: ...


class _Paths(Protocol):
    def session_root(self, thread_id: str) -> Path: ...

    def project_root(self, project_id: str) -> Path: ...


@dataclass
class _CacheEntry:
    text: str
    built_at: float


class ConversationContextMiddleware(AgentMiddleware[Any, Any]):
    """Append a verifiable snapshot of the current conversation's world.

    The snapshot is cached per thread for ``ttl_seconds`` so one turn plus its
    tool loop does not rescan the workspace on every model call.
    """

    def __init__(
        self,
        *,
        thread_repo: _ThreadLookup,
        project_repo: _ProjectLookup,
        paths: _Paths,
        agent_id: str,
        agent_name: str,
        workspace_dir: Path,
        default_timezone: str = "UTC",
        cron_manager: Any = None,
        ttl_seconds: float = 90.0,
    ) -> None:
        super().__init__()
        self._thread_repo = thread_repo
        self._project_repo = project_repo
        self._paths = paths
        self._agent_id = agent_id
        self._agent_name = agent_name
        self._workspace_dir = Path(workspace_dir).expanduser()
        self._default_timezone = default_timezone
        self._cron_manager = cron_manager
        self._ttl_seconds = ttl_seconds
        self._cache: dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()

    # -- model hooks -----------------------------------------------------
    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        return handler(_append_block(request, self._block()))

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        return await handler(_append_block(request, self._block()))

    # -- rendering -------------------------------------------------------
    def _block(self) -> str:
        thread_id = current_thread_id()
        cache_key = thread_id or f"{self._agent_id}:{id(self)}"
        now = time.monotonic()
        with self._lock:
            entry = self._cache.get(cache_key)
            if entry is not None and now - entry.built_at < self._ttl_seconds:
                return entry.text
        text = self._render(thread_id)
        with self._lock:
            self._cache[cache_key] = _CacheEntry(text=text, built_at=now)
            if len(self._cache) > 64:
                self._cache.clear()
                self._cache[cache_key] = _CacheEntry(text=text, built_at=now)
        return text

    def _render(self, thread_id: str) -> str:
        thread = self._thread(thread_id)
        tz = self._timezone()
        lines = [f"now: {_fmt_now(tz)}", f"expert: {self._agent_name or self._agent_id}"]

        workspace, scope = self._workspace(thread_id, thread)
        if scope:
            lines.append(f"scope: {scope}")
        if workspace is not None:
            lines.append(f"workspace: {workspace}")

        recent = _recent_files(workspace, tz) if workspace is not None else []
        if recent:
            lines.append("recent files:")
            lines.extend(f"- {item}" for item in recent)

        warm = self._recent_threads(thread_id)
        if warm:
            lines.append("recent conversations:")
            lines.extend(f"- {item}" for item in warm)

        jobs = self._scheduled_jobs(tz)
        if jobs:
            lines.append("scheduled:")
            lines.extend(f"- {item}" for item in jobs)

        body = "<conversation-context>\n" + "\n".join(lines) + "\n</conversation-context>"
        return f"{body}\n\n{self._rules()}"

    def _rules(self) -> str:
        raw = str(self._configurable().get("locale") or "").strip().lower()
        return _RULES_ZH if raw.startswith("zh") else _RULES_EN

    def _timezone(self) -> ZoneInfo:
        name = (
            str(self._configurable().get("timezone") or "").strip()
            or (self._default_timezone or "").strip()
        )
        try:
            return ZoneInfo(name) if name else datetime.now().astimezone().tzinfo  # type: ignore[return-value]
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")

    @staticmethod
    def _configurable() -> dict[str, Any]:
        """Runnable config for this call; empty outside a graph run (unit tests)."""
        try:
            return dict(get_config().get("configurable") or {})
        except RuntimeError:
            return {}

    def _thread(self, thread_id: str) -> Any | None:
        if not thread_id:
            return None
        try:
            return self._thread_repo.get(thread_id)
        except Exception:  # pragma: no cover - legacy rows
            return None

    def _workspace(self, thread_id: str, thread: Any | None) -> tuple[Path | None, str]:
        """Resolve the directory this turn really writes to, plus a human scope line."""
        if thread is not None:
            # Quick chat runs without a workspace on purpose: never fall back to
            # the expert home directory, or the model would claim files it cannot read.
            if (getattr(thread, "workspace_kind", "") or "") == QUICK_KIND:
                return None, "quick chat (no workspace)"
            project_id = str(getattr(thread, "project_id", "") or "").strip()
            if project_id:
                try:
                    project = self._project_repo.get(project_id)
                except Exception:  # pragma: no cover - legacy schemas
                    project = None
                name = str(getattr(project, "name", "") or project_id)
                raw_root = str(getattr(project, "root_dir", "") or "").strip()
                root = Path(raw_root) if raw_root else self._paths.project_root(project_id)
                return root, f"project {name}"
            if (getattr(thread, "workspace_kind", "") or "") == SESSION_KIND:
                return self._paths.session_root(
                    thread_id
                ), "temporary session workspace (no project)"
            raw_dir = str(getattr(thread, "workspace_dir", "") or "").strip()
            if raw_dir:
                return Path(raw_dir), "thread workspace"
        return self._workspace_dir, ""

    def _recent_threads(self, thread_id: str) -> list[str]:
        try:
            rows = self._thread_repo.list_by_agent(agent_id=self._agent_id, limit=12)
        except Exception:  # pragma: no cover - legacy schemas
            return []
        items: list[str] = []
        seen_titles: set[str] = set()
        for row in sorted(rows, key=lambda r: int(getattr(r, "last_active", 0) or 0), reverse=True):
            if str(getattr(row, "thread_id", "")) == thread_id:
                continue
            title = str(getattr(row, "title", "") or "").strip()
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)
            stamp = _fmt_ts(int(getattr(row, "last_active", 0) or 0), self._timezone())
            items.append(f"{_quote(title)} ({stamp})")
            if len(items) >= 5:
                break
        return items

    def _scheduled_jobs(self, tz: ZoneInfo) -> list[str]:
        if self._cron_manager is None:
            return []
        try:
            rows = self._cron_manager.list_by_agent(self._agent_id)
        except Exception:  # pragma: no cover - optional subsystem
            return []
        items: list[str] = []
        for row in rows:
            if not int(getattr(row, "enabled", 0) or 0):
                continue
            name = str(getattr(row, "name", "") or getattr(row, "cron_id", "") or "").strip()
            trigger = str(getattr(row, "trigger", "") or "").strip()
            next_at = getattr(row, "next_run_at", None)
            detail = f"{name} — {trigger}" if trigger else name
            if next_at:
                detail += f" (next {_fmt_ts(int(next_at), tz)})"
            items.append(detail)
            if len(items) >= 4:
                break
        return items


def _append_block(request: ModelRequest[Any], block: str) -> ModelRequest[Any]:
    if not block:
        return request
    base = request.system_message.text if request.system_message is not None else ""
    content = f"{base}\n\n{block}" if base else block
    return request.override(system_message=SystemMessage(content=content))


def _recent_files(root: Path, tz: ZoneInfo, limit: int = _MAX_RECENT_FILES) -> list[str]:
    """Recently modified user files, newest first, with relative paths."""
    try:
        if not root.is_dir():
            return []
    except OSError:
        return []
    found: list[tuple[float, str]] = []
    seen = 0
    try:
        stack = [(root, 0)]
        while stack and seen < _MAX_SCAN_ENTRIES:
            directory, depth = stack.pop()
            try:
                entries = list(directory.iterdir())
            except OSError:
                continue
            for entry in entries:
                seen += 1
                if seen >= _MAX_SCAN_ENTRIES:
                    break
                name = entry.name
                if name.startswith(".") or name in _SYSTEM_FILES:
                    continue
                try:
                    if entry.is_dir():
                        if name in _SYSTEM_DIRS or depth >= 1:
                            continue
                        stack.append((entry, depth + 1))
                        continue
                    stat = entry.stat()
                except OSError:
                    continue
                try:
                    rel = entry.relative_to(root).as_posix()
                except ValueError:
                    continue
                found.append((stat.st_mtime, rel))
    except OSError:
        return []
    found.sort(reverse=True)
    return [
        f"{rel} ({datetime.fromtimestamp(mtime, tz).strftime('%Y-%m-%d %H:%M')})"
        for mtime, rel in found[:limit]
    ]


def _fmt_now(tz: ZoneInfo) -> str:
    now = datetime.now(tz)
    weekdays = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    label = getattr(tz, "key", None) or getattr(tz, "tzname", None) or "local"
    return f"{now.strftime('%Y-%m-%d')} {weekdays[now.weekday()]} {now.strftime('%H:%M')} ({label})"


def _fmt_ts(ts: int, tz: ZoneInfo) -> str:
    if not ts:
        return "unknown time"
    return datetime.fromtimestamp(ts, tz).strftime("%Y-%m-%d %H:%M")


def _quote(text: str) -> str:
    return text if text.startswith(("「", '"')) else f"「{text}」"
