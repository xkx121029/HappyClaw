# 后端独立可执行：打包与交付说明

给桌面壳/安装器那条线看的。后端不再需要目标机器上有 Python。

## 产物

```
dist/backend/octop/
├── octop.exe          # 63.3 MB，含全部纯 Python 模块（PYZ 归档）
└── _internal/         # 4 423 个文件，约 293 MB：.pyd/.dll、dashboard 静态资源、技能库
```

总计 4 424 个文件 / 356.5 MB。`octop.exe` **按相对路径**找 `_internal`，两者必须同级、不可改名。

## 打包会自动重建前端（重要）

后端产物内嵌 dashboard 的静态文件（Vite 输出到 `src/happyclaw/dashboard`）。`make package-backend` 现在会先跑 `package-dashboard`：

1. `node_modules` 缺失或 `package-lock.json` 比它新时执行 `npm ci`，然后 `npm run build`；
2. 前端构建**失败就中止打包**，不会沿用上一次留在 `src/happyclaw/dashboard` 的旧产物；
3. 构建成功后在输出目录写 `version.json`（git commit、构建时间、`index.html` 的 sha256），随包进入 `_internal/happyclaw/dashboard/`。

> **只改前端也必须重打后端**。桌面壳重打安装包前不要复用旧的 `dist/backend/octop`；`verify_backend.py` 会把包内 `index.html` 的哈希与本次前端构建输出对比，不一致直接判失败。

运行时确认包里是哪版前端：`GET /api/health` 的 `build` 字段。

```json
{"build": {"git_commit": "abc123…", "git_dirty": false,
           "dashboard_built_at": "2026-11-12T10:20:31+00:00",
           "index_sha256": "9f2c…", "build_seconds": 121.4}}
```

## 安装器需要做的

1. 把 `octop.exe` 和 `_internal/` **一起**放进同一个程序目录（例如 `C:\Program Files\Octop\backend\`）。
2. 升级时**整目录替换**：先解到临时目录再切换，不要只覆盖 `octop.exe` —— 新 exe 配旧 `_internal` 会缺扩展模块，属于最难查的一类故障。
3. 启动方式：`octop.exe run --port <端口>`（与 `pip install octop` 后的 `octop run` 完全一致）。
4. 数据目录通过环境变量 `HAPPYCLAW_HOME` 指定；不设则用 `~/.happyclaw`。日志固定写在 `<HAPPYCLAW_HOME>/logs/octop.log`。
5. 程序目录按**只读**处理：运行期不写 `_internal`，不生成 `.pyc`（已自检，见下）。

### 目标机器不需要

- 不需要 Python、pip、venv、`.pyc`、`site-packages`
- 不需要 VC++ 运行库：`python313.dll`、`VCRUNTIME140.dll`、`VCRUNTIME140_1.dll`、`MSVCP140.dll` 及 `api-ms-win-crt-*` 已随包
- 不需要 npm / dashboard 构建产物：`_internal/happyclaw/dashboard/` 已是构建好的静态文件

### 平台限制

PyInstaller 产物**不跨平台、不跨 Python 小版本**：这份包只能在 Windows x64（Python 3.13 ABI）上跑。要 macOS/Linux 或别的 Python 版本，必须在对应平台上重新 `make package-backend`。

## 运行时行为

| 项 | 说明 |
| --- | --- |
| 端口 | 由 `--port` 决定；就绪判定用 `GET /api/health` 200 |
| dashboard | 已内置，`/` 与 `/assets/*` 直接返回；无需前端构建 |
| 首次启动 | 冷 health 约 10–26s、可对话约 16–44s（本机 iSCSI 慢盘；刚构建完、杀软扫描新文件时取上限，机器空闲时取下限，口径见 `docs/perf/backend-cold-start-baseline.md` §3） |
| Playwright | driver 随包（`_internal/playwright/driver/node.exe`）；**浏览器二进制不随包**，优先用系统 Chrome/Edge，找不到时 `/api/browser/env-status` 返回 `hint_zh` 中文提示，不会崩 |
| 端口冲突 | 与 pip 版行为一致：绑定失败退出并写日志 |

## 不要这样发包

- **不要用 onefile**：单文件看着省事，但每次启动都要把 182.7 MB 解压到 `%TEMP%\_MEIxxxx`，实测冷启动 86.2s（解压单独量 73.5s），并且被强杀后残留解压目录、只结束父进程时子进程仍占端口。
- 不要把 `build/`、`dist/` 之外的东西（尤其 `.venv`）打进安装包；后端只需要上面那两个条目。
- 不要在安装器里对 `_internal` 做压缩安装后再删源 —— 直接整目录铺开即可。

## 自检（改完 spec 后跑一遍）

```powershell
cd E:\HAPPYclaw\Octop
make package-backend     # 构建 + 自动跑 scripts/packaging/verify_backend.py
```

自检覆盖五件事（任一项失败，`make` 以非 0 退出）：

0. **agent 栈自检**：跑 `octop.exe selfcheck`，导入 20 个 agent 相关模块（`langchain*` 全家、`langchain_aws.embeddings.bedrock`、`tiktoken*`、`tqdm`、`numpy`、Gmail/Drive loader）并用 `langgraph` 编译+调用一张一次性的图。这一条专门防“包能启动、发第一条消息才炸”的懒加载依赖缺失（numpy 那次就是这么漏的）。
1. `HAPPYCLAW_HOME` 自定义路径生效（DB / 日志 / 数据落在该目录）
2. dashboard 静态资源可返回（SPA 外壳、`index.html`、`/assets/*`），且包内 `index.html` 的 sha256 与本次前端构建输出一致（防旧界面），`/api/health` 的 `build` 版本戳与之匹配
3. Playwright 路径可解析（缺失时给中文提示 `hint_zh`，不崩）
4. 日志写在 home 下，且启动前后 `_internal` 文件数与字节数不变

单独跑自检（不重新构建）：

```powershell
.venv\Scripts\python.exe scripts\packaging\verify_backend.py `
    --exe dist\backend\octop\octop.exe --port 8117
```

只查 agent 栈（秒级失败定位）：

```powershell
dist\backend\octop\octop.exe selfcheck
```

> `numpy` 是 `langchain_aws` 在 agent 构图时导入的隐式依赖，已写进 `hiddenimports`，**不要把它加回 `excludes`**。

## 文件职责

| 文件 | 作用 |
| --- | --- |
| `scripts/packaging/entry_octop.py` | 冻结入口，等价于 console script `octop` |
| `scripts/packaging/build_dashboard.py` | 打包前强制重建前端，写 `version.json`（commit / 构建时间 / index.html sha256） |
| `scripts/packaging/octop.spec` | PyInstaller 配置：收集 `octop*` 子模块与数据、排除测试与未用 optional |
| `scripts/packaging/verify_backend.py` | 产物自检（agent 栈 + 上述四项 + 前端版本一致性） |
| `Makefile` 的 `package-backend` | 先 `package-dashboard` 再构建 + 自检，产物落 `dist/backend/` |
| `Makefile` 的 `package-dashboard` | 单独重建前端（不打包后端时用） |
