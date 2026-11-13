# 后端冷启动基线（onedir 独立可执行）

回归对照用。数字退化时先对这张表，再去看 `startup.segment` 日志。

## 1. 这份基线测的是什么

| 项 | 值 |
| --- | --- |
| 形态 | PyInstaller `onedir`（`octop.exe` + `_internal/`），入口 `octop.cli.main:cli` |
| 产出方式 | `make package-backend` → `dist/backend/octop/` |
| 构建耗时 | 2026-11-12 最终版（含强制前端重建）：dashboard 1720s + PyInstaller 930s + 自检，约 45 分钟（本机慢 CPU）。历史：`make package-backend` 1411s（复用分析缓存）；`--clean` 全量 1937s；numpy 修复后 2056s；discovery 裁剪后 2485s |
| 产物 | 4 424 个文件 / 356.5 MB（`octop.exe` 63.3 MB 含 PYZ，`_internal` 4 423 文件 / 293.1 MB） |
| 与上一版差异 | +14 文件 / +0.2 MB：dashboard 重建（508 → 509 文件，新增 `version.json`）+ exe 内 health/selfcheck 改动。相对起点 5 009 文件 / 454.3 MB 累计 −585 文件 / −97.8 MB |
| 运行时依赖 | 无。不需要 Python / pip / venv / `.pyc` / VC++ 运行库（`python313.dll`、`VCRUNTIME140.dll`、`MSVCP140.dll` 已在内） |

四个指标的口径（都是从**进程创建**到该事件首次可达）：

| 指标 | 判定 |
| --- | --- |
| `health` | `GET /api/health` 首次返回 200（uvicorn `startup()` 完成，端口可连） |
| `agents` | `GET /api/agents` 首次返回 200（延迟挂载的路由组已 splice） |
| `first_frame` | 建 WS → 发 `user_turn` → 收到第一帧 |
| `all_routes` | 日志出现 `startup.segment name=post_listen`（后台导入 + 路由挂载全部完成） |

## 2. 测量条件

> 换机器、换盘、换 Python 版本必须重测，这张表只在下列条件下可比。

| 条件 | 值 |
| --- | --- |
| 机器 | 同一台 Windows 11 x64；E 盘是 iSCSI 网络块设备，CPU 约为普通机 1/5–1/8，冷读约 26 ms/文件 |
| Python | 3.13.15（PyInstaller 6.22.3） |
| home | `E:\HAPPYclaw\.octop-rebuild-check`（**同一个**已初始化 home，内含 1 个 `main` agent） |
| 冷态定义 | 每轮先 `robocopy` 一份**全新**的产物目录再执行，保证所有文件从未被读过；不做任何删除 |
| 轮次 | 3 轮取中位数 |
| 端口 | 8097 |

为什么不用「全新 home」：全新 home 里没有 agent，`first_frame` 无法测（WS 会直接 409），四个指标就断了两个。本机也无法清系统文件缓存，所以冷态用「全新产物目录」模拟。

## 3. 基线数字（`make package-backend` 产物，中位，秒）

2026-11-12 discovery 文档裁剪后的保守基线（构建刚结束、杀软扫描新产物时测得；同窗口配对实测见 §3.1）：

| 里程碑 | 冷（每轮全新目录） | 热（同目录连跑） |
| --- | ---: | ---: |
| `health` | **26.14** | **18.86** |
| `/api/agents` | **39.06** | **29.90** |
| `first_frame` | **43.57** | **31.29** |
| `all_routes` | **59.30** | **43.38** |

冷态五轮（构建刚结束、杀软仍在扫新产物）：

| 里程碑 | 冷 1 | 冷 2 | 冷 3 | 冷 4 | 冷 5 | 中位 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| health | 26.14 | 29.92 | 25.80 | 30.32 | 22.62 | 26.14 |
| agents | 38.45 | 48.43 | 39.06 | 46.20 | 34.81 | 39.06 |
| first_frame | 43.57 | 51.99 | 41.50 | 48.18 | 37.16 | 43.57 |
| all_routes | 63.54 | 75.20 | 55.20 | 59.30 | 50.74 | 59.30 |

