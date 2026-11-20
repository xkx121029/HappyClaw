# HappyClaw 插件界面扩展规范 v1（接口草案 + 实现方案）

状态：已批准，实施中
范围：`e:\HAPPYclaw\Octop`（后端 `src/octop`、前端 `dashboard`、内置插件目录）
约束：不提交（no commit）；不改与插件/DSH 无关的模块；现有 Octop 插件行为不变。

范围修订（用户分工）：DSH 的运行兼容（接口不一致、调用方式不同、转译/垫片）由另一条线负责。
本线只做两件事：
1. 把 HappyClaw 插件规范与对外可修改接口定清楚并落成对外文档（`docs/plugin-ui-surfaces.md`），作为兼容层消费的标准；
2. 把「实时任务进度」首批可视化插件做到装上能用、卸了干净。
DSH 在本规范中只保留「可识别/可装载 + 明确告知无界面扩展」的状态表达，不实现 DSH 的 UI 转译。

对外文档与界面必须明示：v1 是同源受信 ESM，**不是沙箱**。

## 1. 目标与非目标

目标：

1. 在现有 `plugin.yaml` + `ui.entry` 能力之上，增加**可控的界面位置（slot）**、**只读产品数据域（data）**、**产品事件（events）**三组接口，插件可绘制自己的信息视图。
2. 首批只开放真实挂载、真实有数据的接口，不做“声明了但没实现”的假能力。
3. 现有 Octop 插件零改动可用；旧 `setup(host)` 与 `registerRenderer` 保持原语义。
4. DSH 插件继续可识别、可装载，但明确标注「无界面扩展入口」，不得伪装成可用。
5. 交付首个信息可视化插件 `task-progress-monitor`（实时任务进度），完成装/卸闭环且卸载无残留。
6. 上架到插件市场：可浏览、一键装载、卸载，装载结果显示真实状态。

非目标（v1 不做）：

- 不做 iframe / Web Worker 沙箱。现有插件 UI 是经鉴权后注入页面的受信 ESM，v1 沿用该信任模型；规范中明确写出，不宣称沙箱隔离。
- 不开放写数据、发消息、调用任意 API 的新权限；`host.request` 维持现状。
- 不新增插件生态类型；DSH 不获得界面扩展能力。

## 2. 兼容模型

| 插件类型 | 识别/装载 | 现有 `ui.entry` | v1 `ui.surfaces` | 能力差异提示 |
|---|---|---|---|---|
| Octop（旧） | 不变 | 可用 | 不声明则无 | 无 |
| Octop（新） | 不变 | 可用 | 可用 | 管理页显示挂载位置 |
| DSH | 现有 DSH 装载链路 | 不支持 | 不支持 | 市场/已安装页显示「无界面扩展」及原因码 |
| DSH（依赖缺失） | 已装载但不可用 | 不支持 | 不支持 | 沿用现有 `DSH_DEP_*` / runtime 状态 |

DSH 的差异通过 `runtime.surface_supported=false` + `surface_reason_code` + `surface_reason` 明确返回，前端只做展示，不推断。

## 3. Manifest 扩展（向后兼容）

`plugin.yaml` 的 `ui` 对象新增可选 `surfaces`：

```yaml
ui:
  entry: ui/dist/index.js
  manifest: ui/dist/manifest.json
  surfaces:
    - id: task-progress
      slot: home.sidebar
      title: 实时任务进度
```

规则：

- `surfaces` 缺省 → 与今天完全一致。
- `id`：非空，`[A-Za-z0-9._-]+`，同一插件内唯一；重复时后项标记为无效。
- `slot`：必须在宿主白名单内。未知 slot 不阻止插件加载，但该项标记 `supported:false`、`reason_code:"SURFACE_SLOT_UNKNOWN"`，前端不挂载并显示原因。
- `title`：可选；缺省用 `id`。
- `entry` 文件不存在 → 维持现有行为：`ui` 视为不存在（仅后端插件）。

