<p align="center">
  <img src="docs/assets/readme-banner-zh.png" alt="HappyClaw Banner" width="600" />
</p>

<p align="center">
  <strong>装在自己电脑上的单人 AI 工作台 — 一个进程，一个你。</strong>
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img alt="Python 3.12+" src="https://img.shields.io/badge/python-3.12%2B-blue?logo=python&logoColor=white" /></a>
  <a href="https://github.com/xkx121029/HappyClaw/blob/main/LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-green" /></a>
  <img alt="Version 1.0.3b5" src="https://img.shields.io/badge/version-1.0.3b5-orange" />
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

**HappyClaw** 是给个人用的本地 AI 工作台。没有账号体系，没有登录页，也不需要配置成员与权限：装好、启动、打开浏览器，就是以本机使用者的身份在工作。

服务端是一个进程，Web 控制台、IM 通道与定时任务都在它里面；CLI 连的是同一个控制面数据库。所有数据都留在 `~/.octop/`。你可以创建多个专家，每个专家有自己的模型、工作区、技能与定时任务，日常可以在网页里对话，也可以把飞书、钉钉、企业微信、微信、QQ、元宝、小艺、MQTT、Telegram、Discord 接进来。

> 产品叫 HappyClaw，但 Python 分发名、`octop` 命令、`~/.octop/` 数据根目录和 `OCTOP_*` 环境变量沿用原来的命名。两个名字说的是同一个东西。

## 🚀 快速开始

> 完整 Windows 步骤见 [docs/quickstart.md](docs/quickstart.md)，5 分钟内可以跑通。

**Windows（PowerShell）**

```powershell
if (-not $env:OCTOP_INSTALL_BASE) { $env:OCTOP_INSTALL_BASE = 'https://raw.githubusercontent.com/xkx121029/HappyClaw/main' }; irm "$env:OCTOP_INSTALL_BASE/scripts/install.ps1" | iex
```

**macOS / Linux**

```bash
curl -fsSL "${OCTOP_INSTALL_BASE:-https://raw.githubusercontent.com/xkx121029/HappyClaw/main}/scripts/install.sh" | bash
```

> 两条一键命令都读 `OCTOP_INSTALL_BASE`，默认取本仓库 GitHub `main` 分支。若你的网络访问 GitHub 受限，把该变量指向提供同样 `scripts/` 目录的自建镜像，再重跑一键命令。

安装完成后打开一个新终端，启动服务：

```bash
octop run
```

然后访问 **http://127.0.0.1:8088**。首次启动会自动创建本机使用者与数据库，不需要注册，也不会要求设置密码；直接进入控制台，在「管理 → 模型管理」里加一个模型就能开始对话。

## 🧭 能做什么

| | 能力 | 说明 |
|---|------|------|
| 💬 | **本机对话** | Web 控制台实时对话，支持附件与工具调用过程展示 |
| 🎭 | **多专家** | 每个专家独立的工作区、模型、技能与定时任务；内置 3 个专家模板与 16 种 MBTI 人格模板 |
| ⏰ | **自动化任务** | 自然语言或 Cron 表达式触发的定时任务，按专家隔离 |
| 🎯 | **Agent Teams**（Beta） | 协调者调度多位专家完成多步骤任务，[说明](docs/expert-teams.md) |
| 🔌 | **Connector** | 30 个接入预设：腾讯文档、腾讯会议、Notion、滴答清单、Obsidian、有道云笔记、飞书 / 企业微信 / 钉钉 CLI 等，走 OAuth、API Key 或 MCP，[目录](docs/connectors.md) |
| 📚 | **知识库** | 对本地文档做 RAG 检索，回答锚定自己的资料 |
| 🧩 | **插件与技能** | 安装第三方插件，按专家启用技能 |
| ↔️ | **ACP 双向集成** | `octop acp` 给 Zed 等 IDE 当 ACP 服务端；`acp_runner` 工具把任务委派给 OpenCode、CodeBuddy、Claude Code、Codex、Kimi Code、Cursor CLI 或 `pi` |
| 💻 | **终端 AI+** | 浏览器内的交互式 Shell，Agent 就在旁边 |
| 🌐 | **浏览器 AI+** | 基于 Chromium 的会话，支持网页自动化、截图与远程浏览 |
| 🖥️ | **远程桌面** | 控制台内看屏与键鼠操作，跨 Linux / Windows / macOS |
| 🌉 | **Bridge** | 把本机与另一台 HappyClaw 配对，互相交派任务 |
| 🏠 | **完全本地** | 配置、对话、工作区与凭据都在 `~/.octop/` |

