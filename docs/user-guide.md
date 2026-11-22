# HappyClaw 用户帮助文档

> 本机单人使用。装好、启动、打开浏览器即可，不需要注册、登录，也没有账号与权限配置。
> 所有运行时数据默认存放在 `~/.happyclaw/`（可通过 `HAPPYCLAW_HOME` 覆盖）。

---

## 目录

- [一、简介](#一简介)
- [二、安装](#二安装)
- [三、首次启动](#三首次启动)
- [四、配置模型](#四配置模型)
- [五、基本使用](#五基本使用)
- [六、数据目录与备份恢复](#六数据目录与备份恢复)
- [七、日志与卸载](#七日志与卸载)
- [八、常见问题](#八常见问题)

---

## 一、简介

**HappyClaw** 是一个装在自己电脑上的单人 AI 工作台。一个服务进程（`octop run`）同时提供 Web 控制台、IM 通道和定时任务；命令行 `octop` 是另一个进程，读写同一个 `~/.happyclaw` 数据库。所有数据都保存在本机。

![图 1.1 — HappyClaw 品牌图](assets/overview.png)

核心特性速览：

- 💬 本机对话，无需账号；启动后直接进入控制台。
- 🎭 多个专家，每个专家独立配置模型、工作区、技能与定时任务；内置 16 种 MBTI 人格模板。
- 🔌 Connector（OAuth + MCP）与专家库拓展能力边界。
- 🧠 可迁移记忆，随工作区一起保存。
- 🖥️ 远程桌面、浏览器 AI+、终端 AI+ 等富交互能力。

---

## 二、安装

### 2.1 环境要求

- 操作系统：**macOS / Linux / Windows**（Windows 10/11 64 位）。
- **无需**预先安装 Python —— 安装脚本会通过 [uv](https://docs.astral.sh/uv/) 在 `~/.happyclaw/` 下自动创建隔离的 Python 3.12 虚拟环境。
- 需要可访问外网，用于下载安装包与依赖。
- 磁盘：`~/.happyclaw/` 下会放独立 Python 3.12 环境、wheel 依赖、数据库、专家工作区与备份，建议预留数 GB；本地模型与知识库语料另计。
- 内存：没有硬性下限，实际占用取决于所选模型；在本机跑 Ollama 大模型时按模型规模另算。

### 2.2 一键脚本安装（推荐）

**Windows（PowerShell）**

```powershell
if (-not $env:HAPPYCLAW_INSTALL_BASE) { $env:HAPPYCLAW_INSTALL_BASE = 'https://raw.githubusercontent.com/xkx121029/HappyClaw/main' }; irm "$env:HAPPYCLAW_INSTALL_BASE/scripts/install.ps1" | iex
```

**macOS / Linux**

```bash
curl -fsSL "${HAPPYCLAW_INSTALL_BASE:-https://raw.githubusercontent.com/xkx121029/HappyClaw/main}/scripts/install.sh" | bash
```

安装脚本会在 `~/.happyclaw/venv` 创建隔离环境，**不会改动系统 Python**。

- macOS / Linux：安装器会把 `octop` 软链到一个已经在 PATH 里的目录（优先 `/usr/local/bin`），当前终端即可直接使用；若那个目录不可写，脚本会提示你手动补一行。
- Windows：安装器把 `~/.happyclaw/bin` 写进用户级 `Path`（`HKCU:\Environment`），同时更新当前窗口的 PATH；**新开的终端**才会从注册表读到你之前的其它 PATH 变更。

> **可选附加组件**：浏览器自动化需要 Chromium，可加 `--extras browser`；国内网络可用 `--mirror <url>` 指定 PyPI 镜像。更多选项见 [scripts/README.md](../scripts/README.md)。

### 2.3 验证安装

```bash
octop --version
octop run --help
```

若提示找不到 `octop` 命令，重开一个终端，或检查 `~/.happyclaw/bin` 是否在 PATH 里。

### 2.4 Docker 安装

```bash
# 构建并后台启动
docker compose -f docker/docker-compose.yml up -d --build
```

打开 `http://localhost:8088`。单人模式无需预置管理员密码，容器首次启动会初始化数据库并绑定本机使用者。完整说明见 [docker/README_CN.md](../docker/README_CN.md)。

---

## 三、首次启动

### 3.1 启动服务

```bash
octop run       # 前台启动 API + Web 控制台
```

首次启动会自动创建运行目录、SQLite 数据库和本机使用者，无需手动初始化，也不会要求输入密码。

若希望服务在后台常驻：

```bash
octop service start   # Linux(systemd) / macOS(launchd)
```

启动后打开 **http://127.0.0.1:8088**，直接进入工作台。

### 3.2 自定义监听地址与端口

```bash
octop run --host 0.0.0.0 --port 8090
```

等价的环境变量是 `HAPPYCLAW_BIND_HOST` 与 `HAPPYCLAW_PORT`。默认只监听 `127.0.0.1`；改成 `0.0.0.0` 会把控制台暴露给局域网，请自行确认网络环境。

### 3.3 验证跑通

1. 终端中没有报错，且能看到监听地址。
2. 浏览器打开 `http://127.0.0.1:8088` 能进入对话页。
3. 执行一次健康检查：

```bash
curl http://127.0.0.1:8088/api/health
```

返回 `{"ok":true,...}` 即表示服务与数据库均正常。

---

## 四、配置模型

HappyClaw 通过**供应商（Provider）**接入大模型。每个专家可使用不同的供应商与模型，支持 OpenAI 兼容 API、Anthropic、AWS Bedrock、DashScope（通义千问）、Ollama 本地模型等。

### 4.1 在控制台配置

打开 **管理 → 模型配置**（`/admin/models`）：

1. 选择预设供应商（OpenAI、Anthropic、DeepSeek、智谱、Kimi、Ollama 等），或选择「自定义」。
2. 填写 **Base URL** 与 **API Key**。
3. 勾选要启用的模型。
4. 点击 **测试连接**，通过后保存。

自定义供应商的 `kind` 可选 `openai`（OpenAI 兼容）、`anthropic`、`bedrock`。

![图 4.1 — 自定义供应商与模型选择](assets/model-01-custom.png)

### 4.2 测试连接失败怎么办

依次检查：

- API Key 是否正确、是否过期。
- Base URL 是否包含正确的路径（如 `https://api.openai.com/v1`）。
- 本机网络是否能访问该服务。
- 账户是否有余额或配额。

### 4.3 本地模型 Ollama

若本机已运行 Ollama，选择 `ollama` 预设即可，无需 API Key。模型存放在非默认目录时，在供应商设置里填写**模型下载目录**，HappyClaw 会按该路径识别模型，并在启动本地 Ollama 服务时设置 `OLLAMA_MODELS`。

### 4.4 图片与视频生成

在 **管理 → 模型配置** 页的「生成模型」分区里配置火山方舟 Seedream / Seedance：

1. 在[火山方舟控制台](https://console.volcengine.com/ark)开通所需模型。
2. 创建方舟 API Key。
3. 启用媒体生成，填写图片、视频模型 ID。
4. 验证凭证并按需测试模型，保存后会加密存储 API Key。

> 模型测试会提交真实生成请求，可能产生少量费用。

### 4.5 通过 CLI 配置

```bash
octop models presets       # 列出内置供应商模板
octop models config        # 交互式从模板建供应商并设为当前模型
octop provider list        # 列出已配置供应商
octop provider test <id>   # 用一次单 token 请求探测供应商
```

CLI 只能新增、删除、探测供应商，没有 `provider edit`：改已有的供应商用控制台 **管理 → 模型配置**。

---

## 五、基本使用

### 5.1 对话（Chat）

- 打开 **对话**（`/chat`）页面，选择当前专家即可开始实时聊天。
- 支持多轮对话、附件上传、工具调用展示。
- 可在对话中通过斜杠命令触发特定能力。

![图 5.1 — 对话主界面](assets/use-02-chat.png)

### 5.2 创建专家（专家库 / MBTI 人格）

- 进入 **专家**（`/experts`）页面，从专家库选择模板一键创建，也可以新建空白专家。
- 选择 **MBTI 人格** 模板为专家赋予性格，或做人格测试自动生成。
- 为该专家指定供应商、模型与工作区后端。

![图 5.2 — 专家库](assets/use-03-agent.png)

### 5.3 连接器（Connectors）

- 进入 **设置 → 连接器**（`/connectors`），配置 OAuth 应用与 MCP 网关。
- 内置 30 个预设连接器，覆盖腾讯文档、Notion、新闻等；也可以添加自定义 MCP。完整列表见 [内置连接器](connectors.md)。

### 5.4 通道（Channels / IM）

- 进入 **设置 → 通道**（`/personalization/channels`），安装并配置 IM 平台。
- 内置 10 种通道。飞书、钉钉、QQ、微信、元宝可以在面板里扫码创建/绑定，凭据自动写入；企业微信、Telegram、Discord、小艺、MQTT 需要手填凭据。

| 通道 | 绑定方式 | 需要的凭据 |
|------|----------|------------|
| 飞书 | 扫码创建（也可手填） | App ID、App Secret |
| 钉钉 | 扫码授权，自动建应用 | Client ID、Client Secret |
| QQ | 扫码绑定机器人 | App ID、密钥（扫码后自动填入） |
| 微信 | 扫码登录个人号 | 机器人 UIN、Token |
| 企业微信 | 开放平台创建应用后手填 | 企业凭据（Corp ID、Agent Secret） |
| 元宝 | 扫码绑定 | App Key、App Secret |
| Telegram | Bot API，手填 | Bot Token |
| Discord | 机器人，手填 | Bot Token、允许的频道/用户 ID |
| 小艺 | A2A 协议，手填 | Access Key、Secret Key、Agent ID |
| MQTT | Broker，手填 | 主机、端口、用户名/密码、订阅/发布主题 |
| Web 控制台 | 默认启用 | 无 |

![图 5.3 — 通道配置](assets/use-04-channels.png)

### 5.5 自动化（定时任务）

- 进入 **自动化**（`/tasks`）页面，可视化创建任务。
- 支持自然语言或 Cron 表达式，让专家按时推送或执行任务。

![图 5.4 — 定时任务管理](assets/use-05-cron.png)

### 5.6 ACP（与 IDE / 编码 Agent 协作）

1. **入站** —— 让外部工具（Zed、OpenCode 等）使用你的 HappyClaw 专家：

   ```bash
   octop acp --agent main
   ```

2. **出站** —— 在对话中把编码任务委派给外部 Agent（内置 7 个 Runner：OpenCode、CodeBuddy、Claude Code、Codex、Kimi Code、Cursor CLI、pi）：
   - 控制台 → **ACP 协作**（`/acp`）：配置 Runner。
   - 为专家启用 `acp_runner`，然后在对话中委派。

完整配置见 [docs/acp.md](acp.md)。

### 5.7 设置

侧边栏分三组，界面里没有单独的「系统」页：

- **设置** 组：
  - **个性化**（`/personalization`）— 子页含技能、工具、插件、子智能体、人格（MBTI）、记忆。
  - **通道**、**连接器**、**技能包**、**知识库**、**云端协同**（Bridge）。
- **控制** 组：**工作台**、**远程桌面**、**ACP 协作**。
- **管理** 组：
  - **模型配置**（`/admin/models`）— 供应商、模型、生成模型。
  - **存储管理**（`/admin/backend`）— 工作区后端（本地 / 对象存储）。
  - **插件管理**（`/admin/plugins`）、**安全防护**（`/admin/security`）— 工具审批、Shell 命令护栏（`~/.happyclaw/security/tool_guard/`）、PII 与凭据策略。
  - **应用设置**（`/admin/advanced`）— 环境变量、可观测、**备份与恢复**、HTTPS、应用更新五个标签页。

监听地址与端口没有面板开关：它们来自 `octop run --host/--port`、`HAPPYCLAW_BIND_HOST`/`HAPPYCLAW_PORT` 或 `config.json`；时区是 `config.json` 的 `default_timezone`。详见 [docs/configuration.md](configuration.md)。

![图 5.5 — 设置页面](assets/use-06-settings.png)

### 5.8 工作台与远程桌面

**控制** 组下是两个独立入口，不是一个页面里的开关：

- **工作台**（`/workbench`）—— 三个标签页：**终端**（`/workbench/terminal`）、**浏览器**（`/workbench/browser`）、**云端**（`/workbench/cloud`）。浏览器标签页是基于 Chromium 的会话，支持网页自动化、截图与远程浏览。
- **远程桌面**（`/remote-desktop`）—— 浏览器里看这台机器的屏幕并控制键鼠，另有手机端入口（`/remote-desktop/phone`）。

![图 5.6 — 远程桌面](assets/use-07-remote-desktop.png)

### 5.9 单人使用技巧

**找东西：两个搜索入口**

- `Ctrl/Cmd + K`（或 `Ctrl/Cmd + Shift + M`）打开命令面板，一个输入框同时搜**会话**、**模型**和**本机动作**（新建会话、导出当前会话、打开本机设置、专家页、连接器、记忆库、备份与恢复、快捷键说明）。会话多的时候先用它跳转，比翻列表快。
- 在会话里按 `Ctrl/Cmd + F` 搜**当前会话的消息**（要在这一步的弹层里输入，输入框不在侧边栏）。

**导出一次会话**

打开会话后，点聊天区右侧的「运行轨迹」浮动按钮，抽屉右上角有「导出」，会下载 `trajectory-<thread_id>.jsonl`。一行一个事件，包含输入、模型回复、工具调用和耗时，适合排查「这轮到底做了什么」，不是给人阅读的 Markdown 存档。要连聊天历史一起搬走，用下面的备份命令加 `--include-chats`。

**备份与恢复**

命令行最直接：

```bash
octop backup create --include-chats -o D:\backup\happyclaw-full.tar.gz   # 全量留档
octop backup restore D:\backup\happyclaw-full.tar.gz --yes               # 停服务后恢复
octop backup auto status                                                 # 看自动备份是否开启
```

图形界面在 **管理 → 应用设置 → 备份与恢复**：可以创建备份、上传归档导入、从列表恢复，也能看到自动备份计划和保留份数。恢复会替换数据库，操作前先 `Ctrl+C` 停掉 `octop run`；细节与失败回退见 [单机迁移与恢复](migration-and-restore.md)。

**快捷键（mod = macOS 的 ⌘，其他平台 Ctrl）**

| 快捷键 | 作用 |
|--------|------|
| `mod + K` | 命令面板（搜索会话 / 模型 / 动作） |
| `mod + Shift + O` | 新建会话 |
| `mod + Shift + M` | 命令面板（与 `mod + K` 同一入口） |
| `mod + F` | 搜索当前会话的消息（会话为空时不接管） |
| `mod + /` | 快捷键说明弹层 |
| `mod + ,` | 打开本机设置 |
| `mod + B` | 收起 / 展开最左侧导航栏 |
| `mod + Shift + B` | 收起 / 展开会话历史栏 |
| `Esc` | 关闭当前弹层 / 退出消息搜索 |

这些键在聊天输入框里同样有效；只有富文本编辑器会自己接管 `mod + B`（加粗），此时侧栏不响应。

**三条省事习惯**

1. 自动备份默认关闭，建议在设置里打开，再每隔一段时间手动 `octop backup create --include-chats` 留一份可搬走的全量包。
2. 长期项目单独建专家，会话按项目分开，搜索和备份时都更容易定位。
3. 常用操作记住 `mod + K` 一个入口就够，不用背全部快捷键。

---

## 六、数据目录与备份恢复

### 6.1 数据目录

```
~/.happyclaw/
├── config.json              # 进程配置（地址、端口、TLS、database …）
├── env                      # 可选环境变量（API Key 等）
├── octop.db                 # 默认 SQLite 控制面（专家、通道、定时任务 …）
├── cli_state.json           # CLI 固定项（default_user / default_agent）
├── secrets/                 # 加密凭据（cloud/、cloud.key：工作台的腾讯云登录）
├── agents/<agent_id>/       # 各专家工作区（SOUL.md、skills …）
├── plugins/                 # 已安装插件（含内置插件）
├── skill-packages/          # 全局技能包（SQLite 后端下的文件）
├── knowledge/               # 知识库原始文件（SQLite 后端下的文件）
├── security/tool_guard/     # Shell 命令允许 / 拒绝规则
├── ssl/                     # octop run --ssl 自签证书
├── logs/                    # 运行日志
├── backups/                 # octop backup create 的归档
├── venv/                    # 安装脚本创建的 Python 环境
└── bin/octop                # 命令入口
```

用 `HAPPYCLAW_HOME` 可以把整个数据目录改到其他磁盘。

### 6.2 备份

```bash
octop backup create                                # 生成归档（数据库 + 工作区 + 配置）
octop backup create --include-chats                # 连聊天历史一起打包
octop backup create -o ~/backup/happyclaw.tar.gz   # 指定输出位置
octop backup auto status                           # 查看自动备份配置
octop backup auto run                              # 立即执行一次自动备份
```

默认输出到 `~/.happyclaw/backups/`，文件名形如 `octop-backup-20261111T120000Z.tar.gz`（UTC）。归档包含数据库、`config.json`、`env`、专家工作区、技能包、插件与知识库；`secrets/`、`security/`、`ssl/`、`logs/` 不进归档，需要时手工复制。默认不含聊天历史，完整迁移加 `--include-chats`。

自动备份默认**关闭**（`backup.auto_enabled: false`），开启后在 `octop run` 进程内按 `backup.schedule` 执行，默认每天 04:00，默认保留 7 份。自动归档以 `octop-auto-backup-` 开头，保留策略不会删除手动备份。用 `octop backup auto status` 查看当前值。

### 6.3 恢复

```bash
octop backup create -o ~/backup/before-restore.tar.gz   # 恢复前先留一份现场
octop backup restore <归档文件>                          # 会先要求确认
octop backup restore <归档文件> --yes                    # 跳过确认
```

恢复前必须停止正在运行的服务（前台 Ctrl+C，或 `octop service stop`）。恢复会替换数据库；归档里没有聊天历史时，当前聊天记录会先保存再写回。SQLite 与 PostgreSQL 的备份不能跨引擎互恢；归档 schema 版本高于当前程序时会被拒绝，需要先升级 HappyClaw。PostgreSQL 的备份与恢复还要求 `pg_dump` / `pg_restore` 在 PATH 中。

逐步命令与失败回退见 [单机迁移与恢复](migration-and-restore.md)。

### 6.4 迁移到新机器

完整步骤（含换目录、PostgreSQL、失败回退）见 [单机迁移与恢复](migration-and-restore.md)。最短路径：

1. 旧机器 `octop backup create --include-chats -o D:\backup\happyclaw-full.tar.gz`。
2. 把归档文件拷贝到新机器。
3. 新机器安装 HappyClaw，停止服务，执行 `octop backup restore D:\backup\happyclaw-full.tar.gz --yes`。
4. 启动 `octop run`，检查专家、通道与模型配置是否完整。

---

## 七、日志与卸载

### 7.1 日志位置

- 前台运行：直接输出到终端，同时写入 `~/.happyclaw/logs/octop.log`。
- 系统服务：日志同样在 `~/.happyclaw/logs/`，按日期轮转为 `octop.YYYY-MM-DD.log`。
- Linux 可查看 journal：`journalctl --user -u octop -f`。

### 7.2 停止服务

```bash
# 前台运行时按 Ctrl+C
octop service stop      # 已注册为系统服务时
```

### 7.3 卸载

1. 先备份需要保留的数据：`octop backup create`。
2. 停止服务并删除系统服务注册：`octop service stop`。
3. 删除安装与数据目录：
   - Windows：删除 `%USERPROFILE%\.octop`
   - macOS / Linux：`rm -rf ~/.happyclaw`
4. 从 PATH 中移除 `~/.happyclaw/bin`（安装脚本添加的那一行）。

> 删除 `~/.happyclaw` 会连同数据库、专家工作区、密钥与备份一起删除。确认归档已另行保存后再执行。

---

## 八、常见问题

**Q：访问 http://127.0.0.1:8088 打不开？**
- 确认 `octop run` 仍在运行且终端无报错。
- 若改过端口，请访问对应地址。
- 已注册系统服务时，用 `octop service status` 查看状态。

**Q：需要登录吗？忘记密码怎么办？**
- 不需要登录，也没有密码。启动后直接以本机使用者身份进入控制台。

**Q：模型测试连接失败？**
- 检查 API Key、Base URL、网络连通性与账户配额。

**Q：如何修改监听地址让局域网访问？**
- `octop run --host 0.0.0.0 --port 8088`，或设置 `HAPPYCLAW_BIND_HOST=0.0.0.0`、`HAPPYCLAW_PORT=8088`。

**Q：局域网访问不了插件市场和专家市场？**
- HappyClaw 不内置任何远程目录：没设 `HAPPYCLAW_PORTAL_ORIGIN` 时这两页不会发出请求，只显示「暂时不可用」。内网自建（或指向你自己的公网目录）见 [内网自建市场](private-market.md)。

**Q：局域网访问不了技能市场？**
- 技能页默认请求 `https://api.skillhub.cn`。按同一接口自建并设置 `SKILL_MARKET_ORIGIN`，见 [技能市场](skill-market.md)。

**Q：如何升级？**
- `octop update`；升级前先 `octop backup create`。数据库结构会在下次启动时自动迁移。

**Q：数据目录丢了，或者要换一台机器怎么办？**
- 数据目录就是 `~/.happyclaw/`（Windows 下是 `C:\Users\你的用户名\.octop\`），配置、会话数据库、专家工作区、密钥和备份都放在这里。
- 如果这个目录被删除或清空，下次启动不会报错，程序会自动建出一套全新的空目录。看起来能正常打开，但原来的会话、专家和配置都不在了。
- 空目录里没有历史数据可以恢复。想找回内容，只能依靠之前做过的备份：`~/.happyclaw/backups/` 里的归档，或你另存到其他磁盘的备份包。
- 正确做法是先停掉服务，不要在残缺目录里继续操作；确认最近一次备份的位置，再按 [单机迁移与恢复](migration-and-restore.md) 恢复。换机器时，整目录拷贝或先执行 `octop backup create --include-chats`，到新机器再恢复。
- 之后建议打开自动备份，并把重要备份另存到别的磁盘。

**Q：数据会传到云端吗？**
- 不会。配置、对话、工作区与凭据都在 `~/.happyclaw/`；只有你主动配置的模型供应商与 Connector 会收到相应请求。

---

## 九、插图清单

| 编号 | 位置 | 文件名 | 内容说明 |
|------|------|--------|----------|
| 图 1.1 | 一、简介 | `overview.png` | HappyClaw 品牌图（与 `octop-banner.png` 同一张图） |
| 图 4.1 | 四、配置模型 | `model-01-custom.png` | 自定义供应商弹窗 |
| 图 5.1 | 5.1 对话 | `use-02-chat.png` | 对话主界面 |
| 图 5.2 | 5.2 专家 | `use-03-agent.png` | 专家库模板列表 |
| 图 5.3 | 5.4 通道 | `use-04-channels.png` | IM 通道开关列表 |
| 图 5.4 | 5.5 Cron | `use-05-cron.png` | 创建定时任务弹窗 |
| 图 5.5 | 5.7 设置 | `use-06-settings.png` | 应用设置页面 |
| 图 5.6 | 5.8 远程桌面 | `use-07-remote-desktop.png` | 远程桌面连接页 |

> 登录页、设置向导创建管理员等截图已不再适用于单人模式，未在本文引用。
