# HappyClaw 用户帮助文档

> 本机单人使用。装好、启动、打开浏览器即可，不需要注册、登录，也没有账号与权限配置。
> 所有运行时数据默认存放在 `~/.octop/`（可通过 `OCTOP_HOME` 覆盖）。

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

**HappyClaw** 是一个装在自己电脑上的单人 AI 工作台。它在单进程里同时提供 Web 控制台、CLI、IM 通道（飞书、钉钉、QQ、微信、企业微信等）和定时任务，所有数据都保存在本机。

![图 1.1 — HappyClaw 产品总览](assets/overview.png)

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
- **无需**预先安装 Python —— 安装脚本会通过 [uv](https://docs.astral.sh/uv/) 在 `~/.octop/` 下自动创建隔离的 Python 3.12 虚拟环境。
- 需要可访问外网，用于下载安装包与依赖。
- 建议预留 2 GB 以上内存；磁盘空间用于数据库、专家工作区与文档语料。

### 2.2 一键脚本安装（推荐）

**Windows（PowerShell）**

```powershell
irm https://download.octop.cloud/octop/scripts/install.ps1 | iex
```

**macOS / Linux**

```bash
curl -fsSL https://download.octop.cloud/octop/scripts/install.sh | bash
```

安装完成后，**打开一个新终端**或重新加载 shell 配置，使 PATH 生效：

```bash
source ~/.zshrc   # Zsh
# 或
source ~/.bashrc  # Bash
```

安装脚本会把 `octop` 命令放入 `~/.octop/bin` 并加入 PATH，并在 `~/.octop/venv` 创建隔离环境；**不会改动系统 Python**。

> **可选附加组件**：浏览器自动化需要 Chromium，可加 `--extras browser`；国内网络可用 `--mirror <url>` 指定 PyPI 镜像。更多选项见 [scripts/README.md](../scripts/README.md)。

### 2.3 验证安装

```bash
octop --version
octop run --help
```

若提示找不到 `octop` 命令，请确认已重新加载 shell，或检查 `~/.octop/bin` 是否在 PATH 中。

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

等价的环境变量是 `OCTOP_BIND_HOST` 与 `OCTOP_PORT`。默认只监听 `127.0.0.1`；改成 `0.0.0.0` 会把控制台暴露给局域网，请自行确认网络环境。

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

打开 **设置 → 模型**：

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

在 **设置 → 模型 → 生成模型** 中配置火山方舟 Seedream / Seedance：

1. 在[火山方舟控制台](https://console.volcengine.com/ark)开通所需模型。
2. 创建方舟 API Key。
3. 启用媒体生成，填写图片、视频模型 ID。
4. 验证凭证并按需测试模型，保存后会加密存储 API Key。

> 模型测试会提交真实生成请求，可能产生少量费用。

### 4.5 通过 CLI 配置

```bash
octop models              # 查看供应商预设与模型解析
octop provider list       # 列出已配置供应商
octop provider --help     # 供应商增删改查
```

---

## 五、基本使用

### 5.1 对话（Chat）

- 打开 **对话** 页面，选择当前专家即可开始实时聊天。
- 支持多轮对话、附件上传、工具调用展示。
- 可在对话中通过斜杠命令触发特定能力。

![图 5.1 — 对话主界面](assets/use-02-chat.png)

### 5.2 创建专家（专家库 / MBTI 人格）

- 进入 **专家** 页面，从专家库选择模板一键创建，也可以新建空白专家。
- 选择 **MBTI 人格** 模板为专家赋予性格，或做人格测试自动生成。
- 为该专家指定供应商、模型与工作区后端。

![图 5.2 — 专家库](assets/use-03-agent.png)

### 5.3 连接器（Connectors）

- 进入 **Connectors** 页面，配置 OAuth 应用与 MCP 网关。
- 通过连接器接入外部服务（腾讯文档、Notion、新闻等）。完整列表见 [内置连接器](connectors.md)。

### 5.4 通道（Channels / IM）

- 进入 **通道** 页面，安装并配置 IM 平台。
- 各通道所需凭证：

| 通道 | 所需凭证 |
|------|----------|
| 飞书 | App ID、App Secret |
| 钉钉 | App Key、App Secret |
| QQ | Bot AppID、Token |
| 微信 | 扫码绑定 / 账号凭证 |
| 企业微信 | Corp ID、Agent Secret |
| Web 控制台 | 默认启用 |

![图 5.3 — 通道配置](assets/use-04-channels.png)

### 5.5 定时任务（Cron）

- 进入 **定时任务** 页面，可视化创建任务。
- 支持自然语言或 Cron 表达式，让专家按时推送或执行任务。

![图 5.4 — 定时任务管理](assets/use-05-cron.png)

### 5.6 ACP（与 IDE / 编码 Agent 协作）

1. **入站** —— 让外部工具（Zed、OpenCode 等）使用你的 HappyClaw 专家：

   ```bash
   octop acp --agent main
   ```

2. **出站** —— 在对话中把编码任务委派给外部 Agent（OpenCode、CodeBuddy、Claude Code、Codex）：
   - 控制台 → **ACP**：配置 Runner。
   - 为专家启用 `acp_runner`，然后在对话中委派。

完整配置见 [docs/acp.md](acp.md)。

### 5.7 设置

- **模型** — 供应商、模型、生成模型。
- **备份** — 自动备份计划与保留份数。
- **安全** — 工具审批、Shell 命令护栏（`~/.octop/security/tool_guard/`）。
- **系统** — 监听地址、端口、日志级别、时区。
- **TLS** — 配置 HTTPS（自签或自有证书）。

配置也可以直接编辑 `~/.octop/config.json`，或用环境变量覆盖（如 `OCTOP_PORT`、`OCTOP_BIND_HOST`）。详见 [docs/configuration.md](configuration.md)。

![图 5.5 — 设置页面](assets/use-06-settings.png)

### 5.8 远程桌面与浏览器 AI

在 **控制台 → 控制（Control）** 页面中可使用：

- **远程桌面**：实时查看屏幕并控制键鼠，支持 Linux / Windows / macOS。
- **浏览器 AI+**：基于 Chromium 的会话，支持网页自动化、截图与远程浏览。

![图 5.6 — 远程桌面](assets/use-07-remote-desktop.png)

---

## 六、数据目录与备份恢复

### 6.1 数据目录

```
~/.octop/
├── config.json              # 进程配置（地址、端口、TLS、database …）
├── env                      # 可选环境变量（API Key 等）
├── octop.db                 # 默认 SQLite 控制面（专家、通道、定时任务 …）
├── secrets/                 # 本机密钥与通道 Token
├── agents/<agent_id>/       # 各专家工作区（SOUL.md、skills …）
├── security/tool_guard/     # Shell 命令允许 / 拒绝规则
├── logs/                    # 运行日志
├── venv/                    # 安装脚本创建的 Python 环境
└── bin/octop                # 命令入口
```

用 `OCTOP_HOME` 可以把整个数据目录改到其他磁盘。

### 6.2 备份

```bash
octop backup create                 # 生成归档（数据库 + 工作区 + 配置）
octop backup auto status            # 查看自动备份配置
octop backup auto run               # 立即执行一次自动备份
```

自动备份在 `octop run` 进程内按计划执行，默认每天 04:00，保留份数可配置。自动归档以 `octop-auto-backup-` 开头，保留策略不会删除手动备份。

### 6.3 恢复

```bash
octop backup restore <归档文件>
```

恢复前建议先关闭正在运行的服务。SQLite 与 PostgreSQL 的备份不能跨引擎互恢，恢复时使用的引擎必须与备份一致。

### 6.4 迁移到新机器

1. 旧机器执行 `octop backup create`。
2. 把归档文件拷贝到新机器。
3. 新机器安装 HappyClaw，然后执行 `octop backup restore <归档文件>`。
4. 启动 `octop run`，检查专家、通道与模型配置是否完整。

---

## 七、日志与卸载

### 7.1 日志位置

- 前台运行：直接输出到终端，同时写入 `~/.octop/octop.log`。
- 系统服务：`~/.octop/logs/` 下按日期轮转。
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
   - macOS / Linux：`rm -rf ~/.octop`
4. 从 PATH 中移除 `~/.octop/bin`（安装脚本添加的那一行）。

> 删除 `~/.octop` 会连同数据库、专家工作区、密钥与备份一起删除。确认归档已另行保存后再执行。

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
- `octop run --host 0.0.0.0 --port 8088`，或设置 `OCTOP_BIND_HOST=0.0.0.0`、`OCTOP_PORT=8088`。

**Q：局域网访问不了插件市场和专家市场？**
- 这两处默认请求公网 `octop.cloud`。内网自建方式见 [内网自建市场](private-market.md)。

**Q：局域网访问不了技能市场？**
- 技能页默认请求 `https://api.skillhub.cn`。按同一接口自建并设置 `SKILL_MARKET_ORIGIN`，见 [技能市场](skill-market.md)。

**Q：如何升级？**
- `octop update`；升级前先 `octop backup create`。数据库结构会在下次启动时自动迁移。

**Q：数据会传到云端吗？**
- 不会。配置、对话、工作区与凭据都在 `~/.octop/`；只有你主动配置的模型供应商与 Connector 会收到相应请求。

---

## 九、插图清单

| 编号 | 位置 | 文件名 | 内容说明 |
|------|------|--------|----------|
| 图 1.1 | 一、简介 | `overview.png` | HappyClaw 品牌 Banner |
| 图 4.1 | 四、配置模型 | `model-01-custom.png` | 自定义供应商弹窗 |
| 图 5.1 | 5.1 对话 | `use-02-chat.png` | 对话主界面 |
| 图 5.2 | 5.2 专家 | `use-03-agent.png` | 专家库模板列表 |
| 图 5.3 | 5.4 通道 | `use-04-channels.png` | IM 通道开关列表 |
| 图 5.4 | 5.5 Cron | `use-05-cron.png` | 创建定时任务弹窗 |
| 图 5.5 | 5.7 设置 | `use-06-settings.png` | 应用设置页面 |
| 图 5.6 | 5.8 远程桌面 | `use-07-remote-desktop.png` | 远程桌面连接页 |

> 登录页、设置向导创建管理员等截图已不再适用于单人模式，未在本文引用。
