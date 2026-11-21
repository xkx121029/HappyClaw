# 单人本地工具改造 Spec（后端与架构线）

- 仓库：`e:\HAPPYclaw\Octop`（HappyClaw，Python >=3.12，FastAPI + SQLite/PostgreSQL）
- 范围锁定：仅 `src/`、`tests/`；**不修改 `dashboard/`、`desktop/`、`docs/`**（仅只读确认接口与契约）
- 约束：git 仅本地提交、不 push；不删除任何文件（用 `.gitignore` 或废弃标记）；不操作浏览器
- 边界协作：需要写入文档的改动，由本线在简报中说明，交给「文档与交付」线落盘；桌面壳相关需求交给「桌面壳」线
- 本 Spec 与任务清单暂存于 `tests/specs/single-user-refactor/`（避免占用文档线目录）
- 前端契约保持不变：`POST /api/auth/login` → `{access_token, token_type, expires_in, user}`；`GET /api/auth/me` → `{id, username, role, display_name, locale, permissions, ...}`；`role=admin` 时 dashboard 全量放行

## 1. 现状结论（盘点）

| 层 | 认证/用户相关实现 | 位置 |
| --- | --- | --- |
| 中间件 | 所有 `/api/*` 强制 JWT；无用户时 503 | `api/middleware/jwt_auth.py`、`api/middleware/setup_lockdown.py` |
| 依赖 | 令牌解码、用户解析、滑动续期、权限校验 | `api/deps.py` L102-273 |
| 调用面 | 71 个文件、644 处 `current_user / require_*` | `api/routers/**` |
| 认证路由 | login/logout/me/改密/头像/MFA/设备/OIDC/OAuth/LDAP/邀请/用户/用户组/角色 | `api/routers/auth*.py`、`users.py`、`user_groups.py`、`user_roles.py`、`invites.py` |
| 领域服务 | 用户管理、权限、用户组、身份、密码 | `infra/users/*`、`infra/auth/{tokens,captcha,ldap,mfa,sso}/*` |
| 数据表 | 用户域 13 张表；36 处 `user_id` 归属列 | `infra/db/migrations/001-025` |
| 迁移机制 | 文件式 `NNN_*.sql` / `.pg.sql` + `_schema_version`，末尾幂等补丁 | `infra/db/migrate.py#run_migrations` |
| 单人能力 | 备份/导出/恢复、用量统计已存在，但挂在 admin 权限下 | `api/routers/backup.py`、`api/routers/usage.py` |

## 2. 目标设计

### 2.0 交付主路径（最高优先级，先于 §2.4 OOP 与 §5 设计吸收）

前端线已确认不实现登录流程，以下四条必须先落地，处理完在简报中逐条说明实际行为：

| # | 接口 | 单人模式行为 |
| --- | --- | --- |
| 1 | `GET /api/health` | 永久匿名可访问；JWT 门禁移除后天然放行，且保持不依赖用户表 |
| 2 | `GET /api/auth/me`、`POST /api/auth/logout` | 前端已不调用；仍保留为无鉴权空实现 —— `me` 返回本机 owner（200），`logout` 返回 204，均不读 token、不查会话 |
| 3 | `/api/sessions*`、`/api/tasks*`、`/api/preferences*` 及其它全部 `/api/*` | 去掉「必须登录 token」强校验：`current_user` 恒返回 owner，本机直进不再出现 401；多标签、多端口视为同一人 |
| 4 | `GET /api/setup/status` | 固定返回 `setup_required=false`（不再需要初始化账号），避免前端被拉到 setup 页；`/api/setup/begin`、`initial-admin`、`verify-password`、`finish` 等写接口返回 400 + 中文「单人模式无需初始化账号」，`presets` / `test-database` 保留可用 |

### 2.0.1 QA 第一轮走查（P0/P1，逐条给出实际行为）

