# 工作区归属重构：盘点与方案（已定稿，实现中）

> 状态：方案已定稿，按 P0 → P3 实现。目标是把「工作区 = 专家」改为「工作区 = 会话 / 项目」。

## 0. 结论摘要

1. 现状的工作区本质上是**专家级**的：`agents.config_json.workspace_dir` 是唯一权威，`threads` / `sessions` 表里没有工作区字段。
2. 现有「项目」只是**按 workspace_dir 反推的分组**：dashboard 项目 tab 和宝（Bao）的 `project_identity()` 都是这个规则；没有 projects 表。
3. Harness 的 `HarnessAgent` 在构造时固定一个 workspace，memory / sessions(JSONL) / checkpoints 也挂在 workspace 下。因此「按会话分目录」必须引入**运行时实例池（agent_id + workspace 双键）**，不能只改一个 cwd 参数。
4. 推荐落地顺序：先建 projects 表与 thread 归属 → 再切 cwd 解析 → 再做无工作区会话按需建目录 → 最后做「对话转项目」；每一步都以「老 Octop 安装整包升级」的迁移能力为前提（见第 4 节）。
5. 首次读写已定混合方案；家目录、冲突配置、外部目录、项目级技能、运行时上限、设备直连均已确认；「默认目录有用户文件时的分组冲突」已定为**不设固定默认、由升级向导强制用户二选一并留档**（见 4.4、第 8 节），方案已全部定稿，进入 P0 实现。

## 1. 现状盘点

### 1.1 数据模型

