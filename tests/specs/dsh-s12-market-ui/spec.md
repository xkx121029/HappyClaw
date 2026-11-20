# S12 — DSH 插件源接入「插件管理 → 插件市场」

状态：待批准（批准后进入实现）
范围：把已存在但未接线的 `DshSource` / `MarketplaceIndex` 接入应用层与界面；不改变 octop portal 市场既有行为。

## 1. 目标与边界

### 目标
1. `~/.octop/config.json` 持久化多条 DSH 索引源，可增、删、刷新。
2. 提供 DSH 专属 API：源管理、条目列表、安装、升级、卸载。
3. 插件市场界面新增「DSH 插件源」区块：空态说明、源管理、条目与版本、安装/升级/卸载、卸载清理确认。
4. 诚实性：安装成功但运行时不满足条件时，界面显示真实错误码与原因，不显示成普通成功。

### 明确不做
- 不把 DSH 条目混进 `GET /plugins/market`（octop portal 列表）。
- 不修改 `install_from_market` / `list_market` / `DELETE /plugins/{id}` 的现有语义。
- 不执行 `npm install`，不联网补依赖闭包；只如实报告缺口。
- 不伪造 DSH 官方索引地址；验证一律使用本地 fixture。
- 不 commit / push。

## 2. 关键设计决策

### 2.1 持久化
- 位置：现有 `PluginManager._config_path`（即 `~/.octop/config.json`），新增键：
  ```json
  { "plugin_market": { "dsh_sources": ["https://example.com/index.json"] } }
  ```
- 读写方式沿用 `_read_global_plugins` / `_write_global_plugin_enabled` 的模式：直接读取 JSON、原子合并写回，不进入 `OctopConfig` dataclass，避免影响配置加载。
- 归一化：去空白、去重、保序；仅接受 `http(s)://` URL 或**存在**的绝对本地路径（fixture 用）；上限 20 条；非法值抛 `OctopError(INVALID_ARGUMENT, details={"url": ...})`（若 `INVALID_ARGUMENT` 不存在则用 `VALIDATION_ERROR`，实现时以 `infra/errors.py` 现有枚举为准）。

### 2.2 安装根目录
- 新增 `PathLayout.market_dir = root / "market"`（`~/.octop/market`）。
- `PluginManager.dsh_market_root()`：`OCTOP_DSH_MARKET_ROOT` 优先，否则 `self._config_path.parent / "market"`。
- 安装布局由 pipeline 负责：`<market_root>/dsh/<native>/index.json` + `<version>/`。
- octop 插件仍在 `~/.octop/plugins/<id>`，两套目录互不影响。

### 2.3 让安装结果真正可被发现
- `infra/agents/manager.py:903` 当前只读 `OCTOP_DSH_MARKET_ROOT`，未设置时 `None`。
- 改为：`market_root=os.environ.get("OCTOP_DSH_MARKET_ROOT") or str(default_market_root())`。
- `default_market_root()` 放在 `octop/infra/plugins/market/__init__.py`（或 `market_source.py`），返回 `PathLayout.from_env().root / "market"`，供 manager 与 API 共用，避免两处路径漂移。
- 该改动只影响 DSH 发现：目录不存在时 `discover_dsh_plugins` 只产出一条 skip，不影响启动。

### 2.4 运行时就绪状态（诚实性核心）
新增 `PluginManager._dsh_runtime_status(plugin_id: str) -> dict`，只读，不 import 插件、不执行 JS。按顺序产出：

