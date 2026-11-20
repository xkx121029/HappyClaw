# S12 任务清单

依赖顺序从上到下；每项完成即勾选并记录证据（命令/输出/文件路径）。

## T1 安装根与配置存储
- [x] `PathLayout.market_dir` + `default_market_root()`。
- [x] `PluginManager.dsh_source_urls/add_dsh_source/remove_dsh_source`，写入 `config.json.plugin_market.dsh_sources`（原子合并）。
- [x] 校验：http(s) 或存在的绝对路径、去重、上限 20、非法值报错。
- 验收：临时 `OCTOP_HOME` 下增删后重启仍保留（`.tmp/s12-home/config.json` 实测保留）。

## T2 运行态探针
- [x] `_node_dependency_gaps(slot)`：`package.json.dependencies` vs `node_modules/<dep>`。
- [x] `_dsh_runtime_status(plugin_id)` 六分支（missing ledger / broken / missing deps / entry missing / engine unsatisfied / not granted / visible）。
- [x] 复用 `discover_dsh_plugins`、`host_node_version`、`version_satisfies`、`resolve_exec_plugins`。
- 验收：单测覆盖六分支，错误码与 spec §2.4 一致。

## T3 Manager 市场方法
- [x] `_dsh_index()`：每次新建 `MarketplaceIndex([DshSource(...)])`。
- [x] `list_dsh_market(language)`：逐源容错，返回 sources + entries + runtime。
- [x] `install_dsh_market` / `upgrade_dsh_market` / `uninstall_dsh_market`：走 pipeline，返回 install_dir、cleaned、remaining_versions。
- [x] 安装/升级后重新计算 runtime，返回 `status=installed|installed_not_ready|upgraded|upgraded_not_ready`。
- 验收：单测用本地 fixture 完成 install→upgrade→uninstall。
  > ✅ 复验通过（2026-11-14，修复后）：`pytest tests/unit/plugins/market tests/unit/api/test_plugins_dsh_market.py -q`
  > → **67 passed**（13.87s）。
  > 复核结论：install/upgrade/uninstall 用例本身没有依赖问题——
  > `tests/fixtures/dsh_market/serve.py:120-128` 的 `needs-dep` 是**故意**的缺依赖失败 fixture，
  > 本用例用的是 `test_manager_dsh_market.py` 的 `_bundle()`，其 `package.json` 没有 `dependencies`。
  > 本轮真正的红是 `test_plan.py` 四例（`capabilities_before/after` 全空）：`conftest.dsh_package()`
  > 已把能力写在 `package.json` 顶层（运行态 `runtime/dsh_plugin.py:345` 读的也是顶层），
  > 而安装信封 `market/envelope.py:_capabilities()` 只读 `dsh.bundle.capabilities`，
  > 导致装完记录不到能力、升级的能力扩张保护失效。已在 `envelope.py` 同时接受顶层与旧嵌套写法。
  > 「市场只解包、不执行 `npm install`」是既定设计（`spec.md:17`），未改市场行为。

## T4 API 路由
- [x] `GET /plugins/market/dsh`
- [x] `POST /plugins/market/dsh/sources`
- [x] `DELETE /plugins/market/dsh/sources`
- [x] `POST /plugins/market/dsh/install`
- [x] `POST /plugins/market/dsh/upgrade`
- [x] `DELETE /plugins/market/dsh/plugin`
- [x] `POST /plugins/market/dsh/refresh`
- [x] `MarketError.details` 完整透出；错误码映射写入 `details.market_code`。
- [x] 安装/卸载后 `agent_registry.reload_all()`（仅当 `app_runtime` 存在）。
- 验收：FastAPI TestClient 覆盖成功与失败路径；octop `/plugins/market` 回归测试不变。

## T5 前端 API 与类型
- [x] `plugins.ts` 新增类型与方法（spec §3.6）。
- 验收：`npx vite build` 通过；`npx tsc -b` 仍被工作树内与本任务无关的 Home 页既有类型错误阻断，未处理。

