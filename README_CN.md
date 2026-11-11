<p align="center">
  <img src="docs/assets/readme-banner-zh.png" alt="HappyClaw Banner" width="600" />
</p>

<p align="center">
  <strong>装在自己电脑上的单人 AI 工作台 — 一个进程，一个你。</strong>
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img alt="Python 3.12+" src="https://img.shields.io/badge/python-3.12%2B-blue?logo=python&logoColor=white" /></a>
  <a href="https://github.com/TencentCloud/Octop/blob/main/LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-green" /></a>
  <a href="https://github.com/TencentCloud/Octop/releases"><img alt="Version" src="https://img.shields.io/badge/version-1.0.3b5-orange" /></a>
  <a href="https://github.com/astral-sh/ruff"><img alt="Code Style: Ruff" src="https://img.shields.io/badge/code%20style-ruff-000000?logo=ruff&logoColor=white" /></a>
</p>

<p align="center">
  <a href="#-快速开始">快速开始</a> ·
  <a href="#-能做什么">能做什么</a> ·
  <a href="#-安装">安装</a> ·
  <a href="#️-配置模型">配置模型</a> ·
  <a href="#-数据目录与备份">数据目录与备份</a> ·
  <a href="#-常见问题">常见问题</a>
</p>

<p align="center">
  <a href="README.md">English</a> · <b>中文</b>
</p>

---

**HappyClaw** 是给个人使用的本地 AI 工作台。没有账号体系，没有登录页，也没有团队与权限配置：装好、启动、打开浏览器，就是以本机使用者的身份在工作。

它在同一个进程里提供 Web 控制台、CLI、IM 通道与定时任务，所有数据都留在你自己的机器上（默认 `~/.octop/`）。你可以创建多个专家，为每个专家配置模型、工作区、技能与通道；日常通过网页对话，也可以把飞书、钉钉、QQ、微信、企业微信、Telegram、Discord 接进来。

## 🚀 快速开始

> 完整 Windows 步骤见 [docs/quickstart.md](docs/quickstart.md)，5 分钟内可以跑通。

**Windows（PowerShell）**

```powershell
irm https://download.octop.cloud/octop/scripts/install.ps1 | iex
octop run
```

**macOS / Linux**

```bash
curl -fsSL https://download.octop.cloud/octop/scripts/install.sh | bash
octop run
```

然后打开 **http://127.0.0.1:8088**。首次启动会自动创建本机使用者，不需要注册，也不需要输入密码；直接进入控制台，在「设置 → 模型」里配置模型即可开始对话。

## 🧭 能做什么

| | 能力 | 说明 |
|---|------|------|
| 💬 | **本机对话** | Web 控制台实时对话，支持多轮、附件、工具调用展示 |
| 🎭 | **多专家** | 每个专家独立的工作区、模型、技能与定时任务；内置专家库与 16 种 MBTI 人格模板 |
| 🎯 | **AgentTeams**（Beta） | 协调者调度多位专家完成多步骤任务，[说明](docs/expert-teams.md) |
| 🔌 | **Connector** | 腾讯文档、腾讯会议、Notion、滴答清单、飞书 CLI、企业微信 CLI 等 OAuth / MCP 接入，[目录](docs/connectors.md) |
| 📚 | **知识库** | 对本地文档做 RAG 检索，回答锚定自己的资料 |
| 🧩 | **插件与技能** | 安装第三方插件，按专家启用技能 |
| ↔️ | **ACP 双向集成** | `octop acp` 接入 IDE；对话中委派 OpenCode / CodeBuddy / Claude Code / Codex |
| 💻 | **终端 AI+** | 浏览器内交互式 Shell，AI 辅助执行命令与排障 |
| 🌐 | **浏览器 AI+** | 基于 Chromium 的会话，支持网页自动化、截图与远程浏览 |
| 🖥️ | **远程桌面** | 控制台内看屏与键鼠操作，跨 Linux / Windows / macOS |
| ⏰ | **定时任务** | 自然语言或 Cron 表达式创建，按时执行并推送结果 |
| 🏠 | **完全本地** | 配置、对话、工作区与凭据都在 `~/.octop/`，不依赖外部账号服务 |

