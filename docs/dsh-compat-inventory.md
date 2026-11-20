# DSH 插件兼容性盘点（HappyClaw）

采集时间：2026-11-16（第二轮，宿主补齐插槽/服务后复测）。样本：9 个真实 DSH 插件包，两个来源——

- 已安装市场：`%USERPROFILE%\.octop\market\dsh\*`（5 个）
- 独立下载样本：`.tmp/dsh-compat/downloads/*`（4 个，`npm pack` 自 registry）

运行环境：Node v24.11.1；隔离实例 `OCTOP_HOME=.tmp/dsh-compat/home`，宿主端口 4971，
`OCTOP_DSH_MARKET_ROOT=.tmp/dsh-compat/market`（把两处样本 junction 成一个市场根），
`OCTOP_DSH_COMPAT=1`、`OCTOP_DSH_COMPAT_PLUGINS=dsh:*`。

> 结论先行：9/9 宿主半边挂载成功且全部 `OK`，`missing` 为空；10 个此前无 slot 的客户端条目
> 现在都落到宿主真实插槽（`conversation.view`、`conversation.input.left/overlay`、
> `settings.section`）并能渲染出可见 DOM。剩余不可达项按原因码逐条列在 §5。

## 1. 失败原因分类（首轮 → 本轮）

| 错误码 | 首轮 | 本轮 | 典型真实原因 | 处理方式 |
| --- | ---: | ---: | --- | --- |
| `OK` | 2 | **9** | — | — |
| `MISSING_API` | 5 | **0** | `@deepseek-ai/dsh-tools`、`@deepseek-ai/schemastery`；`jobs`/`attachments`/`agentDefaultModel` | Node 解析钩子 + 本地兼容模块；后三者在宿主服务表里落地 |
| `IMPORT_FAILED` | 2 | 0 | `ERR_MODULE_NOT_FOUND` | 同上 |
| `RUNTIME_THROW`（曾误报 `DSH_RPC_UNKNOWN`） | 1 | 0 | runner 把宿主对 runner 主动 RPC 的应答当新请求二次分发 | 无 `method` 的消息只走 pending 应答 |
| `HOST_JOBS_UNSUPPORTED` | — | 1 包 | 插件要常驻定时调度，宿主无调度器 | 服务存在但调用返回稳定原因码，`/status` 逐条展示 |
| `HOST_SERVER_HOOK_UNSUPPORTED` | — | 1 包 | `webServer.tapIndex` 想注入服务端 HTML | 同上（`meme`） |
| `HOST_ATTACHMENTS_UPLOAD_API_ONLY` | — | 1 包 | 宿主半边不直接落盘附件 | 服务存在，写入走宿主上传接口；无接口时返回该码（`meme`） |
| `HOST_AGENT_DEFAULT_MODEL_READONLY` | — | 0 | 默认模型只读 | `set` 返回该码（`meme` 只读读取成功） |
| `SLOT_UNSUPPORTED` | 4 包 | **3 包** | `settings.plugins.tab`、`plugins.detail.section`、`main`、`main.conversation` 宿主仍无 slot | 逐条上报，不自行扩接口 |
| `CLIENT_MISSING` | 1 | 1 | `dsh-plugin-demo` 本来没有客户端包 | 宿主半边照常运行 |
| `NATIVE_MODULE` | 0 | 0 | `dsh-meme` 用 `node:sqlite`，Node 24 自带 | 无需处理 |
| `NEEDS_NETWORK` / `NEEDS_CREDENTIAL` | 0 | 0 | 运行期触发（表情外发、模型调用） | 按插件隔离 |
| `NOT_ALLOWED` | — | 0 | 白名单外 | 有单测覆盖 |

## 2. 逐插件结果（端口 4971，全部 mounted）

