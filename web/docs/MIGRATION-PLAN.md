# `dashboard/` → `web/` 迁移计划

本文是后续每一轮的依据。数据来自对 `dashboard/` 的逐文件清点（原始数据见
[`dashboard-inventory.md`](dashboard-inventory.md)），在 `happyclaw/web-rewrite`
分支的 worktree 上实测。

**原则**

1. `dashboard/` 在迁移完成前一行不动，也可以继续发布；新前端在 `/web` 下独立演进。
2. 每个批次都能单独上线：批次完成后 `web/` 的对应页面可用，其余页面仍是占位，
   旧前端继续服务。
3. 判定的唯一标准是「这段代码值不值得搬到新栈」。UI 层一律重写（antd + less 到
   Tailwind + 自建组件不是平移，是重画）；纯逻辑（解析、状态机、时间格式化、
   socket 协议）直接复用，不重写。

## 0. 规模与判定

| 指标 | 数值 |
| --- | --- |
| `dashboard/src` TS/TSX | 258,748 行 / 1,316 文件 |
| `dashboard/src` LESS | 59,282 行 / 174 文件 |
| 路由条目 `routeConfigs` | 73 条 → 35 个真实页面（30 个页面模块）+ 38 个重定向 |
| 手机端独立树 `mobile/` | 6,803 行，13 条 `/m/*` 路由 |
| 最大单页 | Chat：62,719 行 / 303 文件（`chatStore.ts` 单文件 4,392 行） |
| 前四名合计 | Chat + Experts + Memory + CloudHosts ≈ 130k 行，占全站一半 |

结论：**Chat 是长杆，不是「一个批次」**。计划把 Chat 拆成 3 个子批次，并按
「消息列表 → 输入/工具 → 预览/附件」的顺序推进。

## 1. 路由与页面清单（判定到文件）

`FS` 全屏 / `SH` 自带头部 / `WRAP` 由 `MainLayout` 替换挂载 / `KA` 常驻挂载。