热态三轮：18.86 / 29.90 / 31.29 / 43.38（20.43、18.58、18.86 等）。

冷态分段（中位，ms）：`process` 23 088（其中 `interpreter_before_package_ms` 5 578）、`listen` 933、`post_listen.imports_critical` 6 976、`catalogs.load` 3 853、`post_listen.imports` 16 188。

**构建后噪声 vs 真实差异**：上面五轮是构建刚结束、杀软扫描新产物时测的，`post_listen.imports`/`catalogs.load` 波动可达 2 倍。为排除干扰，另做了 A/B 交替（同一时间窗，同一份旧包副本 vs 新包，各 2 轮）：

| 包 | health | agents | first_frame | all_routes |
| --- | ---: | ---: | ---: | ---: |
| 旧（含 discovery 文档，A1/A2） | 23.64 / 25.40 | 38.71 / 40.51 | 40.41 / 41.85 | 52.98 / 58.82 |
| 新（裁剪后，B1/B2） | 24.26 / 25.73 | 35.75 / 39.55 | 36.83 / 40.91 | 50.93 / 56.13 |

两版持平（新包在 `agents`/`first_frame` 上略快），说明上一节五轮里 +11% ~ +16% 的差值来自机器负载，不是裁剪导致的；`read_bytes` 基本不变（旧 51–52 MB，新 50–51 MB）——离线 discovery 文档本来就不在启动读取路径上。

### 3.1 最终版（前端版本戳）冷启动实测

最终产物 `dist/backend/octop`（4 424 文件 / 356.5 MB）与上一版（4 410 文件，无 `version.json`）在同一时间窗交叉测（A = 上一版，B = 最终版，各 3 轮，每轮全新 robocopy 目录）：

| 包 | health | agents | first_frame | all_routes | read_bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| A（上一版） | 10.62 / 6.52 / 11.68（中位 10.62） | 16.27 / 10.74 / 17.07（16.27） | 17.14 / 11.15 / 17.89（17.14） | 23.44 / 15.18 / 23.30（23.30） | 53.4 MB |
| **B（最终版）** | 9.84 / 8.26 / 11.82（**9.84**） | 15.66 / 11.62 / 16.68（**15.66**） | 16.29 / 12.31 / 17.30（**16.29**） | 23.48 / 15.83 / 22.10（**22.10**） | 53.2 MB |

- B 四项都不慢于 A（为 A 中位的 93%–96%），属噪声内持平；`read_bytes` / `read_count` 两版一致（约 53 MB / 242 k），说明新增的 `version.json` 与 `/api/health.build` 字段没有进入启动关键路径。
- 本轮绝对值比上表 26.14 / 39.06 / 43.57 / 59.30 低约 60%，原因是那五轮在**构建刚结束、杀软仍在扫新产物**时测得；同一二进制在机器空闲窗口快 2–4 倍（`process` 段 9.0–9.5s vs 16.5–23s，`read_bytes` 不变）。跨版本比较必须**同窗口配对**，或沿用上表的保守值做 ×1.5 告警。
- 机器更空闲时的另一组 3 轮（`final2-cold1..3`）可视为本机下限：health 7.67 / 6.88 / 4.64，agents 11.71 / 10.41 / 8.86，first_frame 12.59 / 10.77 / 9.50，all_routes 15.86 / 14.29 / 13.27。

### 3.2 历史基线（无 numpy 版，保留对照）

| 里程碑 | 冷（每轮全新目录） | 热（同目录连跑） |
| --- | ---: | ---: |
| `health` | 23.29 | 19.80 |
| `/api/agents` | 36.18 | 30.18 |
| `first_frame` | 37.86 | 31.26 |
| `all_routes` | 48.01 | 44.11 |

差异（当前 vs 无 numpy）：`health` +1.1%、`/api/agents` +2.4%、`first_frame` +1.8%、`all_routes` +6.4%；热态 +2.7% ~ +4.0%。全部在噪声 + numpy 导入成本内，未触发 ×1.5 告警。`all_routes` 涨幅最大，来自 `post_listen.imports_critical`（6 455 → 7 457 ms，+1.0s）与 `post_listen.imports`（12 717 → 15 138 ms，+2.4s）：numpy 与 `langchain_aws.embeddings.bedrock` 只在监听后导入，不进 `health` 关键路径，所以 `health` 几乎不变。


