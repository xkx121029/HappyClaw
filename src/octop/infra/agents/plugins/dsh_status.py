"""Read-only DSH status views for the admin page."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from octop.infra.agents.plugins.constants import (
    DSH_DEFAULT_SOURCES,
    DSH_STATUS_SCHEMA_VERSION,
    DSH_UI_SURFACE_REASON,
    DSH_UI_SURFACE_REASON_CODE,
)
from octop.infra.agents.plugins.manager_base import PluginManagerBase
from octop.infra.agents.plugins.node_deps import (
    _node_dependency_gaps,
    _node_engine_problem,
    _probe_dsh_entry,
)
from octop.infra.utils.json_file import (
    JsonFileCorruptError,
    read_json_object,
)


class DshStatusMixin(PluginManagerBase):
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
            "generated_at": datetime.now(UTC).isoformat(),
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

        grants = dict.fromkeys(resolve_exec_plugins(), "host exec grant")
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