后端 `parse_plugin_ui_meta`（`src/octop/infra/agents/plugins/manager.py:1015`）返回值从 `dict[str, str]` 扩展为：

```json
{
  "entry": "ui/dist/index.js",
  "manifest": "ui/dist/manifest.json",
  "surfaces": [
    {"id": "task-progress", "slot": "home.sidebar", "title": "实时任务进度", "supported": true}
  ]
}
```

`GET /api/plugins` 的 `ui` 字段原样带出该结构。

## 4. Host API v1

在 `dashboard/src/plugins/toolRenderers/types.ts` 的 `OctopPluginUIHost` 上追加，**不删除、不改名**现有成员：

```ts
type SurfaceSlot = "home.sidebar" | "chat.messages.top";

interface SurfaceRegistration {
  id: string;
  slot: SurfaceSlot;
  title?: string;
  order?: number;          // 升序，默认 100
  component: React.ComponentType<SurfaceProps>;
}

interface SurfaceProps {
  host: OctopPluginUIHost;
  pluginId: string;
  surfaceId: string;
}

interface OctopPluginUIHost {
  apiVersion: 1;
  surfaces: {
    supports(slot: string): slot is SurfaceSlot;
    list(slot: SurfaceSlot): { id: string; title: string; order: number }[];
    register(reg: SurfaceRegistration): () => void;
  };
  data: {
    read<T = unknown>(domain: DataDomain): Promise<T>;
    subscribe<T = unknown>(domain: DataDomain, cb: (value: T) => void): () => void;
  };
  events: {
    on<T = unknown>(event: ProductEventName, cb: (payload: T) => void): () => void;
  };
  context: { locale: string; theme: "light" | "dark" };
}
```

`setup(host)` 可返回清理函数；宿主卸载插件时调用：

```ts
export interface PluginUiModule {
  setup?: (host: OctopPluginUIHost) => void | (() => void);
}
```

### 4.1 首批 Slot（只列真实挂载点）

| slot | 位置 | 挂载文件 |
|---|---|---|
| `home.sidebar` | 首页右侧栏 `<aside className={styles.side}>` 内、会话盒之后 | `dashboard/src/pages/Home/index.tsx` |
| `chat.messages.top` | 聊天页消息列表 `<MessageList>` 上方 | `dashboard/src/pages/Chat/index.tsx` |

排序：`order` 升序，其次 `pluginId`、`id` 字典序。每个 surface 独立错误边界；单个插件渲染报错不影响其他插件或宿主页面。

### 4.2 首批 Data Domain（只读、有真实来源）

| domain | 返回 | 来源 |
|---|---|---|
| `runtime.activity` | `RuntimeActivity` | `GET /api/runtime/activity` |
| `sessions.running` | `{ updated_at, sessions: RunningSession[] }` | `GET /api/agents` + `GET /api/agents/{id}/threads?limit=20` |
| `plugins.installed` | `{ plugins: InstalledPluginSummary[] }` | `GET /api/plugins` |
| `host.context` | `{ locale, theme, now }` | 宿主运行时 |

`RunningSession`：`agent_id, agent_name, thread_id, title, turn_active, awaiting_user, last_active, model_ref`。
运行中判定：`turn_active === true || awaiting_user === true`。
轮询：`sessions.running` / `runtime.activity` 3s，`plugins.installed` 10s；无订阅者时停止轮询。

### 4.3 首批 Event（由真实轮询差分产生，不造数据）

| event | payload |
|---|---|
| `session.started` | `{ at, session }` |
| `session.updated` | `{ at, session }` |
| `session.ended` | `{ at, session_id }` |

仅当 `sessions.running` 的线程集合/字段变化时发出；宿主断开订阅即停止。

## 5. 生命周期与“卸载无残留”