热态波动说明：同一产物在机器负载不同时，热态实测到 13.83 / 19.80 两档（`process` 11.2s vs 16.5s），**热态只作参考**。冷读代价用同批配对（冷 23.13 / 热 13.83，同一份 `.perf` 产物）估为 **9.3–10.7s**：`health` 9.30（40.2%）、`/api/agents` 9.97（28.7%）、`first_frame` 10.72（29.5%）、`all_routes` 11.82（24.8%）。

同一个 spec 在 `.perf` 下构建的产物冷态为 23.13 / 34.77 / 36.40 / 47.63，与上表差 ≤1.5s，属本机噪声。

## 4. 回归判据

| 指标 | 基线 | 告警线（×1.5） | 先查哪里 |
| --- | ---: | ---: | --- |
| 冷 `health` | 26.14s（§3 保守值） | **> 39s** | `process`（模块变多了？）、`post_listen.imports_critical` |
| 冷 `first_frame` | 43.57s（§3 保守值） | **> 65s** | `post_listen.imports`、`catalogs.load` |
| 热 `health` | 18.86s | **> 28s** | `process` 里的 `interpreter_before_package_ms` |
| 产物体积 | 356.5 MB | **> 535 MB** | 新增依赖是否把大件（playwright 之类）又拉进来了 |

冷热差本身也有意义：`health` 的冷读代价从 venv 形态的 62.4s 降到约 9.3s 是这个形态的核心收益，若这一项涨回 30s 以上，说明有模块被移出 PYZ 归档（例如被打成散装数据文件）。

## 5. 历史对照

| 形态 | 冷 health | 冷 agents | 冷 first_frame | 冷 all_routes |
| --- | ---: | ---: | ---: | ---: |
| venv + 预编译 pyc | 94.37 | 140.99 | 143.27 | 165.09 |
| **onedir（本基线）** | **23.29** | **36.18** | **37.86** | **48.01** |
| onefile（已否决） | 86.19 | 94.53 | 95.60 | 106.01 |

onefile 否决原因：每次启动把 182.7 MB 解压到 `%TEMP%\_MEIxxxx`，单独量到 73.5–73.9s（占启动 85%），且被强杀后残留解压目录、只 terminate 父进程时子进程仍占端口。

## 6. 复现

```powershell
cd E:\HAPPYclaw\Octop

# 1) 产出 + 自检（自检见 scripts/packaging/verify_backend.py）
make package-backend

# 2) 冷启动三轮：每轮一份全新目录（不要复用，复用就是热态）
robocopy dist\backend\octop E:\HAPPYclaw\.perf\cold\a\octop /E /MT:16 /NFL /NDL /NJH /NJS
& .venv\Scripts\python.exe E:\HAPPYclaw\.perf\boot_bench_frozen.py `
    --exe E:\HAPPYclaw\.perf\cold\a\octop\octop.exe --rounds 1 --kind cold --label onedir-cold1

# 3) 热态三轮（同一目录连跑，不拷贝）
& .venv\Scripts\python.exe E:\HAPPYclaw\.perf\boot_bench_frozen.py `
    --exe dist\backend\octop\octop.exe --rounds 3 --kind warm --label onedir-warm
```