## 🧠 技术栈

| 层级 | 技术 |
|------|------|
| 语言 | Python 3.12+ |
| Web 框架 | FastAPI + uvicorn |
| Agent 运行时 | [HappyClaw Harness](https://github.com/TencentCloud/octop-harness) |
| IM 桥接 | [HappyClaw Gateway](https://github.com/TencentCloud/octop-gateway) |
| 控制面数据库 | SQLite（WAL，默认）或 PostgreSQL（可选） |
| 前端 | React 18 + TypeScript + Vite + Ant Design |
| 调度 | APScheduler |
| ACP | agent-client-protocol |
| 构建 / 质量 | hatchling · ruff · mypy · pytest |

单进程运行：Web UI、IM 与定时任务都经由进程内的 `HarnessProcessor` 处理，不依赖外部消息队列。重启后状态从控制面数据库重建。

## 📦 安装

| 方式 | 平台 | 命令 |
|------|------|------|
| 一键脚本 | macOS / Linux | `curl -fsSL https://download.octop.cloud/octop/scripts/install.sh \| bash` |
| 一键脚本 | Windows | `irm https://download.octop.cloud/octop/scripts/install.ps1 \| iex` |
| 仓库内脚本 | macOS / Linux | `bash scripts/install.sh` |
| 仓库内脚本 | Windows | `powershell -ExecutionPolicy Bypass -File scripts/install.ps1` |
| PyPI | 全平台 | `pip install octop` |
| Docker | 全平台 | `docker compose -f docker/docker-compose.yml up -d --build` |

安装脚本会把运行环境放在 `~/.octop/venv`，并在 `~/.octop/bin/octop` 生成命令入口，不会改动系统 Python。安装完成后请打开新终端，或重新加载 shell 配置。

可选组件：

```bash
# 浏览器自动化需要 Playwright Chromium（系统已有 Chrome/Chromium 时跳过）
bash scripts/install.sh --extras browser
```

安装选项（`--version`、`--from-source`、`--mirror`，其中 `--mirror` 仅 Unix 脚本提供）见 [scripts/README.md](scripts/README.md)。

### Docker

```bash
# 构建并启动
docker compose -f docker/docker-compose.yml up -d --build

# 打开控制台
# http://localhost:8088
```

单人模式下 Docker 不需要预置管理员密码。容器首次启动会初始化数据库并自动绑定本机使用者；数据卷仍挂载在 `/data/.octop`。完整说明见 [docker/README_CN.md](docker/README_CN.md)。

### 升级

```bash
octop update
```

`octop update` 只替换程序本体，`~/.octop/` 下的数据库、工作区、密钥与 `config.json` 都会保留；数据库结构在下次启动时自动迁移。跨版本升级前建议先备份：

```bash
octop backup create
```

## ⚙️ 配置模型

模型按专家配置，也可以在控制台「设置 → 模型」中统一管理。

```bash
octop models              # 查看预设与模型解析
octop provider list       # 列出已配置供应商
octop provider --help     # 供应商增删改查
```

支持 OpenAI 兼容 API、Anthropic、AWS Bedrock、DashScope（通义千问）、Ollama 本地模型等。新增供应商时填写 Base URL 与 API Key，勾选模型后点「测试连接」；测试通过再保存。Ollama 默认连接本机地址，无需 API Key。

### 常用配置命令

```bash
octop agent list                 # 专家列表
octop agent create               # 新建专家
octop channel list               # IM 通道
octop skills list --agent main   # 技能
octop cron list                  # 定时任务
```

环境变量与 `config.json` 的完整字段见 [docs/configuration.md](docs/configuration.md)。

## 📁 数据目录与备份

```
~/.octop/                          ← 安装与数据根目录
├── config.json                    # 进程配置（端口、TLS、数据库等）
├── env                            # 可选环境变量（API Key 等）
├── octop.db                       # SQLite 控制面（专家、通道、定时任务 …）
├── secrets/                       # 腾讯云授权缓存（cloud/、cloud.key）
├── agents/<agent_id>/             # 各专家工作区（SOUL.md、skills …）
├── security/tool_guard/           # Shell 命令允许/拒绝规则
├── backups/                       # octop backup create 生成的归档
├── logs/                          # 运行日志
├── venv/                          # 安装脚本创建的 Python 环境
└── bin/octop                      # 命令入口
```

数据目录可用 `OCTOP_HOME` 整体改到其他磁盘。

### 备份与恢复

```bash
octop backup create              # 生成归档（数据库 + 工作区 + 配置）
octop backup restore <归档文件>   # 恢复到 ~/.octop
octop backup auto status         # 自动备份配置
octop backup auto run            # 立即执行一次自动备份
```

自动备份默认**关闭**（`backup.auto_enabled`）。开启后在 `octop run` 进程内每天 04:00 执行，默认保留 7 份；只清理 `octop-auto-backup-*` 旧归档，不会删除手动备份。

> 默认归档不含聊天历史；迁移完整会话时使用 `octop backup create --include-chats`。SQLite 与 PostgreSQL 的备份不能跨引擎互恢，恢复前请确认运行中的数据库引擎与备份一致。

换机、回退的逐步命令见 [docs/migration-and-restore.md](docs/migration-and-restore.md)。

## 📖 CLI 速查

| 命令 | 说明 |
|------|------|
| `octop init` | 初始化 `~/.octop/`（数据库与运行目录） |
| `octop run` | 前台启动服务 |
| `octop service start` | 注册并启动系统服务（systemd / launchd） |
| `octop agent` | 创建、列出、启停专家 |
| `octop channel` | 安装与管理 IM 通道 |
| `octop chats` | 会话列表与交互式对话 |
| `octop acp` | 为 IDE 提供 stdio ACP 服务 |
| `octop cron` | 管理定时任务 |
| `octop models` | 供应商预设与模型解析 |
| `octop skills` | 按专家启用/禁用技能 |
| `octop plugin` | 安装与管理第三方插件 |
| `octop backup` | 创建与恢复备份 |
| `octop update` | 检查并安装更新 |
| `octop clean` | 清理 CLI 状态或清空 `~/.octop/` |

完整参数见 [docs/cli.md](docs/cli.md)。

## 📚 文档索引

| 文档 | 内容 |
|------|------|
| [docs/quickstart.md](docs/quickstart.md) | Windows 优先的 5 分钟上手 |
| [docs/user-guide.md](docs/user-guide.md) | 安装、模型、专家、通道、定时任务、常见问题 |
| [docs/migration-and-restore.md](docs/migration-and-restore.md) | 备份、换机器迁移、恢复失败回退 |
| [docs/configuration.md](docs/configuration.md) | 环境变量与 `config.json` 字段 |
| [docs/cli.md](docs/cli.md) | 全部 CLI 命令与参数 |
| [docs/api.md](docs/api.md) | HTTP API 参考 |
| [docs/architecture.md](docs/architecture.md) | 运行结构与模块边界 |
| [docs/connectors.md](docs/connectors.md) | OAuth / MCP Connector 目录 |
| [docs/RELEASE-CHECKLIST.md](docs/RELEASE-CHECKLIST.md) | 发布前检查清单 |

## 🖥️ Web 控制台

`octop run` 启动后访问 **http://127.0.0.1:8088**，直接进入工作台。

- **对话** — 与专家或团队实时聊天
- **专家** — 创建专家、选择专家库 / MBTI、配置供应商与工作区
- **Connector** — OAuth 应用与 MCP 网关
- **通道** — IM 平台配置
- **定时任务** — 可视化 Cron 管理
- **知识库** — 文档语料、语义检索
- **插件** — 安装、启用与配置
- **控制** — 远程桌面、浏览器 AI+
- **ACP** — 配置出站编程 Agent Runner
- **设置** — 模型、备份、TLS、监听地址与日志

交互式 API 文档默认关闭，在 `config.json` 中设置 `"enable_api_docs": true` 后访问 `/api/docs`。

## 🏗️ 架构与项目结构

```
OctopServer
 ├─ DatabasePool          SQLite (WAL) 或 PostgreSQL
 ├─ SharedServices        依赖注入根 — 所有 repo 与配置
 ├─ ExpertCatalog         启动时扫描专家库
 ├─ LocalOwner            本机使用者（启动时自动解析/创建）
 └─ AgentRuntime（按专家）
     ├─ HarnessAgent      Agent 运行时（octop-harness）
     ├─ HarnessProcessor  IM / UI / 定时任务入口
     ├─ ChannelManager    IM 连接（octop-gateway）
     └─ CronManager       APScheduler
```

```
src/octop/
  config.py    环境变量配置
  launch.py    OctopServer 启动 + uvicorn
  infra/       业务核心（agents、gateway、cron、db …）
  api/         HTTP 层 — FastAPI 路由与 SSE
  cli/         CLI 层 — Click 命令
  dashboard/   构建后的 React SPA（wheel 产物）

dashboard/     前端源码（Vite）— 在此编辑，运行 make build-frontend
docker/        Docker Compose、入口脚本、构建脚本
docs/          使用与架构文档
tests/         unit/ + integration/
```

详见 [docs/architecture.md](docs/architecture.md)。

## 🛠️ 开发

**前置条件：** Python 3.12+、Node 18+、[uv](https://docs.astral.sh/uv/)

```bash
# 后端
make install
make all                   # format + lint + typecheck + test

# 前端（另开终端）
make dev-frontend          # Vite 开发服务器 :5173
make build-frontend        # 生产构建 → src/octop/dashboard/
```

单独执行：`make test`、`make lint`、`make typecheck`、`make format`。

## 🔒 安全与隐私

- **本地优先**：配置、对话、工作区与凭据都在 `~/.octop/`，不上传第三方。
- **本机边界**：默认只监听 `127.0.0.1`；需要局域网访问时显式改 `--host`。
- **工具护栏**：高风险工具与 Shell 命令按 `~/.octop/security/tool_guard/` 规则审批。
- **敏感信息脱敏**：离开工作区前对敏感数据做遮盖。
- **无厂商锁定**：模型供应商、存储后端与 IM 通道都可替换。

## ❓ 常见问题

**打不开 http://127.0.0.1:8088？**
确认 `octop run` 仍在运行且终端没有报错；改过端口就用实际端口访问。

**需要登录吗？**
不需要。单人模式没有登录页与账号体系，启动后直接以本机使用者身份进入。

**怎么让局域网里的其他设备访问？**
`octop run --host 0.0.0.0 --port 8088`，或设置 `OCTOP_BIND_HOST=0.0.0.0`。注意这会把控制台暴露给局域网，请自行确认网络环境。

**模型测试连接失败？**
检查 API Key、Base URL、网络连通性与账户配额；本地模型确认 Ollama 已在运行。

**数据在哪里？怎么迁移到新机器？**
全部在 `~/.octop/`。用 `octop backup create --include-chats -o <路径>` 生成归档，把归档拷到新机器后执行 `octop backup restore <归档> --yes`。完整步骤与回退方式见 [docs/migration-and-restore.md](docs/migration-and-restore.md)。

**忘记端口或被别的程序占用？**
换端口启动：`octop run --port 8090`；或修改 `~/.octop/config.json` 的 `port`。

更多问题与排障见 [docs/user-guide.md](docs/user-guide.md)。

## 🤝 参与贡献

1. Fork 本仓库
2. 创建功能分支（`git checkout -b feature/amazing-feature`）
3. 提交前运行 `make all`
4. 发起 Pull Request

完整指南见 [CONTRIBUTING.md](CONTRIBUTING.md)，安全问题见 [SECURITY.md](SECURITY.md)，模块边界见 [AGENTS.md](AGENTS.md)。

## 📋 更新日志

详见 [CHANGELOG.md](CHANGELOG.md)。

## 📄 许可证

本项目采用 [MIT License](LICENSE)。