- 注册：`surfaces.register` 写入按 `pluginId` 分组的注册表，返回 `dispose`。
- 加载：`loader.ts` 记录每个插件的 `setup` 清理函数；`resetPluginUiLoader()` 依次调用清理函数、`unregisterPluginSurfaces(pluginId)`、`unregisterPluginRenderers(pluginId)`、撤销 blob URL。
- 卸载：后端删除 `~/.octop/plugins/<id>`；前端 `pluginsEvents` 触发重载，surface 与数据订阅随之消失。
- 市场/已安装页在卸载成功后刷新，面板下一次渲染即无该插件。

## 6. 安全边界（如实声明）

- v1 插件 UI 仍是经登录鉴权、与 Dashboard 同源的受信 ESM，拥有页面上下文权限；**不是沙箱**。
- 新增的 `data/events/surfaces` 是稳定接口与最小数据面，不是权限提升；`host.request` 仍可访问当前用户可访问的 API。
- 只从可信来源安装 UI 插件；DSH 插件不执行 HappyClaw UI 代码。
- 后续若引入 iframe 沙箱，将提升 `apiVersion`，不静默改变现有语义。

## 7. 市场与状态

### 7.1 内置目录上架

- 新插件放在 `src/octop/infra/agents/plugins/bundled/task-progress-monitor/`（`default_bundled_plugins_root()`）。
- `PluginManager.list_market`（`manager.py:2520`）合并内置目录行与远端 portal 行：
  - 内置行字段与 `MarketPlugin` 一致，另加 `source:"bundled"`、`install_kind:"bundled"`；
  - 远端失败且内置行非空时返回内置行并记录 warning；两者都空才按现有错误抛出。
- 新增 `PluginManager.install_bundled(plugin_id, force=False)`：仅允许 `default_bundled_plugins_root()` 下的直接子目录，`shutil.copytree` 到 `~/.octop/plugins/<id>`，校验 `plugin.yaml`，`_load_plugin_dir(install_deps=False)`，启用。
- 新增 API：`POST /api/plugins/market/bundled/{plugin_id}/install?force=`。
- 新增 API：`GET /api/plugins/ui/capabilities`，返回 `{api_version, slots, data, events}`。

### 7.2 前端

- `PluginMarketPanel.tsx`：内置条目显示「内置」标签；`source==="bundled"` 调新接口；已安装条目提供「卸载」。装载/卸载后调用 `notifyPluginsChanged()` 并刷新，状态与 DSH 面板一致。
- `InstalledPluginsPanel.tsx`：显示 `ui.surfaces` 的挂载位置与不支持原因。
- `DshMarketPanel.tsx` + `plugins.ts`：`DshRuntimeStatus` 增加三个 surface 字段，已安装/市场条目显示「无界面扩展」提示。

## 8. 首个插件：task-progress-monitor

目录：

```text
src/octop/infra/agents/plugins/bundled/task-progress-monitor/
├── plugin.yaml
├── main.py
└── ui/dist/
    ├── index.js        # 自包含 ESM，无 bare import
    └── manifest.json
```

- `plugin.yaml`：`id: task-progress-monitor`、`version: 0.1.0`、`kind: tool`、`ui.entry: ui/dist/index.js`、`ui.surfaces: [{id: task-progress, slot: home.sidebar, title: 实时任务进度}]`。
- `main.py`：`setup(ctx)` 注册只读工具 `task_progress_about`，返回面板用途与数据来源说明；无副作用。
- `ui/dist/index.js`：用 `window.__OCTOP_REACT__` / `__OCTOP_JSX__`，`React.createElement` 编写；订阅 `sessions.running` 与 `runtime.activity`；渲染运行中会话列表（标题、Agent、持续时长、等待用户标记）、计数与空状态；`setup` 返回 dispose。
- 视觉：内联样式 + `currentColor`/半透明背景，适配明暗主题，不注入全局 CSS。

## 9. 实现文件清单

后端：