`boot_bench_frozen.py` 目前放在仓库外的 `E:\HAPPYclaw\.perf\`（测量工具，未入库）；它只写 E 盘、不删文件，每轮输出的 JSON 落在同目录。

详细过程与分段解释见 `E:\HAPPYclaw\2026-11-12\cold-start\outputs\cold-start.md` §11。

## 7. 文件数构成与可压缩空间（2026-11-12 最终产物，4 424 文件 / 356.5 MB）

安装耗时主要花在杀软逐文件扫描，文件数比体积更关键。`_internal` 前几大目录：

| 目录 | 文件数 | 体积 | 内容 | 可压缩性 |
| --- | ---: | ---: | --- | --- |
| `botocore` | 1 804 | 16.0 MB | 约 400 个 AWS 服务的 JSON 模型 | 高（按需服务裁剪，见 7.2） |
| `octop` | 1 138 | 57.5 MB | `dashboard` 509（assets 296 + monaco 151 + `version.json`）、`infra` 627（专家库/skills/migrations） | 低（业务数据，dashboard 属前端线） |
| `tzdata` | 605 | 0.5 MB | IANA 时区库，一个时区一个文件 | 中（见 7.4） |
| `googleapiclient` | 0 | 0 | 原 586 文件 / 97.7 MB，已裁剪（见 7.1） | 已完成 |
| `octop_harness` | 157 | 2.0 MB | 模板 / 技能 / 子代理清单 | 低 |
| `playwright` | 110 | 100.3 MB | driver（`node.exe`） | 无（浏览器能力依赖） |
| 其余（含 dist-info 250 文件、根目录 DLL） | 609 | 116.8 MB | 扩展模块 / 运行库 | 低 |

### 7.1 `googleapiclient/discovery_cache/documents`（−586 文件 / −97.7 MB，已落地）

`octop` 与 `octop_harness` 源码里**没有** `import googleapiclient`（它只是 `octop_harness` 的 `web-search-all` extra 依赖，被装进 venv 后被 PyInstaller 收进来）。真正会用到它的是 `langchain_community` 的 Gmail / Google Drive / YouTube loader。

- 实现：`octop.spec` 在 **Analysis 之后**过滤 `a.datas` 里 `googleapiclient/discovery_cache/documents/` 开头的条目（hook 在 Analysis 阶段才把数据塞进来，过滤必须放在其后）。
- 副作用处理：`googleapiclient.discovery.build()` 默认 `static_discovery=True`，文档缺失会抛 `UnknownApiNameOrVersion`。冻结包的 `discovery.py` 在 PYZ 里不可改写，因此新增 `src/octop/infra/utils/google_discovery.py`：用 `sys.meta_path` finder 在该模块首次 import 时包装 `build()`，静态文档缺失就自动以 `static_discovery=False` 重试（联网获取）；联网也失败时抛中文 `RuntimeError` 提示检查网络/代理。`server.py` preflight 里安装该 finder（零导入成本，不进入 health 关键路径）。
- 验证：`octop selfcheck` 的输出带 `google_discovery: {"offline_documents": false, "network_fallback": true, "hint_zh": "…"}`；另用伪服务名 + 不可达 URL 测得中文提示路径（`E:\HAPPYclaw\.perf\test_google_fallback.py`）。
- 代价：Gmail / Drive loader 首次调用需要联网下载 API 描述（离线环境下会失败并给出中文提示），这是裁剪换来的体积收益。

### 7.2 裁剪 `botocore/data` 到实际用到的服务（约 −1 700 文件 / −14 MB）

`botocore` 占文件数的 36%，其中最大的是 `cloudfront`（86 文件）、`ec2`（37）、`rds`（11），大部分服务后端从未调用。保留白名单（`bedrock`、`bedrock-runtime`、`s3`、`sts`、`sso`、`sso-oidc`、`kms`、`sqs`、`sns`、`lambda` 等）后可降到约 50–100 文件。

- 风险：用户把 AWS 相关工具配到白名单外的服务时，报 `UnknownServiceError`。属于产品决策（要支持任意 AWS 服务就不能裁）。
- 实现：spec 里按前缀过滤 `botocore/data/<service>` 的 datas，同时保留 `botocore/data/endpoints.json` 等根文件。

### 7.3 裁剪 `dist-info`（−约 200 文件 / <1 MB）

36 个 `.dist-info` 共 250 文件，绝大多数只为 `importlib.metadata.version()` 服务。可只保留 `octop` / `octop_harness` / `octop_memory` 等会被运行时查询的元数据。收益小、排查成本高（缺 metadata 的报错很隐晦），优先级低。

### 7.4 压缩 `tzdata`（−约 560 文件 / 体积不变）

604 个时区文件。两种做法：只保留常用时区（约 40 文件，冷门时区会 `ZoneInfoNotFoundError`）；或把 `tzdata` 打成单个 zip 加到 `sys.path`（需 runtime hook，`importlib.resources` 支持 zip）。**不建议**默认开启：用户时区不可预知。

### 7.5 结论（2026-11-12 定稿）

- **已做：7.1**（−586 文件、−97.7 MB）。产物 5 009 文件 / 454.3 MB → **4 424 文件 / 356.5 MB**（−11.7% 文件数、−21.5% 体积）。
- **不做：7.2**（`botocore` 白名单）。会缩小用户可用的 AWS 服务范围，收益不值。
- 不建议：7.3（收益太小、排查成本高）、7.4（破坏任意时区）。
- 若将来产品决定接受 AWS 服务白名单，7.2 可在 7.1 基础再降到约 2 700 文件；按 586s/4 968 文件 ≈ 0.118 s/文件估算，安装扫描时间再省约 3 分钟（估算，需安装器线实测）。

## 8. P0 回归：numpy 缺失与构建期自检

| 项 | 内容 |
| --- | --- |
| 现象 | 装完能进主界面，发第一条消息时 `ModuleNotFoundError: No module named 'numpy'`（`langchain_aws/embeddings/bedrock.py` → `_create_bedrock_prompt_caching_middleware`） |
| 根因 | `octop.spec` 的 `excludes` 里有 `numpy`。PyInstaller 静态分析把它排除，启动路径不导入它，所以 health / dashboard 都正常，直到 agent 构图才炸 |
| 修复 | 从 `excludes` 移除 `numpy`；`hiddenimports` 补 `numpy`、`tqdm`、`tiktoken_ext`、`tiktoken_ext.openai_public` |
| 防回归 | 新增 `octop selfcheck`（`src/octop/cli/commands/selfcheck.py`）：导入 20 个 agent 栈模块（`langchain*` 全家、`tiktoken*`、`tqdm`、`numpy`、Gmail/Drive loader）并用 `langgraph` 编译+调用一张一次性的图；`verify_backend.py` 在启动服务**之前**先跑它，失败则构建失败 |
| 冻结包实测 | `{"ok": true, "imports": [20 项], "failures": [], "graph": {"nodes": 1, "messages": 1}}`，55.4s（`make package-backend` 自检内） |

numpy 带来的体积代价：+41 文件 / +27.7 MB（`numpy` 13 个 `.pyd` 6.0 MB + `numpy.libs` 2 个 DLL 20 MB + 24 个 dist-info 文件；纯 `.py` 进 `octop.exe` 的 PYZ，exe 62 → 63.3 MB）。

## 9. 前端与后端产物一致性（2026-11-12）

后端产物内嵌 dashboard 静态文件，但打包以前不会自动重建前端，所以“只改前端”可能装出旧界面且无人发现。现在：

- `make package-backend` 依赖 `package-dashboard`：`scripts/packaging/build_dashboard.py` 先跑 `npm ci`（`node_modules` 缺失或 `package-lock.json` 更新时）和 `npm run build`，**任何失败都中止打包**；Vite `emptyOutDir=true`，不存在沿用旧产物的路径。
- 构建完成后写 `src/octop/dashboard/version.json`：`git_commit`、`git_dirty`、`dashboard_built_at`（完成时间）、`index_sha256`、`build_seconds`，随包进入 `_internal/octop/dashboard/`。
- 运行时可查：`GET /api/health` 的 `build` 字段返回同一份内容，拿到安装包即可确认是哪一版前端。
- 自检两道：`octop selfcheck` 校验包内 `index.html` 与其 `version.json` 的 sha256 一致；`verify_backend.py --dashboard-dir` 再把包内 `index.html` 与**本次**前端构建输出对比，并核对 `/api/health.build.index_sha256`。
- 本次实测：commit `0652610c`（dashboard 有 46 个未提交改动，`git_dirty=true`），前端构建 1720s（本机慢 CPU），`index.html` sha256 `c69f6a36…`。
- 最终产物验证：`octop selfcheck` 返回 `dashboard.match=true`（`built_at` 2026-11-12T11:50:34+00:00，`stamp_sha256` 与包内 `index.html` 一致）；`verify_backend.py` 五项全过，含「dashboard 版本一致」与「health 版本戳」（`/api/health.build.index_sha256 = c69f6a36…`），且启动前后 `_internal` 保持 4 423 文件 / 307,388,702 B 不变。

