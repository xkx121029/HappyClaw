# Spec：模型侧提示词品牌清理（Octop → HappyClaw）

## 目标与范围

清掉所有会进入模型上下文的提示词文本里残留的 Octop 品牌自称，统一为 HappyClaw。

只改「面向模型的品牌与自称」。以下一律不动：

- 包名/模块名 `octop`、`octop_harness`、`octop_memory`、`octop_gateway`、`OctopError` 等代码标识符
- CLI 命令 `octop` 与 `python -m octop.cli.main`
- 路径 `~/.octop/`、`.octop/`、`/.octop/...`
- 环境变量 `OCTOP_*`、模板变量 `{{OCTOP_*}}`
- API 路径与请求头 `X-Octop-Agent-Id`、`X-Octop-Access-Token`
- 日志前缀、许可证与版权归属
- URL：`https://octop.cloud`、`https://docs.octop.cloud/...`、`https://download.octop.cloud/...`、GitHub 仓库地址

## 现状结论（已核实）

1. 默认专家 `library/happyclaw/{AGENTS,SOUL}.md`、`library/default/AGENTS.md` 的品牌自称已经是 HappyClaw 或无品牌；`persona/loader.py` 的通用人格模板无品牌。
2. 真正会进入每个 Agent 上下文的「通用」提示词是 **`experts/supplements/octop-assistant/SKILL.md`**：`install_supplements()` 会把 `supplements/*` 复制进每个工作区 `skills/<slug>/`，模型每次都能看到，且标题已是 `# HappyClaw Assistant`、正文仍是「你是 Octop 助手」。这是本次主修复点。
3. 专家库 `library/tencent-cvm-ops/` 的 SOUL/IDENTITY/SKILL/kb 里把「跑 Octop 的宿主机」作为产品自称使用，属于模型可见品牌，需改。
4. 规划类内置提示 `experts/manifest_generator_skill.md`（英文 system prompt）仍有 3 处 Octop。
5. 内置技能 `builtin_skills/skill-manager/scripts/manage_skills.py` 有一条工具结果文本 `cannot replace an Octop-owned built-in skill`，模型可见，需改。
6. 已安装的 `octop_harness`（`.venv`，非本仓库源码）中检索不到 `Octop` 品牌文本，无需也无法在本仓库修改。
7. 子代理库 `subagents/library/**` 无 Octop 品牌文本。

## 改动清单（逐文件）

### 1. `src/octop/infra/agents/experts/supplements/octop-assistant/SKILL.md`

保留：`octop` CLI、`~/.octop/`、`OCTOP_AGENT`、网址、GitHub 地址、`Octop Memory`/`Octop Harness`/`Octop Gateway`（组件/包名）。

| 行 | 原文片段 | 改为 |
|---|---|---|
| 4 | 帮助用户了解 Octop、解答产品与使用问题 | 帮助用户了解 HappyClaw、解答产品与使用问题 |
| 5 | Octop 是什么、能做什么 | HappyClaw 是什么、能做什么 |
| 10 | 即使用户只是问「Octop 是什么」或「怎么配置 octop」 | 即使用户只是问「HappyClaw 是什么」或「怎么配置 HappyClaw」 |
| 16 | `zh: "Octop 助手"` | `zh: "HappyClaw 助手"` |
| 19 | 介绍 Octop、解答使用问题 | 介绍 HappyClaw、解答使用问题 |
| 20 | Introduce Octop, answer usage questions | Introduce HappyClaw, answer usage questions |
| 25 | 你是 Octop 助手。先帮用户理解 Octop | 你是 HappyClaw 助手。先帮用户理解 HappyClaw |
| 27 | 与 LightClaw 不同，Octop 的 CLI | 与 LightClaw 不同，HappyClaw 的 CLI |
| 33 | 用户问「Octop 是什么」 | 用户问「HappyClaw 是什么」 |
| 39 | **Octop** 是开源、自托管的 AI 助手 | **HappyClaw** 是开源、自托管的 AI 助手 |
| 160 | 配置 Octop 时 | 配置 HappyClaw 时 |
| 172 | 本次对话的 Octop 用户 | 本次对话的 HappyClaw 用户 |
| 190 | 通道映射的 Octop 用户 id | 通道映射的 HappyClaw 用户 id |
| 304 | Octop 的 Provider 为**全局（管理员）**配置 | HappyClaw 的 Provider 为**全局（管理员）**配置 |
| 609 | 场景：Octop 是什么 / 能做什么 / 求助 | 场景：HappyClaw 是什么 / 能做什么 / 求助 |

不改：67 行 `基于 Octop Memory`、76 行 `Octop Harness`/`Octop Gateway`、85 行 GitHub 地址、全部 `octop` 命令与 `~/.octop/` 路径。

### 2. `src/octop/infra/agents/experts/manifest_generator_skill.md`（英文 system prompt）

| 行 | 原文 | 改为 |
|---|---|---|
| 3 | Generate bilingual Octop expert manifest metadata | Generate bilingual HappyClaw expert manifest metadata |
| 8 | manifest metadata Octop needs | manifest metadata HappyClaw needs |
| 142 | Octop may remap | HappyClaw may remap |

其余格式、语气、内容不动。

### 3. 专家库 `src/octop/infra/agents/experts/library/tencent-cvm-ops/`

只改「产品/宿主机自称」；`.octop/skills` 路径、`octop-<uid>` profile、`systemctl status octop`、域名都不动。