| 检查 | status | error_code | reason 示例 |
| --- | --- | --- | --- |
| 市场目录/账本缺失或 `current` 不可读 | `broken` | `TOOL_RUNTIME_PLUGIN_NOT_LOADED` | `账本指向的安装目录不存在：...` |
| slot 中 `package.json` 的 `dependencies` 非空，但缺少 `node_modules/<dep>` | `not_loaded` | `TOOL_RUNTIME_PLUGIN_NOT_LOADED` | `缺少 npm 依赖闭包：a, b；市场安装只解包，不执行 npm install` |
| `main`/`exports` 入口文件不存在 | `not_loaded` | `TOOL_RUNTIME_ENTRY_MISSING` | `入口文件不存在：lib/index.js` |
| `engines.node` 与宿主 Node 不满足 | `not_loaded` | `TOOL_RUNTIME_ENGINE_UNSATISFIED` | `宿主 Node 24.1.0 不满足 >=24.9.0` |
| `discover_dsh_plugins()` 拒绝该插件 | `not_visible` | 由 skip 原因映射：安全权限 → `TOOL_CAPABILITY_UNAVAILABLE`，其它 → `TOOL_RUNTIME_PLUGIN_NOT_LOADED` | skip 的 `detail` 原文 |
| 被 discovery 接纳，但未在 `OCTOP_DSH_EXEC_PLUGINS` 中授权且无 `tool` 能力 | `not_visible` | `TOOL_CAPABILITY_UNAVAILABLE` | `宿主未授予 exec（OCTOP_DSH_EXEC_PLUGINS 不含该插件）` |
| 被 discovery 接纳且可执行 | `visible` | `null` | `已对 Agent 可见；可执行性未在安装时实测` |

- `visible` **不叫 ready**：安装流程不会启动 Node，不宣称可执行。
- 直接依赖检查只覆盖 `package.json.dependencies` 的直接键，并在 reason 中写明这是静态检查。
- Node 版本探测复用 `octop.infra.dsh.tools.runtime.host_node_version` / `version_satisfies`，取 `OCTOP_DSH_NODE` 或 `node`；探测失败不阻塞安装，只标 `unknown`。