## 🧠 技术栈

| 层级 | 技术 |
|------|------|
| 语言 | Python 3.12+ |
| Web 框架 | FastAPI + uvicorn |
| Agent 运行时 | `octop-harness`（以 `[all]` 附加项安装） |
| 记忆与检索 | `octop-memory` |
| IM 桥接 | `octop-gateway` |
| 浏览器宿主 | `octop-browser` + Playwright |
| 控制面数据库 | SQLite（WAL，默认）或 PostgreSQL（可选） |
| 前端 | React 18 + TypeScript + Vite + Ant Design |
| 调度 | APScheduler |
| ACP | stdio JSON-RPC：入站 `octop acp` 服务端 + 出站 `acp_runner` 工具 |
| 构建 / 质量 | hatchling · ruff · mypy · pytest |

Web UI、IM 通道与定时任务都在同一个 `OctopServer` 进程里，不依赖外部消息队列或中间件。状态存在控制面数据库，重启后重建。

## 📦 安装

| 方式 | 平台 | 命令 |
|------|------|------|
| 一键脚本 | macOS / Linux | `curl -fsSL https://raw.githubusercontent.com/xkx121029/HappyClaw/main/scripts/install.sh \| bash` |
| 一键脚本 | Windows | `irm https://raw.githubusercontent.com/xkx121029/HappyClaw/main/scripts/install.ps1 \| iex` |
| 仓库内脚本 | macOS / Linux | `bash scripts/install.sh` |
| 仓库内脚本 | Windows | `powershell -ExecutionPolicy Bypass -File scripts/install.ps1` |
| PyPI | 全平台 | `pip install octop` |
| Docker | 全平台 | `docker compose -f docker/docker-compose.yml up -d --build` |

安装脚本把运行环境放在 `~/.octop/venv`，命令入口放在 `~/.octop/bin/octop`，不改动系统 Python。macOS 与 Linux 上还会把 `octop` 链接进一个已在 `PATH` 里的目录，当前终端即可使用；Windows 上会把 `%USERPROFILE%\.octop\bin` 写入用户 `PATH`，新开的终端生效。

`pip install octop` 装的是 PyPI 上最新的**稳定版**。本仓库当前处在 beta 线，要装 `1.0.3b*` 预发布版本请用 `pip install --pre octop`。

可选组件：

```bash
# 浏览器自动化需要 Playwright Chromium（系统已有 Chrome/Chromium 时会跳过）
bash scripts/install.sh --extras browser

# 知识库的本地 ONNX / fastembed 向量模型，或 OCR
bash scripts/install.sh --extras local-embedding
bash scripts/install.sh --extras knowledge-ocr
```

安装选项：`--version`、`--from-source`、`--from-pypi`、`--extras`，以及仅 Unix 脚本提供的 `--mirror`（Windows 对应 `-Version`、`-FromSource`、`-SourceDir`、`-Extras`、`-UvPath`），详见 [scripts/README.md](scripts/README.md)。

### Docker

```bash
docker compose -f docker/docker-compose.yml up -d --build
# 打开 http://localhost:8088
```

容器首次启动会执行 `octop init` 并拉起服务，数据放在 `/data/.octop`（Compose 把 `${OCTOP_DATA:-~/.octop}` 挂到这里）。单人模式不需要预置管理员密码。完整说明见 [docker/README_CN.md](docker/README_CN.md)。

同目录下还有 `docker-compose.postgres.yml`（PostgreSQL + pgvector）与 `docker-compose.cn.yml`（直接拉取已发布镜像，不在本地构建）。

### 升级

```bash
octop update --check    # 只看有没有新版本
octop update            # 安装
```

