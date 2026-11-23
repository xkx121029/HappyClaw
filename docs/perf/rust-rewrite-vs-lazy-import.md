# 启动优化评估：Rust 重写 vs 惰性导入

决策参考。2026-11-17 用现有 `.perf` 基准 + `-X importtime` 实测得出。

## 1. 结论先行

**全量 Rust 重写不划算**：瓶颈不在 CPU，而在启动期导入 + LLM/IO 等待。

- 单轮对话执行 `chat_turn_s=0.69`，CPU 早已不是瓶颈；真正延迟在网络与模型响应。
- 热启动 19.8s 中，**16.5s 是解释器 + 模块导入**（占 83%），业务初始化仅 1.3s。
- Rust 能显著改善的只有「启动 + 内存 + 单文件分发」，却要付出重写 807 文件 / 19.7 万行 + 整套 AI 生态（LangChain / LangGraph / MCP / Playwright / 微信飞书 SDK / 文档处理库）的代价。投入产出比不成立。

真正的高性价比路径是：**在 Python 侧把启动期导入树砍掉**，配一个轻量 Rust 启动器改善「感知启动时间」。

## 2. 瓶颈画像（改造前）

来源：`.perf/importtime-server.txt`，`profile_imports.py` 解析。

| 类型 | 模块 | 耗时 | 说明 |
| --- | --- | --- | --- |
| cumulative | `happyclaw.infra.server` → `happyclaw_harness` → `deepagents`/`langchain` | ~13.5s | 拖入整棵 LangChain 树 |
| self | `apscheduler.schedulers.base` | 1.19s | 自身初始化重 |
| self | `mcp.types` | 1.16s | Pydantic 模型构建 |
| self | `langsmith.schemas` | 650ms | — |
| self | `charset_normalizer.api` | 633ms | — |
| self | `wecom_creds`（顶层 AESGCM） | 307ms | 启动时无需 |

**关键发现**：`gateway/__init__.py` 顶层 eager import 了 langchain 工具构建器，导致任何 `gateway.*` 子模块（哪怕只是加密工具）都会拉入整棵 langchain/harness/cryptography 树。实测单独 `import wecom_creds` 耗时 **33s**。

## 3. 已落地的改造（方案 1）

| 提交 | 改动 | 效果 |
| --- | --- | --- |
| `a8f5fd5f` | `gateway/__init__.py` 改 PEP 562 惰性导出；`wecom_creds` 的 AESGCM 改为首次使用加载 | `wecom_creds` 导入 33s → 1.3s；langchain/harness/cryptography 不再出现在启动期 |
| `aeba7557` | 导入轻量化回归守卫（3 项，独立子进程断言） | 锁住成果，防回归 |
| `9513f161` | `-X importtime` 测绘脚本 `scripts/profile_imports.py` | 可复用的量化工具 |

改造后实测（`importtime-after-lazy.txt`）：

| 指标 | 改造前 | 改造后 |
| --- | --- | --- |
| `import gateway` + `wecom_creds` 累计 | ~8.8s（另 wecom_creds 33s） | **1.83s** |
| 启动期加载 langchain_core / happyclaw_harness / cryptography | 全部加载 | **均不加载** |
| 导入模块数 | 2221 | 316 |

验证：`tests/unit/connectors/` + `gateway/test_gateway.py` **314 passed, 1 skipped**；加密加解密往返正常。

## 3b. 第二轮：httpx NO_PROXY 补丁惰性化（2026-11-17 深夜）

用真实 wall-clock A/B 复测发现的新大头：`octop/__init__.py` 顶层调用
`install_httpx_cidr_no_proxy()`，而该函数一进来就 `import httpx._client`——
**每个进程、每条 CLI 命令、每次 pytest 收集**都要为此付约 1.1~1.6s，哪怕
根本不发网络请求。注意 `-X importtime` 的 cumulative 是嵌套导入树的累计
求和（会重复计数），不能当 wall-clock 用，本轮全部改用 fresh 进程实测。

改动（`c3691cc9` / `9d877d79` / `d57450c7`）：

- `httpx_proxy.py` 新增 `install_lazy_httpx_proxy_patch()`：注册一次性 import
  hook，在 **httpx 首次被 import 时**才装 CIDR 补丁；hook 本身纯 stdlib、
  注册耗时≈0，装完自动从 `sys.meta_path` 移除。
- `octop/__init__.py` 改为注册 hook 而非即时安装。
- 契约不变：任何 `import httpx` 的路径在构造 `Client` 前补丁都已就位；
  `install_httpx_cidr_no_proxy()` 保持幂等供测试/显式调用。

**收益**（同环境、git worktree 隔离改动前后快照，各 3 次取平均）：

| 场景 | 改动前 | 改动后 | 收益 |
| --- | --- | --- | --- |
| fresh `import octop` | 2.069s | 0.487s | **-1.58s（-76%）** |
| fresh `import happyclaw.api.app` | 4.246s | 2.974s | **-1.27s（-30%）** |

