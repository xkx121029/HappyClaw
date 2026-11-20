# DSH 插件运行兼容层 spec（v1）

状态：待批准（批准后才动代码）
范围：`e:\HAPPYclaw\Octop`（后端 `src/octop`、前端 `dashboard`）；隔离工作区 `e:\HAPPYclaw\.tmp\dsh-compat`
约束：不提交；不改 `specs/plugin-ui-platform` 已定义的接口体系；DSH 开关默认关闭，关闭时零 Node 进程、零导入。

## 1. 目标

让真实 DSH 插件在 HappyClaw 里**真的运行**，而不是“装上了但用不了”。覆盖五类：外观（主题/配色/皮肤）、记忆（写入/检索/改写）、对话框（消息渲染、输入区、富内容）、叠加层（浮层/遮罩/悬浮操作）、挂件（独立信息块/面板）。

硬性要求：

1. 先盘点再动手：对真实 DSH 插件逐个试装试跑，按失败原因分类并给出可量化分布。
2. 每类跑通一类就交付一次，附插件名与运行证据（状态 JSON、日志、截图）。
3. 真跑不起来的必须如实列出原因码，不得把“挂载成功但无效果”报成成功。
4. 适配层可独立关闭；单个坏插件不得拖垮宿主或其他插件。
5. 只消费 `specs/plugin-ui-platform` 的 `OctopPluginUIHost` / `surfaces` / `data` / `events`，不新增第二套插件接口。

## 2. 盘点结论（已完成的静态证据）

已安装样本（`C:\Users\linch\.octop\market\dsh`）：

| 样本 | 类别 | host 半边 | client 半边 | 关键事实 |
|---|---|---|---|---|
| `dsh-plugin-demo@1.1.0` | 工具 | `index.js` ESM，`apply/provide` | 无 | 可作为最小回归样本 |
| `@99galaxy/dsh-turn-notify@1.0.5` | 挂件/通知 | `ctx.inject(["webServer"])` + `ctx.effect` | `window.__ModuleLoader__.load`，依赖 `uiSession/sessions` | 客户端不是 ESM，无 import |
| `@aeroscis/dsh-temptask@0.6.0` | 侧边栏 + 浮层 | `host.js` 用 `ctx.get/effect/inject/settings/fiber/configEditor/logger/on` | ModuleLoader，`require("react")`，用 `ctx.slots/locale/sessions/remote/layout/configForms/uiWorkspace` | 需要 `react` 由宿主提供 |
| `@agentduel/agentduel-dsh@0.1.6` | 对话区/叠加游戏 | `apply(_ctx){}` | ModuleLoader，`require("react","react-dom","react/jsx-runtime")`，canvas 叠加 | 体积 2.8MB，单文件 |
| `@a9i5k4/dsh-auto-memory@3.3.17` | 记忆 + 皮肤 | 1.4MB，仅 `node:` 内置模块；`ctx.get/on/systemPrompt/tools/remote/effect/webServer/sessions/agents/subagents/locale/policy/head/tokenMeter/directoryPicker` | ModuleLoader，`require("react","react-dom")`，用 `ctx.slots/locale/sessions/remote/config/effect/on` | 有 Python sidecar 与可选 `@huggingface/transformers` |

由此确定三条关键设计事实：

1. **client 半边不是标准 ESM**，而是注册到 `window.__ModuleLoader__` 的工厂函数，`require("react")` 等由宿主解析。因此 v1 不需要 esbuild 转译已装样本；需要的是一个 ModuleLoader + `require` 解析垫片。
2. **host 半边是 Cordis 插件**（`name/inject/apply`），需要 `ctx.get/provide/inject/effect/on/logger/webServer/tools/systemPrompt/sessions` 等。现有 `dsh/tools/runtime.py` 只做一次性探针，不足以承载常驻服务。
3. **宿主 slot 只有两个**：`home.sidebar`、`chat.messages.top`（见 `dashboard/src/plugins/surfaces/types.ts`）。DSH 的 `sidebar.*`/`shell.overlay` 可映射；逐条消息渲染、输入区没有对应 slot，必须诚实报 `DSH_SLOT_UNSUPPORTED`（见 §8 接口缺口）。

