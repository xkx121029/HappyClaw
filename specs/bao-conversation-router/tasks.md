# 宝：多轮对话 Router — 实施任务

> 依据 `spec.md`。按顺序执行，每完成一项勾选。

## T1 迁移与仓储（后端）

- [x] 新增 `src/octop/infra/db/migrations/028_bao_chat_followup.sql` 与 `.pg.sql`：`bao_messages`、`bao_proactive_log`、`bao_tasks` 增列，`_schema_version=28`。
- [x] 新增 `src/octop/infra/db/repos/bao_messages.py`（append/list/prune）。
- [x] 新增 `src/octop/infra/db/repos/bao_proactive.py`（claim 去重+频控+静音落日志、prune）。
- [x] 扩展 `src/octop/infra/db/repos/bao_tasks.py`：`get_for_thread`、`latest_terminal_for_thread`、`record_followup`、`mark_evaluated`、行模型增列。
- [x] `src/octop/infra/db/services.py`：`RepoBundle` / `SharedServices` 注册两个新 repo。
- [x] 跑 `pytest tests/unit/db/test_bao_tasks_repo.py tests/unit/db/test_bao_messages_repo.py tests/unit/db/test_bao_proactive_repo.py`。

## T2 团队成员识别

- [x] `src/octop/infra/errors.py`：新增 `TEAM_MEMBER_NOT_DIRECT`，HTTP 400。
- [x] `src/octop/api/routers/bao.py`：`_team_member_info`、agent 条目 `direct_dispatchable/direct_dispatch_hint`、`_decision` team 分支、dispatch 前置拦截。
- [x] `/bao/route` 命中成员名时返回不可直派 + 原因，不再返回可执行目标。
- [x] 测试：`tests/unit/api/test_bao.py` 增 route/dispatch 用例。

## T3 聊天 API

- [x] `BaoChatBody` / `BaoSettingsBody`；`POST /bao/chat`、`GET /bao/chat`、`GET/PATCH /bao/settings`。
- [x] 确定性意图：wait/status/cancel/also/retry/target/new_task；指代解析（refs → 最近任务 → 台账）。
- [x] 抽取 `_dispatch_core` 供 `/bao/dispatch` 与 chat 共用。
- [x] 用户消息与宝回复写入 `bao_messages`；静音设置读写 `preferences_json["bao"]`。
- [x] 测试：五轮指代对话、`needs_target` clarify、`also` 重派、cancel 不派发。

## T4 跟进与主动推送

- [x] 新增 `src/octop/infra/bao/followup.py`：`BaoFollowupService`（classify、追问 ≤2 次、推送、频控）。
- [x] `src/octop/infra/gateway/gateway.py`：`set_bao_followup`，`_record_bao_turn_finished` 末尾调用（try/except）。
- [x] `src/octop/infra/server.py`：构造并注入 `BaoFollowupService`。
- [x] 测试：`tests/unit/gateway/test_bao_followup.py`（stuck→追问→done；耗尽→决策；done/failed/awaiting 推送；去重/120s/6 次每时/静音）。

## T5 前端

- [x] `dashboard/src/api/modules/bao.ts`：chat/settings 类型与请求，agent/task 字段。
- [x] `dashboard/src/components/Bao/useBaoData.ts`：`useBaoChat`（打开/可见时拉取，发送走 chat）。
- [x] `dashboard/src/components/Bao/BaoPage.tsx`：消息流 + 任务卡、clarify 目标选择、静音开关、团队成员禁选与提示、错误码映射。
- [x] `dashboard/src/components/Bao/baoTaskStore.ts`：`followup_count`。
- [x] `dashboard/src/locales/zh.json`、`en.json`：`bao.tasks.retryHint` 改为回合回写 + 可见时补偿刷新；新增 chat/settings/team 文案。
- [x] `npx vitest run src/components/Bao` 通过，`npm run build` 或 `tsc --noEmit` 通过。

## T6 线上验证（8088 / 5173）

- [x] `GET /api/runtime/activity`：确认无活跃回合；有则等待，不硬重启。
- [x] 重启 8088（保留 `OCTOP_DSH_*`、`DSH_HARNESS_ROOT`），确认日志/env 未丢。
- [x] 五轮指代对话：逐条记录 request/response 的 intent 与 reply。
- [x] 追问推进：派发 → stuck → 自动追问 → done，记录 `followup_count` 与消息。
- [x] 主动推送：WS 捕获 1 条帧；120s 内第二条被限流；静音后不推。
- [x] 团队成员：route 返回不可直派；dispatch 返回 400 + 明确文案（无 409）。
- [x] 5173 页面：对话、静音开关、文案更新。

## T7 汇报

- [x] 中文汇报：三项验证证据 + 团队成员处理 + 文案修正。
- [x] 再次为上次「未先探 activity 即重启」致歉，并确认今后做不到的约束当场说明。