守卫：`tests/unit/test_httpx_lazy_patch.py`（独立子进程断言 octop 导入不加载
httpx、后续导入仍打补丁、CIDR 绕代理有效、hook 幂等）。相关单测 20 passed。

**收益边界（诚实说明）**：`happyclaw run` 主流程本来就要 import httpx 发 LLM 请求，
这部分延迟只是从「进程启动」移到「首次请求前」，总时长不变；真正省下的是
不发网络的路径——CLI 元命令（`--help`/`--version`）、pytest 收集、插件扫描、
以及任何只 import octop 做配置/检查的场景。

## 3c. 第三轮：i18n domains 惰性导出（2026-11-18）

继续分解 CLI 启动链发现第二条隐藏导入树：`cli/support/errors.py` →
`happyclaw.infra.errors` → `octop.i18n` → **`domains/stream.py` 顶层 import
`langchain_core.exceptions`（2.25s）**。根因是 `i18n/domains/__init__.py`
顶层 eager 导入了全部子域（含 stream），而任何错误处理/CLI 命令只需要
`error_message`（来自轻量的 `domains/errors.py`）却被迫拉进整棵 LangChain。

改动（`9f698f2b` / `3ec38030`）：

- `domains/__init__.py` 改 PEP 562 `__getattr__` 惰性导出，25 个符号按映射表
  按需加载；`slash_tr` 是 `slash.tr` 的别名，特判处理。
- 无任何代码 `from octop.i18n.domains import X`（grep 确认为空），直接子模块
  导入（如 `from octop.i18n.domains.stream import ...`）完全不受影响。

**收益**（同环境、git worktree 隔离快照，各 3 次均值）：

| 导入路径 | 改动前 | 改动后 | 收益 |
| --- | --- | --- | --- |
| `import octop.i18n.domains` | 1.250s | 0.785s | **-465ms** |
| `from happyclaw.infra.errors import HappyclawError` | 1.219s | 0.817s | **-401ms** |
| `import happyclaw.cli.commands.run` | 1.479s | 1.013s | **-466ms** |

所有上述路径改造后不再加载 `langchain_core`。守卫
`tests/unit/i18n/test_domains_lazy.py`（4 子进程断言）。跨三轮守卫全集 10 passed。

**收益边界**：真正用到 stream 错误分类时（服务运行中处理模型错误）langchain
仍会加载，但那时对启动无感。

## 3d. 第四轮：cron 交付链惰性导入（2026-11-18）

`_prepare_runtime()` 在监听后逐个 import 运行时模块，其中 `import happyclaw.infra.cron.manager`
实测 **7.62s**，是 `post_listen.imports` 里仅次于 harness 主树的第二块。用 `-X importtime`
拆开发现根因不在 apscheduler（仅 ~0.28s），而在 `cron/manager.py` 顶层导入
`CronDeliveryService` → `cron/delivery.py` 顶层导入了 `langchain_core.messages`、
`happyclaw.infra.gateway.process`、`happyclaw.infra.history.projection`、`knowledge.default_open`，
把 deepagents/langchain 整棵树拖进来（cumulative 5.3–6.3s）。

改动（`src/happyclaw/infra/cron/delivery.py`）：上述重符号全部改为在用到它们的
`_deliver_text` / `_deliver_agent` / `_build_agent_request` / `_attach_turn_knowledge_config`
内部局部导入；模块顶层只保留 i18n、errors、`gateway.threads`、轻量 utils。

**收益**（同环境 fresh 进程，各 3 次取中位）：

| 导入路径 | 改动前 | 改动后 | 收益 |
| --- | ---: | ---: | ---: |
| `import happyclaw.infra.cron.delivery` | 6.88s | 1.78s | **-5.10s（-74%）** |
| `import happyclaw.infra.cron.manager` | 7.62s | 2.12s | **-5.50s（-72%）** |

剩余 1.6s 来自 `gateway.threads` → `db.repos.sessions` → `happyclaw_gateway.models`（aiohttp/pydantic），
属共享基础设施，本轮不动。守卫：`tests/unit/test_import_lightweight.py` 新增
「cron manager 不拉 agent 栈」与「惰性化后符号仍可解析」两项；`tests/unit/cron` 157 passed。

**提交说明（2026-11-18）**：本轮落地时 `delivery.py` 工作区已叠加了用户的功能改动
（cron 运行历史/重试/补跑、无模型降级 note 等）。为避免污染功能代码，优化改动在
独立 worktree 的干净 HEAD 快照上重做，通过 `git update-index --cacheinfo` 只把
纯优化 blob 写进 index 提交（`690be820`），工作区混合文件全程未改动——提交后
功能改动仍是工作区的未提交 `M` 状态，两者互不干扰。守卫测试随后单独提交（`5d3ef9f6`）。
上表 A/B 数据来自同环境 worktree 隔离快照的改动前后对比；分离提交后在同一台机器复测，
绝对值随负载在 3.5–4.3s 波动，但「不拉 agent 栈」的不变式由守卫锁定。

