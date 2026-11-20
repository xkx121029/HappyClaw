# 宝：多轮对话 Router + 子会话推进 + 主动推送

## 1. 背景与目标

宝目前是「派活入口」：`/bao/route` 决定目标，`/bao/dispatch` 派发，`bao_tasks` 持久化，Worker 回合结束回写。
本轮把宝变成能对话的 Router，三件事：

1. **多轮连续对话**：记住前文，能接「再等等」「把那个也一起做了」「刚才那个怎么样了」。对话本身不执行任务，宝不下场读写文件、跑命令。
2. **持续推进子会话**：回合结束后判定「完成 / 卡住 / 需要决策」。卡住时自动补一句追问（最多 2 次），仍卡住或需要决策则上报。
3. **主动发送消息**：完成 / 需要决策 / 异常时通过现有 dashboard_push 通道推给用户，带频控与静音开关，只报这三类。

附加：

4. **团队成员不可直派**：`AGENT_NOT_RUNNING`（如 NHWB2G）在路由/派发阶段就识别，返回明确原因「团队成员不能直派，请派给所属团队或该项目会话」，不等到后端 409。
5. 修掉过期文案「持续跟进靠轮询驱动：每 4 秒 / 20 秒」。

约束遵守（用户明确要求）：先探再重启这类约束，做不到就当场说明，不允许先斩后奏。

## 2. 现状（已实现，复用）

- `bao_tasks`（migration 027）+ `BaoTaskRepo`：create / `complete_running` / `acknowledge` / `reconcile_interrupted` / `import_legacy` / `prune`。
- `Gateway._record_bao_turn_finished` → `repo.complete_running(...)`；WS `on_turn_finished` 传入 status `done|failed|awaiting`。
- `/bao/route` 确定性优先，歧义时一次 `_model_route`；`/bao/dispatch` 复用 `prepare_dashboard_turn` + WS 队列。
- 前端 `useBaoData` 已无轮询：挂载 / 打开 / `visibilitychange` 补偿刷新。
- 主动推送通道：`gateway.ws_hub.push_to_user(user_id, frame)`；前端 `useDashboardPushToast` 只认 `{type:"dashboard_push", agent_id, thread_id, text, agent_name?}`，走 `/notifications/ws`。
- 团队：`server.app_runtime.agent_registry.teams` 是 `TeamService`，`visible_member_ids(team_agent_id)` 可用。

## 3. 数据模型（migration 028）

新增 `src/octop/infra/db/migrations/028_bao_chat_followup.sql` 与 `.pg.sql`，`_schema_version = 28`。

### 3.1 `bao_messages`

| 列 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | ULID |
| user_id | INTEGER NOT NULL | 用户 |
| role | TEXT NOT NULL | `user` / `bao` |
| text | TEXT NOT NULL | 消息正文 |
| intent | TEXT NOT NULL DEFAULT '' | `wait/status/also/retry/cancel/target/new_task/clarify/followup/dispatch/overview` |
| refs_json | TEXT NOT NULL DEFAULT '{}' | `{task_id?, agent_id?, thread_id?, candidates?}` |
| task_id | TEXT | 关联派发任务 |
| created_at | INTEGER NOT NULL | 秒 |

索引 `idx_bao_messages_user_created (user_id, created_at DESC)`。
保留：每用户最多 200 条，写入时按时间倒序裁剪最旧的。

### 3.2 `bao_tasks` 增列

- `followup_count INTEGER NOT NULL DEFAULT 0`
- `last_followup_at INTEGER`
- `eval_status TEXT`（NULL / `done_stuck` / `stuck_escalated` / `needs_decision` / `failed` / `done_ok`）
- `eval_at INTEGER`

### 3.3 `bao_proactive_log`

| 列 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | ULID |
| user_id | INTEGER NOT NULL | 用户 |
| task_id | TEXT NOT NULL | 任务 |
| kind | TEXT NOT NULL | `done` / `needs_decision` / `failed` |
| dedupe_key | TEXT NOT NULL UNIQUE | `{task_id}:{kind}` |
| delivered | INTEGER NOT NULL DEFAULT 0 | 是否真的推送 |
| suppressed_reason | TEXT | `muted` / `rate_limited` / `duplicate` |
| created_at | INTEGER NOT NULL | 秒 |

索引 `idx_bao_proactive_user_created (user_id, created_at DESC)`。
保留：30 天或每用户 500 条，先删旧行。

## 4. 后端改动

### 4.1 仓储

