# 实施任务：插件界面扩展平台 v1

依赖顺序执行；每完成一组先自检，再进入下一组。全部不提交。

## T0 对外文档与信任模型提示

- [x] `docs/plugin-ui-surfaces.md`：规范正文，含 slot/data/event、错误码、卸载语义。
- [ ] 管理页（已安装/市场）显示「插件界面为同源受信代码，非沙箱」提示。
- [ ] DSH 条目显示「无界面扩展」原因码与解释，不呈现为故障。

## T1 后端 manifest 与能力清单

- [ ] `src/octop/infra/agents/plugins/manager.py`
  - 扩展 `parse_plugin_ui_meta`：解析 `ui.surfaces`，校验 `id/slot/title`，返回 `supported`、`reason_code`。
  - 新增常量 `PLUGIN_UI_SLOTS = ("home.sidebar", "chat.header")` 与 `PLUGIN_UI_DATA_DOMAINS`、`PLUGIN_UI_EVENTS`。
- [ ] `src/octop/api/routers/plugins.py`：新增 `GET /plugins/ui/capabilities`。
- 验收：`GET /api/plugins` 带出 `ui.surfaces`；未知 slot 返回 `supported=false` 且不影响插件加载。

## T2 内置市场源与一键装载

- [ ] `manager.py`
  - `_bundled_plugin_rows(language)`：读 `default_bundled_plugins_root()` 下每个含 `plugin.yaml` 的目录，生成 `MarketPlugin` 行（`source:"bundled"`、`install_kind:"bundled"`、installed/version/update 状态）。
  - `list_market`：合并内置行；portal 失败且内置非空时返回内置行。
  - `install_bundled(plugin_id, force=False)`：路径白名单 + `copytree` + 校验 + `_load_plugin_dir(install_deps=False)` + 启用。
- [ ] `plugins.py`：新增 `POST /plugins/market/bundled/{plugin_id}/install?force=`。
- 验收：全新 `OCTOP_HOME` 可装载；重复装载给 `force` 语义；未知 id 返回 404。

## T3 DSH 能力差异

- [ ] `manager.py` 的 `_dsh_runtime_status`：所有返回的 `status` 加 `surface_supported=false`、`surface_reason_code="DSH_UI_SURFACE_UNSUPPORTED"`、`surface_reason`。
- [ ] `dashboard/src/api/modules/plugins.ts`：`DshRuntimeStatus` 补三个字段。
- [ ] `DshMarketPanel.tsx`：市场与已安装条目显示「无界面扩展」标签与原因。
- 验收：DSH 状态接口/列表返回三字段；前端不把 DSH 当作可挂界面插件。

## T4 前端 surface 运行时

- [ ] 新增 `dashboard/src/plugins/surfaces/`
  - `types.ts`：slot/data/event 类型与 surface 注册类型。
  - `registry.ts`：按 `pluginId` 注册/注销、按 slot 查询、`useSyncExternalStore` 版本号。
  - `data.ts`：`runtime.activity`、`sessions.running`、`plugins.installed`、`host.context` 的读取、轮询、差分事件；引用计数，无订阅停止。
  - `SurfaceBoundary.tsx`：单个 surface 错误隔离。
  - `PluginSurfaceSlot.tsx`：排序渲染、空态不占位、`data-plugin-surface` 标记。
  - `index.ts`：导出。
- [ ] `toolRenderers/types.ts`：`OctopPluginUIHost` 增加 `apiVersion/surfaces/data/events/context`；`setup` 可返回清理函数。
- [ ] `toolRenderers/host.ts`：实现新接口，旧成员不变。
- [ ] `toolRenderers/loader.ts`：保存/调用 setup 清理函数；`resetPluginUiLoader` 增加 `unregisterPluginSurfaces`。
- [ ] `Home/index.tsx`：`<aside className={styles.side}>` 内会话盒后挂 `<PluginSurfaceSlot slot="home.sidebar" />`。
- [ ] `Chat/index.tsx`：`<MessageList>` 上方挂 `<PluginSurfaceSlot slot="chat.messages.top" />`。
- 验收：手写一个临时 surface 能在首页出现，卸载后消失。

## T5 首个插件 task-progress-monitor

- [ ] `src/octop/infra/agents/plugins/bundled/task-progress-monitor/plugin.yaml`
- [ ] `.../main.py`：`setup(ctx)` 注册只读工具 `task_progress_about`。
- [ ] `.../ui/dist/manifest.json`
- [ ] `.../ui/dist/index.js`：自包含 ESM；订阅数据；列表/计数/空态；返回 dispose。
- 验收：装后首页出现卡片，3s 刷新；卸后目录删除、卡片消失。

## T6 市场与管理页

- [ ] `PluginMarketPanel.tsx`：内置标签、按 `source` 选安装接口、已安装可卸载、操作后刷新。
- [ ] `InstalledPluginsPanel.tsx`：展示 `ui.surfaces` 挂载位置与不支持原因。
- [ ] i18n（`dashboard/src/i18n` 对应 zh/en 文件）：新增标签与提示文案。
- 验收：市场可浏览/装载/卸载；portal 不可达时内置条目仍可见。

## T7 测试与实测

- [ ] `tests/unit/plugins/test_ui_surfaces.py`
- [ ] `tests/unit/api/test_plugins_ui.py`
- [ ] DSH 现有测试补 surface 字段断言
- [ ] `dashboard/src/plugins/surfaces/registry.test.ts`、`loader.test.ts`
- [ ] 运行：
  - `.\.venv\Scripts\python.exe -m pytest tests/unit/plugins tests/unit/api/test_plugins_ui.py tests/unit/test_plugin_manager.py -q`
  - `cd dashboard; npx tsc --noEmit`
  - `npm run test -- --run src/plugins/surfaces`
- [ ] 隔离实例：全新 `OCTOP_HOME` 启动，API 安装/卸载；浏览器实点首页与市场。
- [ ] 清理临时目录与后台进程；确认 `git status` 无无关改动。