### 2.5 API 形状
所有路由沿用 `require_permission("plugin_market")`，放在 `api/routers/plugins.py` 末尾。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/plugins/market/dsh` | 源 + 条目 + 每条运行态 |
| POST | `/plugins/market/dsh/sources` | body `{url}`，返回全部源 |
| DELETE | `/plugins/market/dsh/sources?url=` | 返回全部源 |
| POST | `/plugins/market/dsh/install?plugin_id=&version=&force=` | 安装 |
| POST | `/plugins/market/dsh/upgrade?plugin_id=&version=&allow_capability_expansion=` | 升级/切版本 |
| DELETE | `/plugins/market/dsh/plugin?plugin_id=&version=` | 卸载 |
| POST | `/plugins/market/dsh/refresh` | 重新拉取并返回同 GET 结构 |

- 用查询参数承载 `plugin_id`，避免 `dsh:scope__name` 的路径转义歧义。
- `GET` 响应：
  ```json
  {
    "market_root": "C:\\Users\\x\\.octop\\market",
    "sources": [{
      "url": "...", "status": "ok|error",
      "error": {"code": "PLUGIN_SOURCE_UNREACHABLE", "message": "...", "details": {}},
      "entry_count": 2, "diagnostics": "", "fetched_at": "2026-11-14T10:00:00Z"
    }],
    "entries": [{
      "plugin_id": "dsh:demo", "package_name": "dsh-plugin-demo",
      "name": "...", "description": "...", "icon": "https://.../icon.png",
      "tags": [], "homepage": null, "source_url": "...",
      "versions": ["1.1.0", "1.0.0"], "recommended_version": "1.1.0",
      "installed": true, "installed_version": "1.0.0", "update_available": true,
      "runtime": {
        "status": "not_loaded", "visible_to_agents": false, "executable": false,
        "error_code": "TOOL_RUNTIME_PLUGIN_NOT_LOADED", "reason": "...", "notes": []
      }
    }]
  }
  ```
- 单源失败不隐藏其它源：每个源独立 `fetch_index()`，错误进该源 `error`；条目来自成功源。
- 索引整体非法（`format != 1`、版本非法、重复名、相对 icon 无法解析）→ 该源 `status=error`，`error.code` 为 `PLUGIN_MANIFEST_INVALID` / `PLUGIN_INDEX_UNUSABLE`，`details.path` 保留 `IndexFormatError.path`，`message` 保留原文。**不静默丢条目**。
- 安装/升级/卸载失败：抛 `OctopError`，`details` 合并 `MarketError.details`（含 `market_code`、`path`、`rejected`、`dependents`）。装成功但 `runtime.status != "visible"` 时 HTTP 200，响应体带 `status="installed_not_ready"` 与 `runtime`，由前端按失败样式提示。
- 卸载返回：
  ```json
  { "plugin_id": "dsh:demo", "version": "1.0.0",
    "install_dir": "...", "cleaned": true, "remaining_versions": [] }
  ```
  `cleaned` = 卸载后 `market_root/dsh/<native>` 已不存在。仍有其它版本时 `cleaned=false` 并列出。

### 2.6 前端
- 新组件 `dashboard/src/pages/Admin/Plugins/DshMarketPanel.tsx`，在 `PluginMarketPanel.tsx` 顶部渲染，与 octop 列表视觉分隔（标题 + `Divider`）。
- 空态（无源）：`Empty` + 文案明确「DSH 官方不提供索引；请填写静态 JSON 地址（format 1）」+「添加索引」按钮 + 折叠的格式示例（`format/title/plugins[].versions[]`）。
- 源卡片：URL、`entry_count`、`fetched_at`、删除按钮；`status=error` 时展示 `Alert`，包含 `error.code` 与 `error.message`（`IndexFormatError.path` 一并显示）。
- 条目卡片：图标、名称、`plugin_id`、描述、标签、版本选择（默认 `recommended_version`）、安装/升级/卸载按钮、状态 Tag。
- 安装后：`runtime.status === "visible"` 才显示成功 toast；否则显示 `message.warning` + 卡片内 `Alert`（`error_code`、`reason`），文案为「已安装，但运行时未就绪」。
- 卸载：`Modal.confirm`；返回 `cleaned=false` 时提示「已卸载 X，仍保留其它版本：...」。
- 语言：全部走 i18n，新增 `plugins.dsh.*`（见 §4）。

## 3. 精确改动清单

### 后端
1. `src/octop/infra/utils/paths.py`
   - 新增 `market_dir` property。
2. `src/octop/infra/plugins/market/__init__.py`
   - 导出 `default_market_root()`。
   - 新增实现（放 `market_source.py` 或新 `paths.py`，避免循环导入）。
3. `src/octop/infra/agents/plugins/manager.py`
   - 新增：`dsh_source_urls`、`add_dsh_source`、`remove_dsh_source`、`dsh_market_root`、`list_dsh_market`、`install_dsh_market`、`upgrade_dsh_market`、`uninstall_dsh_market`、`_dsh_index`、`_dsh_runtime_status`、`_node_dependency_gaps`。
   - 内部统一 `MarketplaceIndex([DshSource(...) for url in urls])`，每次请求新建实例以保证刷新。
   - 安装/升级后如 `server.app_runtime` 存在，由路由层触发 `agent_registry.reload_all()`；不调用 `load_installed()`。
4. `src/octop/infra/agents/manager.py:903`
   - `market_root` 改为 env 或 `default_market_root()`。
5. `src/octop/api/routers/plugins.py`
   - 追加 §2.5 七个路由与 Pydantic body `DshSourceBody`。

### 前端
6. `dashboard/src/api/modules/plugins.ts`
   - 类型：`DshMarketSource`、`DshMarketEntry`、`DshRuntimeStatus`、`DshMarketView`、`DshInstallResult`、`DshUninstallResult`。
   - 方法：`listDshMarket`、`addDshSource`、`removeDshSource`、`refreshDshMarket`、`installDsh`、`upgradeDsh`、`uninstallDsh`。
7. `dashboard/src/pages/Admin/Plugins/DshMarketPanel.tsx`（新增）。
8. `dashboard/src/pages/Admin/Plugins/PluginMarketPanel.tsx`
   - 顶部插入 `<DshMarketPanel />`；现有 octop 逻辑不动。
9. `dashboard/src/pages/Admin/Plugins/index.module.less`
   - 追加 `dshSection`、`dshSourceList`、`dshErrorAlert` 等样式；卡片复用现有 `card` 类。
10. `dashboard/src/locales/zh.json` / `en.json`
    - 新增 `plugins.dsh` 命名空间。

### 测试与 fixture
11. `tests/fixtures/dsh_market/index.json`（合法，2 个插件、2 个版本）
12. `tests/fixtures/dsh_market/index-bad-format.json`（`format: 2`）
13. `tests/fixtures/dsh_market/index-bad-row.json`（版本 `1.0` 非精确 semver）
14. `tests/fixtures/dsh_market/index-bad-icon.json`（file 源 + 相对 icon）
15. `tests/unit/infra/plugins/market/test_dsh_source_store.py`
    - 增删源、去重、持久化到临时 config.json、非法 URL 拒绝、上限。
16. `tests/unit/api/test_plugins_dsh_market.py`
    - 本地 `ThreadingHTTPServer` 提供 index 与动态生成的 `.tgz`（`package.json` 含 `dsh.bundle`）。
    - 覆盖：列表、单源失败隔离、安装、`status=installed_not_ready`（构造无 `node_modules` 且 `dependencies` 非空）、升级、卸载 `cleaned=true`、坏索引三条错误。
17. `tests/unit/infra/agents/plugins/test_manager_dsh_market.py`
    - `_dsh_runtime_status` 六种分支。

## 4. i18n 键（中英同名）
`plugins.dsh.` 下：
`title`、`subtitle`、`emptyTitle`、`emptyHint`、`formatHint`、`addSource`、`sourcePlaceholder`、`add`、`cancel`、`remove`、`removeConfirm`、`refresh`、`sourceCount`、`sourceOk`、`sourceError`、`entryCount`、`versionLabel`、`recommended`、`install`、`upgrade`、`uninstall`、`uninstallConfirm`、`installed`、`notInstalled`、`installedNotReady`、`cleanupDone`、`cleanupPartial`、`runtimeVisible`、`runtimeNotVisible`、`runtimeBroken`、`runtimeMissingDeps`、`errorCode`、`fetchFailed`、`invalidSource`、`noDescription`、`addSourceFailed`、`removeSourceFailed`。

空态中文文案（原文实现）：
> DSH 官方不提供插件索引。请自行填写一个静态 JSON 索引地址（format 1），例如 `https://your-host/index.json`，或本地绝对路径用于离线测试。