- 新增 `src/octop/infra/db/repos/bao_messages.py`：`BaoMessageRepo`
  - `append(user_id, role, text, intent, refs, task_id) -> BaoMessageRow`
  - `list_for_user(user_id, limit)`
  - `latest_task_ref(user_id)`：返回最近一条带 `task_id` 的 bao 消息 refs。
  - `prune(user_id)`：200 条上限。
- 新增 `src/octop/infra/db/repos/bao_proactive.py`：`BaoProactiveRepo`
  - `claim(user_id, task_id, kind, *, muted, now, min_interval=120, hourly_cap=6) -> (claimed, reason)`
    - 先看 `dedupe_key` 是否已存在 → `(False,"duplicate")`；
    - `muted` → 写入 `delivered=0, suppressed_reason='muted'` 并返回 `(False,"muted")`；
    - 近 120 秒已有一条 delivered → `rate_limited`；近 3600 秒 delivered ≥ 6 → `rate_limited`；
    - 通过则写入 `delivered=1` 并返回 `(True,None)`（事务内完成，防并发重复）。
  - `prune(user_id)`。
- `BaoTaskRepo` 增：
  - `get_for_thread(thread_id, agent_id, statuses=None)`
  - `latest_terminal_for_thread(thread_id, agent_id)`（取 `eval_status IS NULL` 且状态终态/awaiting 的最新一行）
  - `record_followup(task_id, now)`：`followup_count+1`、`last_followup_at`、`status='running'`、`completed_at=NULL`、`eval_status=NULL`
  - `mark_evaluated(task_id, eval_status, now)`
- `RepoBundle` / `SharedServices` 注册 `bao_message_repo`、`bao_proactive_repo`。

### 4.2 聊天 API（`src/octop/api/routers/bao.py`）

新增模型：

```python
class BaoChatBody(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    scope: Literal["global", "project"] = "global"
    project_key: str | None = None
    agent_id: str | None = None      # 手动指定目标（原「指定目标」）
    thread_id: str | None = None

class BaoSettingsBody(BaseModel):
    proactive_muted: bool
```

接口：

- `GET /bao/chat?limit=100` → `{messages, settings:{proactive_muted}, updated_at}`
- `POST /bao/chat` → `{reply_code, reply_params, reply_text, messages:[新增的 user/bao 消息], task?, decision?, needs_target?, candidates?, settings}`
- `GET /bao/settings` / `PATCH /bao/settings`：读写 `user_repo.preferences_json["bao"]["proactive_muted"]`（缺省 False）。

意图识别（确定性，不调模型；保证可解释）：

| intent | 触发（casefold 包含） | 行为 |
|---|---|---|
| `wait` | 再等 / 等等 / 等一下 / 先等 / 稍等 | 回复「好，我继续盯着，完成或卡住会主动告诉你」；不派发 |
| `status` | 怎么样 / 进度 / 完成了吗 / 完成没 / 好了吗 / 做到哪 / 状态 | 从 `bao_tasks` 汇总最近 3 条，回复状态与结果摘要；不派发 |
| `cancel` | 算了 / 不用了 / 取消 | 回复「好，我不再跟这条」；把引用任务 `acknowledge`；不派发 |
| `also` | 把那个也 / 也一起 / 一起做 / 顺便把 / 那个也 | 取引用任务（`refs.task_id` → 最近任务）的 `task_text`，重派到同一 agent/thread；目标忙则回复 `busy` |
| `retry` | 再试一次 / 重试 / 继续那个 | 同上，重派引用任务 |
| `target` | 上一条宝消息是 `clarify` 且文本含「派给/交给/给」或直接命中 agent/project 名 | 以该目标派发上一条待派文本 |
| `new_task` | 其他 | 复用现有 `/bao/route` 确定性链（含一次模型兜底）；`needs_target` 时回复 `clarify` 并带候选 |

指代解析优先级：`message.refs.task_id` → 最近一条 task 消息 → 台账最新任务。
回复文案：后端返回 `reply_code`（如 `bao.chat.reply.wait` 的短码）+ `reply_text`（中文兜底）；前端有 i18n 用 i18n，否则用 `reply_text`。

重构：把 `dispatch_task` 的派发主体抽成 `_dispatch_core(server, user, *, agent_id, thread_id, text, route_reason, source) -> dict`，`POST /bao/dispatch` 与 `POST /bao/chat` 共用，避免两条执行路径。

对话边界：聊天分支只做（a）读 `bao_tasks`/`bao_messages`，（b）调用现有 route/dispatch。宝自身不读写工作区、不跑命令、不直接调用模型工具。