## 3e. 第五轮：auth tokens 的 jwt 惰性导入（2026-11-19 凌晨）

对当前树重新 `-X importtime` 测绘发现，启动关键路径上还剩一条重链：
`happyclaw.api.app` → `api.deps` → `infra.auth.tokens` 顶层 `import jwt`，把
jwt + cryptography 整棵树（`cryptography.hazmat.bindings._rust` 等 40+ 模块）
拖进 app 工厂导入。SSO/MFA/captcha 模块不在启动链中（测绘确认无出现），
`tokens.py` 是启动路径上唯一的 jwt 入口。

改动（`src/happyclaw/infra/auth/tokens.py`）：顶层 `import jwt` 移除，改为在
`sign_token` / `decode_token` 内部局部导入；异常类捕获（`ExpiredSignatureError` /
`InvalidTokenError`）随局部导入走，模块顶层只保留 stdlib。

**收益**（`-X importtime` 结构对照，温态）：

| 模块累计 | 改动前 | 改动后 | 收益 |
| --- | ---: | ---: | ---: |
| `happyclaw.infra.auth.tokens` | 245.3ms | **4.1ms** | 树整体移出 |
| `happyclaw.api.deps` | 324.5ms | **110.7ms** | −213.8ms |

改后捕获中 jwt/cryptography 相关行**零出现**。jwt 树连同 cryptography 不再
进入 `import happyclaw.api.app` 的启动路径（对冻结包冷启动收益更大——冷态测绘中
该树累计 42.5s，几乎全是磁盘冷读；PYZ 内同样省去 40+ 模块的首次读取）。

**Wall-clock 说明（诚实记录）**：本轮 A/B 期间前端 vitest 全量测试正在同一台
机器上运行，fresh 进程 `import happyclaw.api.app` 绝对值在 3.2–4.8s 间波动，
前后中位数不可比；参照第四轮的处理方式，以 importtime 结构数据与守卫不变式
为准，待机器空闲后可复测绝对值。

守卫：`tests/unit/test_import_lightweight.py` 新增 2 项——「api.app 导入不拉
jwt/cryptography 栈」与「tokens 签名/解码往返 + 篡改拒绝仍正常（jwt 首用时
才加载）」；既有 token 功能单测 `tests/unit/auth/test_mfa_purpose.py` +
`tests/unit/api/test_jwt_tokens.py` 10 passed。既有 gateway 重符号解析守卫在
本轮负载下超时（与本次改动无交集，昨轮通过），待负载恢复复跑。

## 4. 局限与未做项

诚实说明，避免高估：

- 这些是**子模块级**改造，不是全进程热启动从 19.8s 降到个位数秒——那需要动 `infra/server.py` / `api/app.py`（当前有在途改动，本轮刻意不碰）。
- `apscheduler`（1.19s self）这条线未动：其顶层导入点 `infra/cron/manager.py` 有在途改动，避免制造冲突。
- 惰性化的收益在「首次真正用到该符号」时会以导入延迟的形式回来，但那时已在服务运行中、对 splash 无感。

## 5. 下一步（方案 2）

Rust 启动器 `tools/octop-launcher`：极速起进程 + 健康检查前置 + 后台预热，让 dashboard splash 更早切换，对外感知的「启动时间」进一步缩短。见后续提交。

## 6. 复现

```bash
# 测绘
.venv/Scripts/python.exe -X importtime -c "import happyclaw.infra.connectors.gateway" 2> imports.txt
.venv/Scripts/python.exe scripts/profile_imports.py imports.txt --top 25

# 守卫测试（三轮全部）
.venv/Scripts/python.exe -m pytest tests/unit/test_import_lightweight.py \
  tests/unit/test_httpx_lazy_patch.py tests/unit/i18n/test_domains_lazy.py -q

# 验证 i18n 惰性导出：导入不拉 langchain，符号仍可解析
.venv/Scripts/python.exe -c "import sys; import happyclaw.infra.errors; \
  assert 'langchain_core' not in sys.modules; \
  import happyclaw.i18n.domains as d; assert all(hasattr(d,s) for s in d.__all__); print('OK')"

# 验证 httpx 惰性补丁契约
.venv/Scripts/python.exe -c "import sys, octop; assert 'httpx' not in sys.modules; \
  import httpx; from httpx._utils import URLPattern; \
  assert getattr(URLPattern.matches, '_octop_cidr_no_proxy', False); print('OK')"

# fresh 进程 import octop 耗时（应 ~0.5s，改造前 ~2s）
.venv/Scripts/python.exe -c "import subprocess,time; \
  t=time.perf_counter(); subprocess.run(['.venv/Scripts/python.exe','-c','import octop']); \
  print('%.2fs' % (time.perf_counter()-t))"
```
