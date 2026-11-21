"""Plugin catalogue and DSH market tunables."""

from __future__ import annotations

import re
from typing import Any

PLUGINS_ENABLED = "plugins.enabled"

PLUGINS_REVISION = "plugins.revision"

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

DSH_UI_SURFACE_REASON_CODE = "DSH_UI_SURFACE_UNSUPPORTED"

DSH_UI_SURFACE_REASON = "DSH 插件没有 HappyClaw 界面扩展入口，仅参与运行时"

DSH_SOURCES_LIMIT = 20

DSH_DEFAULT_SOURCES: tuple[str, ...] = (
    "https://cdn.dsh.so/market/index.json",
    "https://cdn.jsdelivr.net/npm/dsh-plugin-catalog/index.json",
    "https://dshopen.org/index.json",
)

DSH_MARKET_PAGE_SIZE = 50

DSH_MARKET_MAX_PAGE_SIZE = 200

DSH_MARKET_CACHE_TTL_SECONDS = 120.0

DSH_STATUS_SCHEMA_VERSION = 1

DSH_INDEX_FETCH_TIMEOUT_SECONDS = 20.0

DSH_SOURCE_BUDGET_SECONDS: dict[str, float] = {
    "https://cdn.jsdelivr.net/npm/dsh-plugin-catalog/index.json": 45.0,
}

DSH_SOURCE_ATTEMPTS = 2

DSH_SOURCE_RETRY_BACKOFF_SECONDS = 0.8

DSH_SOURCE_BACKGROUND_BUDGET_SECONDS = 180.0

DSH_SOURCE_FETCH_WORKERS = 4

DSH_MARKET_SNAPSHOT_DEADLINE_SECONDS = 15.0

DSH_INDEX_CACHE_DIRNAME = ".dsh-index-cache"

DSH_DEP_INSTALL_TIMEOUT_SECONDS = 600.0

DSH_PROBE_TIMEOUT_SECONDS = 30.0

DSH_PROGRESS_HISTORY = 20

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

_ICON_FILE_SUFFIXES = {".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif"}

_MARKET_ASSET_SUFFIXES = frozenset({".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif"})

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

_CHANNEL_FINGERPRINTS: dict[str, str] = {}
