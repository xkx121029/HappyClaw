# DSH 兼容层任务清单

图例：`[ ]` 未开始，`[~]` 进行中（部分达成），`[x]` 完成。每项完成都必须附证据（命令输出 / JSON / 截图路径）。

## T1 盘点基础设施（先行，不改宿主）
- [x] T1.1 建 `.tmp\dsh-compat\{downloads,home,reports}`，写样本清单（5 已装 + 4 新下载）
- [x] T1.2 `npm pack` 拉取 4 个 appearance/dialog 样本并解包（不改主实例）
- [x] T1.3 实现 `probe.py::classify_static`（入口形态、ctx/require 集合、原生模块、构建/网络/凭据信号）
- [x] T1.4 实现 `node/cordis-lite.mjs` + `node/probe.mjs` 动态探针
- [x] T1.5 跑遍 9 个样本，产出 `reports/inventory.json` + `docs/dsh-compat-inventory.md`（含分类计数与每插件证据）
- [x] 证据：`docs/dsh-compat-inventory.md` §1 分类表（9 = 7 OK + 2 MISSING_API）与 §2 逐插件表

## T2 宿主运行器（工具 + 基础服务）
- [x] T2.1 `switch.py`（`OCTOP_DSH_COMPAT`、`OCTOP_DSH_COMPAT_PLUGINS`）与错误码
- [x] T2.2 `transport.py::NodeRpcClient`（JSONL、超时、退出检测、未知错误码降级）
- [x] T2.3 `host-services.mjs`：`get/provide/inject/effect/on/logger/webServer/tools`
- [x] T2.4 `runner.mjs`：mount、`ready`、`http.request`、`tools.call`、`shutdown`
- [x] T2.5 `registry.py`：懒启动、状态、退避、`shutdown_all`
- [x] T2.6 工具并入 agent 工具表（经 `agents/manager.py` 合并，未改 `catalog.py` 结构）
- [x] 证据：隔离实例 `POST /dsh%3Adsh-auto-memory/start` → mounted，19 tools / 3 prompts / 73 routes；
      9/9 挂载见 `docs/dsh-compat-inventory.md` §2；坏包（无入口）单测确认只失败自身且不 spawn node

## T3 记忆类
- [x] T3.1 `systemPrompt.section` → `compose_system_prompt` 桥接（失败静默，空块不注入）
- [x] T3.2 `write_shadow_turn` 发 `turn.done` 事件（daemon 线程，异常吞掉）
- [~] T3.3 `remote` 未接宿主内部方法：`remote.call` 返回 undefined（安全默认，不放行任意调用）；`sessions/agents` 只读桥已提供
- [~] T3.4 `dsh-auto-memory` 验证：19 工具可调（`memory_status` 返回真实 `C:\Users\linch\.dsh\memory` 状态）、3 个提示段注册；`memory_log` 落盘未做写操作（避免污染真实记忆）
- [x] 证据：`POST .../tools/memory_status` 输出；`docs/dsh-compat-inventory.md` §3

## T4 客户端垫片（挂件 + 侧边栏 + 浮层）
- [x] T4.1 `loaderShim.tsx`：`__ModuleLoader__` + `require` 解析（含 `react/jsx-runtime`）+ React 注入
- [x] T4.2 DSH client ctx：`sessions/uiSession/locale/theme/uiTheme/remote/effect/on/config/configForms`
- [x] T4.3 slot 映射表 + `SurfaceBoundary` + portal 浮层
- [x] T4.4 `status/ui/report/route/tools/inventory/slots` API + 客户端文件只读路由（路径校验）
- [x] T4.5 `boot.tsx` + `main.tsx` 一行接入；单插件 try/catch + 结果上报
- [~] 证据：jsdom 中真实 bundle 全量加载并渲染（`loaderShim.test.tsx` live 用例，11/11 通过）；
      **未做**浏览器截图，改用 DOM 断言与 `SurfaceBoundary` 无告警作为替代

## T5 外观类
- [x] T5.1 `theme` 服务映射（light/dark/system ↔ `data-theme`/`.dark` + localStorage）、`uiTheme` 主题注册表、
      字体角色写入 `--dsh-font-size-*` / `--dsh-font-family-*`
- [x] T5.2 `dsh-bloom-theme` 挂载并注册 `conversation.header.leading` + `shell.overlay`；自装 CSS 生效；
      `dsh-chat-typography` 的 `settings.section` 渲染 93 个节点，`setFontSize` 写入的变量已被宿主聊天气泡消费
      （`chatMessages.partial.less:528`），字号改动可见
- [x] 证据：`docs/dsh-compat-inventory.md` §3.2/§3.3

## T6 对话框 / 富内容
- [x] T6.1 宿主新增 slot 后的映射：`conversation.view` / `conversation.input.left` /
      `conversation.input.overlay` / `settings.section` 已落到真实插槽
- [x] T6.2 逐消息渲染 / 输入区：`auto-memory` 会话视图渲染 212 节点；`dsh-meme` 输入区按钮渲染并在点击后展开浮层；
      仍不可达的 `settings.plugins.tab` / `plugins.detail.section` / `main*` 逐条上报 `SLOT_UNSUPPORTED`
- [x] 证据：`docs/dsh-compat-inventory.md` §2 逐插件表、§3.2 live 渲染输出、§5 缺口表

## T7 验收与回归
- [x] T7.1 `pytest tests/unit/dsh_compat -q` → 38 passed；`npx tsc --noEmit -p tsconfig.app.json` → 0 error
- [x] T7.2 隔离实例全流程：发现 9 包 → 启动 → 工具调用（`memory_status` / `meme_list`）→ 停止；
      `OCTOP_HOME` 隔离，市场根用 junction 合并，不动主实例数据
- [x] T7.3 关闭开关（4963）：`status.enabled=false`、控制路由 503 `DISABLED`、不 spawn runner
- [x] T7.4 `pytest tests/unit/plugins -q` → 112 passed；`pytest tests/unit/dsh -q` → 29 passed
- [x] 证据：命令输出见本文各条；`docs/dsh-compat-inventory.md` §3

## 依赖关系
T1 → T2 → T3/T4 可并行 → T5/T6 → T7。
T6 的逐消息/输入区依赖 `plugin-ui-platform` 线新增 slot；未落地前只出原因码，不自行扩接口。
