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
| cumulative | `octop.infra.server` → `octop_harness` → `deepagents`/`langchain` | ~13.5s | 拖入整棵 LangChain 树 |
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
| 启动期加载 langchain_core / octop_harness / cryptography | 全部加载 | **均不加载** |
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
| fresh `import octop.api.app` | 4.246s | 2.974s | **-1.27s（-30%）** |

守卫：`tests/unit/test_httpx_lazy_patch.py`（独立子进程断言 octop 导入不加载
httpx、后续导入仍打补丁、CIDR 绕代理有效、hook 幂等）。相关单测 20 passed。

**收益边界（诚实说明）**：`octop run` 主流程本来就要 import httpx 发 LLM 请求，
这部分延迟只是从「进程启动」移到「首次请求前」，总时长不变；真正省下的是
不发网络的路径——CLI 元命令（`--help`/`--version`）、pytest 收集、插件扫描、
以及任何只 import octop 做配置/检查的场景。

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
.venv/Scripts/python.exe -X importtime -c "import octop.infra.connectors.gateway" 2> imports.txt
.venv/Scripts/python.exe scripts/profile_imports.py imports.txt --top 25

# 守卫测试
.venv/Scripts/python.exe -m pytest tests/unit/test_import_lightweight.py \
  tests/unit/test_httpx_lazy_patch.py -q

# 验证 httpx 惰性补丁契约
.venv/Scripts/python.exe -c "import sys, octop; assert 'httpx' not in sys.modules; \
  import httpx; from httpx._utils import URLPattern; \
  assert getattr(URLPattern.matches, '_octop_cidr_no_proxy', False); print('OK')"

# fresh 进程 import octop 耗时（应 ~0.5s，改造前 ~2s）
.venv/Scripts/python.exe -c "import subprocess,time; \
  t=time.perf_counter(); subprocess.run(['.venv/Scripts/python.exe','-c','import octop']); \
  print('%.2fs' % (time.perf_counter()-t))"
```