| 级别 | 问题 | 决策与验收方式 |
| --- | --- | --- |
| P0-1 | `/api/setup/status` 仍可能 `setup_required=true` / `wizard_password_required=true` | 固定 `setup_required=false`、`wizard_password_required=false`、`needs_admin=false`；不返回数据库选择项、不写 `octop-login.txt`；`/api/setup/begin|initial-admin|verify-password|finish` → 400 中文「单人模式无需初始化账号」。验证：干净 `OCTOP_HOME` 下 `GET /api/setup/status` 200 且两字段为 false |
| P0-2 | 全站依赖 24h JWT，直进 401 | JWT 门禁整体移除；`/api/*` 无令牌均按本机使用者解析。验证：无 `Authorization` 头请求 `/api/sessions`、`/api/tasks`、`/api/preferences`、`/api/agents` 均 200 |
| P0-3 | `/api/providers` 明文返回 `api_key` | 响应中 `api_key` 改为脱敏（`****` + 末四位；无 key 为 `null`），新增 `api_key_set: bool`；`PATCH` 收到脱敏值视为「未修改」，不会覆盖真实密钥；全仓日志审计，禁止打印完整 key。验证：`GET /api/providers` 不含完整 key；`PATCH` 回传脱敏值后 DB 中 key 不变 |
| P1-4 | `/auth/me` 返回 admin 权限与 `sso_*` | `me` 仅返回 `{id, username, display_name, locale, role: "local", is_local_owner: true}`；不返回 `permissions`、`sso_*`、密码/MFA 字段。`/api/user-groups/audience` 返回 `[]`；`/api/teams` **保留原实现**（专家团是单人功能，见 §2.0.2 决策表） |
| P1-5 | agent 返回含 `user_id/visibility/group_ids` | 列表/详情 payload 移除 `user_id`、`visibility`、`group_ids`；保留 `is_owner/is_shared`（dashboard 仍引用，恒 `true`/`false`） |
| P1-6 | 无模型时默认 agent `state=failed` + 内部错误键 | 改为 `state="created"`、`error=None`，payload 增加 `setup_hint`：「尚未配置可用模型，请先在「模型」中添加并启用一个模型。」 |
| P1-7 | 备份默认 `include_chats=false` 与菜单「导出会话」矛盾 | 产品语义定为「备份=完整本机状态」，手动备份与计划任务默认 `include_chats=true`；已显式保存为 false 的配置不强制覆盖。验证：默认参数创建备份的 manifest 含 sessions 条目 |

### 2.0.2 桌面壳首次启动阻断（P0，与 setup 同批）

| 问题 | 决策 |
| --- | --- |
| 全新 `OCTOP_HOME` 下 `should_defer_control_plane_db` 跳过建库，`/api/health` 90 秒不可用 | 单人版删除「选后端」概念：`should_defer_control_plane_db()` 恒返回 `False`（保留函数名标 `@deprecated`），`server.start()` 始终 `open_database()` + `run_migrations()` 后再监听；桌面模式（`OCTOP_DESKTOP_SHELL=1`）不再等待向导 |
| 首次可用耗时无证据 | 用全新目录实测：进程启动 → `/api/health` 首次 200 的毫秒数，写入简报（改前为 ≥90s 不可用） |
| `GET /api/runtime/activity` 未实现，退出守卫拿不到繁忙状态 | 新增只读接口。桌面 `quit-guard.ts` 实际读的是 `body.counts`（kind→数量，`agent_turn`/`terminal`），因此返回 `{busy, counts, active_turns, terminal_sessions, running_agents, running_jobs, updated_at}`，且 `busy === sum(counts) > 0`；无 DB 依赖，2s 内缓存 |
| 前端 `window.octopDesktop.setUnsavedContent()` 与新建会话快捷键对接点 | 已确认前端实现完毕：`dashboard/src/pages/Chat/index.tsx` L1054–1070，`composerDirty \|\| 排队项` → `setUnsavedContent`，壳层转发 Ctrl/Cmd+Shift+N → `onNewSessionShortcut` → `handleNewChat`；后端无需新端点 |
| 「专家团」`/api/teams` 是否算多用户功能 | **不是**。它是同一使用者下的 agent 分组，单人照常可用：恢复原 `list_for_user(user.id)` 实现，并在路由注释里写明与租户无关 |
| WebSocket 无 token 时 `close(4001)` | 单人模式一律放行：`chat/ws`、`notify_ws`、`terminal`、`browser/stream`、`desktop/stream`、`mobile/*`、`bridge`、`voice` 共 10 处改为 `token or ""`，由 `resolve_user_from_token` 返回本机 owner；有 token 时行为不变（向后兼容），不再依赖前端假 token |
| 全新实例没有默认 agent，首屏为空 | 监听之后**异步**创建 `main`（`server._schedule_default_agent_bootstrap()`，fire-and-forget），失败只记英文日志；不阻塞 `/api/health`。测试用 `OCTOP_DISABLE_DEFAULT_AGENT=1` 关闭 |