| 路由 | 页面模块（文件） | 行数 | 判定 | 后续批次 |
| --- | --- | --- | --- | --- |
| `/home` | `pages/Home/index.tsx`（11 文件） | 5,534 | **重写**：活动流 + 卡片，逻辑简单但样式全换 | B1 完成 |
| `/chat`、`/chat/:agentId`、`/chat/:agentId/:threadId` | `pages/Chat/index.tsx`（303 文件） | 62,719 | **拆分重写**：见 §3 的 Chat 拆解 | B5a/b/c |
| `/solo` | `pages/Solo/index.tsx`（21 文件） | 4,988 | **重写**：chat + monaco + xterm 组合，依赖 B5、B6 | B6 |
| `/bao` | `components/Bao/BaoPage.tsx`（9 文件） | 2,575 | **重写**：Router 页，`?project=` 作用域 | B3 |
| `/experts` | `pages/Experts/index.tsx`（67 文件） | 15,188 | **拆分重写**：列表/详情/子智能体管理 | B3 |
| `/tasks` | `pages/Control/CronJobs/index.tsx`（17 文件） | 3,535 | **重写**：表单 + 运行记录表 | B3 |
| `/connectors` | `pages/Agent/Connectors/index.tsx`（22 文件） | 5,927 | **重写**：目录 + OAuth 回调 | B2 |
| `/skill-packages` | `pages/SkillPackages/index.tsx`（6 文件） | 1,876 | **重写** | B2 |
| `/knowledge-bases` | `pages/KnowledgeBases/index.tsx`（12 文件） | 5,082 | **重写**：依赖文档预览（B5c） | B2 |
| `/bridge` | `pages/Settings/Bridge/index.tsx` | 16 | **删**：只有一行转发到 `AdvancedSettings/BridgeSettings` | — |
| `/personalization/*` | `pages/Agent/Personalization/index.tsx`（8 文件） | 2,514 | **重写**：壳 + 6 个 tab | B3 |
| ↳ Skills | `pages/Agent/Skills/**`（32 文件） | 7,901 | **重写** | B3 |
| ↳ Tools | `pages/Agent/Tools/**`（4 文件） | 812 | **重写** | B3 |
| ↳ Memory | `pages/Agent/Memory/**`（48 文件） | 15,336 | **重写**：recharts → recharts（保留） | B3 |
| ↳ Channels | `pages/Agent/Channels/**`（11 文件） | 4,898 | **重写**：二维码/轮询逻辑可复用 | B3 |
| ↳ Subagents | `pages/Experts/components/SubagentManager/**` | （计入 Experts） | **重写** | B3 |
| `/token-usage` | `pages/Control/TokenUsage/index.tsx`（5 文件） | 1,574 | **重写**：一个图表 + 一张表 | B1 |
| `/acp` | `pages/Agent/ACP/index.tsx`（4 文件） | 765 | **重写** | B3 |
| `/workbench` + 三个 tab | `pages/Control/Workbench/index.tsx` | 118 | **重写**：壳 | B6 |
| ↳ Terminal | `pages/Control/Terminal/**`（14 文件） | 3,435 | **重写 UI，复用 `useTerminal` 逻辑**（xterm 5.5） | B6 |
| ↳ RemoteBrowser | `pages/Control/RemoteBrowser/index.tsx`（2 文件） | 1,696 | **重写 UI，复用 canvas 流/交互逻辑** | B6 |
| ↳ CloudHosts | `pages/Control/CloudHosts/**`（20 文件） | 11,040 | **重写** | B6 |
| `/remote-desktop/*` | `pages/Control/RemoteDesktop/index.tsx`（4 文件） | 1,791 | **重写 UI，复用快捷键/指针捕获** | B6 |
| `/admin/models` | `pages/Settings/Models/**`（36 文件）+ `Settings/{Voice,SearchConfig,MediaGeneration}` | 8,572 | **重写** | B4 |
| `/admin/backend` | `pages/Admin/Storage/index.tsx`（9 文件） | 2,541 | **重写** | B2 |
| `/admin/plugins` | `pages/Admin/Plugins/index.tsx`（9 文件） | 2,444 | **重写** | B2 |
| `/admin/advanced` | `pages/Settings/AdvancedSettings/**`（12 文件）+ `Settings/{Environments,Observability,BackupRestore,HttpsSettings,PhoneAccess}` | 4,489 | **重写** | B4 |
| `/admin/security` | `pages/Settings/Security/index.tsx`（6 文件） | 1,429 | **重写** | B4 |
| `/agent-config` | `pages/Agent/Config/index.tsx`（3 文件） | 290 | **复用逻辑**：体积小、无 antd 布局依赖，逻辑近乎可直接搬 | B1 |
| `/setup`（壳外） | `pages/Setup/**`（8 文件） | 3,317 | **重写为诊断页**：见下方「Setup 的真相」 | B1 完成 |
| `*` | `components/NotFoundPage.tsx` | 23 | **已在 `web/` 内实现**（`routes/__root.tsx`） | 完成 |
| `/pwa-debug` | `pages/PwaDebug/index.tsx` | 710 | **删**：调试页，新 PWA 用 `vite-plugin-pwa` 重做 | — |
| `/motion-preview` | `pages/MotionPreview/index.tsx`（2 文件） | 796 | **删**：已被 `/design` 取代 | 完成 |
| `/m/*`（13 条） | `mobile/**` | 6,803 | **删**（待产品确认）：新外壳响应式，不再维护第二套页面树 | B7 |
| 38 条重定向 | `routes/index.tsx` | — | **直接搬**：`RedirectPreserveSearch` 语义必须保留 `?search` + `#hash` | B1 完成 |

### Setup 的真相（B1 实测）

这个构建里向导的**写入**接口全部直接抛 `SINGLE_USER_UNSUPPORTED`：
`POST /api/setup/database`、`/setup/begin`、`/setup/initial-admin`、`/setup/finish`、
`/setup/verify-password`（`api/routers/setup.py` 里的 `_single_user()`）。单人模式下
SQLite 与本地所有者在启动时自动绑定创建——用一个全新的 `OCTOP_HOME` 起服务，
`GET /api/setup/status` 直接返回 `{"setup_required": false, "database_bound": true,
"single_user": true}`，向导从来不会被触发。