`octop update` 只替换程序本体，`~/.octop/` 下的数据库、工作区、密钥与 `config.json` 都会保留，数据库结构在下次启动时自动迁移。升级前建议先备份：

```bash
octop backup create
```

## ⚙️ 配置模型

模型按专家配置，也可以在「管理 → 模型管理」里一次配好供所有专家共用。

```bash
octop models                       # 查看预设与模型解析结果
octop models active                # 某个专家当前解析到的模型
octop provider list                # 列出已配置供应商
octop provider create              # 新增；另有 delete、test
```

内置预设覆盖 OpenAI 与 OpenAI 兼容端点、Anthropic、Google Gemini、AWS Bedrock、DashScope（通义千问）、DeepSeek、Groq、OpenRouter、SiliconFlow、智谱，以及本地 Ollama。新增供应商时填 Base URL 与 API Key，勾选要启用的模型，点「测试连接」（命令行 `octop provider test`）通过后再保存。Ollama 连本机守护进程，不需要 API Key，可用 `octop models ollama-pull <模型>` 拉权重。

### 常用命令

```bash
octop agent list                 # 专家列表
octop agent create               # 新建专家
octop agent experts              # 内置专家模板
octop channel list               # IM 通道
octop skills list --agent main   # 某个专家的技能
octop cron list                  # 定时任务
```

环境变量与 `config.json` 的完整字段见 [docs/configuration.md](docs/configuration.md)。

## 📁 数据目录与备份