### 2.1 本机唯一使用者（Owner）

新增 `src/octop/infra/users/owner.py`：

```python
class OwnerIdentityService:
    def __init__(self, services: SharedServices) -> None: ...
    def owner(self) -> User: ...          # 进程内缓存
    def owner_id(self) -> int: ...
    def reset_cache(self) -> None: ...    # services 热切换后重算
```

- 解析顺序：`local_owner.user_id` → `users` 中该行（`disabled=0`）→ 首个 `role=admin` → 最小 `id` → 自动创建 `local-owner`（`password_hash=NULL`、`role=admin`、`desc` 中文显示名「本机使用者」）
- 返回 `User` 的 `permissions` 为 `list(PERMISSIONS)`，`role="admin"`，保证 dashboard `userCan` 全量放行
- 解析失败：日志英文原文，向上抛出中文 `OctopError`（`INTERNAL_ERROR`，message 中文「单人模式初始化失败，已保留原有数据，请查看日志」）

### 2.2 拆除认证判定（保留路径与返回结构）

| 文件 | 改动 |
| --- | --- |
| `api/deps.py` | `current_user` 直接返回 `server.owner_identity.owner`；`require_permission/require_any_permission/require_admin` 恒放行（仍校验 key 合法）；`resolve_user_from_token` / `maybe_sliding_renew_token` / `extract_raw_token` 保留为废弃 shim（返回 owner / None），标注「@deprecated 单人模式」 |
| `api/middleware/jwt_auth.py` | 不再解析令牌；仅设置 `request.state.octop_user = owner` |
| `api/middleware/setup_lockdown.py` | 保留文件，`install` 标记废弃、不再挂载 |
| `api/app.py` | 移除 `install_jwt_auth` / `install_setup_lockdown` 挂载与 CORS 暴露头依赖 |
| `api/routers/auth.py` | login 返回本机 owner 占位令牌（`access_token="local-owner"`）；me/改密/头像按单人语义；captcha 返回禁用态 |
| `api/routers/users.py` | 列表仅返回 owner；创建/删除/改角色等写操作返回 `400` + 中文「单人模式不支持多账号」 |
| `api/routers/user_groups.py` / `user_roles.py` / `invites.py` | 读接口返回空集合/内置项；写接口同上中文提示 |
| `api/routers/auth_mfa.py` / `auth_device.py` / `auth_oidc.py` / `auth_oauth.py` / `auth_ldap.py` | status 返回 `enabled=false`；启动/校验返回中文「单人模式已关闭该登录方式」；设备令牌返回本地占位令牌（桌面壳不受影响） |
| `infra/server.py` | 启动时调用 `owner.ensure()`；`_ensure_jwt_secret` 仅保留文件兼容，不再参与鉴权；`_emit_wizard_password` 不再输出登录口令（改为中文提示「单人模式无需初始密码」） |