- `src/octop/infra/agents/plugins/manager.py`
  - `parse_plugin_ui_meta`：解析/校验 `ui.surfaces`，返回 `supported` 与 `reason_code`。
  - `list_market`：合并内置目录行（`source/install_kind`）。
  - `install_bundled`：新增。
  - `_dsh_runtime_status`：每个返回的 `status` 加 `surface_supported/surface_reason_code/surface_reason`。
- `src/octop/api/routers/plugins.py`
  - `GET /plugins/ui/capabilities`、`POST /plugins/market/bundled/{plugin_id}/install`。
  - 安装后沿用 `load_installed` / `refresh_plugin_channels` / `reload_all`。

前端：

- 新增 `dashboard/src/plugins/surfaces/{types,registry,data,PluginSurfaceSlot,SurfaceBoundary,index}.ts(x)`。
- `dashboard/src/plugins/toolRenderers/{types,host,loader,index}.ts`：扩展 host、清理函数、surface 卸载。
- `dashboard/src/pages/Home/index.tsx`、`Chat/index.tsx`：挂载 slot。
- `dashboard/src/pages/Admin/Plugins/{PluginMarketPanel,InstalledPluginsPanel,DshMarketPanel}.tsx`、`dashboard/src/api/modules/plugins.ts`、i18n 词条。

插件与测试：

- `src/octop/infra/agents/plugins/bundled/task-progress-monitor/`（上列文件）。
- `tests/unit/plugins/test_ui_surfaces.py`（manifest 解析、slot 校验、market 合并、install_bundled、uninstall）。
- `tests/unit/api/test_plugins_ui.py`（capabilities、bundled install）。
- `tests/unit/plugins/market/test_dsh_status.py` 或现有 DSH 测试补 surface 字段断言。
- `dashboard/src/plugins/surfaces/registry.test.ts`、`loader.test.ts`（注册/卸载/清理/错误边界）。

## 10. 验收标准（可测量）

1. `GET /api/plugins/ui/capabilities` 返回 `api_version=1`、2 个 slot、4 个 data domain、3 个 event。
2. 干净 `OCTOP_HOME` 下安装 `task-progress-monitor`：`GET /api/plugins` 出现该插件，`loaded=true`，`ui.surfaces[0].supported=true`。
3. 首页右侧栏 5s 内出现「实时任务进度」；有运行中会话时最长 3s 刷新一次；无会话显示空状态，不显示编造数据。
4. 卸载后 `~/.octop/plugins/task-progress-monitor` 不存在；刷新首页面板消失；浏览器控制台无该插件注册残留（`listSurfaces` 为空）。
5. 插件市场在内置源可浏览、可一键装载、可卸载；portal 不可达时内置条目仍展示。
6. DSH 已安装条目返回 `surface_supported=false` 与原因码，前端显示「无界面扩展」。
7. 现有 Octop 插件 UI/工具渲染测试不回归；新增后端 pytest 与前端 vitest 通过。

## 11. 验证步骤

```powershell
# 后端
.\.venv\Scripts\python.exe -m pytest tests/unit/plugins tests/unit/api/test_plugins_ui.py tests/unit/test_plugin_manager.py -q

# 前端
cd dashboard
npx tsc --noEmit
npm run test -- --run src/plugins/surfaces

# 隔离实例（全新 OCTOP_HOME）
$env:OCTOP_HOME="<tmp>"
.\.venv\Scripts\python.exe -m octop run --host 127.0.0.1 --port 4949
# 通过 API 安装/卸载，再用 browser_use 实点首页与市场
```

## 12. 风险与回滚

- `list_market` 行为改变：仅在内置目录非空时生效；portal 正常时行集合是「内置 + 远端」，回滚只需移除合并分支。
- `parse_plugin_ui_meta` 返回类型扩展：旧字段不变，旧调用方不受影响。
- 插件 ESM 加载失败：沿用现有 `console.warn` + 插件卡片 `error` 展示；不影响宿主。
- 不做自动安装：新内置插件必须从市场点击装载，符合现有 seed 语义。
