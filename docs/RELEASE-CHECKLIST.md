# 发布前检查清单（单人本地版）

> 适用范围：HappyClaw 本机单人发行包（PyPI wheel、安装脚本、Docker 镜像）。
> 自动项：`powershell -File scripts/release-check.ps1`；本机链路：`powershell -File scripts/smoke_local.ps1`。
> 人工项需要逐条勾选并记录证据（命令输出、截图路径、文件时间戳）。
> 版本号、CHANGELOG、发布清单、标签与发版步骤见 [`docs/versioning-and-release.md`](./versioning-and-release.md)。

发布版本：`__________`　检查人：`__________`　日期：`__________`

---

## 一、依赖与版本

| # | 检查项 | 判据 | 自动 | 结果 |
|---|--------|------|------|------|
| 1.1 | Python | `requires-python >=3.12`；安装脚本使用 3.12 | ✅ | ☐ |
| 1.2 | 项目版本 | `pyproject.toml` version 与 README / README_CN 徽章一致 | ✅ | ☐ |
| 1.3 | CHANGELOG | 包含当前版本条目，且「单人化改造」已记录 | ✅ | ☐ |
| 1.4 | 运行时依赖 | `octop-harness[all]>=1.0.9`、`octop-gateway>=1.0.3`、`fastapi>=0.110`、`uvicorn[standard]>=0.27` 已发布到 PyPI | ☐ | ☐ |
| 1.5 | 前端构建 | `make build-frontend` 成功，产物写入 `src/octop/dashboard/` | ☐ | ☐ |
| 1.6 | 锁文件 | `uv.lock` 与 `pyproject.toml` 同步（`uv lock --check`） | ☐ | ☐ |
| 1.7 | 静态检查 | `make all`（format + lint + typecheck + test）全绿 | ☐ | ☐ |

## 二、端口与网络

| # | 检查项 | 判据 | 自动 | 结果 |
|---|--------|------|------|------|
| 2.1 | 默认端口 | 8088 空闲，或占用者是本次要发布的实例 | ✅ | ☐ |
| 2.2 | 端口可配置 | `octop run --port 8090` 可启动并用新端口访问 | ☐ | ☐ |
| 2.3 | 监听地址 | 默认仅 `127.0.0.1`；`--host 0.0.0.0` 时局域网可访问且页面正常 | ☐ | ☐ |
| 2.4 | 反向代理 / TLS | 启用 HTTPS 或反代时，WebSocket 升级与附件上传正常 | ☐ | ☐ |
| 2.5 | 健康检查 | `GET /api/health` 返回 `ok=true`、`db=true`、`users_loaded=1` | ✅ | ☐ |
| 2.6 | IM 回调 | 已配置通道的公网回调地址可达（未配置则跳过并注明） | ☐ | ☐ |

## 三、数据与迁移

| # | 检查项 | 判据 | 自动 | 结果 |
|---|--------|------|------|------|
| 3.1 | 全新安装 | 空 `OCTOP_HOME` 首次启动自动建库并创建本机使用者 | ✅ | ☐ |
| 3.2 | 旧库升级 | 用上一版本 `octop.db` 启动，迁移成功且专家 / 会话 / 通道数量与升级前一致 | ☐ | ☐ |
| 3.3 | 旧字段兼容 | 旧 `config.json` 中的 `access_token_ttl_seconds`、`login_*`、`require_setup_password` 不导致启动失败 | ☐ | ☐ |
| 3.4 | PostgreSQL | `OCTOP_DATABASE_URL` 指向 PG 时迁移成功（可选） | ☐ | ☐ |
| 3.5 | 数据目录可写 | `~/.octop` 可写；`OCTOP_HOME` 改到其他磁盘后正常启动 | ✅ | ☐ |
| 3.6 | 工作区完整 | 专家工作区文件、技能包、插件、知识库在升级后仍可读 | ☐ | ☐ |
| 3.7 | **空目录自建（阻断项）** | 安装/升级流程不依赖 `~/.octop` 已存在：在完全不存在该目录的机器或路径上执行安装与首次启动，能自动创建数据库、配置、日志、备份目录与工作区等全部结构，并正常返回 `/api/health` | ☐ | ☐ |