| 插件 | 类别 | 宿主半边 | 工具/提示段/路由 | 客户端条目 → 宿主 slot | 仍未映射 |
| --- | --- | --- | --- | --- | --- |
| `dsh-turn-notify` 1.0.5 | 对话 | OK | 0 / 0 / 1 | 无 slot 注册 | — |
| `dsh-auto-memory` 3.3.17 | 记忆 | OK | **19 / 3 / 73** | `sidebar.footer.action`→`home.sidebar`；3×`shell.overlay`→`chat.messages.top`+portal；`settings.section`；2×`conversation.view` | `settings.plugins.tab`、`plugins.detail.section` |
| `dsh-temptask` 0.6.0 | 挂件 | OK | 0 / 0 / 11 | `sidebar.panellist`、2×`shell.overlay`、2×`sidebar.workspaces.*`、`settings.section`(+icon) | `main` |
| `agentduel-dsh` 0.1.6 | 挂件 + 叠加层 | OK | 0 / 0 / 0 | `sidebar.footer.action`、`shell.overlay` | `main.conversation` |
| `dsh-bloom-theme` 0.27.0 | 外观 | OK | 0 / 0 / 1 | `conversation.header.leading`→`chat.messages.top`；`shell.overlay` | — |
| `dsh-meme` 0.1.81 | 对话（表情） | OK（`attachments`/`tapIndex` 带原因码） | 4 / 0 / 4 | `settings.section`、`plugins.bundle.config`→`settings.section`、`conversation.input.left`、`conversation.input.overlay` | — |
| `dsh-plugin-demo` 1.1.0 | 基线 | OK | 0 / 0 / 0 | 无客户端包（`CLIENT_MISSING`） | — |
| `whale-girl` 0.2.4 | 挂件（桌宠） | OK（`jobs` 带原因码） | 0 / 0 / 0 | `plugins.bundle.config`→`settings.section` | — |
| `dsh-chat-typography` 1.5.6 | 外观 | OK | 0 / 0 / 1 | `settings.section`、`settings.section.icon` | — |

## 3. 运行证据

### 3.1 宿主实例

```
GET  /api/dsh-compat/status        -> enabled=true, plugins=9
GET  /api/dsh-compat/slots         -> home.sidebar, chat.messages.top, conversation.view,
                                      conversation.input.left, conversation.input.overlay, settings.section
POST /api/dsh-compat/{id}/start    -> 9/9 mounted, code=OK, missing=[]
POST .../dsh-auto-memory/tools/memory_status -> {"ok":true,"result":{"ok":true,...}}
POST .../dsh-meme/tools/meme_list           -> {"ok":true,"result":{"ok":true,"total":24,"shown":20,...}}
```

`/status` 中带原因码的条目（不是静默失败）：

```
dsh:dsh-meme       unsupported=[service:attachments:HOST_ATTACHMENTS_UPLOAD_API_ONLY,
                                service:webServer.tapIndex:HOST_SERVER_HOOK_UNSUPPORTED]
dsh:whale-girl     unsupported=[service:jobs:HOST_JOBS_UNSUPPORTED]
```

### 3.2 浏览器垫片（jsdom，真实 bundle 原样加载）

`loaderShim.test.tsx` live 用例现在会把每个 bundle 映射出的**每个宿主 slot 都渲染一遍**，
并断言没有 `[role=alert]`；输入区条目还会点一次触发器、断言浮层真的出现：

```
[live] dsh-auto-memory    settings.section nodes=11  text="记忆设置 展开设置 加载中…"
[live] dsh-auto-memory    conversation.view nodes=212 text="☰ 记忆中枢 关闭 导航 dsh-auto-memory …"
[live] dsh-temptask       settings.section nodes=20  text="临时任务 · 配置 每个任务 = DSH 目录下…"
[live] dsh-chat-typography settings.section nodes=93 text="对话流排版 统一设置对话流中的字体、字号与间距…"
[live] dsh-meme           settings.section nodes=32  text="图库发现设置 新建图包库 导入图库…"
[live] dsh-meme           conversation.input.left nodes=3（图标按钮）
[live] dsh-meme           overlay-after-click nodes=7（点击后浮层展开）
[live] dsh-whale-girl     settings.section nodes=51  text="更新检查中…网页端显示 关闭后网页端宠物不渲染…"
Tests 14 passed (14)
```

### 3.3 字体变量确实生效

- `dsh-chat-typography` 走 `ctx.theme.setFontSize(role, px)`，垫片写入
  `documentElement.style --dsh-font-size-<role>` / `--dsh-font-family-<role>`；
