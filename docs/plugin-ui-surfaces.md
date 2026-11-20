# HappyClaw 插件界面扩展规范 v1

本文件是 HappyClaw 插件（Octop 生态）界面扩展的对外标准，供插件作者与兼容层共同消费。
状态：v1 已定稿。实现位于 Dashboard `src/plugins/surfaces` 与后端 `plugin.yaml` 解析。

## 0. 先读：信任模型（不是沙箱）

**v1 的插件界面代码是经登录鉴权后、与 Dashboard 同源加载的受信 ESM，运行在页面主上下文中，拥有与页面脚本相同的权限。它不是沙箱，也不提供进程或 DOM 隔离。**

- 只安装你信任来源的 UI 插件。
- `host.data` / `host.events` / `host.surfaces` 是稳定、最小化的接口约定，**不是权限边界**。
- 插件仍可使用 `host.request(path)` 调用当前登录用户有权访问的 API。
- DSH 插件不会获得本规范的界面扩展能力，也不会执行 HappyClaw UI 代码。
- 未来若提供 iframe/Worker 沙箱，会提升 `apiVersion` 并单独公告，不会静默改变 v1 语义。

## 1. 适用范围与兼容性

| 插件类型 | 可装载 | 可用 `ui.entry` | 可用 `ui.surfaces` | 说明 |
|---|---|---|---|---|
| Octop 旧插件 | 是 | 是 | 否（未声明） | 现有 `setup(host)` / 工具渲染器行为不变 |
| Octop 新插件 | 是 | 是 | 是 | 本规范 |
| DSH 插件 | 是（走 DSH 线） | 否 | 否 | 返回 `surface_supported=false` 与原因码 |
| DSH 依赖缺失 | 已装载但不可用 | 否 | 否 | 沿用 `DSH_DEP_*` 与 runtime 状态 |

DSH 的「无界面扩展」不是故障：它只有运行时能力。宿主通过
`surface_supported=false`、`surface_reason_code="DSH_UI_SURFACE_UNSUPPORTED"` 和
`surface_reason` 明确告知；界面显示提示，不显示为损坏。

## 2. `plugin.yaml` 声明

```yaml
id: task-progress-monitor
version: 0.1.0
name: 实时任务进度
kind: tool
entry: main.py
ui:
  entry: ui/dist/index.js
  manifest: ui/dist/manifest.json
  surfaces:
    - id: task-progress
      slot: home.sidebar
      title: 实时任务进度
```

- `ui.entry` 仍是自包含 ESM 的入口；文件缺失时插件按纯后端插件处理（与旧行为一致）。
- `ui.surfaces` 可选。缺省时不挂载任何界面，旧插件无需改动。
- `id`：`[A-Za-z0-9._-]+`，同插件内唯一。
- `slot`：必须是宿主白名单值（见 §3）。未知 slot 不阻止安装，但该项返回
  `supported=false`、`reason_code="SURFACE_SLOT_UNKNOWN"`，界面不挂载并显示原因。
- `title`：可选，缺省为 `id`。
- 同一插件重复 `id`：后者标记 `reason_code="SURFACE_DUPLICATE_ID"`。

后端在 `GET /api/plugins` 的 `ui` 字段返回解析结果：

```json
{
  "entry": "ui/dist/index.js",
  "manifest": "ui/dist/manifest.json",
  "surfaces": [
    {
      "id": "task-progress",
      "slot": "home.sidebar",
      "title": "实时任务进度",
      "supported": true,
      "reason_code": null
    }
  ]
}
```

## 3. 可挂载位置（slots v1）

| slot | 实际位置 | 状态 |
|---|---|---|
| `home.sidebar` | 首页右侧栏，会话盒之后 | 已挂载 |
| `chat.messages.top` | 聊天页消息列表上方 | 已挂载 |
| `conversation.view` | 每条消息气泡下方，逐条渲染 | 已挂载 |
| `conversation.input.left` | 输入框左侧（与输入行同一行） | 已挂载 |
| `conversation.input.overlay` | 输入区浮层（不遮挡输入框点击） | 已挂载 |
| `settings.section` | 设置页（个性化页）顶部区块 | 已挂载 |

只有本表列出的位置会真正渲染。宿主不会为未实现的 slot 提供占位。

`conversation.view` 是唯一「按消息实例化」的 slot：注册一次，宿主为每条消息渲染一次，
组件会收到 `props.context.message`：

```ts
interface SurfaceMessage {
  id: string;
  role: string;
  content?: unknown;
  createdAt?: string | number | null;
}
```