```
~/.octop/                          ← 安装与数据根目录
├── config.json                    # 进程配置（端口、TLS、数据库等）
├── env                            # 可选环境变量（API Key 等）
├── octop.db                       # SQLite 控制面（PostgreSQL 部署下为设置表）
├── secrets/                       # 腾讯云授权缓存（cloud/、cloud.key）
├── agents/<agent_id>/             # 各专家工作区（SOUL.md、skills、记忆 …）
├── plugins/                       # 内置与已安装插件
├── knowledge/                     # 全局知识库文件
├── security/tool_guard/           # Shell 命令允许/拒绝规则
├── ssl/                           # TLS 证书与 ACME 账号密钥
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

自动备份默认**关闭**（`backup.auto_enabled`）。开启后在 `octop run` 进程内按 `backup.schedule` 指定的 Cron 执行，默认每天 04:00，保留 7 份（`backup.retention_count`）；只清理 `octop-auto-backup-*` 旧归档，不会删除手动备份。

`octop backup create` 支持 `-o/--output` 指定归档路径、`--include-chats` 带上对话历史（默认不含），以及 `--no-config`、`--no-workspaces`、`--no-skill-packages`、`--no-plugins`、`--no-knowledge` 排除对应内容。SQLite 与 PostgreSQL 的归档不能跨引擎互恢，恢复前请确认运行中的引擎与归档一致。

换机、回退的逐步命令见 [docs/migration-and-restore.md](docs/migration-and-restore.md)。

## 📖 CLI 速查

| 命令 | 说明 |
|------|------|
| `octop run` | 前台启动服务（`--host`、`--port`、`--ssl`、`--workers`） |
| `octop init` | 重新初始化 `~/.octop/` 并执行迁移；`--force` 会清空应用数据。正常安装不需要，首次 `octop run` 会自动完成 |
| `octop service` | 注册为系统服务并 start / stop / restart / status（Linux systemd、macOS launchd，**不支持 Windows**） |
| `octop agent` | 创建、列出、切换、启停、删除专家；`agent experts` 列出内置模板 |
| `octop chats` | 会话列表与历史、单条 `send`、交互式 `repl` |
| `octop channel` | IM 通道增删改查、`config`、`test`、`feishu-setup` |
| `octop cron` | 定时任务：`list`、`create`、`delete`、`run-now` |
| `octop models` | 供应商预设、模型解析、当前生效模型、Ollama 拉取 / 列表 / 删除 |
| `octop provider` | 供应商记录：`list`、`create`、`delete`、`test` |
| `octop skills` | 按专家启用、禁用、配置技能 |
| `octop plugin` | `list`、`install`、`uninstall`、`reload` |
| `octop memory` | 记忆维护：`list` 列出专家，`slim` 精简记忆文件 |
| `octop backup` | `create`、`restore`、`auto status`、`auto run` |
| `octop update` | 检查并安装更新（`--check`、`--yes`、`--allow-prerelease`） |
| `octop acp` | 为 IDE 提供 stdio ACP 服务 |
| `octop bridge` | 远端 Bridge 节点：`list`、`create`、`connect`、`probe` 等 |
| `octop migrate` | 把 OpenClaw 或 Hermes Agent 的配置导入成专家 |
| `octop clean` | 清理 CLI 状态；`--all` 清空 `~/.octop/` |
| `octop config` | 查看或固定 CLI 默认值（`config show`、`config set-user`） |
| `octop admin` | 管理操作：`overview`、`audit`、`rotate-jwt-secret`，用户 `list` / `create` / `delete` |
| `octop user` | 为兼容保留的用户记录：`list`、`create`、`passwd`、`role` 等 |
| `octop cloud` | 腾讯云凭据桥（`import-tccli`） |
| `octop captcha` | 清除登录验证码锁定（应急入口） |
| `octop version` | 打印当前版本 |
| `octop selfcheck` | 导入 Agent 栈并编译一个临时图（打包自检） |
| `octop completion` | Shell 补全：`show`、`install` |

完整参数见 [docs/cli.md](docs/cli.md)。

## 📚 文档索引

| 文档 | 内容 |
|------|------|
| [docs/quickstart.md](docs/quickstart.md) | Windows 优先的 5 分钟上手 |
| [docs/user-guide.md](docs/user-guide.md) | 安装、模型、专家、通道、定时任务、日志与常见问题 |
| [docs/migration-and-restore.md](docs/migration-and-restore.md) | 备份、换机器迁移、恢复失败回退 |
| [docs/configuration.md](docs/configuration.md) | 环境变量与 `config.json` 字段 |
| [docs/cli.md](docs/cli.md) | 全部 CLI 命令与参数 |
| [docs/api.md](docs/api.md) | HTTP API 参考 |
| [docs/architecture.md](docs/architecture.md) | 运行结构与模块边界 |
| [docs/connectors.md](docs/connectors.md) | OAuth / MCP Connector 目录 |
| [docs/acp.md](docs/acp.md) | ACP 双向集成与内置 Runner |
| [docs/personas.md](docs/personas.md) | 专家人格与 MBTI 模板 |
| [docs/RELEASE-CHECKLIST.md](docs/RELEASE-CHECKLIST.md) | 发布前检查清单 |

## 🖥️ Web 控制台

`octop run` 启动后访问 **http://127.0.0.1:8088**，直接进入对话界面。

| 侧边栏分组 | 页面 |
|------------|------|
| 顶部 | **对话**（会话与历史）、**专家**、**自动化**（定时任务）、**Token 统计** |
| 设置 | **个性化**（专家配置、MBTI 人格、通道）、**通道**、**连接器**、**技能包**、**知识库**、**Bridge** |
| 控制 | **工作台** — 终端 AI+、浏览器 AI+、云浏览器；**远程桌面**；**ACP**（出站编程 Agent Runner） |
| 管理 | **模型管理**、**存储管理**（数据库与对象存储）、**插件管理**、**安全管理**（工具审批、命令护栏、文件规则、PII 脱敏）、**应用设置**（TLS、监听地址、日志、备份、更新） |

交互式 API 文档默认关闭，在 `~/.octop/config.json` 里设置 `"enable_api_docs": true`（或 `OCTOP_ENABLE_API_DOCS=1`）后访问 `/api/docs`。

## 🏗️ 架构与项目结构

```
OctopServer                        launch.py → infra/server.py
 ├─ DatabasePool                    SQLite (WAL) 或 PostgreSQL
 ├─ SharedServices                 依赖注入根 — 所有 repo 与配置
 ├─ ExpertCatalog                  启动时扫描专家库
 ├─ OwnerIdentityService           本机使用者（启动时解析/创建）
 ├─ AgentManager                   为每个专家持有 HarnessAgent
 ├─ ChannelManager（octop-gateway） IM 连接
 └─ CronManager                    APScheduler