- 宿主聊天气泡已消费（`chatMessages.partial.less:528`）：
  `font-size: var(--dsh-font-size-text, var(--octop-message-font-size, 14px))`；
- 单测 `writes font roles into the variables the chat UI consumes` 断言写入值。

### 3.4 关闭开关（未设 `OCTOP_DSH_COMPAT`）

- `/status` → `{"enabled": false, "allow": [], "plugins": []}`
- 控制路由 → `503 {"code":"DISABLED"}`
- 不启动任何 Node 子进程。

## 4. 已补的接口（按类）

| 类别 | 真实缺口 | 适配实现 |
| --- | --- | --- |
| 外观 | `ctx.theme.*`、`ctx.uiTheme` | `data-theme`/`.dark` 双向切换；字体角色 → `--dsh-font-size-*` / `--dsh-font-family-*`（宿主气泡已消费） |
| 记忆 | `ctx.tools.register`、`ctx.systemPrompt.section/context`、`turn.done` | 19 个工具并入 agent 工具表；3 个提示段拼进 system prompt；回合结束广播事件 |
| 对话 | 会话 store、`conversation.view`、`conversation.input.*` | `sessions.list`(`{byId, phase}`) + `sessionStatus`；`conversation.view` 透传 threadId/message；输入区提供 `inputActions`（setDraft/insertText/submit，驱动宿主 textarea） |
| 叠加层 | `ctx.slots.register` + portal | `shell.overlay`/`overlay.*`/`modal.*`/`toast.*` → `chat.messages.top` + `createPortal(document.body)`，逐条 `SurfaceBoundary` |
| 挂件 / 设置 | `slots.inject/register`、`configForms`、`locale.bind`、`plugins.bundle.config` | 立即回调式 `inject`；配置作用域按 namespace 落 localStorage，支持 `mutate([{op:"set",path,value}])`；`bind()` 真正查表翻译；`hooks` → `useXxx(selector)` 并用快照缓存避免 `useSyncExternalStore` 死循环 |
| 组件库 | `@deepseek-ai/dsh-client-ui-primitives` | `primitivesShim.tsx`：Button/Input/Textarea/Select/Checkbox/Switch/Field/Label/Tooltip，沿用宿主主题变量 |
| 通用 | `@deepseek-ai/dsh-tools`、`@deepseek-ai/schemastery` | Node `module.register` 解析钩子，真实包优先，否则回退 `node/shims/*.mjs` |
| 宿主服务 | `jobs`/`attachments`/`agentDefaultModel`/`webServer.tapIndex` | 前三者真实提供（定时=拒绝、附件=转上传接口、模型=只读）；`tapIndex` 拒绝。拒绝一律返回稳定原因码 |

## 5. 仍存在的真实缺口

1. **包页专属 slot 仍无宿主承载**：`settings.plugins.tab`（auto-memory 的插件页签）、
   `plugins.detail.section`（auto-memory 详情块）、`main` / `main.conversation`
   （temptask、agentduel 的整页视图）→ 记 `SLOT_UNSUPPORTED`。这些是「插件详情页/整页应用」形态，
   宿主暂不提供承载位。
2. **`jobs` 真调度未实现**：`whale-girl` 的定时行为（会话记忆汇总等）只能拿到
   `HOST_JOBS_UNSUPPORTED`，不会静默成功。
3. **`webServer.tapIndex` 拒绝**：`dsh-meme` 无法向服务端 HTML 注入内容，返回
   `HOST_SERVER_HOOK_UNSUPPORTED`。
4. **宿主半边附件**：`dsh-meme` 的图片保存/读取走 `attachments.*` RPC，宿主未实现对应 RPC 时返回
   `HOST_ATTACHMENTS_UPLOAD_API_ONLY`；浏览器半边已复用宿主上传接口。
5. **`inject` 依赖缺口**：`dsh-meme` 声明 `workspaces`、`agentduel` 声明
   `workspaces`/`modelDirectories`、`bloom-theme` 声明 `remote.pluginManager`/`cordisInspect`——
   均记为 `inject:<name>`，对应面板里与这些服务相关的按钮不出现（其余功能正常）。
6. **`settings.section` 没有分组语义**：所有插件的设置卡片平铺在同一区域；
   `settings.section.icon` 被接受但不渲染图标。
