# S4 任务清单

## T1 bridge 增补（可单独回退）
- [ ] `bridge/errors.py`：加 `TOOL_SANDBOX_DENIED`、`TOOL_SANDBOX_NOT_ASSEMBLED`
- [ ] `bridge/approval.py`：加 `SANDBOX_COVERAGE_UNAVAILABLE`；`SandboxBacking.inspected`；
      `ApprovalRecord.sandbox_inspected`；`from_probe` 读 inspected + 接受 unavailable；
      `_check_capability` 读取 `bridge_code`（缺省行为不变）

## T2 sandbox 三态 + 是否检查过
- [ ] `sandbox/inspection.py`：`SandboxCoverage.UNAVAILABLE`；`SandboxProbeResult.inspected/bridge_code`
- [ ] `sandbox/absence.py`：放行分支 coverage 改 `UNAVAILABLE`
- [ ] `sandbox/gate.py`：`_inspect` 四处显式 `inspected`

## T3 DSH 层接线
- [ ] 新增 `dsh/tools/sandbox.py`：`DshSandboxState` / `SandboxProbe` /
      `build_capability_probe` / 告警去重 / 非法策略降级 strict
- [ ] `dsh/tools/guardrail.py`：删 stub，`capability` 必填
- [ ] `dsh/tools/catalog.py`：新增 4 个可选参数，收 `sandboxes`，`report()` 出 `sandbox`
- [ ] `dsh/tools/__init__.py`：导出
- [ ] `agents/manager.py`：传 agent 工作区 + 缺席开关读数

## T4 测试
- [ ] 更新 3 个既有测试（coverage 断言、guardrail 必填探针）
- [ ] 新增 `tests/unit/infra/dsh/test_tools_sandbox.py`（8 条）

## T5 验证
- [ ] `pytest tests/unit/plugins_sandbox tests/unit/plugins_bridge tests/unit/infra/dsh tests/dsh_integration -q`
- [ ] 贴结果