## T6 DSH 面板
- [x] `DshMarketPanel.tsx`：空态、源管理、错误 Alert、条目卡片、版本选择、安装/升级/卸载。
- [x] 安装后 `runtime.status !== "visible"` → warning + 错误码/原因，不显示成功 toast。
- [x] 卸载确认与 `cleaned=false` 提示。
- [x] `PluginMarketPanel.tsx` 顶部接入，octop 列表不改。
- [x] 样式追加到 `index.module.less`。
- [ ] 验收：5173 实际点击通过 —— 本会话浏览器不可用（`browser_navigate` = inactive execution round；browser_use 子代理 = client does not support browser subagent isolation），未完成点击，仅验证 dev server 模块编译与接口。

## T7 文案
- [x] `zh.json` / `en.json` 新增 `plugins.dsh.*`（清单见 spec §4）。
- 验收：切换语言无缺失键（两侧键集合一致）。

## T8 Fixture 与测试
- [x] `tests/fixtures/dsh_market/` 四个索引。
- [x] HTTP fixture server + 动态 tgz（`serve.py`）。
- [x] `test_dsh_source_store.py`、`test_manager_dsh_market.py`、`test_plugins_dsh_market.py`。
- 验收：`pytest` 15 passed，坏索引断言 code + path。
  > ✅ 复验（2026-11-14，修复后）：`pytest tests/unit/plugins/market tests/unit/api/test_plugins_dsh_market.py -q`
  > → **67 passed**；坏索引三条（format / 非精确 semver / file 源相对 icon）断言 code + path 均通过。

## T9 端到端与打包
- [x] fixture + 后端 + 前端同时运行（8765/8088 被占用，实际使用 8790 fixture + 8098 后端 + 5173 前端），按 spec §5.2 走完接口流程。
- [x] 文件系统确认卸载清理（1.1.0 卸载后残留 1.0.0、cleaned=false；1.0.0 卸载后目录删除、cleaned=true）。
- [x] `npx vite build` 更新 assets；`pip wheel .` 检查 wheel（含新 chunk 与 `market/sources/dsh.py`）。
- 验收：目录列表/接口输出留证；已向调用方报告「界面已可运行」。
- [ ] 浏览器逐项点击（见 T6 验收说明）。

## T10 收尾
- [x] 汇总改动文件、测试结果、已知限制（静态依赖检查只覆盖直接依赖；`visible` 不等于实测可执行）。
- [x] 确认未 commit / 未 push（HEAD 仍为 `fccc2377`）。

## 复验记录（2026-11-14，修复后）

| 命令 | 结果 |
| --- | --- |
| `pytest tests/unit/plugins/market tests/unit/api/test_plugins_dsh_market.py -q` | **67 passed**（修复前 63 passed / 4 failed，4 例均为 `test_plan.py` 的能力字段） |
| `pytest tests/unit/infra/dsh/test_tools_switch.py -q` | **7 passed**（修复前 5 passed / 2 failed） |
| `pytest tests/unit --collect-only -q` | **5275 tests collected**，退出码 0 |
| `pytest tests/unit/device_link tests/unit -q -k "device_link or tool_catalog or hitl"` | **194 passed, 5081 deselected** |

### 本轮修复（均为最小改动，未提交、未打包、未动暂存区）

1. `src/octop/infra/plugins/market/envelope.py`：`_capabilities()` 改为同时读取 `package.json` 顶层
   `capabilities`（`str` 逗号分隔或 `list`）与旧的 `dsh.bundle.capabilities`，新增 `_capability_list()`。
   修掉 `test_plan.py` 四例「装完 capabilities 为空 → 能力扩张保护失效」。
2. `tests/unit/infra/dsh/test_tools_switch.py`：两条断言 skip 列表的用例改为把 `OCTOP_DSH_MARKET_ROOT`
   指向一个**已存在但为空**的临时目录，避免 `market_root_missing` 混入。
   依据：`tests/specs/dsh-s2-tools/spec.md:92` 明确「market_root 不存在 → `market_root_missing`，返回空候选，不抛」，
   且 `tests/unit/infra/dsh/test_tools_discovery.py:57` 已固定该行为——属既定设计，测试期望落后于实现。
3. `tests/unit/device_link/__init__.py`（空文件）：消除与 `tests/unit/agents/test_agent_tools.py` 的同名模块冲突。