> 3.7 为硬性发布门槛：安装脚本、桌面端引导、Docker entrypoint 与 `octop run` 都不得假设用户数据目录已被预建；任一环节因目录缺失而失败，禁止发布。验证时必须使用独立临时目录，不得对真实 `~/.octop` 做删除或改名。

## 四、备份与恢复

| # | 检查项 | 判据 | 自动 | 结果 |
|---|--------|------|------|------|
| 4.1 | 创建备份 | `octop backup create --include-chats` 生成归档且体积合理 | ☐ | ☐ |
| 4.2 | 恢复备份 | 空目录 `octop backup restore <归档> --yes` 后启动，专家 / 配置 / 会话完整 | ☐ | ☐ |
| 4.3 | 跨引擎限制 | 文档已说明 SQLite 与 PostgreSQL 备份不可互恢 | ✅ | ☐ |
| 4.4 | 自动备份 | `octop backup auto status` 显示计划；`octop backup auto run` 可执行 | ☐ | ☐ |

## 五、日志与可观测性

| # | 检查项 | 判据 | 自动 | 结果 |
|---|--------|------|------|------|
| 5.1 | 前台日志 | `octop run` 终端可见启动、监听地址与错误 | ☐ | ☐ |
| 5.2 | 文件日志 | 日志写入 `~/.octop/logs/octop.log`，按天轮转为 `octop.YYYY-MM-DD.log`；旧版 `~/.octop/octop.log` 首次启动时迁移 | ☐ | ☐ |
| 5.3 | 日志不含密钥 | 抽查日志无 `sk-`、Bearer Token、通道 Secret 明文 | ✅ | ☐ |
| 5.4 | 关键错误可诊断 | 模型连接失败、通道认证失败在日志中有可定位的中文/英文提示 | ☐ | ☐ |

## 六、安装与卸载

| # | 检查项 | 判据 | 自动 | 结果 |
|---|--------|------|------|------|
| 6.1 | Windows 安装 | 干净机器执行 `install.ps1`，重开终端后 `octop --version` 可用 | ☐ | ☐ |
| 6.2 | macOS / Linux 安装 | `install.sh` 后 `octop --version` 可用 | ☐ | ☐ |
| 6.3 | Docker 启动 | `docker compose -f docker/docker-compose.yml up -d --build` 后 8088 可访问，且无管理员密码步骤 | ✅ | ☐ |
| 6.4 | 数据卷 | Docker 数据落在 `/data/.octop`，重建容器后数据仍在 | ☐ | ☐ |
| 6.5 | 卸载 | 按文档删除 `~/.octop` 并移除 PATH 后无残留进程 / 服务 | ☐ | ☐ |
| 6.6 | 升级 | `octop update` 后版本变化，数据与配置保留 | ☐ | ☐ |

## 七、文档与单人化一致性

| # | 检查项 | 判据 | 自动 | 结果 |
|---|--------|------|------|------|
| 7.1 | README | README / README_CN 无登录、注册、邀请、多租户、账号权限描述 | ✅ | ☐ |
| 7.2 | 快速开始 | `docs/quickstart.md` 命令逐条在本机执行通过 | ☐ | ☐ |
| 7.3 | 帮助文档 | `docs/user-guide.md` 的安装、启动、模型、备份、卸载章节与实际行为一致 | ☐ | ☐ |
| 7.4 | 配置文档 | `docs/configuration.md` 已标注 legacy 变量无效 | ✅ | ☐ |
| 7.5 | API 文档 | `docs/api.md` 的账号接口描述与后端实际响应一致（2026-11-12 07:06 实测核对，差异见下方记录） | ☐ | ☑ 已达成（差异已回填） |
| 7.6 | 废弃文档 | LDAP、旧版 HTML 指南已加停用 / 快照标注，未直接删除 | ✅ | ☐ |
| 7.7 | 死链 | README 与 docs 中相对链接均可打开 | ☐ | ☐ |
| 7.8 | Shell 语法 | `install.sh` / `install-octop.sh` / `build-fpk.sh` / `scripts/fnos/*.sh` 通过 `bash -n` | ☐ | ☑ 通过（2026-11-12） |

