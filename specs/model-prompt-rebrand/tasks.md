# Tasks：模型侧提示词品牌清理（Octop → HappyClaw）

## T1 通用助手技能（主修复）

- [x] `src/octop/infra/agents/experts/supplements/octop-assistant/SKILL.md`：按 spec 改动表替换 15 处品牌自称（frontmatter description/summary/label、正文「你是 Octop 助手」、产品介绍、用户身份、Provider、场景标题）。
- [x] 保留 `octop` CLI、`~/.octop/`、`OCTOP_*`、全部 URL、GitHub 地址、`Octop Memory`/`Octop Harness`/`Octop Gateway` 组件名。
- [x] 不改写语气、段落、表格与文档结构。

## T2 规划类内置提示

- [x] `src/octop/infra/agents/experts/manifest_generator_skill.md`：第 3、8、142 行 `Octop` → `HappyClaw`，英文语气不变。

## T3 专家库提示词

- [x] `src/octop/infra/agents/experts/library/tencent-cvm-ops/IDENTITY.md`：1 处。
- [x] `.../SOUL.md`：第 18、101、240 行 3 处。
- [x] `.../kb/06-TAT远程执行规范.md`：1 处。
- [x] `.../skills/cvm-ai-doctor/SKILL.md`：第 3、17 行 2 处。
- [x] `.../skills/cvm-ai-doctor/scripts/README.md`：1 处。
- [x] `.../skills/cvm-ai-doctor/references/skill-collaboration-tencentcloud.md`：1 处。
- [x] `.../skills/cvm-ai-doctor/references/cluster-quick-check.md`：1 处。
- [x] 保留 `.octop/skills`、`octop-<uid>`、`systemctl status octop`、域名。

## T4 工具结果文本与测试断言

- [x] `src/octop/infra/agents/builtin_skills/skill-manager/scripts/manage_skills.py:443`：`an Octop-owned` → `a HappyClaw-owned`。
- [x] `tests/unit/agents/test_octop_builtin_skills.py:196`：断言同步为 `HappyClaw-owned built-in`。

## T5 复查与测试

- [x] 扫描模型可见文件中的 `Octop[^A-Za-z_]`，逐条对照 spec「明确保留」清单；新增遗漏则补改或列入待确认。
- [x] 运行：
  `.venv\Scripts\python.exe -m pytest tests/unit/agents/test_octop_builtin_skills.py tests/unit/agents/test_default_agent.py tests/unit/agents/test_library_quick_prompts.py tests/unit/i18n/test_skills.py tests/integration/test_setup_bootstrap.py -q`
- [x] 若存在 `tests/unit/agents/test_manifest_generator.py` 一并运行。
- [x] 输出：改动清单、剩余项（文件/行/原句/理由）、测试结果、未动边界。

## 交付边界

- 不改 dashboard、不改 `.venv`、不 git commit/push。
- 不重命名包/CLI/路径/环境变量/API 头。