| 文件:行 | 原文片段 | 改为 |
|---|---|---|
| `IDENTITY.md:20` | 跑 Octop 的这台宿主机 | 跑 HappyClaw 的这台宿主机 |
| `SOUL.md:18` | 系统医生只看跑 Octop 的这台宿主机 | 系统医生只看跑 HappyClaw 的这台宿主机 |
| `SOUL.md:101` | 不要在 Octop 主机本地跑（那诊断的是 Octop 自己） | 不要在 HappyClaw 主机本地跑（那诊断的是 HappyClaw 自己） |
| `SOUL.md:240` | 跑 Octop 的这台宿主机自己出问题 | 跑 HappyClaw 的这台宿主机自己出问题 |
| `kb/06-TAT远程执行规范.md:76` | 不要在 Octop 主机本地跑这些脚本——那诊断的是 Octop 自己 | 不要在 HappyClaw 主机本地跑这些脚本——那诊断的是 HappyClaw 自己 |
| `skills/cvm-ai-doctor/SKILL.md:3` | 不在 Octop 宿主机上执行 | 不在 HappyClaw 宿主机上执行 |
| `skills/cvm-ai-doctor/SKILL.md:17` | 在 Octop 本机执行这些脚本，诊断的是 Octop 自己 | 在 HappyClaw 本机执行这些脚本，诊断的是 HappyClaw 自己 |
| `skills/cvm-ai-doctor/scripts/README.md:3` | 不在 Octop 本机上跑 | 不在 HappyClaw 本机上跑 |
| `skills/cvm-ai-doctor/references/skill-collaboration-tencentcloud.md:32` | 在 Octop 所在机器上编码 | 在 HappyClaw 所在机器上编码 |
| `skills/cvm-ai-doctor/references/cluster-quick-check.md:99` | 在 Octop 所在机器上编码 | 在 HappyClaw 所在机器上编码 |

### 4. 工具结果文本

`src/octop/infra/agents/builtin_skills/skill-manager/scripts/manage_skills.py:443`

- 原文：`"cannot replace an Octop-owned built-in skill: "`
- 改为：`"cannot replace a HappyClaw-owned built-in skill: "`

同步测试 `tests/unit/agents/test_octop_builtin_skills.py:196` 的断言 `"Octop-owned built-in"` → `"HappyClaw-owned built-in"`。

## 明确保留（剩余项，待用户确认）

| 位置 | 原句/片段 | 理由 |
|---|---|---|
| `experts/library/default/AGENTS.md:14` | 保存到 `octop-memory` | 记忆命名空间/标识符，属代码标识 |
| `octop-assistant/SKILL.md:67` | 基于 Octop Memory | 组件名，对应 `octop_memory` 包 |
| `octop-assistant/SKILL.md:76` | Octop Harness / Octop Gateway | 组件名，对应 `octop_harness` / `octop_gateway` 包 |
| `octop-assistant/SKILL.md:85` | github.com/TencentCloud/Octop | 仓库地址，属路径 |
| `experts/library/tencent-cvm-ops/MEMORY.md:8` | Octop 运行在腾讯云 CVM 上，域名 `<internal-host>`，服务 `systemctl status octop` | 该条绑定具体部署的域名与服务名；品牌词虽可改，但属「分不清」项，默认先保留，等用户确认 |
| `builtin_skills/skill-manager/SKILL.md` | `octop:` 元数据键、`{{OCTOP_SKILLS}}` 等 | 元数据键与模板变量，属代码标识 |
| `subagents/library/**` | 无 Octop | 无需改 |
| `tests/unit/trajectory/test_projector.py:145` | `You are Octop` | 测试用合成 prompt 夹具，不进入产品上下文 |
| `tests/unit/test_docker_entrypoint.py` | 密码样例 `Octop123` | 测试夹具 |
| `tests/unit/cli/*` | `Not applicable for Octop`、`Octop bootstrapped` | CLI 输出，非模型上下文 |
| `dashboard/src/locales/*.json` | `OctopBot`、`askOctopHint` 等 | 外部平台名/代码 key，且非模型上下文 |
| `plugins/**` | `octop_ui`、`octop:`、CLI 示例 | 协议/元数据/命令，属代码标识 |

## 验收与验证

1. 品牌扫描（模型可见文件）：
   - `src/octop/infra/agents/experts/**/*.md`、`src/octop/infra/agents/subagents/**/*.md`、`src/octop/infra/agents/builtin_skills/**/*.md`、`src/octop/infra/agents/persona/*.py` 中 `Octop[^A-Za-z_]` 仅剩上表「明确保留」项。
   - `manage_skills.py` 中不再有 `Octop-owned`。
2. 断言更新后运行：
   - `.venv\Scripts\python.exe -m pytest tests/unit/agents/test_octop_builtin_skills.py tests/unit/agents/test_default_agent.py tests/unit/agents/test_library_quick_prompts.py tests/unit/i18n/test_skills.py tests/integration/test_setup_bootstrap.py -q`
   - 如涉及提示词模板，再跑 `tests/unit/agents/test_manifest_generator.py`（若存在）。
3. 不改 dashboard、不改 `.venv`、不提交。

## 非目标 / 边界

- 不重命名 `octop` 包、CLI、目录、环境变量、API 头。
- 不修改 `.venv` 内已安装的 `octop_harness`（检索确认无 Octop 品牌文本）。
- 不改 dashboard 的 UI 文案与非模型可见的日志/错误信息。
- 不改写提示词风格、不补内容、不调整段落结构。