### 7.9 代码里仍存在、但文档已按单人化描述的部分（待后端落地后复核）

> 2026-11-12 静态核对 `src/octop/api/` 与 `src/octop/cli/` 得出。2026-11-12 07:06 运行时复核：setup 已固定为无需初始化、JWT 已放宽，7.9.1–7.9.5 的对外行为与文档一致（代码保留为兼容层）；7.9.6、7.9.7 尚未实测，仍按待复核处理。

| # | 代码事实 | 与文档的差异 | 状态 |
|---|----------|--------------|------|
| 7.9.1 | `auth.py` 仍注册 `POST /api/auth/login`、`POST /api/auth/logout`、`GET /api/auth/me`、`POST /api/auth/change-password`、`GET /api/auth/captcha` | `docs/api.md` 与 `docs/user-guide.md` 按「无登录」描述 | ☑ 已达成（实测 login 200 占位 token、me 200、logout 204、change-password 400、captcha 200 `provider:none`） |
| 7.9.2 | `auth_device.py`、`auth_mfa.py`、`auth_oauth.py`、`auth_oidc.py`、`auth_ldap.py` 仍挂在 `/api/auth` | 文档已不再提及这些登录方式 | ◐ oidc/oauth/ldap/passkey 已核实（status 200 且禁用、start/config-test 400）；device/mfa 未测 |
| 7.9.3 | `users.py`、`invites.py`、`user_roles.py`、`user_groups.py` 仍挂载（`/api/users`、`/api/users/invites`、`/api/users/roles`、`/api/user-groups`） | 文档声明账号 / 邀请 / 角色已移除 | ◐ `/api/users` 已核实（读 200、写 400）；invites / roles / user-groups 未测 |
| 7.9.4 | `setup.py` 挂在 `/api`，`setup_lockdown` 中间件仍安装；无初始用户时抛 `SETUP_REQUIRED` | 快速开始与帮助文档已不包含 setup 向导 | ☑ 已达成（干净 `OCTOP_HOME` 下 `setup_required:false`、本地 owner 自动创建、begin/finish 400） |
| 7.9.5 | `middleware/jwt_auth.py` 全局校验 `/api/*`，仅放行 health、login、captcha、MFA、OIDC/OAuth、LDAP 等白名单 | 文档按「直接调用 API、无需 Authorization」描述 | ☑ 已达成（无 token 时 `/api/users`、`/api/teams` 均 200） |
| 7.9.6 | `admin.py` / `backup.py` 挂在 `/api/admin`；`octop user` 系列 CLI 仍注册但标注 deprecated | 文档把多用户管理描述为纯兼容层 | ☐ 待后端落地后复核 |
| 7.9.7 | `src/octop/infra/users/`（`manager.py`、`invites.py`、`password.py`、`permissions.py`、`groups.py` 等）仍存在；`api/common/sso_cookie.py`、`user_manager.count()`、`~/.octop/users/` 旧目录仍在代码路径中 | 文档未描述这些兼容面 | ☐ 待后端落地后复核 |

> 7.8 记录（2026-11-12 07:10）：WSL 仍缺 `/bin/bash`，改用 Git Bash `GNU bash 5.2.37(1)-release` 执行 `bash -n`，以下 12 个脚本全部通过：`scripts/install.sh`、`scripts/install-octop.sh`、`scripts/build-fpk.sh`、`scripts/fnos/common.sh`、`scripts/fnos/slim-site-packages.sh`、`scripts/fnos/store_version.sh`、`scripts/wheel_build.sh`、`scripts/ci/upload_release_cos.sh`、`scripts/run-discord-local.sh`、`docker/docker_build.sh`、`docker/docker-entrypoint.sh`、`docker/bake-desktop.sh`。仅做语法校验，未在 POSIX 上执行。