### 4.3 团队成员不可直派

- 新增 `_team_member_info(server, user, agent_id) -> dict | None`：
  - 遍历 `_visible_agent_rows` 中 `is_team_agent(row)` 的团队，`server.app_runtime.agent_registry.teams.visible_member_ids(team_id)` 命中即返回 `{team_agent_id, team_name}`。
- `_overview_payload` 的 agent 条目增加：
  - `direct_dispatchable: bool`
  - `direct_dispatch_hint: "team_member"`（可空）
- `_decision(...)`：若目标 agent 是团队成员，返回 `direct_dispatchable=false`，`reason.code="team_member"`，`params={team}`，**不返回可执行的 thread/create_thread**；`/bao/route` 文本只命中成员名时同样走该分支。
- `_dispatch_core` 与 `POST /bao/dispatch` 入口先查团队归属，命中直接 `OctopError(ErrorCode.TEAM_MEMBER_NOT_DIRECT, "team members cannot be dispatched directly", details={...})`。
- `ErrorCode` 新增 `TEAM_MEMBER_NOT_DIRECT = "TEAM_MEMBER_NOT_DIRECT"`，HTTP 映射 400。
- 前端 `dispatchErrorMessage` 按该 code 提示「这是 {{team}} 的成员，不能直接派活；请派给团队或该项目会话」。

### 4.4 回合结束的持续推进与主动推送

新增 `src/octop/infra/bao/__init__.py`、`src/octop/infra/bao/followup.py`：`BaoFollowupService`

- `on_turn_finished(thread_id, agent_id, status, result_text, error_text)`：同步入口，`asyncio.get_running_loop().create_task(self._evaluate(...))`，异常只记日志。
- `_evaluate`：
  1. `task_repo.latest_terminal_for_thread(...)`，无则返回；
  2. `_classify(status, result_text, error_text)`：
     - `failed` → `failed`
     - `awaiting` → `needs_decision`（等待审批，推一条）
     - `done` 且结果为空/少于 20 字 → `stuck`
     - `done` 且命中「需要更多信息 / 请提供 / 无法继续 / 缺少 / 不能完成 / 需要你确认」→ `stuck`
     - `done` 且以问号结尾或含「是否」→ `needs_decision`
     - 其他 → `done`
  3. `stuck` 且 `followup_count < 2`：
     - `record_followup` → 追加一条 bao 消息（intent=`followup`）→ 用 `_dispatch_core` 向同一 thread 补一句固定追问：
       「继续完成上一个任务，不要停在提问上；缺少资料时先用现有信息给出可交付的一版并列出缺口。」
     - 不发主动推送（避免每一步都报）。
  4. `stuck` 且次数耗尽 → 按 `needs_decision` 推送，文案「任务卡住了，需要你决定：…（已自动追问 2 次）」。
  5. `done` → 推送「已完成：{结果摘要前 80 字}」；`failed` → 推送「执行失败：{错误摘要}」；`awaiting` → 推送「等待你审批」。
  6. 最后 `mark_evaluated`。
- `_push`：
  - 读用户偏好静音；`proactive_repo.claim(...)`；未通过则只落日志，不发帧；
  - 通过则 `await gateway.ws_hub.push_to_user(user_id, {"type":"dashboard_push","agent_id":..., "thread_id":..., "text":..., "agent_name":...})`。
- 频控参数：**同任务同类型永久去重；同用户 120 秒内最多 1 条；每小时最多 6 条；静音时不推。**
- Gateway 增 `set_bao_followup(service)`；`_record_bao_turn_finished` 在回写后调用 `self._bao_followup.on_turn_finished(...)`（try/except，绝不影响回合）。
- `server.py` 在 gateway boot 与 services 就绪后构造 `BaoFollowupService` 并注入；不新增后台循环。

## 5. 前端改动