所以 `web/src/features/setup/` 没有复刻旧的多步向导（那会是一条每步都 500 的假流程），
而是做成本构建里**真实可用**的首次运行页：实例状态（驱动/绑定/所有者/模式）+
`POST /api/setup/test-database` 数据库探测 + `POST /api/setup/test-provider` 供应商探测。
旧向导（8 文件 3,317 行）只有在后端真的重新支持多用户初始化时才值得搬，届时按
`docs/dashboard-inventory.md` 的 (b) 表逐文件对照即可。

**明确不迁移的死代码**（已核实）：

| 目标 | 原因 |
| --- | --- |
| `pages/Invite`、`pages/Login` | 已退化为 `Navigate` 到 `/chat`，单人模式无登录 |
| `pages/Admin/SharedModels`（111 行） | `/admin/shared-models` 重定向到 `/admin/models`，不可达 |
| `api/modules/embedding.ts` | 调 `/api/embedding/*`，后端没有任何 router 挂载该前缀；无人 import |
| `motion/`、`page-transitions/` | 被 `/design` 的 token 动效取代 |

**必须复用的纯逻辑**（不重写，搬家即可）：

| 来源 | 行数 | 内容 |
| --- | --- | --- |
| `pages/Chat/hooks/chatStore.ts` + 同目录 78 个 hook | 20,840 | 会话状态机、SSE/WS 帧解析（`parseHarnessChunk`）、HITL 审批、重连排序 |
| `pages/Chat/utils/**`（92 文件） | 10,406 | 消息投影、内容块解析、附件处理、工具卡片格式化 |
| `api/modules/wsChat.ts` + `desktopWsUrl.ts` | — | WS URL 构造（含 `octop_token` 查询参数） |
| `hooks/useServerTimezone` + `utils/formatMessageTime.ts` | — | 服务端时区渲染 |
| `pages/Control/Terminal/hooks/useTerminal.ts` | — | xterm 生命周期与 WS 绑定 |
| `pages/Control/RemoteBrowser/**/useBrowserCanvasInteraction` | — | canvas 指针/滚轮映射 |
| `utils/pcmCapture.ts`、`realtimeStt.ts` | — | 语音输入输出 |
| `styles/themePalettes.ts` | — | 自定义品牌色的对比度推导（可作为主题生成器保留） |

## 2. 批次计划

每批的验收都是「在 `web/` 里跑通 + 旧前端不受影响」。行数是 TS/TSX 实测。