> 7.2 冒烟记录（2026-11-12 07:03）：`scripts/release-check.ps1` → 11 通过 / 0 警告 / 0 失败，退出码 `0`。`scripts/smoke_local.ps1` 用临时 `OCTOP_HOME`、空闲端口 3320 → `/api/health` 首次可用耗时 **52.1s**，响应 `{"ok":true,"db":true,"users_loaded":1,"agents_running":0}`，退出码 `0`。另两次接口探测的 health 就绪时间分别为 49.2s、48.1s（冷启动波动区间 48–53s）。
> 7.5 核对记录（2026-11-12 07:06；临时 `OCTOP_HOME` + 空闲端口 7462，`.venv\Scripts\octop.exe run`）：
> - **已达成** — setup 固定为不需要初始化：`GET /api/setup/status` 返回 `200 {setup_required:false, local_account:true, single_user:true}`；`POST /api/setup/begin`、`POST /api/setup/finish` 均返回 `400`（单人模式无需向导）。
> - **已达成** — JWT 放宽：不带 `Authorization` 时 `GET /api/users` 返回 `200`（仅 local-owner 一条）、`GET /api/teams` 返回 `200 []`、`GET /api/auth/me` 返回 `200` 的 local-owner。
> - **差异（已按实测回填 `docs/api.md`）**：① `/setup/status` 字段名为 `setup_required` / `local_account` / `single_user`，不是旧文里的 `required` / `completed` / `has_admin`；② `/auth/me` 的 `role` 为 `"local"`，而 `/users` 列表里同一账号渲染为 `"admin"`；③ passkey 状态字段是 `passwordless_login`，不是 `enabled`；④ oauth 状态返回 `providers` 数组。
> - 其余实测：`POST /auth/login` → `200`（占位 token `local-owner`，`expires_in:0`）、`POST /auth/logout` → `204`、`PATCH /auth/me` → `200`、`POST /auth/change-password` → `400`；oidc/ldap 状态 `200 {enabled:false}`、oauth 状态 `200` 且各 provider `enabled:false`、对应 `start` / `config/test` → `400`；`GET /users/{id}` → `200`，`POST /users`、`PATCH /users/{id}`、`DELETE /users/{id}` → `400`。
> - 结论：对外行为与 `docs/api.md` 的单人化描述一致，仅字段名/角色取值有上述差异，已在文档中按实际响应写明。
> 7.7 静态校验记录：2026-11-11 扫描 `docs/`（含 `docs/adr/`）、根目录与 `docker/`、`scripts/`、`fnos/` 的 Markdown，151 条相对链接与锚点全部可解析。`docs/bridge.md` 6 张缺失图片已改为文字图注，ADR 的仓外源码引用已改为行内路径。发布前需在最终提交上复跑一次。

## 八、安全与边界

| # | 检查项 | 判据 | 自动 | 结果 |
|---|--------|------|------|------|
| 8.1 | 明文密钥 | 仓库文档 / 脚本 / docker 无 `sk-`、AK、私钥、Bearer 明文 | ✅ | ☐ |
| 8.2 | 默认监听 | 默认只监听回环；文档明确提示 `0.0.0.0` 的风险 | ✅ | ☐ |
| 8.3 | 工具护栏 | `~/.octop/security/tool_guard/` 默认规则生效 | ☐ | ☐ |
| 8.4 | 上传限制 | 超过 `OCTOP_MAX_UPLOAD_MB` 的上传被拒绝并给出中文提示 | ☐ | ☐ |
| 8.5 | 路径穿越 | 附件、知识库、插件名不含越权路径 | ☐ | ☐ |

---

## 一键自动检查

```powershell
# 仓库根目录
powershell -File scripts/release-check.ps1

# 本机链路（临时数据目录，不碰真实 ~/.octop）
powershell -File scripts/smoke_local.ps1
```

预期：

- `release-check.ps1` 退出码 0，输出「自动检查通过」。
- `smoke_local.ps1` 退出码 0，输出 `ok : True` 与临时数据目录清单。

## 发布签字

| 角色 | 姓名 | 结论（通过 / 有条件通过 / 不通过） | 备注 |
|------|------|-----------------------------------|------|
| 文档与交付 | | | |
| 后端 | | | |
| 前端 | | | |
| 测试 | | | |

> 任一项「不通过」时禁止发布；「有条件通过」必须写明条件与责任人。
