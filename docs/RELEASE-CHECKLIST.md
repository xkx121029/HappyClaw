# 发布前检查清单（单人本地版）

> 适用范围：HappyClaw 本机单人发行包（PyPI wheel、安装脚本、Docker 镜像）。
> 自动项：`powershell -File scripts/release-check.ps1`；本机链路：`powershell -File scripts/smoke_local.ps1`。
> 人工项需要逐条勾选并记录证据（命令输出、截图路径、文件时间戳）。

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
| 5.2 | 文件日志 | 日志写入 `~/.octop/octop.log`；系统服务写入 `~/.octop/logs/` | ☐ | ☐ |
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
| 7.5 | API 文档 | `docs/api.md` 的账号接口描述与后端实际响应一致（当前按目标态编写，未核对） | ☐ | ☐ 待核对 |
| 7.6 | 废弃文档 | LDAP、旧版 HTML 指南已加停用 / 快照标注，未直接删除 | ✅ | ☐ |
| 7.7 | 死链 | README 与 docs 中相对链接均可打开 | ☐ | ☐ |

> 7.2 冒烟记录：待 `.venv` 依赖就绪后执行 `scripts/smoke_local.ps1`，把真实输出附在本节。
> 7.5 核对记录：待后端单人化接口落地后，实测 `/api/auth/*` 与 `/api/users/*`，以实际响应为准修改 `docs/api.md`，并在此填写核对时间（`YYYY-MM-DD HH:mm`）与结论。当前文档中的账号写接口 `400` 属于目标态，未经实测确认。

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
