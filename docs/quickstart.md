# 5 分钟快速开始（Windows 优先）

> 目标：从零到「浏览器里能对话」。全程不需要注册、登录或配置账号。
> macOS / Linux 的差异命令会单独标注。

---

## 0. 先确认三件事

| 项 | 要求 | 怎么确认 |
|----|------|----------|
| 系统 | Windows 10/11 64 位（macOS 12+ / 主流 Linux 发行版同样支持） | 设置 → 系统 → 关于 |
| PowerShell | 5.1 或更高 | `$PSVersionTable.PSVersion` |
| 网络 | 能访问外网（下载安装包与依赖） | 浏览器能打开任意网站 |

**不需要**预装 Python、Node 或数据库：安装脚本会在 `%USERPROFILE%\.octop\venv` 创建隔离环境。

> 磁盘：`~/.happyclaw` 下要放独立 Python 3.12 环境、依赖、数据库与备份，建议预留数 GB；本地模型与知识库文件另计。内存没有硬性下限，取决于你选的模型。

---

## 1. 安装（约 2 分钟）

打开 **PowerShell**（普通权限即可），执行（命令默认从本仓库 GitHub `main` 拉脚本；GitHub 访问受限时先把 `$env:OCTOP_INSTALL_BASE` 指向提供同样 `scripts/` 目录的镜像）：

```powershell
if (-not $env:OCTOP_INSTALL_BASE) { $env:OCTOP_INSTALL_BASE = 'https://raw.githubusercontent.com/xkx121029/HappyClaw/main' }; irm "$env:OCTOP_INSTALL_BASE/scripts/install.ps1" | iex
```

安装完成后**关闭当前窗口，重新打开一个 PowerShell**，让 PATH 生效。然后验证：

```powershell
octop --version
```

能看到版本号（例如 `1.0.3b6`）就说明安装成功。

<details>
<summary>安装脚本被策略拦截？</summary>

如果提示「禁止运行脚本」，用下面这条替代（只对当前进程放行）：

```powershell
powershell -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/xkx121029/HappyClaw/main/scripts/install.ps1 | iex"
```

</details>

<details>
<summary>macOS / Linux</summary>

```bash
curl -fsSL "${OCTOP_INSTALL_BASE:-https://raw.githubusercontent.com/xkx121029/HappyClaw/main}/scripts/install.sh" | bash
source ~/.zshrc   # 或 source ~/.bashrc
octop --version
```

</details>

---

## 2. 启动（约 10 秒）

```powershell
octop run
```

首次启动会自动创建 `%USERPROFILE%\.octop\`、SQLite 数据库和本机使用者。看到类似下面的输出即表示服务已起来：

```
Uvicorn running on http://127.0.0.1:8088
```

> 这个窗口要保持运行。按 `Ctrl+C` 停止服务。

---

## 3. 打开控制台（约 10 秒）

浏览器访问：

```
http://127.0.0.1:8088
```

应当直接进入对话页，**没有登录页**。

> 若改了端口，用实际端口访问；如果页面打不开，先看第 2 步的终端有没有报错。

---

## 4. 配置模型（约 1 分钟）

1. 左侧进入 **管理 → 模型配置**（`/admin/models`）。
2. 点 **添加供应商**，选择预设（OpenAI、DeepSeek、通义千问、Kimi、Ollama 等）或「自定义」。
3. 填写 **Base URL** 与 **API Key**；本地 Ollama 不需要 Key。
4. 勾选要使用的模型，点 **测试连接**。
5. 测试通过后保存。

没有 API Key？先用本机 Ollama 验证全流程：

```powershell
ollama serve          # 另开一个窗口
ollama pull qwen3:8b  # 按机器配置选择模型
```

然后在供应商里选 `ollama`，Base URL 保持默认即可。

---

## 5. 验证跑通

### 5.1 服务健康检查

另开一个 PowerShell：

```powershell
Invoke-RestMethod http://127.0.0.1:8088/api/health
```

应返回包含 `ok : True` 的对象，例如：

```
ok             : True
started_at     : 2026-11-11T12:00:00+08:00
db             : True
users_loaded   : 1
agents_running : 1
channels       : []
build          : @{commit=...}
```

macOS / Linux：

```bash
curl -s http://127.0.0.1:8088/api/health
# {"ok":true,...}
```

### 5.2 真实对话

1. 回到控制台 **对话** 页。
2. 在输入框发送：`你好，请用一句话介绍你自己`。
3. 能看到流式回复，即表示「服务 → 模型 → 会话」整条链路打通。

### 5.3 数据落盘检查

```powershell
Get-ChildItem $env:USERPROFILE\.octop
```

应能看到 `config.json`、`octop.db`、`agents`、`backups`、`logs` 等条目。

---

## 6. 第一次备份（建议）

```powershell
octop backup create --include-chats
```

归档默认写到 `%USERPROFILE%\.octop\backups\`，文件名形如 `octop-backup-20261111T120000Z.tar.gz`（UTC 时间）。需要放到指定位置时用 `-o`：

```powershell
octop backup create --include-chats -o D:\backup\happyclaw-full.tar.gz
```

把它复制到其他磁盘或网盘即可。

> 手动 `octop backup create` 默认不含聊天历史，需要完整迁移时加 `--include-chats`；自动备份与托盘「立即备份」默认包含。

---

## 7. 停止与再次启动

```powershell
# 停止：在运行的窗口按 Ctrl+C

# 再次启动
octop run

# 后台常驻：Linux / macOS 用 octop service start；Windows 用「任务计划程序」开机启动 octop run
# octop service start
```

---

## 8. 常见问题（5 分钟内最可能遇到的）

| 现象 | 原因 | 处理 |
|------|------|------|
| `octop` 不是内部或外部命令 | 安装后没有重开终端 | 重开 PowerShell，或检查 `%USERPROFILE%\.octop\bin` 是否在 PATH |
| 8088 被占用 | 其他程序占用端口 | `octop run --port 8090`，再用新端口访问（端口会写回 `config.json`，之后直接 `octop run` 也是 8090） |
| 页面能开但对话报错 | 模型未配置或 Key 无效 | 管理 → 模型配置 → 测试连接 |
| 模型测试超时 | 网络不通 / Base URL 错 | 检查代理与 URL 路径（通常以 `/v1` 结尾） |
| 想从别的设备访问 | 默认只监听本机 | `octop run --host 0.0.0.0 --port 8088`，注意局域网暴露风险 |
| 安装下载很慢 | 默认源慢 | 先设置 `$env:UV_DEFAULT_INDEX="https://pypi.tuna.tsinghua.edu.cn/simple"` 再执行安装；macOS/Linux 可用 `install.sh --mirror <url>` |

更多问题见 [用户帮助文档](user-guide.md#八常见问题)。

---

## 9. 卸载

1. 备份需要保留的数据：`octop backup create --include-chats`。
2. 停止服务。
3. 删除数据目录：`Remove-Item -Recurse -Force $env:USERPROFILE\.octop`。
4. 从 PATH 中移除 `%USERPROFILE%\.octop\bin`。

> 删除后数据库、专家工作区、密钥与备份都会消失，请确认归档已另存。

---

## 附：Docker 方式（可选）

```powershell
git clone <仓库地址> Octop
cd Octop
docker compose -f docker/docker-compose.yml up -d --build
```

访问 `http://localhost:8088`。数据保存在容器卷 `/data/.octop`，无需预置管理员密码。详见 [docker/README_CN.md](../docker/README_CN.md)。