其余 slot 的 `context` 只有 `agentId` / `threadId`（宿主未知时为 `null`）。
`conversation.input.overlay` 的容器默认 `pointer-events: none`，插件自己的节点可以点击。

排序：`order` 升序（缺省 100），再按 `pluginId`、`surface id` 字典序。
每个 surface 有独立错误边界，单个插件渲染异常不影响宿主或其他插件。

## 4. Host API v1

`ui/dist/index.js` 必须导出自包含的 `setup(host)`，不得使用裸模块导入。
React 由页面提供：`window.__OCTOP_REACT__`、`window.__OCTOP_JSX__`。

```ts
export function setup(host: OctopPluginUIHost): void | (() => void) {
  const dispose = host.surfaces.register({
    id: "task-progress",
    slot: "home.sidebar",
    title: "实时任务进度",
    order: 100,
    component: TaskProgressCard,
  });
  return dispose;
}
```

`setup` 返回的清理函数会在插件卸载/重载时调用；`register` 返回的 dispose 也会被宿主兜底调用。

### 4.1 宿主对象

```ts
interface OctopPluginUIHost {
  /** 当前宿主契约版本，v1 = 1。 */
  apiVersion: 1;

  // ---- 既有接口（保持不变）----
  registerRenderer(reg: ToolRendererRegistrationInput): void;
  getToolContext(): { agentId: string | null; threadId: string | null; locale: string; theme: "light" | "dark" };
  patchResult(callId: string, nextData: unknown): void;
  request<T>(path: string, init?: RequestInit): Promise<T>;
  openSidePanel(opts: { callId: string; title?: string; toolName?: string }): void;
  closeSidePanel(callId: string): void;

  // ---- v1 新增 ----
  surfaces: {
    supports(slot: string): slot is SurfaceSlot;
    list(slot: SurfaceSlot): Array<{ id: string; title: string; order: number }>;
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

### 4.2 数据域（只读）

| domain | 结构 | 来源 | 刷新 |
|---|---|---|---|
| `runtime.activity` | `RuntimeActivity` | `GET /api/runtime/activity` | 3s |
| `sessions.running` | `{ updated_at, sessions: RunningSession[] }` | `GET /api/agents` + `GET /api/agents/{id}/threads?limit=20` | 3s |
| `plugins.installed` | `{ plugins: InstalledPluginSummary[] }` | `GET /api/plugins` | 10s |
| `host.context` | `{ locale, theme, now }` | 宿主 | 即时 |

```ts
interface RunningSession {
  agent_id: string;
  agent_name: string;
  thread_id: string;
  title: string;
  turn_active: boolean;
  awaiting_user: boolean;
  last_active: number;   // epoch ms；0 表示未知
  model_ref: string | null;
}
```

`RunningSession` 只包含 `turn_active === true || awaiting_user === true` 的会话。
`last_active` 统一转换为 epoch 毫秒。没有运行中的任务时返回空数组，**不生成占位或示例数据**。

引用计数：没有订阅者时停止轮询；最后一个订阅取消后释放定时器。

### 4.3 产品事件

| event | payload | 触发条件 |
|---|---|---|
| `session.started` | `{ at, session: RunningSession }` | 新会话进入运行集合 |
| `session.updated` | `{ at, session: RunningSession }` | 运行集合内字段变化 |
| `session.ended` | `{ at, session_id: string }` | 会话离开运行集合 |

事件由宿主对 `sessions.running` 的真实轮询结果做差分产生，不是合成流。
`at` 为宿主本地 epoch 毫秒。

### 4.4 错误码

| code | 含义 | 插件应如何处理 |
|---|---|---|
| `SURFACE_SLOT_UNKNOWN` | 声明了宿主不支持的 slot | 不挂载；管理员界面显示原因 |
| `SURFACE_DUPLICATE_ID` | 同插件内 surface id 重复 | 保留首个；后者忽略 |
| `SURFACE_REGISTER_FAILED` | 运行时注册失败（如缺 component） | 宿主记录 warning，不中断其他插件 |
| `PLUGIN_UI_LOAD_FAILED` | ESM 拉取/执行失败 | 插件卡片显示错误，其余插件继续 |
| `HOST_JOBS_UNSUPPORTED` | `jobs` 定时行为在 v1 不可用 | 插件降级为打开面板时执行 |
| `HOST_AGENT_DEFAULT_MODEL_READONLY` | 试图写默认模型 | 只读；引导用户到宿主设置页 |
| `HOST_AGENT_CONTEXT_MISSING` | 上传附件时没有 Agent 上下文 | 先等待有会话再调用 |
| `HOST_ATTACHMENT_UPLOAD_FAILED` | 附件上传失败 | 展示错误，可重试 |
| `HOST_SERVER_HOOK_UNSUPPORTED` | `webServer.tapIndex` 等只存在于服务端 | 不要依赖 HTML 注入 |

### 4.5 宿主服务（DSH 兼容层按需解析）

| 服务 | 支持 | 说明 / 原因码 |
|---|---|---|
| `jobs` | 否 | v1 插件只存在于浏览器运行时，无服务端常驻调度器 → `HOST_JOBS_UNSUPPORTED`；调用返回 `{ ok:false, code, reason }`，不会抛错 |
| `agentDefaultModel` | 只读 | `resolve()/get()` 读取当前 Agent 的 `default_model`；`set()` → `HOST_AGENT_DEFAULT_MODEL_READONLY` |
| `attachments` | 是 | `upload(file)` / `add(file)` 复用宿主上传接口；无 Agent 上下文 → `HOST_AGENT_CONTEXT_MISSING` |
| `webServer.tapIndex` | 否 | 客户端插件无法改写服务端 `index.html` → `HOST_SERVER_HOOK_UNSUPPORTED` |

不支持的服务仍然「可解析」，插件不会因 `ctx.get("jobs")` 拿到 `undefined` 而崩溃；
首次访问会把 `service:<name>:<code>` 写进兼容层的状态报告，管理界面据此提示。

### 4.6 字体变量

插件写入的 CSS 变量由宿主界面真实消费，作用在全局（HTML 根节点）：

| 变量 | 宿主消费位置 |
|---|---|
| `--dsh-font-size-text` | 用户消息气泡、助手正文（优先于宿主字号偏好） |
| `--dsh-font-family-text` | 用户消息气泡、助手正文 |
| `--dsh-font-size-code` | 消息内 `pre` / `code` |
| `--dsh-font-family-code` | 消息内 `pre` / `code` |

宿主不会预置这些变量：插件没设置时回落到宿主自身的阅读字号设置。
插件卸载时，它写过的变量会被清除，不残留到下一次安装。

## 5. 生命周期与卸载

1. 装载：`GET /api/plugins` 返回插件与 `ui`；Dashboard 拉取 `ui.entry`，执行 `setup(host)`。
2. 注册：surface 进入按 `pluginId` 分组的注册表；宿主记录 `setup` 的清理函数。
3. 卸载：后端删除 `~/.octop/plugins/<id>`；前端收到插件变更事件后：
   - 调用该插件的 `setup` 清理函数；
   - `unregisterPluginSurfaces(pluginId)`；
   - 注销工具渲染器并撤销 blob URL；
   - 停止无人订阅的数据轮询。
4. 结果：页面不再渲染该插件，注册表与 DOM 均无残留；重新安装后可再次注册。

## 6. 安全与隐私

- 同源受信 ESM，无沙箱；见 §0。
- 数据域只读，宿主做白名单校验；未知 domain 返回 rejected Promise。
- 事件订阅随插件卸载自动释放；插件不应在全局对象上挂持久引用。
- 插件不得修改宿主 DOM 结构之外的全局样式；建议使用内联样式或局部容器。
- 不要在其他用户的会话中渲染敏感信息；数据域只返回当前鉴权用户可见的数据。

## 7. 版本策略

- `apiVersion` 为整数。新增 slot/data/event 属于向后兼容的 minor 变更，`apiVersion` 不变。
- 删除或改变语义时提升 `apiVersion`；插件可通过 `host.apiVersion` 做能力判断。
- 宿主对未知 slot 返回 `supported=false`，不静默挂载到错误位置。

## 8. 最小示例

```js
export function setup(host) {
  const React = window.__OCTOP_REACT__;
  const h = React.createElement;

  function Card({ host: h2 }) {
    const [state, setState] = React.useState(null);
    React.useEffect(() => h2.data.subscribe("sessions.running", setState), [h2]);
    const sessions = state?.sessions ?? [];
    return h(
      "div",
      { style: { padding: 12 } },
      h("strong", null, `运行中：${sessions.length}`),
      sessions.map((s) => h("div", { key: s.thread_id }, s.title)),
    );
  }

  return host.surfaces.register({
    id: "example",
    slot: "home.sidebar",
    title: "示例",
    component: Card,
  });
}
```

> 再次提醒：上面的代码与宿主同权限执行，不是沙箱。