### 2.3 数据库迁移（只增不删）

- 新增 `026_single_user_owner.sql` / `026_single_user_owner.pg.sql`
  - `CREATE TABLE IF NOT EXISTS local_owner (user_id INTEGER PRIMARY KEY, adopted_at INTEGER NOT NULL, source TEXT NOT NULL DEFAULT 'migration')`
  - 回填：若表为空，选 `users` 中 `role='admin'` 的最小 `id`；否则最小 `id`
  - `UPDATE _schema_version SET version = 26`
- `migrate.py` 末尾新增幂等 `_ensure_single_user_schema(db)`，可重复执行
- **不删除任何用户行、不改 `users` 结构**；迁移事务失败自动回滚保留原值；日志英文原文 + 中文告警
- 兼容：`user_id` 字段继续写入 owner id，不再参与可见性判定

### 2.4 面向对象收口（只为消除隐式状态）

| 新服务 | 位置 | 替换的过程式逻辑 |
| --- | --- | --- |
| `OwnerIdentityService` | `infra/users/owner.py` | `deps.resolve_user_from_token`、server 内散落的 owner 推导 |
| `BackupService` | `infra/backup/service.py` | `api/routers/backup.py` 的 `_create_and_store_manual_backup` / `_restore_stored_backup` / `_rehydrate_runtime_after_restore` |
| `UsageReportService` | `infra/usage/report.py` | `api/routers/usage.py` 的 `_resolve_user_scope` / `_label_*` / `_username_map` |
| `StartupSelfCheck` | `infra/selfcheck.py` | `server.start()` 中的静默校验（端口/DB/目录/模型凭据/磁盘） |
| `LocalConfigService` | `infra/config_service.py` | `load_config` 的直接调用点（备份设置、自检） |

- 构造注入：服务均接收 `SharedServices` / `PathLayout` / 配置对象，禁止模块级全局实例
- 不在 router 内 new 服务：`server` 暴露 `services.owner` / `services.backup` 等只读属性

### 2.5 单人友好能力

- **一键备份/导出/恢复**：沿用 `/api/admin/backup/*` 路径；新增 `GET /api/admin/backup/verify?filename=` 校验归档完整性（manifest + checksum），恢复前自动校验，失败返回中文「备份文件校验失败：…」
- **启动自检**：`GET /api/health/selfcheck` 返回 `{ok, checks:[{key,label,status,detail}]}`；启动时日志输出中文摘要；端口占用/依赖缺失/模型凭据缺失给出明确中文原因
- **本机用量**：沿用 `/api/usage/summary`、`/api/usage/export.xlsx`；单人下 `as_user` 参数被忽略（不再 403），新增 `granularity=by_model` 默认可用
- **错误中文**：API 响应 message 中文；`logger` 保留英文原文；`dashboard/` 文案不动

## 3. 验收标准

1. 无任何令牌请求 `GET /api/auth/me` 返回 200 且 `role=admin`
2. `GET /api/agents`、`GET /api/usage/summary`、`GET /api/admin/backup/list` 无令牌可用
3. 旧库升级：迁移前 `users` 行数 = 迁移后行数；`local_owner` 指向原 admin
4. 迁移失败注入时：原数据不变，错误信息为中文，日志为英文
5. `pytest tests/unit/single_user tests/unit/db tests/unit/api -q` 通过
6. 服务在 8089 端口启动成功，自检接口返回 `ok=true`

## 4. 不在本轮范围

- `dashboard/`、`desktop/`、`docs/` 任何改动
- 删除旧认证模块文件、MFA 表、JWT 密钥文件
- 远端口令/多租户能力恢复
- 为吸收 `deepseek-harness` 工具护栏设计而大改工具链路（见 §5）

## 5. 延后吸收：工具与护栏设计（单人化收口后）

