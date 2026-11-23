# 任务清单（单人本地工具改造）

> 规则：每项先补/改测试，再改实现；完成一项发一次中文简报。

## 阶段 0：环境与基线

- [x] T0.1 依赖安装完成（系统 pip → `.venv`），`pytest --collect-only` 可跑
- [ ] T0.2 记录基线：`pytest tests/unit -q` 结果、服务启动耗时、`/api/health` 响应时间

## 阶段 0.3：桌面壳首次启动（P0）

- [x] T0.3a `should_defer_control_plane_db` 恒 False（废弃标记），启动始终建库 + 迁移后再监听
- [ ] T0.3b 全新 `HAPPYCLAW_HOME` 实测 `/api/health` 首次 200 耗时，写入简报
- [x] T0.3c 新增 `GET /api/runtime/activity`，返回 `{busy, counts, active_turns, terminal_sessions, running_agents, running_jobs, updated_at}`（`counts` 是桌面退出守卫实际读的契约）
- [x] T0.3d 确认 `setUnsavedContent()` / 新建会话快捷键对接点（前端已实现于 `Chat/index.tsx` L1054–1070），写入简报交前端线
- [x] T0.3e 监听后异步创建默认 `main` agent（fire-and-forget，失败只记日志，`OCTOP_DISABLE_DEFAULT_AGENT=1` 可关）
- [ ] **简报：桌面首次启动可用 + activity 接口**

## 阶段 0.4：QA 第一轮阻断项（P0 优先）

- [x] T0.4a `/api/setup/status` 固定 false，setup 写接口中文拒绝，不写 `octop-login.txt`（P0-1）
- [x] T0.4b 全站去除 JWT 依赖，无令牌直进 200（P0-2）
- [x] T0.4c provider `api_key` 脱敏 + PATCH 忽略脱敏值 + 日志审计（P0-3）
- [x] T0.4d `/auth/me` 精简字段；`/user-groups/audience` 返回空；`/teams` 恢复专家团原实现（P1-4，已按拍板修正）
- [x] T0.4h WebSocket 允许空 token（10 处 `close(4001)` 改为按本机 owner 解析，有 token 仍兼容）
- [x] T0.4e agent payload 去掉 `user_id/visibility/group_ids`（P1-5）
- [x] T0.4f 无模型 agent 改 `created` + `setup_hint` 中文（P1-6）
- [x] T0.4g 备份默认 `include_chats=true`（P1-7）
- [ ] **简报：QA 七条逐条实际行为（请求 + 返回）**

## 阶段 0.5：交付主路径（最高优先级，先于 OOP 与设计吸收）

- [x] T0.3 `GET /api/health` 匿名可用（门禁移除后回归测试）
- [x] T0.4 `/api/auth/me` 返回 owner、`/api/auth/logout` 204，均不读 token
- [x] T0.5 `/api/sessions*`、`/api/tasks*`、`/api/preferences*` 无 token 直进 200（新增回归测试）
- [x] T0.6 `/api/setup/status` 固定 `setup_required=false`；setup 写接口中文拒绝
- [ ] **简报 0：交付主路径四条实际行为**

## 阶段 1：单用户身份（可独立验证）

- [x] T1.1 新增 `tests/unit/single_user/test_owner_identity.py`（解析顺序、空库自建、缓存、失败中文告警）
- [x] T1.2 实现 `src/octop/infra/users/owner.py::OwnerIdentityService`
- [x] T1.3 接入 `SharedServices` 只读属性 `owner`，`server.owner_identity` 访问器
- [x] T1.4 重写 `api/deps.py`：`current_user` 恒 owner，`require_*` 恒放行，保留废弃 shim
- [x] T1.5 新增 `tests/unit/api/test_single_user_access.py`（无令牌 200）
- [x] T1.6 `jwt_auth` 只注入 `request.state.octop_user`；`app.py` 移除 lockdown 挂载
- [ ] **简报 1：后端单用户跑通**

## 阶段 2：数据库迁移（可独立验证）