```

```
src/octop/
  config.py    环境变量配置
  launch.py    OctopServer 启动 + uvicorn
  infra/       业务核心（agents、gateway、cron、db …）
  api/         HTTP 层 — FastAPI 路由与 SSE
  cli/         CLI 层 — Click 命令
  dashboard/   构建后的 React SPA — wheel 产物，运行 make build-frontend 之前是空的

dashboard/     前端源码（Vite）— 在此编辑，运行 make build-frontend
docker/        Docker Compose、入口脚本、构建脚本
docs/          使用与架构文档
tests/         unit/、integration/、dsh_integration/、live/
```

详见 [docs/architecture.md](docs/architecture.md)。

## 🛠️ 开发

**前置条件：** Python 3.12+、Node 20 与 npm 10（前端 lockfile 是 npm 10，`mise.toml` 固定了工具链）、[uv](https://docs.astral.sh/uv/)。

```bash
# 后端
make install               # uv sync（无 uv 时回退 pip install -e ".[dev]"）
make all                   # format（后端+前端）+ lint + typecheck + test

# 前端（另开终端）
make dev                   # 同时起 Vite :5173 与 octop run
make dev-frontend          # 只起 Vite 开发服务器
make build-frontend        # 生产构建 → src/octop/dashboard/
```

单独执行：`make test`、`make test-fast`（跳过 `slow`）、`make test-live`、`make lint`、`make typecheck`、`make format`、`make check-all`；只跑前端用 `make lint-frontend`、`make typecheck-frontend`。pytest 标记在 `pyproject.toml` 中声明：`live`（真实 LLM 调用）、`slow`、`postgresql`（需要 `OCTOP_TEST_DATABASE_URL`）。

## 🔒 安全与隐私

- **本地优先**：配置、对话、工作区与凭据都在 `~/.octop/`。
- **本机边界**：默认只监听 `127.0.0.1`；要暴露到局域网必须显式改 `--host`。
- **安全策略**：工具审批（人工确认）、命令护栏、文件系统规则与 PII 脱敏按专家在「管理 → 安全管理」中配置；Shell 规则可直接编辑 `~/.octop/security/tool_guard/dangerous_shell_commands.yaml`。
- **密钥遮盖**：环境变量接口返回值经过遮盖，Agent 命令行输出进入控制台前也会脱敏。
- **无厂商锁定**：模型供应商、存储后端与 IM 通道都可替换。

## ❓ 常见问题

**打不开 http://127.0.0.1:8088？**
确认 `octop run` 仍在运行且终端没有报错；改过端口就用实际端口访问。

**需要登录吗？**
不需要。单人模式没有登录页与账号体系，启动后直接以本机使用者身份进入；访问 `/login`、`/invite` 会直接跳回对话页。

**要先跑 `octop init` 吗？**
不需要。首次 `octop run` 会创建 `~/.octop/`、数据库与本机使用者。`octop init` 用于重新初始化和执行迁移，`octop init --force` 会清空应用数据。

**怎么让局域网里的其他设备访问？**
`octop run --host 0.0.0.0 --port 8088`，或设置 `OCTOP_BIND_HOST=0.0.0.0`。注意命令行上的 `--host` / `--port` 会被写进 `config.json`，并且这等于把控制台暴露给局域网，请自行确认网络环境。

**模型测试连接失败？**
检查 API Key、Base URL、网络连通性与账户配额；本地模型确认 Ollama 已在运行。

**数据在哪里？怎么迁移到新机器？**
全部在 `~/.octop/`。用 `octop backup create --include-chats -o <路径>` 生成归档，把归档拷到新机器后执行 `octop backup restore <归档> --yes`。完整步骤与回退方式见 [docs/migration-and-restore.md](docs/migration-and-restore.md)。

**端口被别的程序占用？**
换端口启动：`octop run --port 8090`；或修改 `~/.octop/config.json` 的 `port`。

**为什么包名还是 `octop`？**
分发名、CLI 命令、数据目录与 `OCTOP_*` 变量都在 HappyClaw 这个名字之前就定了，为兼容保留。你安装的产品叫 HappyClaw，它以 `octop` 的名字发布。

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