参考资料：`e:\HAPPYclaw\2026-11-11\dsh-解析\outputs\tools-guardrails.md`（落点对应 `engine/tools/*`、`manager.py`、`router.py`）

- 时机：单人化 + 迁移 + OOP 收口完成、第一阶段简报发出之后
- 原则：不改工具主链路，只挑 1–2 个低风险高收益点；候选优先级——
  1. **工具输出 schema 校验**（在既有 middleware 层增加返回值校验，失败降级为结构化错误）
  2. **执行前 checkpoint**（复用现有 thread artifact / trajectory 落盘，不新增存储）
- 实施前必须先在简报中写清：改哪个文件/函数、影响面、回退方式（开关或 revert 单文件）
- 采纳与否由用户拍板，未拍板不实施

### 5.1 待确认（只确认、不改）

参考资料：`e:\HAPPYclaw\2026-11-11\dsh-解析\outputs\providers-persistence.md`（token 估算 `CHARS_PER_TOKEN=4`，中文长会话压缩触发偏晚）

- 本仓库现状（已确认）：`src/` 内**没有** `CHARS_PER_TOKEN` 之类的字符估算；上下文占用取自 provider/harness 回传的 `usage.input_tokens / prompt_tokens / used_tokens`（见 `infra/agents/threads/context_breakdown.py`）
- 未确认：压缩阈值与裁剪策略在外部依赖 `happyclaw-harness` 内，需要读该包实现或配置才能判断是否存在「按 4 字符/token 估算」导致的触发偏晚
- 处理方式：本轮只把结论写进简报，**不改代码**；单人化收口后单独评估是否引入中文加权估算或按 provider 真实 usage 触发

## 6. 第二轮后端优化（单人化完成即进入）

按收益排序，每项先测基线再动手，改前/改后都要给数字：

1. 启动耗时与接口响应（`/api/health`、`/api/agents`、`/api/usage/summary` P50/P95）
2. 单用户并发与资源占用（多标签、多端口、长跑内存与连接回收）
3. 稳定性与可恢复性（异常退出、断电、SQLite 损坏自愈、备份完整性校验）
4. 架构收尾（剩余隐式全局状态收敛）
5. 错误可读性全量收口（用户可见中文、日志英文）

## 7. 环境与验证（已就绪）

- `.venv` 依赖：`pip --python .venv install -r .req-lock.txt`（`uv` 在此网络下 wheel 会被截断，已弃用）
- 可编辑安装：需先装 `hatchling / editables / trove-classifiers`，再 `--no-build-isolation -e .`；当前 `import octop` 正常（1.0.3b5）
- 测试：`& .venv\Scripts\python.exe -m pytest ... -q`（pytest 9.2 + pytest-asyncio 已装）
- 冒烟：`OCTOP_HOME=E:\HAPPYclaw\.octop-preview`，端口 8089，禁止浏览器操作
- 基线记录（T0.2）：本轮开始前的 `tests/unit` 通过项、启动耗时、接口 P50/P95，将写入第一份节点简报

## 8. 逐条验证请求（QA 七条）

```bash
# P0-1
curl -s localhost:8089/api/setup/status            # setup_required=false, wizard_password_required=false
# P0-2
curl -s localhost:8089/api/sessions                # 200，无 Authorization
curl -s localhost:8089/api/tasks                   # 200
curl -s localhost:8089/api/preferences             # 200
# P0-3
curl -s localhost:8089/api/providers               # api_key 为 ****xxxx 或 null；含 api_key_set
# P1-4
curl -s localhost:8089/api/auth/me                 # 无 permissions / sso_*
curl -s localhost:8089/api/teams                   # []
curl -s localhost:8089/api/user-groups/audience    # []
# P1-5/6
curl -s localhost:8089/api/agents                  # 无 user_id/visibility/group_ids；state/setup_hint 可读
# P1-7
curl -s -X POST localhost:8089/api/admin/backup/run -H 'content-type: application/json' -d '{}'
```