| 对象 | 表/字段 | 现状 |
|---|---|---|
| 专家 | `agents`，工作区存 `config_json.workspace_dir` | 创建时写入；之后 DB 值权威，harness 原样接收（[dir.py](file:///e:/HAPPYclaw/Octop/src/octop/infra/agents/workspace/dir.py#L1-L23)） |
| 会话（渠道） | `sessions(session_key, agent_id, thread_id, ...)` | 没有 workspace / project 字段（[001_initial.sql](file:///e:/HAPPYclaw/Octop/src/octop/infra/db/migrations/001_initial.sql#L115-L131)） |
| 对话（线程） | `threads(thread_id, agent_id, session_key, title, last_active, ...)` | 没有 workspace / project / cwd 字段（[001_initial.sql](file:///e:/HAPPYclaw/Octop/src/octop/infra/db/migrations/001_initial.sql#L133-L146)） |
| 项目 | 无表 | dashboard 与宝在内存里按 `workspace_dir` 归一化分组 |

### 1.2 绑定与创建

- 默认值：`{OCTOP_HOME}/agents/<id>/`；scoped backend 下是 `{root_dir}/.octop/workspaces/<id>/`（[dir.py](file:///e:/HAPPYclaw/Octop/src/octop/infra/agents/workspace/dir.py#L245-L270)）。
- 每次建专家都会 `seed_workspace_dir_on_create()` 建目录并把 `workspace_dir` 写进 config（[dir.py](file:///e:/HAPPYclaw/Octop/src/octop/infra/agents/workspace/dir.py#L297-L315)）。
- 专家模板文件（AGENTS.md / SOUL.md / IDENTITY.md / MEMORY.md / skills 等）直接写进 workspace 根，manifest 写进 `.octop/manifest.json`（[manager.py](file:///e:/HAPPYclaw/Octop/src/octop/infra/agents/manager.py#L4198-L4262)、[catalog.py](file:///e:/HAPPYclaw/Octop/src/octop/infra/agents/experts/catalog.py#L223-L249)）。
- 前端「新建项目」= 选一个文件夹 → 创建/复用一个绑定该 `workspace_dir` 的专家（[workspaceAgent.ts](file:///e:/HAPPYclaw/Octop/dashboard/src/pages/Chat/utils/workspaceAgent.ts#L11-L28)、[Chat/index.tsx](file:///e:/HAPPYclaw/Octop/dashboard/src/pages/Chat/index.tsx#L317-L367)）。所以「项目」今天其实是一个专家。

### 1.3 读取点清单（要一一改到）

| 类别 | 读取点 |
|---|---|
| 解析 / 运行时 | `resolve_workspace_dir`（[manager.py](file:///e:/HAPPYclaw/Octop/src/octop/infra/agents/manager.py#L1828-L1860)）、`BackendWorkspace` 构造（manager.py:4192-4196）、backend resolver（[resolver.py](file:///e:/HAPPYclaw/Octop/src/octop/infra/backend/resolver.py#L15-L85)） |
| 文件 / 工作区 API | 全部按 `agent_id` 寻址：[workspace.py](file:///e:/HAPPYclaw/Octop/src/octop/api/routers/workspace.py#L122-L240)、[agent_files.py](file:///e:/HAPPYclaw/Octop/src/octop/api/routers/agent_files.py)、[agent_workspace.py](file:///e:/HAPPYclaw/Octop/src/octop/api/common/agent_workspace.py#L9-L16) |
| 工具 cwd / 终端 | PTY 以 agent workspace 为 cwd（[terminal.py](file:///e:/HAPPYclaw/Octop/src/octop/api/routers/terminal.py#L458-L464)、:553）；dsh 工具/沙箱经 backend resolver 取根目录 |
| 技能 | 技能路由按 agent 取 workspace（[skills.py](file:///e:/HAPPYclaw/Octop/src/octop/api/routers/skills.py#L101)、:425/:476/:879/:1206）；[workspace_catalog.py](file:///e:/HAPPYclaw/Octop/src/octop/infra/skills/workspace_catalog.py) |
| 记忆 | memory client 按 agent workspace 解析（[memory_client.py](file:///e:/HAPPYclaw/Octop/src/octop/api/common/memory_client.py#L107-L109)）；memory 清理也按 workspace（`memory/thread_cleanup.py`） |
| 会话 / 欢迎 | chat welcome 用 `registry.workspace_for_agent(agent_id)`（[routes.py](file:///e:/HAPPYclaw/Octop/src/octop/api/routers/chat/routes.py#L67-L68)）；history 序列化 13 处 |
| 会话归组 | dashboard 项目 tab 按 `workspace_dir` 分组，默认组名「默认工作区」（[MinimalAgentSessionNav.tsx](file:///e:/HAPPYclaw/Octop/dashboard/src/pages/Chat/components/MinimalAgentSessionNav.tsx#L519-L622)、[chatNavScope.ts](file:///e:/HAPPYclaw/Octop/dashboard/src/pages/Chat/utils/chatNavScope.ts#L5-L43)） |
| 宝的路由 | 宝的 overview/route 用 `project_identity(workspace_dir)` 反推项目 key/name/is_default（[bao.py](file:///e:/HAPPYclaw/Octop/src/octop/api/routers/bao.py#L81-L116)、:119-245）；全局/项目作用域靠 `project_key` |
| SOLO | 前端独立的 agent/thread 选择（[Solo/index.tsx](file:///e:/HAPPYclaw/Octop/dashboard/src/pages/Solo/index.tsx#L29-L42)）；文件树与编辑器复用工作区 API，仍按 agent 取目录。后端没有 `/solo` 专属路由 |
| 备份 / 导出 | 全量备份按 agent 打包 workspace（[system_archive.py](file:///e:/HAPPYclaw/Octop/src/octop/infra/backup/system_archive.py#L1-L54)、:150-304、:416）；单工作区 zip 导入导出（[workspace_archive.py](file:///e:/HAPPYclaw/Octop/src/octop/infra/backup/workspace_archive.py#L55-L232)） |
| 发布 / 专家快照 | 发布专家会导出 agent workspace（[publish.py](file:///e:/HAPPYclaw/Octop/src/octop/infra/agents/experts/publish.py#L112-L124)、[published_creation.py](file:///e:/HAPPYclaw/Octop/src/octop/infra/agents/experts/published_creation.py#L111-L122)）——改造后只能导出私有配置，不能夹带用户文件 |
| 其他 | cron（cron.py:1）、gateway 媒体（inbound_store.py:4、backend_files.py:3、agent_resolve.py:2）、browser harness（harness.py:3）、teams（teams.py:4、teams/welcome.py:1）、离线运维（offline_ops.py:9、embedded_ops.py:1/121）、用户资源策略（resource_policy.py:5、users/manager.py:8）、OpenClaw 迁移（openclaw.py:89-91） |

> 全仓 `workspace_dir|workspace_for_agent|agent_workspace` 共 529 处、56 个文件；上表是消费方分类，不是逐行清单。

### 1.4 运行时硬约束（决定方案可行性）

- `HarnessAgent` 构造时固定 `config.workspace_dir`，`agent.workspace` 是只读属性；`init_workspace()` 会把内置模板/技能写进该 workspace（`.venv/.../octop_harness/agent.py:121-212、333-351`）。
- memory、`sessions/` JSONL、`checkpoints.sqlite` 都落在 on-disk workspace（同文件 148-157 行注释）。
- 现有运行时按 `agent_id` 取实例（`HarnessManager.get_agent(agent_id)`）。

含义：要支持「同一专家在不同项目目录里工作」，要么按 `(agent_id, workspace)` 池化实例，要么让 harness 支持逐轮切换 workspace（当前版本没有）。前者可做，但要把 memory / 技能从 workspace 拆到专家私有目录，否则会按目录碎片化。

## 2. 目标模型

### 2.1 术语

- **专家（agent）**：人格、提示词、技能、记忆的载体，可跨项目复用。
- **项目（project）**：长期目录 + 一组会话；有稳定的 project_id 和 root_dir。
- **会话（thread）**：一次对话；可属于项目，也可暂时无工作区。
- **默认项目**：所有没有明确归属的会话的兜底项目，名字沿用「默认工作区」，保证任何会话都能被找到。

### 2.2 目录布局（建议）

```text
{OCTOP_HOME}/
  agents/<agent_id>/                 # 专家私有目录（不再是工作区）
    AGENTS.md SOUL.md IDENTITY.md MEMORY.md
    .octop/manifest.json
    skills/                          # 专家级技能
    memory/                          # 专家级记忆（从 workspace 迁出）
  projects/<project_id>/             # 新建项目的默认落点
  sessions/<thread_id>/              # 无项目、但需要读写的会话
  workspaces/<legacy_id>/            # 仅兼容旧 scoped backend，不再新增
```

- 项目也可以指向用户自选的外部目录：`projects.root_dir` 存绝对路径，不搬动用户文件。迁移产生的项目同样沿用旧 workspace 路径，不强制搬进 `projects/`。
- 命名一律用不透明 ID（`prj_...`、`thr_...`），显示名只进 DB，不进路径，避免中文/重名/改名问题。
- 默认项目 root = `{OCTOP_HOME}/projects/default`，**首次需要读写时才创建**，空数据不落盘。

### 2.3 DB 变更（迁移 029）

```sql
CREATE TABLE projects (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id    TEXT NOT NULL UNIQUE,
  user_id       INTEGER REFERENCES users(id) ON DELETE CASCADE,
  name          TEXT NOT NULL,
  root_dir      TEXT,                 -- NULL = 尚未落盘（默认项目）
  is_default    INTEGER NOT NULL DEFAULT 0,
  origin        TEXT,                 -- 'manual' | 'migrated' | 'upgraded'
  created_at    INTEGER NOT NULL,
  updated_at    INTEGER NOT NULL
);
ALTER TABLE threads ADD COLUMN project_id TEXT;
ALTER TABLE threads ADD COLUMN workspace_kind TEXT;   -- 'project' | 'session' | NULL
ALTER TABLE threads ADD COLUMN workspace_dir TEXT;    -- 解析快照，便于审计
```

- `agents.config_json.workspace_dir` 停止写入；读取仅用于迁移兼容。`agents` 表不加新字段，私有目录由 `{OCTOP_HOME}/agents/<id>` 推出。
- `sessions` 表不动（它是渠道会话，不等于对话）。
- 新增 `projects` 仓储 + API：列表、创建、重命名、删除（保护默认项目）、按项目列会话。

### 2.4 cwd 解析优先级（唯一入口）

1. `thread.workspace_dir` 快照（迁移后指向 checkpoint 实际所在目录，优先于项目根；合并升级时就是 `projects/default/legacy/<id>`）。
2. `thread.project_id` → `projects.root_dir`（外部目录或 `projects/<id>`）。
3. `thread.workspace_kind='session'` → `sessions/<thread_id>/`。
4. 都没有 → 「无工作区」：只允许不落盘的工具；首次读写时走第 3.2 节切换流程。
5. 兼容：未迁移的 thread 回退到旧 `agent.workspace_dir`，并标注 legacy。

## 3. 关键机制

### 3.1 运行时实例池

- 把 `HarnessManager` 的 key 从 `agent_id` 改为 `(agent_id, workspace_dir)`；同一 workspace 复用，同一专家跨项目各一个实例。
- 每个实例仍需独立的 `sessions/` 与 `checkpoints.sqlite`（放 workspace 下没问题，本来就是按对话/实例分开）；**memory 必须指到专家私有目录**，否则跨项目记忆会断。
- 技能从专家私有 `skills/` 加载，避免每个项目目录再复制一份内置技能。
- 代价：同一专家在 N 个项目下会占用 N 份运行时资源；因此设上限与空闲回收。
- **实例上限（已定）**：全局同时加载的运行时默认 **6** 个，单个专家默认 **2** 个；两者都可通过 `config.json` 调整（建议范围 4–16 / 1–4）。
  - 依据：每个实例包含 LLM 客户端、工具注册表、中间件链、memory/checkpoint SQLite 连接与 session 缓存，保守按 150–250MB RSS 估算；6 个约 0.9–1.5GB，控制在 4GB 内存主机的 40% 以内。P1 落实现时用实际 RSS 实测校准，并把实测值写进部署文档。
  - 配置键（`config.json`）：`project_runtime_max_instances`（默认 6）、`project_runtime_per_agent`（默认 2）、`project_runtime_queue_timeout_s`（默认 120）。
  - 超出上限：请求进入等待队列（按到达顺序轮询，500ms 间隔），前端显示「等待运行时资源」状态；超过 120s 提示稍后重试并保留会话。空闲 30 分钟自动释放实例（`_POOL_IDLE_TTL_S`），复用现有 `is_agent_active` / 调用计数判断。

### 3.2 无工作区 → 需要读写文件的切换

| 方案 | 利 | 弊 |
|---|---|---|
| A. 首次文件操作自动建 `sessions/<thread_id>/` | 零打断；符合「按对话分开」 | 静默产生目录；用户不知道文件在哪；误写成本低 |
| B. 先提示用户确认（选「本对话独立目录 / 指定项目 / 取消」） | 意图明确；可顺手归档到项目 | 每次首次读写都打断；交互成本高 |
| C. 混合（推荐） | 读操作：先提示选择目录或「仅本次临时读取」；写操作：自动建会话目录并显示可关闭的提示条「本对话已启用独立工作区 · 位置」 | 需要一套轻量 UI 状态；比 A 多一步读路径判断 |

**已确认采用 C**：写操作自动建 `sessions/<thread_id>/` 并显示提示条（含位置与「转为项目」入口）；读操作先提示选择目录或「仅本次临时读取」。不静默创建目录。

### 3.3 对话转项目

- **推荐：原地升级**。为 thread 创建 project 记录，`root_dir` 就是当前 `sessions/<thread_id>`（或用户指定目录）；目录重命名为 `projects/<project_id>` 或保留原路径并在 DB 记录。该 thread 原地变成项目的第一个会话（`thread_id` 不变，消息历史/产物不动）。
- 备选：复制目录到项目，原会话保留原目录。缺点是双份数据、后续分叉，不推荐。
- 语义细节：原会话不删除、不新建；它只是多了一个 `project_id`。项目下再开新会话时共用同一 root_dir。
- 若会话当前**没有**工作区：转项目时先让用户选目录（或自动建 `projects/<id>`），再绑定。

## 4. 完整迁移：Octop → HappyClaw

> 已确认：按「老 Octop 安装整包升级」设计，不是把文件塞进 `_legacy`。目标是零丢失、逐条可审计、可回滚、可重试。

### 4.1 原则

- **家目录不动**：继续使用 `OCTOP_HOME` / `~/.octop`（[paths.py](file:///e:/HAPPYclaw/Octop/src/octop/infra/utils/paths.py#L14-L20)）。DB、`config.json`、`plugins/`、`device-link/` 原地保留，避免整体搬家失败。
- **数据优先**：旧 workspace 原地保留并映射为项目；只把专家配置/记忆复制或搬出，不移动用户文件、`sessions/*.jsonl`、`checkpoints.sqlite`，保持文件与历史的相对关系不变。
- **一个旧 workspace = 一个项目（1:1）**，不合并、不切碎；共享目录的归属写进报告。
- **幂等**：ledger 记录每项状态与校验和；失败重跑只补未完成项。
- **先 dry-run 后 apply**；apply 前强制全量备份，验证通过前不删除旧目录。

### 4.2 资产盘点与处理

| 资产 | 现状位置 | 迁移处理 |
|---|---|---|
| 专家注册 | DB `agents` | 原样保留；`config_json.workspace_dir` 停止写入，仅作映射证据 |
| 专家提示词/配置 | 旧 workspace 根的 `AGENTS.md`、`SOUL.md`、`IDENTITY.md`、`MEMORY.md`、`.octop/manifest.json`、`skills/` | 复制到 `{OCTOP_HOME}/agents/<agent_id>/`；校验通过后只删除与 seed 完全一致的原文件，偏离模板的保留并列入冲突 |
| 专家记忆 | workspace `.octop/memory/` | 迁到 `agents/<id>/memory/`；`memory.sqlite` 连同 wal/shm 一起搬，搬前停写 |
| 用户文件 | 旧 workspace 其余全部内容 | 零移动；旧 workspace 直接成为项目根目录 |
| 会话/线程历史 | DB `sessions`、`threads`、`thread_messages`、`trajectory_events` | DB 原地保留；逐条写 `threads.project_id` 与 `workspace_dir` 快照 |
| 对话文件 | workspace `sessions/*.jsonl`、`conversation_history/`、`checkpoints.sqlite` | 原地保留，随项目根目录被引用；不重命名、不合并 |
| 侧栏分组 | 由 `workspace_dir` 推导 | 按 4.3 映射；显式 workspace 分组不变，默认目录的冲突见 4.4 |
| 全局配置 | `~/.octop/config.json` | 原地保留；校验 JSON/schema；apply 前单独备份 |
| 已安装插件 | `~/.octop/plugins/` + `config.json` 插件段 + `.control-revision` | 原地保留；逐个校验 `plugin.yaml`、依赖、启用状态，出清单 |
| DSH 开关 | 环境变量 `OCTOP_DSH_*`（进程级，无落盘，见 [switches.py](file:///e:/HAPPYclaw/Octop/src/octop/infra/dsh/switches.py#L1-L39)） | 环境不变即保留；报告只记录快照，不改写 |
| 设备直连 | `~/.octop/device-link/settings.json`、`credentials.json`（[manager.py](file:///e:/HAPPYclaw/Octop/src/octop/infra/control/device_link/manager.py#L36-L40)） | 原地保留；校验可读；迁移后不自动重连，由用户点连接 |
| Cron / 渠道 / 团队 / Bridge / 技能包 / 用户 | DB + 对应目录 | 原地保留；迁移后逐项 smoke check |
| 全量备份 | — | apply 前用 `system_archive` 打包；验证通过前不清理旧数据 |

### 4.3 映射规则

- **A. 显式 workspace**（不在 `agents/`、`.octop/workspaces/` 下）：原地建项目，`root_dir` = 原路径，`origin='migrated'`；引用该目录的所有专家的线程都归入；侧栏分组与现在一致。
- **B. 默认专家目录，只有配置/历史**：配置与记忆迁到 `agents/<id>/`；线程归默认项目，但 `workspace_dir` 快照仍指旧目录（零移动，历史可读）；只有新会话才用默认项目根。
- **C. 默认专家目录且有用户文件**：旧目录原地升级为独立项目（`root_dir` = 旧目录）；配置/记忆迁出；该专家的线程归此项目。侧栏会从「默认工作区」变为独立项目，这是唯一的分组变化，见 4.4。
- **D. scoped backend `.octop/workspaces/<id>`**：解析出宿主路径后按 C 处理。
- **E. 无文件、无历史的专家**：线程归默认项目；只保留专家私有配置目录。

归属关系：每个旧目录记录 `owner_agents[]`（所有 `workspace_dir` 指向它的专家）。多专家共享时用户文件无法再细分到单个专家，报告标记 `shared`，不猜。

### 4.4 完整迁移 vs 分组不变（由升级向导决定）

- 显式 workspace：无冲突，分组完全保持。
- 默认目录有用户文件（C）：无法同时做到「文件原地不动」与「仍归在同一个默认项目」。**这一项没有固定默认值，必须由用户在升级向导里二选一**：
  - **A. 数据优先**：旧目录原地变独立项目（`root_dir` = 旧目录），文件/历史/checkpoint 零移动；代价是侧栏分组变化（「默认工作区」→ 独立项目）。
  - **B. 合并进默认项目**：把多个旧默认目录复制进 `projects/default/legacy/<agent_id>/`，合并为一个默认项目，侧栏分组保住；代价是文件要复制一份、项目内路径变化、`checkpoints.sqlite` 无法真正合并（历史线程仍指向旧快照）。
- 向导要求：
  - 两个选项并列展示，代价直接写在选项旁边（用上面的可见文案，不写内部术语），不预选、不提供「跳过」。
  - **必须显式选择后才能 apply**；不允许默认静默通过，也不允许「不选就按数据优先跑」。未选择时 apply 直接拒绝，并提示去向导选择。
  - 向导先展示 `group-changes.md`（逐条「会话/线程 → 迁移前分组 → 迁移后项目」），用户看清分组影响后再选择。
  - 选择结果写入 `choice.json`（`mode: data-first | merge-default`、时间、操作者、被影响的目录/线程清单），与 `group-changes.md` 一起留档。
  - **回滚按当时的选择执行**：`--merge-default` 的回滚要删除复制出的 `projects/default/legacy/*` 并恢复指向；数据优先的回滚只需恢复 DB 映射（文件本就没动）。两者都用同一份备份 + ledger 反向映射。

### 4.5 执行流程（dry-run / 回滚 / 重试）

1. **preflight**：版本、磁盘空间、权限、DB 可写检查；生成资产清单；强制全量备份。
2. **dry-run**：只读扫描 agents、workspaces、threads、config.json、plugins、device-link；输出 `plan.json` + 可读报告，逐项标注 `migrate / keep / conflict / skip`，不写任何文件。
3. **apply**：DB 迁移 029 → 建项目 → 绑定线程 → 迁配置/记忆 → 写 ledger；每项记录源/目标校验和与时间戳。
4. **verify**：校验文件数/字节/哈希、线程数、项目数、分组映射、插件可加载、config 可解析、device-link 可读、DSH 快照一致；生成 before/after 对照。
5. **rollback**：验证未通过时用备份恢复 DB + 文件；ledger 提供反向映射；旧目录在验证通过前不删除。
6. **retry**：ledger 中 `done` 跳过，`failed/pending` 重跑；重复执行结果一致。

实现放在 `src/octop/infra/migration/octop_upgrade.py`，复用现有 [plan.py](file:///e:/HAPPYclaw/Octop/src/octop/infra/migration/plan.py#L55-L68) / [apply.py](file:///e:/HAPPYclaw/Octop/src/octop/infra/migration/apply.py#L31-L61) 的 item/report 模式，以及 [system_archive.py](file:///e:/HAPPYclaw/Octop/src/octop/infra/backup/system_archive.py) 的备份能力。

### 4.6 迁移报告与验收

输出 `{OCTOP_HOME}/migration-reports/octop-to-happyclaw-<ts>/`：

- `plan.json`：逐项计划（资产、源、目标、动作、原因）。
- `apply.json`：逐项结果（状态、哈希、错误）。
- `diff.md`：迁移前/后对照（专家数、项目数、线程数、文件数/字节、分组映射、插件、配置、DSH、设备直连、冲突/跳过）。
- `conflicts.md`：无法两全的点（默认目录分组变化、共享目录归属、偏离模板的配置文件）。
- `group-changes.md`：逐条列出「会话/线程 → 原分组 → 新项目」，升级向导在 apply 前展示并需用户确认。
- `apply.json` 同时记录运行时上限配置快照（全局/单专家/空闲回收），便于升级后核对。

验收口径：`diff.md` 里「未迁移资产」为 0，或全部在 `conflicts.md` 有解释；线程总数、文件总数与迁移前一致。

## 5. 需要一起改的面

- **前端**：项目 tab 改读 projects API；新建项目从「建专家」改为「建项目」；会话列表按 thread.project_id 分组；宝页面的 `project_key` 改用 project_id；SOLO 的文件树/编辑器改按 thread 解析工作区。
- **后端 API**：workspace/files/terminal/skills 从 `agent_id` 升级为 `thread_id` 或 `project_id` 寻址（保留 agent 级兼容入口）；chat 请求带 thread 时解析 cwd。
- **宝**：`project_identity()` 删除或改为读 projects 表；overview 的 projects/sessions 结构保持不变，避免前端大改。
- **备份/发布**：`system_archive` 备份 agents 私有目录 + projects + sessions；`workspace_archive` 的导入导出改按 project_id；发布专家只导出私有配置（现在会把用户文件一起打包，属于必须修的安全问题）。
- **迁移/工具**：OpenClaw 迁移、离线运维、cron、gateway 媒体、browser harness 里的 workspace 解析统一走新的 resolver。
- **全局状态校验**：`config.json`（含插件启用段）、`plugins/`、DSH 环境开关、`device-link/` 在迁移中只做读取校验与快照，不搬迁、不改写；升级后由启动自检确认可用。

## 6. 分阶段实施（确认后）

| 阶段 | 内容 | 可独立验收 |
|---|---|---|
| P0 | projects 表 + thread 归属 + 完整升级迁移（dry-run/apply/verify/rollback）+ 分组读新表 | dry-run 报告逐条可读；apply 后线程/文件总数与迁移前一致；显式 workspace 分组不变 |
| P1 | cwd 解析唯一入口 + 运行时池 `(agent, workspace)` + memory/技能迁到私有目录 | 同一专家在两个项目下互不串目录 |
| P2 | 无工作区会话 + 首次读写切换（方案 C）+ 提示条 | 新会话不建目录；首次写自动建并提示 |
| P3 | 对话转项目（原地升级）+ 项目内新建会话 | 转换后历史/文件都在，原会话仍在 |

## 7. 不在本次范围

- 不改 `octop` 包名 / CLI / 环境变量 / API 路径。
- 不删除任何存量用户文件；默认不做跨盘复制（`--merge-default` 例外）。
- 不重做 SOLO 的布局与交互，只改工作区解析来源。
- 不改宝的 Router 职责边界。

## 8. 决策（已全部确认）

| # | 事项 | 决定 |
|---|---|---|
| 1 | 首次读写切换 | 已定混合方案：写自动建 `sessions/<thread_id>/` + 提示条；读先提示 |
| 2 | **默认目录有用户文件时的分组冲突** | 已定：**spec 不设固定默认，由升级向导强制用户二选一**。A 数据优先（零移动、分组变）/ B 合并进默认项目（分组保住、复制文件、路径变、checkpoint 不能合并）。未显式选择禁止 apply；选择写入 `choice.json` 与 `group-changes.md` 一起留档，回滚按当时选择执行。详见 4.4 |
| 3 | 偏离模板的 AGENTS.md 等 | 私有目录只留副本，不删原件；冲突项进 `conflicts.md` |
| 4 | 家目录 | 坚持 `~/.octop`，不改名、不搬全局状态 |
| 5 | 外部项目目录 | 保留原路径引用，不迁入 `{OCTOP_HOME}/projects/` |
| 6 | 项目级技能 | 暂不做，技能只跟专家 |
| 7 | 同专家跨项目运行时 | 设上限、超出 FIFO 排队：全局默认 6、单专家 2、空闲 30 分钟释放；依据与调整方式见 3.1 |
| 8 | 设备直连 | 升级后不自动重连；配对凭据保留，由用户手动触发 |
| 9 | DSH 开关 | 只记录环境快照，不改写 |

> 全部决策已确认，按第 6 节 P0 → P3 推进实现。