## 3. 总体架构

三层，逐层独立开关与独立失败：

```
OCTOP_DSH_COMPAT=1
├─ L1 盘点器  inventory.py + node/probe.mjs      → 只读，不注册任何服务
├─ L2 宿主运行器 registry.py + node/runner.mjs   → 每插件一个 Node 子进程，JSONL RPC
└─ L3 客户端垫片 api/routers/dsh_compat.py + dashboard/src/plugins/dshCompat
```

- 开关关闭时：`compat_enabled()` 为 False；不 spawn Node、不生成 bundle、dashboard 不发起状态请求（`startDshCompat()` 首行返回）。
- L2 每个插件独立子进程，超时/崩溃只影响该插件状态。
- L3 每个插件的 UI 在独立 `SurfaceBoundary` 内渲染，渲染异常只显示该插件错误卡。

## 4. L1 兼容性盘点

### 4.1 样本集（9 个，覆盖五类）

已装 5 个（上表）+ 从 `22a8ef2a9027d904.json` 的 `appearance`（88 个）中取 4 个：

- `@zheshiyigehenchang/dsh-chat-typography`（对话排版，外观/对话框）
- `dsh-bloom-theme`（主题）
- `whale-girl` 或 `dsh-pet-live2d`（桌宠叠加层）
- `dsh-meme`（表情包，富内容/输入区）

下载方式：`npm pack <name>@<version>` 解包到 `.tmp\dsh-compat\downloads\<slug>`，不改主实例。需要运行证据的再装进隔离 `OCTOP_HOME`。

### 4.2 静态分类器

`src/octop/infra/dsh/compat/probe.py::classify_static(package_dir) -> StaticFacts`

采集：`main`/`exports` 是否存在；`dsh.bundle.patch`；`dsh.client.platform/inject/entry`；host 入口的 `ctx.*` 集合；client 入口的 `require()` 与 `ctx.*` 集合；`node:` 内置模块；是否只有 TS 源码无构建产物；网络/凭据关键字（`apiKey`、`https://`、`token`）；入口导出形态（ESM 命名导出 / default / ModuleLoader）。

### 4.3 动态探针

`src/octop/infra/dsh/compat/node/probe.mjs`：用 `cordis-lite` + 宿主服务桩导入 host 入口、`ctx.plugin(mod)`，等待 `settleMs`，收集 `provide` 的服务、`inject` 缺失项、首个异常栈。

### 4.4 失败分类（统一错误码，Python/JS 共用）

`OK`、`ENTRY_SHAPE`、`IMPORT_FAILED`、`MISSING_API`、`SIGNATURE_MISMATCH`、`RUNTIME_THROW`、`TIMEOUT`、`NEEDS_BUILD`、`NEEDS_NETWORK`、`NEEDS_CREDENTIAL`、`NATIVE_MODULE`、`ENGINE_UNSATISFIED`、`SLOT_UNSUPPORTED`、`BUNDLE_UNSUPPORTED`。

每个插件输出：`{id, version, category, host:{class, evidence}, client:{class, evidence}, ui_slots:[...], can_run: bool, reasons:[code]}`。汇总写 `docs/dsh-compat-inventory.md` 与 `<OCTOP_HOME>/dsh-compat/inventory.json`。

## 5. L2 宿主运行器

### 5.1 Node 侧（`src/octop/infra/dsh/compat/node/`）