| 批次 | 范围 | 规模 | 依赖 | 验收 |
| --- | --- | --- | --- | --- |
| **B0**（本轮，已完成） | 外壳 + 设计系统 + token + i18n + 路由 + API 客户端 + Chat/设置样板页 | 新写 ~4.2k | — | `npm ci && npm run build && npx tsc -b && npm run lint` 全绿；`/chat`、`/settings`、`/design` 渲染；对 `/api/agents`、`/api/agents/{id}/threads`、`/api/agents/{id}/threads/{tid}/history`、`/api/settings/*`、`/api/preferences` 发起真实请求 |
| **B1**（已完成，本轮） | Home、38 条旧路由重定向（含 `/m/*`）、`/setup` 首次运行诊断页 | 实做 2.1k | B0 | `/home` 用真实数据渲染（agents/threads/activity/usage/HITL 全 200）；旧路由落地且保留 `?search`/`#hash`；未迁移目标回落到 `/home` 而不是 404；`/setup` 能读到实例状态并跑通数据库探测 |
| **B1-余** | TokenUsage 图表、AgentConfig | ~2k | B1 | `/api/usage/summary` 的 `buckets` 出图；`/agent-config` 保存生效 |
| **B2** | 内容 CRUD：KnowledgeBases、SkillPackages、Connectors、Plugins、Storage | ~16k | B0 | 每类各完成一次「新建→列表→删除」；`/api/knowledge-bases`、`/api/skill-packages`、`/api/connectors` 200；上传预览可用 |
| **B3** | 智能体域：Experts（含 SubagentManager）、CronJobs、Personalization 四个 tab（Skills/Tools/Memory/Channels）、ACP、Bao | ~29k | B2 | 智能体 create/start/stop 往返；cron 新建 + run-now 产出一次运行；Memory tab 能列并改一条记忆 |
| **B4** | 设置/管理：Models（含 Voice/Search/媒体/Embedding 面板）、AdvancedSettings（含 Environments/Observability/Backup/TLS/PhoneAccess）、Security、`/bridge` 并入 | ~18k | B2 | 供应商「测试连接」成功；`POST /api/update/check` 200；主题/语言切换免刷新持久化 |
| **B5a** | Chat：消息列表 + 历史分页 + 虚拟滚动 | Chat 的 1/3 | B1 | 打开线程渲染历史；滚到顶触发 `offset` 分页；切换线程**不重挂载** |
| **B5b** | Chat：输入框 + 工具卡片 + HITL 审批 + 附件上传 | Chat 的 1/3 | B5a | 发消息看到流式 token；HITL 审批卡可应答复位 |
| **B5c** | Chat：文件预览（pdf/docx/pptx/xlsx/monaco）+ markdown/katex/mermaid 渲染器 | Chat 的 1/3 | B5b | 上传 PDF/DOCX/XLSX 各一张并能预览；mermaid 懒加载不阻塞首屏 |
| **B6** | Workbench（Terminal/Browser/CloudHosts）+ RemoteDesktop + Solo | ~22k | B5c | 终端执行 `ls` 有输出（WS `/api/agents/{id}/terminal`）；浏览器/桌面各出一帧；Solo 分栏可拖拽 |
| **B7** | 切换：FastAPI 静态挂载指向 `web/dist`；`dashboard/` 保留一个版本后删除 | — | 全部 | `make build-frontend` 从 `web/` 产出；`make all` 绿；Linux + Windows CI 冒烟全部路由 |

为什么这个顺序：B1 建立「一个页面从路由到真实数据」的完整样板（Home 最简单），
B2 建立「列表/表单/上传」的通用骨架，B3 把最常用的日常页面搬完，B4 是低频但必
须有的设置页，B5/B6 是真正有技术风险的部分（流式、终端、canvas），放最后可以
用前面几批把设计系统和组件层磨稳定。B7 之前两套前端并存，没有一天是断的。

## 3. Chat 拆解（B5）

Chat 一个模块 62,719 行，是本轮唯一需要三批的页面。按**谁来渲染**切：

| 子批 | 范围 | 复用 | 重写 |
| --- | --- | --- | --- |
| B5a | 线程列表、消息列表、历史分页、滚动锚定 | `chatStore` 的历史/分页部分、`utils` 消息投影 | 全部 UI、虚拟滚动（`@tanstack/react-virtual`） |
| B5b | 输入框、附件、工具卡片、HITL、模型/模式选择 | `parseHarnessChunk`、HITL 状态机、`wsChat` | 输入 UI、工具卡片外观、审批卡 |
| B5c | 文件预览、markdown/数学/mermaid、dock | `DocumentPreviewCore` 的解析部分 | 预览 UI；渲染器包（react-markdown 系、mermaid）原样复用 |

本轮 B0 的 Chat 页只做了 B5a 的「列表 + 历史」和 B5b 的「发送一次 turn」：
历史走 REST，发送走 WS，但**不解码流式帧**——发完就重取历史。这样数据只有一个
来源，也对得上「先出骨架」的目标。

## 4. 与 `dashboard/` 共存与联调

- **开发期**：`web/` 的 Vite dev server（默认 5174）把 `/api` 代理到
  `HAPPYCLAW_API_ORIGIN`（默认 `http://127.0.0.1:8080`）。旧前端照旧跑自己的 dev
  server。两个进程可以同时开，端口不冲突。
