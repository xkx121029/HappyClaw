# S4：把沙箱探针从 stub 换成真实 `PluginSandbox.probe`

## 1. 问题

S2 给每个挂载的 DSH 工具绑定的 capability 探针是
`dsh/tools/guardrail.py::_read_only_capability`，恒定返回
`CapabilityDecision(available=True, reason="read-only ...")`。它没有检查任何东西，
审批记录里的 `sandbox_backed` 因此永远是 `False`、`sandbox_coverage` 永远是 `unknown`，
「有没有沙箱背书」在记录里看不出来，探针形同虚设。

## 2. 目标（逐条对应本次要求）

1. 权限来源 = 插件清单自己声明的 `PluginEnvelope.permissions`，不是主机另行授予；
   未声明就是空集，按最小权限处理（`PluginSandbox` 现有语义）。
2. 探针在审批之前；沙箱拒绝后直接拒绝，不再请求审批（`ToolGuardrail.evaluate`
   的 capability → risk → approval 顺序已满足，本次补测试锁定）。
3. 覆盖状态三分：`covered`（检查过并通过）/ `not_applicable`（沙箱在，但该工具
   没有声明可检查的参数）/ `unavailable`（沙箱没装配）。三者写入审批记录的
   `sandbox_coverage`，`sandbox_backed` 仅 `covered` 时为 `True`。
   另加 `sandbox_inspected`：声明了可检查参数但实际参数里一个都没匹配上时为 `True`
   且 `checked == ()`，用来和「压根没有检查计划」区分开。
4. 沙箱缺席默认「告警放行」，可用开关切成「拒绝」；进程内必须恰好出现一次明确告警，
   且 `dsh_tools_status()` 能看到当前 mode 与每个插件是否装配。拒绝码
   `TOOL_SANDBOX_NOT_ASSEMBLED` 与路径越界的 `TOOL_SANDBOX_DENIED` 不同。
5. 拒绝后工具不执行，拒绝原因出现在工具结果正文（`Error: <reason>`），而不是只写日志。

## 3. 决策

- **权限**：`permissions=tuple(envelope.permissions)` 原样交给 `PluginSandbox`；
  工具级声明默认取同一集合（DSH 没有逐工具声明文件，插件清单是唯一声明源）。
  主机可以逐工具收窄/声明能力（fixture 用）；声明超出插件权限即被
  `PERMISSION_UNDECLARED` / `PERMISSION_OUT_OF_SCOPE` 拒绝。
- **可检查参数**：DSH 清单不描述「哪个参数是路径/命令」，因此由主机以
  `inspections` 显式提供；未提供即 `not_applicable`，不猜测。
- **三个状态**：`SandboxCoverage` 新增 `UNAVAILABLE`；`SandboxAbsenceGate`
  的放行结果由 `NOT_APPLICABLE` 改为 `UNAVAILABLE`（沙箱确实不在）。
- **缺席开关**：`OCTOP_DSH_SANDBOX_ABSENCE`（`allow` 默认 / `strict`），
  复用现有 `resolve_absence_mode`；**未知值按更严一侧处理**：降级为 `strict`
  并打一条明确告警，既不放行也不静默。
- **状态可见**：`build_capability_probe` 返回带 `state` 的 `SandboxProbe`
  （`plugin_id` / `assembled` / `mode` / `reason`），`DshToolBuild` 收集后由
  `report()` 输出 `sandbox` 段，`manager.dsh_tools_status()` 直接可见。
- **错误码**：`DshToolErrorCode` 新增 `TOOL_SANDBOX_DENIED`、
  `TOOL_SANDBOX_NOT_ASSEMBLED`。真实沙箱的任何拒绝 → `TOOL_SANDBOX_DENIED`
  （reason 内含原始沙箱码，如 `SANDBOX_PATH_OUTSIDE_WORKSPACE`）；
  缺席 + strict → `TOOL_SANDBOX_NOT_ASSEMBLED`。
- **映射位置**：现代码在 DSH 工具层（`dsh/tools/sandbox.py`）把
  `SandboxProbeResult` 翻译成 bridge 错误码，沙箱包本身不反向依赖 DSH。
- **删除 stub**：`_read_only_capability` 删除；`build_read_only_guardrail`
  改为必须传入 `capability`，不提供「默认放行」的后门。未传探针时
  `ToolGuardrail` 原本就按 `TOOL_CAPABILITY_UNAVAILABLE` 拒绝。
- **工作区根**：`manager._dsh_plugin_tools` 传 agent 工作区
  （`workspace_for_agent_row(row, paths=self._paths)`，该函数不建目录）。
  解析失败 → `sandbox_root=None` → 走缺席闸门，不影响启动。

## 4. 改动清单（精确到函数）

### 4.1 `src/happyclaw/infra/plugins/bridge/errors.py`
- `DshToolErrorCode` 增加：
  - `TOOL_SANDBOX_DENIED = "TOOL_SANDBOX_DENIED"`
  - `TOOL_SANDBOX_NOT_ASSEMBLED = "TOOL_SANDBOX_NOT_ASSEMBLED"`

