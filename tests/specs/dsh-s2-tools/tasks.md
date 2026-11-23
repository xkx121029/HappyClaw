# S2 任务清单

对应规格：[spec.md](./spec.md)。按顺序执行，每步可单独验证。

- [ ] T1 新增 `src/octop/infra/dsh/tools/__init__.py`（仅导出，无导入期副作用）
- [ ] T2 新增 `gate.py`：`blocking_permissions` / `is_tool_plugin` / 原因常量
  - 阻断权限：`fs.write` / `exec` / `network`
- [ ] T3 新增 `discovery.py`：`DshToolSkip`（含 `tool` 字段）/ `DiscoveredPlugin` / `discover_dsh_plugins`
  - 只调 `MarketInstallSource.installed_slots()` + `.broken()` 与 `DshPluginLoader.discover()`
  - **发现阶段剔除**非 tool 能力与写/执行/外联插件，只产跳过记录
  - market 根缺失 → `market_root_missing`；账本无 current → `market_slot_unreadable`；源异常 → `discovery_failed`；一律不抛
  - market 优先，本地同 id 记 `duplicate_plugin_id`
- [ ] T4 新增 `guardrail.py`：`build_read_only_guardrail(hitl=...)`
  - `approval=None` 时高危 → `TOOL_APPROVAL_UNAVAILABLE`（拒绝而非放行）
- [ ] T5 新增 `catalog.py`：`DshToolBuild` / `ToolProvider` / `build_dsh_plugin_tools`
  - 每插件独立 `DshToolRegistry(plugin_id=envelope.id)`
  - 全量经过 `build_pipeline(guardrail=...)`，不存在绕过分支
  - 冲突 → `name_conflict`，同时留 `plugin_id` 与 `tool`，不覆盖、不加二次前缀
  - 外层兜异常：返回空结果 + `discovery_failed`，绝不让配置构建失败
- [ ] T6 改 `src/octop/infra/agents/manager.py`
  - `__init__`：`_dsh_tool_providers = {}`、`_dsh_tools_status = None`
  - 插入点：`merged_tools.extend(plugin_tools)` 后一个 `# dsh:stage-tools` 块
  - 新增 `register_dsh_tool_provider()`（可选注入）/ `_dsh_plugin_tools()` / `dsh_tools_status()`
  - 模块级 `_dsh_local_roots()`；顶层不 import `octop.infra.dsh.tools`
- [ ] T7 测试 `tests/unit/infra/dsh/test_tools_discovery.py`（8 条）
- [ ] T8 测试 `tests/unit/infra/dsh/test_tools_mount.py`（8 条）
- [ ] T9 测试 `tests/unit/infra/dsh/test_tools_switch.py`（3 条，含 `sys.modules` 证明）
- [ ] T10 测试 `tests/dsh_integration/test_tools_end_to_end.py`（模型 tool_call → 执行 → 结果回对话）
- [ ] T11 跑验收命令并贴结果：
  `.\.venv\Scripts\python.exe -m pytest tests/unit/infra/dsh tests/unit/dsh tests/unit/plugins_bridge tests/dsh_integration -q`

## 完成标准

1. 四组测试全绿，新增用例全部通过。
2. 关闭态：`octop.infra.dsh.tools*` 不在 `sys.modules`，`merged_tools` 无变化。
3. provider 未注入时行为与现状一致（零新增工具）。
4. `dsh_tools_status()` 对每个未挂载插件给出 `reason`，冲突/定义类另带 `tool`。
5. 未修改 `happyclaw_harness` 包，未改 `dashboard/`，未新增依赖。