- `cordis-lite.mjs`：`Context` 子集 —— `provide/get/inject/effect/on/emit/plugin/registry/logger/fiber`，语义与 Cordis 一致（`effect` 返回 disposer；`inject` 在依赖可用时立即执行、否则挂起；`get` 未知服务返回 `undefined` 并记录到 `accessed`）。
- `host-services.mjs`：把宿主能力做成服务：
  - `webServer.register({kind,path,handler})` → 路由表，handler 通过 RPC `http.request` 由 Python 侧调用；
  - `tools.register(def)` → RPC `tools.register`；
  - `systemPrompt.section({name,order,text,render})` → RPC `prompt.section`；
  - `sessions/agents/subagents` → 只读 RPC；
  - `remote.call(method, params)` → 仅允许该插件声明的路由，否则抛 `DSH_REMOTE_DENIED`；
  - `locale/settings/policy/tokenMeter/head/authorization/directoryPicker/configEditor` → 能给出真实默认值的给默认值，其余抛 `DSH_HOST_API_UNSUPPORTED:<member>`，由 registry 记入 `unsupported_members`。
- `runner.mjs`：常驻进程，stdin/stdout JSONL RPC；启动后 mount 入口，输出 `ready`；支持 `http.request` / `tools.call` / `prompt.list` / `shutdown`。

### 5.2 Python 侧

- `transport.py::NodeRpcClient`：spawn、逐行读写、请求 id、单请求超时、进程退出检测、`kill()`。
- `registry.py::DshCompatRegistry`：
  - `status()` → 每插件 `{host_state, code, published, prompt_sections, tools, unsupported_members, last_error}`；
  - `ensure_started(plugin_id)`：懒启动；最多 3 次/小时，退避后置 `failed`；
  - `prompt_sections(plugin_ids)`：带 1s 超时，失败返回空并记录，绝不阻塞 prompt 组装；
  - `dispatch_http(plugin_id, req)`、`call_tool(plugin_id, name, args)`；
  - `shutdown_all()`：应用退出时调用。
- 集成点（均带 `compat_enabled()` 短路）：
  - `src/octop/infra/dsh/integration.py::compose_system_prompt`：追加 compat prompt sections（记忆类插件靠这里真正进入系统提示词）。
  - `src/octop/infra/dsh/tools/catalog.py::build_dsh_plugin_tools`：追加 compat 工具定义，命名 `dsh_compat.<native>.<tool>`。
  - `src/octop/infra/dsh/session/shadow.py::write_shadow_turn`：回合写入成功后向 registry 发 `turn.done`/`session.updated`（不等待、不抛错），供记忆类插件的事件钩子使用。
- 插件目录来源复用 `src/octop/infra/dsh/tools/discovery.py::discover_dsh_plugins`，不另建发现逻辑。

### 5.3 白名单

`OCTOP_DSH_COMPAT_PLUGINS`（逗号分隔 canonical id，支持 `dsh:*`）。未列入的插件只出现在盘点结果里，不启动进程。默认空 = 仅盘点，不运行。

## 6. L3 客户端垫片（UI 翻译）

### 6.1 服务

- `GET /api/dsh-compat/status`：兼容层与每插件状态（含 `ui.state`、`mapped_slots`、`unsupported_slots`）。
- `GET /api/dsh-compat/ui/runtime.js`：垫片 ESM（ModuleLoader + require 解析 + DSH client ctx）。
- `GET /api/dsh-compat/ui/{plugin_id}/client.js`：只读返回 `dsh.client` 入口文件（路径校验限制在插件目录内）。
- `ANY /api/dsh-compat/route/{plugin_id}/{path}`：把请求转成 `http.request` 交给该插件的 `webServer` handler，回写状态码/头/体。
- `POST /api/dsh-compat/report`：dashboard 回报 `ui.state` 与错误（不抛给宿主）。
- `POST /api/dsh-compat/{plugin_id}/start|stop`：手动启停，便于隔离验证。

### 6.2 垫片行为（`dashboard/src/plugins/dshCompat/`）

- `loaderShim.ts`：定义 `window.__ModuleLoader__.load({id,factory})`；`require` 解析 `react`/`react-dom`/`react-dom/client`/`react/jsx-runtime`（取自 `window.__OCTOP_REACT__`，由 boot 从 dashboard 的 React 注入）；缺失时抛 `DSH_REACT_MISSING` 并显示错误卡。
- 构造 DSH client `ctx`：`slots/sessions/uiSession/uiWorkspace/uiConversation/layout/locale/remote/logger/effect/on/get/config/configForms`。
  - `sessions`/`uiSession` 由 `host.data.read("sessions.running")` + `host.events` 驱动，**不造数据**；`turn-notify` 的“运行→空闲”通知因此基于真实会话状态。
  - `remote` 映射到 `host.request("/dsh-compat/route/{plugin}/...")`，仅限插件自己的路由。
  - `locale` 取 `host.context.locale`。
