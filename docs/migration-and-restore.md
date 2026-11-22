# 单机迁移与恢复手册

> 面向「一台机器上的 HappyClaw 换到另一台机器」或「把误操作后的数据退回去」。
> 全是可直接粘贴的命令；默认 Windows PowerShell，macOS / Linux 的差异单独标注。
> 相关章节：[用户帮助文档 §6 数据目录与备份恢复](user-guide.md#六数据目录与备份恢复)。

---

## 0. 先记住三条

1. **恢复会覆盖**当前数据库与专家工作区，执行前必须先停 `octop run`。
2. 迁移用 `--include-chats`，否则对话记录不进归档。
3. 恢复前先在**目标机**做一次现场备份，失败时才有退路。

---

## 1. 数据目录与归档范围

默认根目录 `~/.octop/`（Windows 即 `%USERPROFILE%\.octop\`），可用 `OCTOP_HOME` 整体改位置。

```powershell
# 确认当前实际使用的根目录
if ($env:OCTOP_HOME) { $env:OCTOP_HOME } else { "$env:USERPROFILE\.octop" }
```

`octop backup create` 打进去和打不进去的内容：

| 路径 | 内容 | 是否进归档 |
|------|------|-----------|
| `octop.db` | 控制面数据库（专家、会话、通道、定时任务、加密密钥） | 是 |
| `config.json` | 端口、监听地址、TLS、数据库连接、自动备份设置 | 是（`--no-config` 可排除） |
| `env` | 可选环境变量文件（API Key 等） | 是（随 `config.json` 一起） |
| `agents/<agent_id>/` | 各专家工作区（SOUL.md、skills、inbound 等） | 是（`--no-workspaces` 可排除） |
| `skill-packages/` | 全局技能包 | 是（`--no-skill-packages` 可排除） |
| `plugins/` | 已安装插件 | 是（`--no-plugins` 可排除） |
| `knowledge/` | 知识库文件 | 是（`--no-knowledge` 可排除） |
| `backups/` | 历史归档 | **否** |
| `logs/` | 运行日志 | **否** |
| `secrets/` | 腾讯云授权缓存（`cloud/`、`cloud.key`） | **否** |
| `security/tool_guard/` | 自定义命令护栏规则 | **否** |
| `ssl/` | TLS 证书与 ACME 账号 | **否** |
| `avatars/` | 用户 / 专家 / 知识库头像 | **否** |
| `users/` | 旧版按用户存放的目录 | **否** |
| `expert_market/`、`published_experts/` | 专家市场缓存与已发布快照 | **否** |
| `connector-cli/` | Connector CLI 的隔离配置目录 | **否** |
| `venv/`、`bin/` | 安装脚本创建的运行环境与命令入口 | **否** |

> 归档里还会带一个 `manifest.json`，记录版本、数据库引擎、schema 版本，以及各可选目录是否包含。

需要连 `security/`、`ssl/`、`avatars/` 一起搬时，用第 3 节的「整目录冷备」，不要指望 `octop backup`。

---

## 2. 备份怎么做

### 2.1 常规备份（推荐）

```powershell
# 默认：数据库 + 工作区 + 配置 + 技能包 + 插件 + 知识库，不含聊天
octop backup create

# 迁移 / 完整留档：加上聊天历史
octop backup create --include-chats
```

输出形如：

```
wrote C:\Users\you\.octop\backups\octop-backup-20261111T120000Z.tar.gz (18342011 bytes)
```

- 默认目录：`~/.octop/backups/`
- 文件名：`octop-backup-<UTC 时间>.tar.gz`
- 指定位置（建议放另一块盘）：

```powershell
octop backup create --include-chats -o D:\backup\happyclaw-full.tar.gz
```

macOS / Linux 相同：

```bash
octop backup create --include-chats -o ~/backup/happyclaw-full.tar.gz
```

### 2.2 自动备份

默认**关闭**。确认当前值：

```powershell
octop backup auto status
```

```
auto_enabled: False
schedule: cron:0 4 * * *
retention_count: 7
```

开启后由 `octop run` 进程内的调度器执行（关掉服务就不再跑）；自动归档前缀 `octop-auto-backup-`，只清理这类旧归档，手动备份不会被删。手动触发一次：

```powershell
octop backup auto run
```

### 2.3 整目录冷备（连证书、护栏规则、头像一起搬）

先停服务（`Ctrl+C` 或停止对应的系统服务），再打包：

```powershell
tar -czf D:\backup\octop-home-20261111.tar.gz --exclude=.octop/venv -C $env:USERPROFILE .octop
```

macOS / Linux：

```bash
tar -czf ~/backup/octop-home-20261111.tar.gz --exclude=.octop/venv -C ~ .octop
```

`venv/` 是平台相关的，换机后必须重新生成，所以排除。不要用 `Compress-Archive` 打这个目录：文件多、易受占用影响。

---

## 3. 校验归档

列出内容，确认有 `manifest.json`、`db/`、`workspaces/`：

```powershell
tar -tzf D:\backup\happyclaw-full.tar.gz | Select-Object -First 20
```

macOS / Linux：

```bash
tar -tzf ~/backup/happyclaw-full.tar.gz | head -20
```

只看清单元数据（判断是否含聊天、数据库引擎）：

```powershell
tar -xOzf D:\backup\happyclaw-full.tar.gz manifest.json
```

关键字段：`database_driver`（`sqlite` / `postgresql`）、`schema_version`、`includes_chats`。

文件完整性：

```powershell
Get-FileHash D:\backup\happyclaw-full.tar.gz -Algorithm SHA256
```

把哈希一起存到网盘备注里；换机后重算一次对比。

---

## 4. 换机器怎么搬

以「旧机 Windows → 新机 Windows」为例；macOS / Linux 把路径换掉即可。

**第 1 步：旧机出包**

```powershell
octop backup create --include-chats -o D:\backup\happyclaw-full.tar.gz
Get-FileHash D:\backup\happyclaw-full.tar.gz -Algorithm SHA256
```

需要证书、护栏规则、头像时，再按 2.3 打一份整目录包。

**第 2 步：新机装同版本或更新版本**

```powershell
if (-not $env:OCTOP_INSTALL_BASE) { $env:OCTOP_INSTALL_BASE = 'https://raw.githubusercontent.com/xkx121029/HappyClaw/main' }; irm "$env:OCTOP_INSTALL_BASE/scripts/install.ps1" | iex
```

重开一个 PowerShell：

```powershell
octop --version
```

> 新机版本必须 **不低于** 旧机。归档 schema 比运行时新时，恢复会被拒绝。
> 想保持旧机端口 / 数据库配置，安装后不要先手动改 `config.json`。

**第 3 步：把归档拷到新机**

例如 `D:\backup\happyclaw-full.tar.gz`，重算哈希对上再继续。

**第 4 步：停新机服务并恢复**

首次安装通常还没启动过；如果启动过，先按 `Ctrl+C` 停掉。

```powershell
# 保留新机自己的端口 / 数据库设置（推荐；新机默认 sqlite 时用它）
octop backup restore D:\backup\happyclaw-full.tar.gz --no-config --yes

# 想连旧机的端口、TLS、数据库设置一起搬过来
octop backup restore D:\backup\happyclaw-full.tar.gz --yes
```

输出示例：

```
restored: {'schema_version': 42, 'octop_version': '1.0.3b5', 'agents': 3, 'workspace_files': 812, ...}
```

**第 5 步：启动并验证**

```powershell
octop run
```

另开窗口：

```powershell
Invoke-RestMethod http://127.0.0.1:8088/api/health
```

看到 `ok : True` 后，浏览器打开 `http://127.0.0.1:8088`，检查：专家列表数量、随便打开一个历史会话、发一条消息、看附件能否预览。

**旧机自定义过 `OCTOP_HOME`？** 新机先设同一个变量，再执行恢复；否则归档会被展开到默认的 `~/.octop/`：

```powershell
[Environment]::SetEnvironmentVariable("OCTOP_HOME", "E:\octop-data", "User")
# 重开终端后再执行 octop backup restore / octop run
```

**Docker 迁移：** 宿主机数据卷挂的是 `/data/.octop`。把归档拷进容器可访问的目录，进容器执行：

```bash
docker compose -f docker/docker-compose.yml exec -T octop octop backup restore /data/backup/happyclaw-full.tar.gz --no-config --yes
```

容器名以 `docker compose ps` 实际输出为准。

---

## 5. 恢复到底改了什么

| 行为 | 说明 |
|------|------|
| 覆盖数据库 | 整个控制面数据库被归档替换，随后自动跑迁移升级到当前版本 |
| 覆盖工作区 | `agents/<agent_id>/` 按归档内容写回；归档未包含的专家目录不会被清空 |
| 配置 | 默认覆盖 `config.json` 与 `env`；`--no-config` 保留目标机现有配置 |
| 聊天 | 归档含聊天则整体替换；**不含**聊天时，先把目标机现有会话存到临时库，恢复后再写回 |
| 技能包 / 插件 / 知识库 | 归档 `manifest` 标记为包含时，对应目录整体替换；未包含则保留目标机现状 |
| 不碰的目录 | `secrets/`、`security/`、`ssl/`、`logs/`、`avatars/`、`users/`、`backups/`、`venv/`、`bin/` |
| 数据库引擎 | 归档 `database_driver` 必须与当前运行时一致，跨引擎直接拒绝 |
| schema 版本 | 归档版本高于运行时支持的最大版本时拒绝，需要先 `octop update` |

恢复命令的全部参数：

```powershell
octop backup restore <归档> --yes --no-config --owner-user-id <id> --home <目录>
```

- `--yes`：跳过确认提示。
- `--no-config`：不恢复 `config.json` / `env`。
- `--owner-user-id`：仅用于旧版 LightClaw 迁移归档；普通备份不用填。
- `--home`：指定数据根目录，等价于临时设置 `OCTOP_HOME`。

---

## 6. 恢复失败怎么回退

### 6.1 先做现场备份（最重要）

```powershell
octop backup create --include-chats -o D:\backup\before-restore.tar.gz
```

带 `--include-chats` 才能把「恢复前一刻的会话」原样退回；不带时，恢复过程中会把当前会话临时保存再写回，行为和预期可能不同。

### 6.2 整包回退

停服务后，把现场备份再恢复回去：

```powershell
octop backup restore D:\backup\before-restore.tar.gz --yes
octop run
```

### 6.3 只回退数据库

恢复在「数据库已替换、工作区还没写完」时中断，优先只还原数据库：

```powershell
# 1) 停服务
# 2) 解出备份里的数据库
$tmp = "$env:TEMP\octop-restore"
Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $tmp | Out-Null
tar -xzf D:\backup\before-restore.tar.gz -C $tmp db/octop.db

# 3) 清掉 SQLite 的 WAL 残留，再覆盖
Remove-Item "$env:USERPROFILE\.octop\octop.db-wal","$env:USERPROFILE\.octop\octop.db-shm" -ErrorAction SilentlyContinue
Copy-Item "$tmp\db\octop.db" "$env:USERPROFILE\.octop\octop.db" -Force

# 4) 启动
octop run
```

macOS / Linux 把 `Copy-Item` 换成 `cp`，`$env:USERPROFILE` 换成 `~`。

PostgreSQL 的归档里是 `db/octop.dump`，用 `pg_restore --clean --if-exists -d <conninfo> db/octop.dump` 手工恢复。

### 6.4 只回退配置

误把旧机的 `config.json` 带过来，导致端口 / 数据库不对：

```powershell
tar -xOzf D:\backup\before-restore.tar.gz config/config.json > $env:TEMP\config.json
Copy-Item $env:TEMP\config.json $env:USERPROFILE\.octop\config.json -Force
```

如果恢复时用了 `--no-config`，这一步不需要。

### 6.5 不要做的事

- 不要用 `octop clean --all` 来「重来一次」：它会删掉 `~/.octop/` 下的数据，包括你还没来得及回退的现场状态。
- 不要在 `octop run` 还开着的时候替换 `octop.db`：Windows 上文件被占用，SQLite 也可能读到半截状态。
- 不要把 SQLite 归档恢复到 PostgreSQL 实例（或反向），引擎检查会直接拒绝。

---

## 7. PostgreSQL 额外步骤

归档与恢复依赖本机客户端工具，PATH 里必须能找到：

```powershell
pg_dump --version
pg_restore --version
```

报 `pg_dump not found on PATH` / `pg_restore not found on PATH` 时，装 PostgreSQL 客户端（不需要装服务端），把 `bin` 目录加进 PATH，重开终端再执行。

迁移顺序固定：

1. 新机把 `config.json` 的 `database.driver` 改成 `postgresql`，填好连接信息；或者用 `OCTOP_DATABASE_URL`。
2. 确认新库可连、为空库（不要指向已有业务库）。
3. 停服后 `octop backup restore <归档> --no-config --yes`。
4. 恢复完成后 `octop run`，看 `/api/health` 的 `db : True`。

SQLite 与 PostgreSQL 之间没有转换工具，只能在同一引擎内搬。

---

## 8. 报错对照

| 报错 / 现象 | 原因 | 处理 |
|-------------|------|------|
| `... does not match runtime dialect ... cross-engine restore is refused` | 归档引擎与当前配置不一致 | 改 `config.json` 的数据库配置，或换成同引擎的归档 |
| `backup schema version N is newer than the maximum supported version M` | 程序版本比归档旧 | `octop update` 后重试 |
| `backup archive missing database file` | 归档损坏或没传完 | 重算 SHA256，重新拷贝 |
| `Migrate the existing history v2 archive before restoring a backup` | 本机还有旧版历史待迁移 | 先 `octop run` 启动一次，等启动完成后 `Ctrl+C` 停掉，再重试恢复 |
| `database is locked` / 文件被占用 | 服务还在跑 | 停掉 `octop run` 或系统服务再试 |
| `pg_dump not found on PATH` | 没装 PostgreSQL 客户端 | 安装客户端并加入 PATH |
| 恢复成功但页面 404 / 空白 | 用旧归档覆盖了配置，或前端资源版本不匹配 | 用 `--no-config` 重新恢复；必要时 `octop update` |
| 恢复后没有头像 / TLS / 护栏规则 | 这些目录本就不在归档里 | 用 2.3 的整目录包单独搬 |

---

## 9. 迁移前后自检

迁移前（旧机）：

- [ ] `octop backup create --include-chats -o ...` 成功，输出有 `wrote ...`
- [ ] `tar -tzf` 能看到 `manifest.json`、`db/`、`workspaces/`
- [ ] 记录了 SHA256
- [ ] 需要证书 / 头像时，另打了整目录包

迁移后（新机）：

- [ ] `octop --version` 不低于旧机
- [ ] `octop backup restore ... --yes` 输出 `restored: {...}`
- [ ] `octop run` 无报错
- [ ] `Invoke-RestMethod http://127.0.0.1:8088/api/health` 返回 `ok : True`
- [ ] 专家数量与旧机一致
- [ ] 打开一个历史会话，消息完整
- [ ] 发一条新消息，模型能回复
- [ ] 上传一个附件，能预览
- [ ] 旧机确认无误后再停用，别提前删数据