- [x] T2.1 新增 `tests/unit/db/test_migration_026_single_user.py`（旧库升级、幂等、失败保留原值）
- [x] T2.2 新增 `026_single_user_owner.sql` / `.pg.sql`
- [x] T2.3 `migrate.py` 增加 `_ensure_single_user_schema`，事务回滚 + 中文告警
- [ ] **简报 2：迁移脚本可用**

## 阶段 3：认证路由兼容壳

- [x] T3.1 `auth.py`：login/me/logout/captcha/改密/头像
- [x] T3.2 `users.py` / `user_groups.py` / `user_roles.py` / `invites.py`：读取单人化、写操作中文拒绝
- [x] T3.3 `auth_mfa/device/oidc/oauth/ldap`：禁用态 + 中文提示
- [x] T3.4a `test_jwt_auth_middleware.py` 重写为「单人访问」测试（无令牌 200、非法令牌忽略、/setup/status）
- [ ] T3.4b 其余冲突测试待处理：`test_jwt_tokens.py`、`test_permissions_api.py`、`test_auth_flow.py`、`test_users_api.py`、`test_boundary_authz.py`、`test_setup_wizard.py`
- [ ] **简报 3：认证路径下线完成**

## 阶段 4：OOP 服务化（每模块一次简报）

- [ ] T4.1 `BackupService`（`infra/backup/service.py`）+ 测试，router 改为调用服务 → **简报 4**
- [ ] T4.2 `UsageReportService`（`infra/usage/report.py`）+ 测试，router 简化 → **简报 5**
- [ ] T4.3 `StartupSelfCheck`（`infra/selfcheck.py`）+ `/api/health/selfcheck` → **简报 6**
- [ ] T4.4 `LocalConfigService`（`infra/config_service.py`），收敛 `load_config` 调用 → **简报 7**

## 阶段 5：单人友好能力

- [ ] T5.1 备份完整性校验 `GET /api/admin/backup/verify`，恢复前自动校验
- [ ] T5.2 启动自检输出中文摘要（端口/DB/目录/模型凭据/磁盘）
- [ ] T5.3 用量接口单人化：`as_user` 忽略、`by_model` 可用、耗时字段确认
- [ ] T5.4 错误中文抽检：`grep` 扫描 `OctopError(` 的英文 message，用户可见的改中文
- [ ] **简报 8：第一阶段完成**

## 阶段 6：第二轮后端优化（基线先行）

- [ ] T6.1 性能基线：启动耗时、`/api/health`、`/api/agents`、`/api/usage/summary` P50/P95（无数据不动手）
- [ ] T6.2 启动优化：延迟导入/懒加载/连接池预热，给出改前改后数字 → **简报 9**
- [ ] T6.3 并发与资源：多标签/多端口/长跑测试，连接与内存回收，给出数据 → **简报 10**
- [ ] T6.4 稳定性：异常退出、断电、SQLite 损坏自愈 + 中文提示；备份恢复完整性校验 → **简报 11**
- [ ] T6.5 架构收尾：剩余隐式全局状态收敛（`PluginRegistry` 等）→ **简报 12**
- [ ] T6.6 错误可读性全量收口 → **简报 13**

## 阶段 7：参考资料沉淀（单人化收口后，需先拍板）

- [x] T7.1 确认 token 估算方式（本仓库无字符估算；阈值在 `happyclaw-harness`）→ 只写简报，不改代码
- [ ] T7.2 阅读 `deepseek-harness` 工具护栏报告，选 1–2 个低风险点（建议：输出 schema 校验、执行前 checkpoint），实施前说明改哪/影响/回退
- [ ] T7.3 文档类改动（README/说明）只写简报，交文档线落盘；`docs/` 不由本线修改

## 验证命令

```powershell
py -3.13 -m pip --python "E:\HAPPYclaw\Octop\.venv\Scripts\python.exe" install -e "E:\HAPPYclaw\Octop" pytest pytest-asyncio httpx
& "E:\HAPPYclaw\Octop\.venv\Scripts\python.exe" -m pytest tests/unit/single_user tests/unit/db tests/unit/api -q
$env:HAPPYCLAW_HOME="E:\HAPPYclaw\.octop-preview"; $env:OCTOP_PORT="8089"
& "E:\HAPPYclaw\Octop\.venv\Scripts\python.exe" -m octop serve
```