- `slots.ts`：slot 映射表

| DSH slot（前缀匹配） | HappyClaw slot | 说明 |
|---|---|---|
| `sidebar.*`、`home.*` | `home.sidebar` | 侧边栏行/面板入口 |
| `chat.*`、`conversation.*` | `chat.messages.top` | 对话区顶部信息块 |
| `shell.overlay`、`overlay.*`、`modal.*`、`toast.*` | `chat.messages.top` + `createPortal(document.body)` | 真浮层，不裁剪、不嵌套 |
| 其他 | 无 | 记 `unsupported_slots`，状态 `partial` |

  - 注册的组件包 `SurfaceBoundary`；卸载时调用插件返回的 dispose。
- `boot.ts::startDshCompat()`：状态请求 → 逐插件拉 `runtime.js`/`client.js`（带 token）→ blob URL import → `mount(host, pluginId)`；单插件 try/catch，失败 `POST /report`。
- `dashboard/src/main.tsx`：登录后一行 `void startDshCompat()`（开关由 status 响应自行短路）。

### 6.3 外观类

`ctx.get('uiTheme')` / `uiThemeService` 映射为：`registerTheme({id,name,vars,className})` 写入受控 `<style>` 与 `data-dsh-theme` 属性，作用域为 body；`setTheme(id)` 持久化到 localStorage；纯 CSS 注入型插件（如排版、Bloom 主题）直接生效。未知成员调用 → `DSH_HOST_API_UNSUPPORTED`，状态 `partial`，不静默。

## 7. 安全与隔离（如实声明）

- client 代码与 Dashboard 同源、受信 ESM，**不是沙箱**；与现有插件 UI 信任模型一致（`docs/plugin-ui-surfaces.md` 已声明）。
- host 代码在独立 Node 子进程运行，拥有当前用户文件权限；默认不联网（仅插件自己 fetch 时联网），`remote` 只放行自有路由。
- 白名单 + 总开关双控；任何插件 mount 抛错只影响自身状态。
- 不改主实例数据库；验证一律使用隔离 `OCTOP_HOME`。

## 8. 依赖其他线的接口缺口（不自行新增）

逐条消息渲染、输入区注入需要 `chat.message.body` / `chat.composer.actions` 这类 slot；当前 `SURFACE_SLOTS` 只有两个。v1 处理：

- 能映射到两个 slot 或 portal 的（侧边栏、顶部信息块、浮层）→ 真跑。
- 需要逐消息/输入区的 → 状态 `partial` + `DSH_SLOT_UNSUPPORTED:<dsl_slot>`，并在 `docs/dsh-compat-inventory.md` 列出，向 `plugin-ui-platform` 线提交 slot 申请；不在本线私自扩展 `OctopPluginUIHost`。

## 9. 实现文件清单

后端新增：

- `src/octop/infra/dsh/compat/{__init__,switch,errors,probe,transport,registry,client_asset}.py`
- `src/octop/infra/dsh/compat/node/{cordis-lite,host-services,runner,probe}.mjs`、`node/package.json`
- `src/octop/api/routers/dsh_compat.py`（在 `src/octop/api/app.py` 的 router 列表中注册）

后端修改（均 3~10 行守卫式调用）：

- `src/octop/infra/dsh/integration.py`（prompt sections）
- `src/octop/infra/dsh/tools/catalog.py`（compat 工具）
- `src/octop/infra/dsh/session/shadow.py`（turn 事件）

前端新增：

- `dashboard/src/plugins/dshCompat/{loaderShim,slots,boot,index}.ts`
- `dashboard/src/api/modules/dshCompat.ts`