### 4.2 `src/happyclaw/infra/plugins/bridge/approval.py`
- 增加常量 `SANDBOX_COVERAGE_UNAVAILABLE = "unavailable"`，加入 `__all__`。
- `SandboxBacking` 增加 `inspected: bool = False`；`from_probe` 读取
  `raw.inspected`（非 bool 视为 False），合法 coverage 集合改为
  `{covered, not_applicable, unavailable}`，其余仍归一为 `unknown`。
- `ApprovalRecord` 增加 `sandbox_inspected: bool`，`to_dict()` 同步；
  `ToolGuardrail._record` 从 `backing.inspected` 填。
- `ToolGuardrail._check_capability`：`raw.available is False` 时，
  若 `raw.bridge_code` 是 `DshToolErrorCode` 实例则用它，否则维持
  `TOOL_CAPABILITY_UNAVAILABLE`（纯 `CapabilityDecision` 行为不变）。
- 不改变 evaluate 的层序（capability 先于 approval）。

### 4.3 `src/happyclaw/infra/plugins/sandbox/inspection.py`
- `SandboxCoverage` 增加 `UNAVAILABLE = "unavailable"`。
- `SandboxProbeResult` 增加字段 `inspected: bool = False`、
  `bridge_code: DshToolErrorCode | None = None`
  （从 `happyclaw.infra.plugins.bridge.errors` 导入，无循环：bridge 不导入 sandbox）。

### 4.4 `src/happyclaw/infra/plugins/sandbox/absence.py`
- `SandboxAbsenceGate.probe` 放行分支 coverage：
  `NOT_APPLICABLE` → `UNAVAILABLE`（allow 与 strict 的「不需要权限」分支都改）。
- 拒绝分支保持 `error_code=SANDBOX_NOT_ASSEMBLED`。

### 4.4b `src/happyclaw/infra/plugins/sandbox/gate.py`
- `_inspect` 三处 `SandboxProbeResult` 明确 `inspected`：
  - readiness 拒绝（还没走到参数检查）→ `False`；
  - 无检查计划 / 计划为空 → `False`；
  - 有检查计划但参数里没匹配到（`checked == ()`）→ `True`；
  - 实际检查过（含检查中途被拒 `SandboxDeniedError`）→ `True`。

### 4.5 新增 `src/happyclaw/infra/dsh/tools/sandbox.py`
- 常量 `ENV_SANDBOX_ABSENCE = "OCTOP_DSH_SANDBOX_ABSENCE"`。
- `DshSandboxState(plugin_id, assembled, mode, reason)` + `to_dict()`。
- `SandboxProbe(state, probe)`：可调用，转调 `probe` 并补 `bridge_code`。
- `resolve_absence_mode_strict(raw)`：调 `resolve_absence_mode`；非法值 →
  `STRICT` + 一条 warning（不静默、不放行）。
- `build_capability_probe(*, plugin_id, permissions, tool_names,
  declarations=None, workspace_root=None, inspections=None, absence_mode=None)`
  → `SandboxProbe`：
  1. `declared = {tool: declarations.get(tool, plugin_permissions) for tool in tool_names}`。
  2. `workspace_root` 非空：构造
     `PluginSandbox(plugin_id=..., workspace_root=..., declarations=declared,
     permissions=plugin_permissions, inspections=inspections or {})`；
     构造失败（`SandboxConfigError` 或其它异常）→ 记 warning，转缺席闸门，
     `state.assembled=False` 且 `reason` 写明构造失败原因。
  3. 否则：`SandboxAbsenceGate(mode=..., plugin_id=..., required_capabilities=declared)`；
     按 `(plugin_id, mode)` 去重，进程内恰好告警一次（allow 与 strict 文案不同）。
  4. 包装 probe：`available is False` 时
     `error_code is SANDBOX_NOT_ASSEMBLED` → `TOOL_SANDBOX_NOT_ASSEMBLED`，
     其余 → `TOOL_SANDBOX_DENIED`，用 `dataclasses.replace` 写入 `bridge_code`。

### 4.6 `src/happyclaw/infra/dsh/tools/guardrail.py`
- 删除 `_read_only_capability`。
- `build_read_only_guardrail` 增加必填关键字参数 `capability: CapabilityProbe`，
  传给 `ToolGuardrail(capability=capability, ...)`。
- 其余风险/审批逻辑不动。

### 4.7 `src/happyclaw/infra/dsh/tools/catalog.py`
- `build_dsh_plugin_tools` 新增可选参数：
  `sandbox_root: str | Path | None = None`、
  `capability_declarations: Mapping[str, Mapping[str, Iterable[str]]] | None = None`、
  `inspections: Mapping[str, Mapping[str, ToolInspection]] | None = None`、
  `sandbox_absence: str | None = None`。
- `DshToolBuild` 增加 `sandboxes: list[DshSandboxState]`；`report()` 增加
  `"sandbox": {"mode": <本次解析的 mode>, "assembled": <全部插件是否都已装配>,
  "plugins": [...]}`，`manager.dsh_tools_status()` 原样透出。