## 5. 验证步骤

### 5.1 自动化
```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/infra/plugins/market tests/unit/infra/agents/plugins/test_manager_dsh_market.py tests/unit/api/test_plugins_dsh_market.py -q
```
期望：全部通过；坏索引用例分别断言 `PLUGIN_MANIFEST_INVALID` / `PLUGIN_INDEX_UNUSABLE` 与 `path`。

### 5.2 本地端到端（fixture，不编造远端源）
1. 启动 fixture HTTP 服务（8765），索引指向本地 `.tgz`，`npm_registry` 指向同服务。
2. `$env:OCTOP_HOME='E:\HAPPYclaw\Octop\.tmp\s12-home'`；`python -m octop run --port 8088`。
3. `cd dashboard; npm run dev`（5173）。
4. 浏览器流程：
   - 市场页空态显示官方不提供索引说明；
   - 添加 `http://127.0.0.1:8765/index.json` → 出现 2 个条目与版本；
   - 安装 `1.0.0` → 状态变为已安装；若 fixture 包缺依赖闭包，必须出现 `TOOL_RUNTIME_PLUGIN_NOT_LOADED` 警告而非成功；
   - 升级到 `1.1.0` → `installed_version` 更新；
   - 卸载 → `cleaned=true`，卡片回到未安装；
   - 文件系统确认 `%OCTOP_HOME%\market\dsh\<native>` 已删除。
5. 坏索引：添加 `index-bad-format.json`，界面显示错误码与 `$.format` 路径。
6. 构建产物：`cd dashboard; npm run build`，确认 `src/octop/dashboard/assets/*` 更新。

### 5.3 打包确认
`python -m build` 后检查 wheel 包含 `api/routers/plugins.py` 与 `infra/plugins/market/*`；前端 assets 已更新。

## 6. 验收标准
- [ ] octop 市场接口与界面行为零变化。
- [ ] DSH 源可持久化、可增删、刷新后反映磁盘真相。
- [ ] 条目与 octop 列表物理/接口分离。
- [ ] 安装/升级/卸载走 `MarketplaceIndex` / `pipeline.uninstall`，不另写一套。
- [ ] 缺依赖闭包、坏索引、坏 icon、非法条目均有可见错误码与说明。
- [ ] 卸载后目录清理结果可见且可核验。
- [ ] 中英文文案齐全。
- [ ] 无 commit / push。

## 7. 需要批准
批准本 spec 与同目录 `tasks.md` 后开始实现；实现顺序按 `tasks.md`，界面可运行即先向调用方报一次，再继续收尾验证。