- **同源生产**：最终 `web/dist` 由 FastAPI 静态挂载提供，`VITE_API_BASE` 保持为空。
- **并行期**：可以先在同一个 FastAPI 上把 `web/dist` 挂到 `/web` 子路径
  （`base: "/web/"` + `routerBasepath`），旧前端继续占根路径；页面级灰度按路由
  跳转即可，不需要后端改动。
- **降级**：后端不可达时，Chat 页回落到示例数据并在工具栏标出「示例数据」；
  设置页显示「后端不可用」而不是假数值。

## 5. 风险与未决

| # | 风险 | 处理 |
| --- | --- | --- |
| 1 | **Chat 不能因 `:threadId` 变化而重挂载**，否则输入框草稿与流式中断 | TanStack Router 的 `loaderDeps` + 保留父路由组件的组合；B5a 验收里专门卡这条 |
| 2 | **Workbench 三个面板常驻 + `display:none`** | 用路由 `match` 保留挂载或显式 keep-alive，不能在 tab 切换时卸载终端 |
| 3 | 43 个导航 key 与 15 条带 `?search` 的重定向 | B1 里对齐 `pathToKey`，重定向统一走同一个 `RedirectPreserveSearch` 组件 |
| 4 | ~~手机端是否保留独立页面树~~ | **已决定删除**（产品负责人）。`web/src/lib/legacy-routes.ts` 里 13 条 `/m/*` 已按「重定向到新外壳对应页」落地，老链接不会 404；`mobile/**` 6,803 行随 B7 一起删 |
| 5 | 桌面 Electron 壳是否也加载 `web/` | 若加载，B0 需要补 `window.octopDesktop` 门控与窗口拖拽区 |
| 6 | `tests/unit/i18n/` 强制后端 `errors.*` 与旧前端 `apiErrors.*` 对齐 | 新前端不改后端文案；错误码映射沿用后端 envelope，见 `src/lib/api/errors.ts` |
| 7 | 手机托管场景要把 API 源指向用户输入的 host | `env.apiBase` 已可注入，B7 前补 `mobileApiBase` 等价逻辑 |
| 8 | 部分聊天接口没有 `response_model`（返回 `dict`），生成类型是 `Record<string, unknown>` | 在 `features/*/types.ts` 声明实际读取的字段并在 `api.ts` 收窄；建议后端补 `response_model`，这会让生成类型真正可用。**B1 又撞上同一处**：`/api/runtime/activity`、`/api/usage/summary`、`/api/setup/status` 同样是 `dict`，Home 与 Setup 的字段声明都在各自 `types.ts`/`api.ts` 里 |

## 5.5 品牌字符串的现状（去 Octop 后）

`web/` 里所有「前端自己的字符串」已改为 HappyClaw：本地存储键、OpenAPI 文档文件名
（`openapi/happyclaw.openapi.json`）、用户可见文案（`happyclaw run`、`happyclaw agent create`）、
类型与示例数据、注释。仍保留 `octop` 字样的只有三类，且都是**别人的契约**，不在前端改名范围：

| 保留处 | 为什么 |
| --- | --- |
| `lib/api/auth.ts` 的 `X-Octop-Access-Token` | 服务端下发的响应头名，前端单侧改名会让 token 续期静默失效 |
| `lib/legacy-routes.ts` 里的 `/octop/cron` 等 4 条 | 用户浏览器里的历史 URL，改了就 404 |
| 迁移文档里的 `OCTOP_HOME`、`octop_token`、`window.octopDesktop` | 环境变量（保留旧名兜底）、WS 查询参数、桌面壳全局对象，均属后端/桌面壳契约 |

后端返回的字段名一律未动。

## 6. 本轮之后第一件该做的事

把 `dashboard/` 里那 31k 行「必须复用的纯逻辑」搬到 `web/src/features/chat/lib/`
（不带任何 antd/less import），因为 B5 的三批全部依赖它，而它也是唯一一处
「搬过来就少写一遍」的地方。搬运时用 `vitest` 把 `chatStore` 的现有测试（含
重连排序、HITL 恢复）一起迁过来，作为回归护栏。