- `_mount_plugin`：按 exposed 名生成 inspections 映射（输入键为 native 名，
  未知工具名忽略并 warning），调用 `build_capability_probe(...)`，把 `.probe`
  传给 `build_read_only_guardrail(capability=...)`，把 `.state` 记入 build。
- 组装失败仍然整体兜底成 `discovery_failed`（不变）。

### 4.8 `src/happyclaw/infra/dsh/tools/__init__.py`
- 导出 `ENV_SANDBOX_ABSENCE`、`build_capability_probe`。

### 4.9 `src/happyclaw/infra/agents/manager.py`
- `_dsh_plugin_tools`：解析 agent 工作区（`workspace_for_agent_row`，try/except），
  将 `sandbox_root` 与 `sandbox_absence=os.environ.get("OCTOP_DSH_SANDBOX_ABSENCE")`
  传给 `build_dsh_plugin_tools`。开关、provider 注入、HITL 接线均不动。

### 4.10 测试更新
- `tests/unit/plugins_sandbox/test_sandbox.py`：缺席放行的 coverage 断言
  `NOT_APPLICABLE` → `UNAVAILABLE`。
- `tests/unit/infra/dsh/test_tools_hitl.py`、`test_tools_mount.py`：
  `build_read_only_guardrail` 调用补 `capability=_passing_probe`
  （测试替身，返回 `SandboxProbeResult(True, ..., NOT_APPLICABLE)`）。

### 4.11 新增 `tests/unit/infra/dsh/test_tools_sandbox.py`
用 `write_package` + `fixture_tool` 覆盖：
1. **路径越界被拒**：插件 `permissions=("fs.read",)`，工作区 tmp，inspections
   `{"echo": ToolInspection(path_args=("path",))}`，参数 `{"path": "../x.txt"}`
   → 结果 `is_error`，`code == TOOL_SANDBOX_DENIED`，正文含
   `SANDBOX_PATH_OUTSIDE_WORKSPACE`，`executed == []`，审批通道 `requests == []`。
2. **未声明权限被拒**：插件 `permissions=()`，主机声明该工具需要 `fs.read`
   → `TOOL_SANDBOX_DENIED`，正文含 `SANDBOX_PERMISSION_UNDECLARED`，不执行。
3. **沙箱缺席 allow**：`sandbox_root=None`、`sandbox_absence="allow"`，
   HITL 开启 → 调用成功执行；审批记录 `sandbox_coverage == "unavailable"`、
   `sandbox_backed is False`；`caplog` 中恰好一条「沙箱未启用」告警；
   `build.report()["sandbox"]["mode"] == "allow"`、`assembled is False`。
4. **沙箱缺席 strict**：同上但 `"strict"` → `TOOL_SANDBOX_NOT_ASSEMBLED`，
   不执行、不请求审批，正文含「沙箱未启用」；状态查询 mode == "strict"。
5. **正常放行 + 背书**：插件 `permissions=("fs.read",)`，参数路径在工作区内 →
   执行成功；审批记录 `sandbox_coverage == "covered"`、`sandbox_backed is True`、
   `sandbox_checked == ("path",)`、`sandbox_inspected is True`。
6. **检查计划存在但参数没覆盖**：有 inspections 但调用参数不含 `path`
   → 放行、`sandbox_coverage == "not_applicable"`、`sandbox_inspected is True`、
   `sandbox_checked == ()`；与「无检查计划」记录的 `sandbox_inspected is False` 相区分。
7. **沙箱拒绝不进入审批**（与 1 合并断言通道零请求）。
8. **非法缺席策略**：`sandbox_absence="bogus"` → 按 strict 处理并告警，
   状态 mode == "strict"。

## 5. 回退

- 关掉 `OCTOP_DSH_TOOLS`：整段不生效，与 S2 前一致。
- 单独回退 `dsh/tools/sandbox.py` + `catalog.py` 的接线：恢复 stub 探针即可，
  但 `guardrail.py` 的必填 `capability` 需一并回退（同一提交内）。
- bridge/sandbox 的改动均为增量：`bridge_code` 缺省为空、coverage 新值不被旧调用读取。

## 6. 验证

```
.\.venv\Scripts\python.exe -m pytest tests/unit/plugins_sandbox tests/unit/plugins_bridge tests/unit/infra/dsh tests/dsh_integration -q
```

验收标准：上述四组全绿；新增 6 条用例覆盖要求中的四种 fixture 场景；
审批记录字段可直接读出三种 coverage。

## 7. 已确认的取舍（按「更严一侧」执行）

1. 默认「工具能力声明 = 插件 permissions」，主机可按工具收窄/声明；声明超出插件
   权限一律拒绝（`PERMISSION_UNDECLARED` / `PERMISSION_OUT_OF_SCOPE`）。
2. `build_read_only_guardrail` 的 `capability` 改为必填，删除默认放行 stub；
   未装配探针即 `TOOL_CAPABILITY_UNAVAILABLE`，不放行。
3. 缺席开关变量名 `OCTOP_DSH_SANDBOX_ABSENCE`（`allow`/`strict`）；非法值降级
   `strict` 并告警，不静默放行。