- `dashboard/src/api/modules/bao.ts`：新增 `BaoChatMessage`、`BaoChatResponse`、`BaoSettings` 类型与 `chat/chatHistory/settings/updateSettings`；`BaoAgent` 增 `direct_dispatchable`、`direct_dispatch_hint`；`BaoTask` 增 `followup_count`。
- `dashboard/src/components/Bao/useBaoData.ts`：新增 `useBaoChat(open)`，挂载/打开/`visibilitychange` 拉 `GET /bao/chat`，`send(text, target?)` 走 `POST /bao/chat`，返回后合并消息并 `refreshTasks`。
- `dashboard/src/components/Bao/BaoPage.tsx`：
  - 转录区改为消息流：user 气泡 + 宝回复气泡 + 关联任务卡（`task_id` 匹配）。
  - composer 调用 `chat`；「指定目标」仍可传 `agent_id/thread_id`。
  - `clarify` 回复内联目标选择器，确认后以 `target` 意图继续。
  - 顶部加静音 `Switch`（`bao.settings.mute`），调 `PATCH /bao/settings`。
  - 目标下拉里禁选 `direct_dispatchable === false`，并显示「团队成员」原因。
  - `dispatchErrorMessage` 处理 `TEAM_MEMBER_NOT_DIRECT`。
- `dashboard/src/components/Bao/baoTaskStore.ts`：映射 `followup_count`。
- 文案：
  - `zh.json:191` / `en.json:191` 的 `bao.tasks.retryHint` 改为：「回合结束时由 Worker 回写结果；页面只在可见时做一次补偿刷新，无需轮询。」/ 对应英文。
  - 新增 `bao.chat.reply.*`、`bao.settings.mute`、`bao.dispatch.teamMember`、`bao.route.reason.teamMember`。
  - `bao.page.capability.followUp` 改为「完成后主动提醒，卡住会追问」。

## 6. 测试

后端：

- `tests/unit/db/test_bao_tasks_repo.py`：`record_followup`、`mark_evaluated`、`latest_terminal_for_thread`、保留策略不误删 running。
- 新增 `tests/unit/db/test_bao_messages_repo.py`：追加/裁剪上限。
- 新增 `tests/unit/db/test_bao_proactive_repo.py`：重复去重、120s 间隔、每小时 6 条、静音。
- 新增 `tests/unit/gateway/test_bao_followup.py`：`_classify` 各分支；卡住自动追问一次；追问耗尽转决策推送；推送帧字段；失败/完成推送。
- 扩展 `tests/unit/api/test_bao.py`：五轮指代对话（wait/status/also/target/new_task）、团队成员 route `direct_dispatchable=false`、dispatch 返回 400 + `TEAM_MEMBER_NOT_DIRECT`、chat 不触发任何工作区写入（只打桩 `_dispatch_core`）。

前端：

- `npx vitest run src/components/Bao`（含现有 `baoModel.test.ts`；如新增纯函数则补测试）。
- `npm run build` 前先 `tsc` 校验类型。

## 7. 实际验证（交付证据）

所有验证在用户实际环境 8088 + 5173 上执行：

1. **五轮带指代对话**（`POST /api/bao/chat` 连续调用，记录每次 `intent/reply`）：
   1. 「看看现在有哪些项目」→ `overview`
   2. 「让 CVM 那个跑一下健康检查」→ `new_task` + dispatch
   3. 「再等等」→ `wait`，无新派发
   4. 「刚才那个怎么样了」→ `status`，引用第 2 条任务
   5. 「把那个也一起做了」→ `also`，引用同任务并重派
   6. 「刚才那个完成了吗」→ `status`，返回终态结果
2. **被追问推进到完成**：派一条会先要求补资料的任务；回合结束判 `stuck` → 自动追问一次 → 任务最终 `done`，`followup_count=1`，附 `/bao/tasks` 与消息记录。
3. **主动推送**：用 WS 客户端连 `/api/notifications/ws`，捕获一条 `dashboard_push` 帧；再在 120 秒内制造第二条 → 日志 `delivered=0, reason=rate_limited`，无帧；打开静音后再触发 → `reason=muted`，无帧。说明触发条件与频控参数。
4. **团队成员**：对 NHWB2G 调 `/bao/route` 得 `direct_dispatchable=false`；调 `/bao/dispatch` 得 400 `TEAM_MEMBER_NOT_DIRECT`，文案含所属团队，不再出现 409。
5. **页面**：5173 上完成一轮对话、看到卡片与静音开关、过期文案已替换。

重启 8088 的前置约束：先 `GET /api/runtime/activity` 确认无活跃回合；有活跃回合则等待结束；重启沿用当前 `OCTOP_DSH_*` 与 `DSH_HARNESS_ROOT` 环境变量，并在日志中确认未丢失。若无法满足，当场说明，不先斩后奏。

## 8. 不做

- 不做自主拆解（多子任务规划）。
- 不做逐步播报；只报完成 / 需要决策 / 异常。
- 不改 `/bao/route` 的模型兜底策略（已经是确定性优先 + 一次轻量模型）。