前端修改：

- `dashboard/src/main.tsx`（一行启动）

测试：

- `tests/unit/dsh_compat/{test_switch,test_probe,test_registry_rpc,test_client_asset,test_prompt_bridge}.py`
- `dashboard/src/plugins/dshCompat/{loaderShim,slots}.test.ts`

文档：

- `docs/dsh-compat-inventory.md`（盘点分布 + 每插件证据）

## 10. 验收标准（可测量）

1. 盘点：9 个样本全部产出 `host/client` 分类与证据；`inventory.json` 的 `failure_class` 计数之和 = 样本数；Markdown 表列出每类数量与插件名。
2. 工具类：`dsh-plugin-demo` 在隔离实例 `host_state=mounted`，`published.demo.greeting == "hello from dsh-plugin-demo"`，`GET /api/dsh-compat/status` 可见。
3. 记忆类：`dsh-auto-memory` 挂载后 `prompt_sections >= 1`、`tools >= 1`；`compose_system_prompt` 输出含 `<memory_system>`；通过桥调用 `memory_log` 在隔离工作区真实落盘。
4. 挂件类：`dsh-turn-notify` 的 client 半边 `ui.state=mounted`；真实会话 running→idle 时触发 `session.ended`，日志可查（不要求弹 Windows 通知，浏览器权限受限时如实标 `NEEDS_PERMISSION`）。
5. 侧边栏/浮层：`dsh-temptask` 在 `home.sidebar` 出现一行（截图）；帮助气泡为 body portal（截图 + DOM 断言）。
6. 外观类：安装一个 CSS/主题样本后，聊天页排版/配色 computed style 变化（截图 + `getComputedStyle` 证据）；否则如实标 `SLOT_UNSUPPORTED`/`MISSING_API`。
7. 故障隔离：注入一个 `apply` 抛错的 fixture，`status=failed/code=RUNTIME_THROW`，其余插件仍 mounted，API 200。
8. 关闭开关：`OCTOP_DSH_COMPAT=0` 时无 node 子进程，status 返回 `disabled`，dashboard 不加载 `dshCompat` 模块。
9. 回归：`pytest tests/unit/dsh_compat`、`npx tsc --noEmit`、现有 `tests/unit/plugins` 通过。

## 11. 验证步骤

```powershell
# 1) 单位测试
.\.venv\Scripts\python.exe -m pytest tests/unit/dsh_compat -q
cd dashboard; npx tsc --noEmit

# 2) 盘点（不启动服务）
.\.venv\Scripts\python.exe -m octop.infra.dsh.compat.probe --root C:\Users\linch\.octop\market\dsh --out E:\HAPPYclaw\.tmp\dsh-compat\inventory.json

# 3) 隔离实例
$env:OCTOP_HOME="E:\HAPPYclaw\.tmp\dsh-compat\home"
$env:OCTOP_DSH_COMPAT="1"
$env:OCTOP_DSH_COMPAT_PLUGINS="dsh:dsh-plugin-demo,dsh:dsh-auto-memory"
.\.venv\Scripts\python.exe -m octop run --host 127.0.0.1 --port 4951
# curl /api/dsh-compat/status；POST start；调用工具；browser_use 截图

# 4) 关闭验证
$env:OCTOP_DSH_COMPAT="0"  # 重启后 status=disabled，node 进程数为 0
```

## 12. 风险与回滚

- Node 子进程崩溃：registry 捕获退出，置 `failed`，不影响宿主；总开关可整体关停。
- host 入口副作用（写文件/起子进程）：白名单默认空，仅显式列出的插件运行；隔离实例先验证。
- client 代码同源执行：与现有插件 UI 同级信任，文档明示非沙箱。
- 回滚：删除 `src/octop/infra/dsh/compat/` 与 `dashboard/src/plugins/dshCompat/`，移除 3 处守卫调用、1 个 router 注册、1 行 boot 调用；无数据库迁移，缓存仅在 `OCTOP_HOME/dsh-compat`。
