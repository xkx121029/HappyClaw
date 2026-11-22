# S2 规格：DSH 插件工具进入工具列表（只读、默认零行为）

- 仓库：`e:\HAPPYclaw\Octop`
- 阶段：S2（工具可见性）
- 前置：S1 开关骨架、S8 模型适配器均已落地
- 本文只描述将要做的改动；**未经批准不写生产代码**

---

## 1. 目标（与用户六条要求一一对应）

| # | 要求 | 本规格的落点 |
| --- | --- | --- |
| 1 | 发现源：市场安装根 current slot + 本地插件目录，复用现有适配器 | `discovery.py` 只用 `MarketInstallSource.installed_slots()` 与 `DshPluginLoader.discover()` |
| 2 | 只挂只读工具；写/外联一律不挂；必须能回答「为什么被跳过」 | `gate.py` 真的按 `PermissionKind` 过滤；`DshToolSkip(reason, detail)` 全部上报，无静默过滤 |
| 3 | 必须走 bridge 管道；HITL 仅在 `OCTOP_DSH_HITL` 开启时审批，关闭时高危拒绝 | 一律 `registry.build_pipeline(guardrail=ToolGuardrail(...))`；`approval=None` 时 `TOOL_APPROVAL_UNAVAILABLE` 拒绝 |
| 4 | 插入点只在 `manager.py` 的 `merged_tools` 合并处 | `_build_harness_config` 中 `merged_tools.extend(plugin_tools)` 之后一个 `# dsh:stage-tools` 块 |
| 5 | fixture 跑通「模型请求工具 → 执行 → 结果回对话」；名字冲突明确处理 | `tests/dsh_integration/test_tools_end_to_end.py`；冲突 → `name_conflict` 跳过并记录，绝不覆盖 |
| 6 | 关闭时：不发现、不 import、不改 `merged_tools`，`sys.modules` 证明 | `test_tools_switch.py` 断言 `happyclaw.infra.dsh.tools*` 不在 `sys.modules`，且工具列表与基线逐项相等 |

---

## 2. 已确认的现状（读码结论）

1. `MarketInstallSource(dest_root).installed_slots() -> dict[str, InstalledSlot]`，`InstalledSlot` 有 `.slot: Path` 与 `.envelope: PluginEnvelope`；`broken() -> Mapping[str, str]` 记录账本指向失败的条目。只读 ledger 的 `current`，不解析 manifest（`profile/market_source.py:74-124`）。
2. `DshPluginLoader.discover(roots=..., strict=False) -> list[PluginEnvelope]`，非法 manifest 只记 warning（`runtime/dsh_plugin.py`）。
3. `PluginEnvelope` 携带 `capabilities: tuple[CapabilityKind,...]` 与 `permissions: tuple[PermissionKind,...]`，另有 `metadata["permissions_source"]`（`manifest` / `undeclared`）。`PermissionKind` 取值：`fs.read` / `fs.write` / `exec` / `network`。
4. `DshToolRegistry(plugin_id="dsh:<native>")`：
   - `register(definition, scope=...)` 同 scope 重名抛 `DshToolError(TOOL_DEFINITION_INVALID)`；
   - `exposed_name(native) -> "dsh__<native>__<tool>"`（超 64 字符加哈希后缀）；
   - `build_pipeline(scope=..., guardrail=...) -> ToolPipeline`；
   - `to_structured_tools(scope=..., pipeline=...) -> list[StructuredTool]`，保留完整 `args_schema`。
5. `ToolPipeline.invoke` 顺序固定：参数快照 → JSON Schema 校验 → `guardrail.evaluate` → pre hooks → checkpoint → dispatch → output.schema 校验 → render → post hooks → 大小限制。**无法绕过**，只要工具由 `to_structured_tools` 生成。
6. `ToolGuardrail(capability=..., approval=..., assessor=..., baseline_risk=LOW, approval_threshold=MEDIUM)`：
   - `capability is None` → `TOOL_CAPABILITY_UNAVAILABLE` 拒绝；
   - 风险 ≥ 阈值且 `approval is None` → `TOOL_APPROVAL_UNAVAILABLE` 拒绝（不是放行）；
   - `approval` 通道会带 `pause_exceptions` 自动穿透。
7. `manager.py:4535` 为 `merged_tools.extend(plugin_tools)`；`merged_tools` 此时已含 cron / knowledge / mobile / plugin 工具，可直接作为保留名集合。
8. `DshToolRegistry` 的 `plugin_id` 必须 `dsh:` 前缀，否则构造即抛错。

### 2.1 关键事实：工具体只能来自进程内

DSH 包的载体是 `package.json` + `cordis.patch.yml` + `index.js`（`tests/dsh_integration/fixtures/plugins/dsh_fixture/`），**仓库内没有任何「声明式工具清单」解析器**，也不允许在 S2 执行 JS。因此：

- 插件身份、版本、能力、权限全部来自现有适配器（要求 1 满足）；
- 工具体（`ToolDefinition`）由调用方通过 **provider** 注入，provider 键是插件 id（`dsh:<native>`）。
- 没有 provider 的插件 → 不挂载，并产生 `no_tool_provider` 跳过记录（可回答「为什么没出现」）。

这是 S2 唯一不臆造清单格式的做法；S3/S4 接真实 JS 运行时后，provider 换成运行时桥即可，上层不变。

---

## 3. 新增文件

### 3.1 `src/happyclaw/infra/dsh/tools/__init__.py`

导出：`DshToolBuild`、`DshToolSkip`、`DshToolProvider`、`build_dsh_plugin_tools`、`discover_dsh_plugins`、`DshToolCatalogStatus`（见 3.4）、原因常量。

### 3.2 `src/happyclaw/infra/dsh/tools/discovery.py`

```python
ORIGIN_MARKET = "market"
ORIGIN_LOCAL = "local"

@dataclass(frozen=True, slots=True)
class DshToolSkip:
    plugin_id: str
    origin: str
    reason: str
    detail: str = ""
    tool: str = ""         # 冲突/定义非法时的工具名，便于按工具查询
    def to_dict(self) -> dict[str, str]

@dataclass(frozen=True, slots=True)
class DiscoveredPlugin:
    """已通过只读过滤、可以进入挂载流程的插件。"""
    plugin_id: str
    origin: str
    location: str          # slot / manifest 目录，绝对路径字符串
    envelope: PluginEnvelope

def discover_dsh_plugins(
    *,
    market_root: str | Path | None = None,
    local_roots: Sequence[str | Path] = (),
) -> tuple[list[DiscoveredPlugin], list[DshToolSkip]]:
```

实现要点：
- **过滤发生在发现阶段**：`is_tool_plugin` 与 `blocking_permissions` 在这里判定；声明了 `fs.write` / `exec` / `network` 的插件**不进入候选列表**，也不建 registry、不查 provider，只产一条 `DshToolSkip`。
- `market_root` 非空 → `MarketInstallSource(Path(market_root))`，取 `installed_slots()` 中 `kind is PluginKind.DSH` 的项；`broken()` 每项产 `DshToolSkip(reason="install_broken", detail=<原消息>)`。`installed_slots()` 默认适配器含 Octop+DSH，这里不再自建适配器。
- `market_root` 不存在 / 不可读 → `DshToolSkip(plugin_id="", origin="market", reason="market_root_missing", detail=<路径>)`，返回空候选，**不抛**。
- 账本 `index.json` 缺失或 JSON 坏：`installed_slots()` 会静默跳过。因此发现器枚举 `<market_root>/dsh/*` 目录，与 `installed_slots()` / `broken()` 的覆盖集合做差；每个未覆盖目录产 `DshToolSkip(reason="market_slot_unreadable", detail="no readable current slot in index.json")`。这里只判断「有没有被适配器解析出来」，不自行解析账本内容。
- `local_roots` 非空 → `DshPluginLoader().discover(roots=list(local_roots), strict=False)`；只保留 `PluginKind.DSH`。
- 去重顺序：market 优先。本地同 id → `DshToolSkip(reason="duplicate_plugin_id", detail="already provided by market")`。
- 任一发现源抛异常 → 捕获，转成 `DshToolSkip(reason="discovery_failed", detail="类型:消息")` 并记 warning；发现结果照常返回（不因为一个源坏掉影响启动）。
- 全部只读：不写盘、不 import 插件代码、不执行 JS。

### 3.3 `src/happyclaw/infra/dsh/tools/gate.py`

```python
SKIP_NOT_TOOL = "not_tool_capability"
SKIP_UNSAFE_PERMISSION = "unsafe_permission"
SKIP_NO_PROVIDER = "no_tool_provider"
SKIP_PROVIDER_FAILED = "tool_provider_failed"
SKIP_DEFINITION_INVALID = "tool_definition_invalid"
SKIP_NAME_CONFLICT = "name_conflict"
SKIP_INSTALL_BROKEN = "install_broken"
SKIP_MARKET_ROOT_MISSING = "market_root_missing"
SKIP_MARKET_SLOT_UNREADABLE = "market_slot_unreadable"
SKIP_DISCOVERY_FAILED = "discovery_failed"
SKIP_DUPLICATE = "duplicate_plugin_id"

BLOCKING_PERMISSIONS = (PermissionKind.FS_WRITE, PermissionKind.EXEC, PermissionKind.NETWORK)

def blocking_permissions(envelope: PluginEnvelope) -> tuple[PermissionKind, ...]
def permission_name(kind: PermissionKind) -> str          # "fs.write"
def is_tool_plugin(envelope: PluginEnvelope) -> bool
```

规则：
- 必须有 `CapabilityKind.TOOL`；否则 `not_tool_capability`。
- **声明里出现任一** `fs.write` / `exec` / `network` → `unsafe_permission`，`detail` 写全部命中项（逗号分隔），`tool=""`，`plugin_id` 为插件 id。该判定在**发现阶段**执行，命中的插件不会进入候选、不会查 provider、不会建 registry（「连发现都别挂进来」）。
- `fs.read` 与「未声明权限」都放行（最小权限，且 S2 不提供写/执行后端）。
- 不做「推断权限」：只看 `envelope.permissions`。
- 所有跳过记录都带 `plugin_id`，冲突/定义类再带 `tool`，因此「某个插件因为什么被跳过」可按插件或按工具直接查。

### 3.4 `src/happyclaw/infra/dsh/tools/guardrail.py`

```python
READ_ONLY_NOTE = "read-only DSH tool: no fs.write/exec/network declared"

def _read_only_capability(tool_name: str, arguments: Mapping[str, Any]) -> CapabilityDecision:
    return CapabilityDecision(available=True, reason=READ_ONLY_NOTE)

def build_read_only_guardrail(
    *,
    hitl: bool,
    approval: ApprovalChannel | None = None,
    risky_tools: Mapping[str, tuple[str, ...]] = {},
    ledger: ApprovalLedger | None = None,
) -> ToolGuardrail:
```

- `capability=_read_only_capability`（S4 前没有沙箱后端；这里只对「已通过只读过滤的工具」放行）。
- `assessor`：工具名在 `risky_tools` 且带任何阻断权限 → `RiskAssessment(HIGH, "declares fs.write")`；否则 `LOW(READ_ONLY_NOTE)`。未知工具名 → `HIGH` 且给理由（fail-closed，不会触发「无理由升级」错误）。
- `approval = approval if hitl else None`。**关闭 HITL 时高危调用得到 `TOOL_APPROVAL_UNAVAILABLE` 拒绝**（`approval.py:476-484`）。
- `baseline_risk=LOW`，`approval_threshold=MEDIUM`，`ledger` 透传。

### 3.5 `src/happyclaw/infra/dsh/tools/catalog.py`

```python
ToolProvider = Callable[[PluginEnvelope], Sequence[ToolDefinition]]

@dataclass
class DshToolBuild:
    tools: list[StructuredTool] = field(default_factory=list)
    mounted: list[str] = field(default_factory=list)   # plugin ids
    skipped: list[DshToolSkip] = field(default_factory=list)
    def report(self) -> dict[str, Any]               # {"tools": [...names], "mounted": [...], "skipped": [ {...} ]}

def build_dsh_plugin_tools(
    *,
    scope: str,
    market_root: str | Path | None = None,
    local_roots: Sequence[str | Path] = (),
    providers: Mapping[str, ToolProvider],
    hitl: bool,
    approval: ApprovalChannel | None = None,
    reserved_names: Iterable[str] = (),
) -> DshToolBuild
```

逐插件流程（输入已是 §3.2 过滤后的候选；每个插件独立 `DshToolRegistry(plugin_id=envelope.id)`，互不影响）：
1. provider 不存在 → `no_tool_provider`；provider 抛异常 → `tool_provider_failed`（`detail=类型:消息`，不向上冒泡）。
2. 逐条 `registry.register(definition, scope=scope)`；`DshToolError` → `tool_definition_invalid`（`tool=<原生名>`，整插件跳过，已注册的丢弃）。
3. 冲突：`exposed_name` 已在 `reserved`（内置/其它插件）→ 该工具不挂，记 `name_conflict`，`plugin_id` + `tool=<暴露名>` 双留痕，`detail` 写出冲突对象；**不覆盖、不加二次前缀**。
4. `pipeline = registry.build_pipeline(scope=scope, guardrail=build_read_only_guardrail(hitl=hitl, approval=approval, risky_tools=...))`；`tools += registry.to_structured_tools(scope=scope, pipeline=pipeline)`。
5. `mounted.append(plugin_id)`，暴露名加入 `reserved`。

整个 `build_dsh_plugin_tools` 外层包一层 `try/except Exception`：任何未预期异常 → warning 日志 + 一条 `discovery_failed` 跳过记录 + 返回空 `DshToolBuild`。**S2 永远不会让 `_build_harness_config` 抛错或启动失败。**

`risky_tools` 由插件 `permissions` 生成：S2 已过滤掉阻断权限，正常情况为空；保留参数是为了让 S3 放开部分权限时审批语义已就位，并让「HITL 关闭时高危拒绝」可单测。

---

## 4. 改动 `src/happyclaw/infra/agents/manager.py`

### 4.1 插入点（唯一）

`_build_harness_config` 内：

```python
        plugin_tools = build_plugin_tools(...)   # 原样
        ...
        merged_tools.extend(plugin_tools)
        # dsh:stage-tools — 唯一插入点。关闭时不 import、不发现、不改列表。
        from happyclaw.infra.dsh import switches as dsh_switches
        if dsh_switches.stage_enabled("tools"):
            merged_tools.extend(self._dsh_plugin_tools(row, reserved=tuple(merged_tools)))
```

- `switches` 是 stdlib-only 模块，关闭时只多一次 dict 查找。
- `_dsh_plugin_tools` 内部才 `from happyclaw.infra.dsh.tools import build_dsh_plugin_tools`。

### 4.2 新增方法

```python
    def register_dsh_tool_provider(self, plugin_id: str, provider: DshToolProvider) -> None:
        """登记某个 dsh:<native> 插件的工具体。S2 唯一的工具体入口。"""

    def _dsh_plugin_tools(self, row: AgentRow, *, reserved: Sequence[Any]) -> list[Any]:
        from happyclaw.infra.dsh.tools import build_dsh_plugin_tools
        build = build_dsh_plugin_tools(
            scope=str(row.id),
            market_root=os.environ.get("OCTOP_DSH_MARKET_ROOT") or None,
            local_roots=_dsh_local_roots(),          # OCTOP_DSH_TOOL_ROOTS 逗号分隔
            providers=self._dsh_tool_providers,
            hitl=stage_enabled("hitl"),
            reserved_names={str(getattr(t, "name", "")) for t in reserved if getattr(t, "name", "")},
        )
        self._dsh_tools_status = build
        for skip in build.skipped:
            logger.info("dsh tool skipped: %s (%s) %s", skip.plugin_id, skip.reason, skip.detail)
        return list(build.tools)

    def dsh_tools_status(self) -> dict[str, Any]:
        """只读状态：哪些 ref/插件走了适配器、跳过原因。"""
        if self._dsh_tools_status is None:
            return {"enabled": stage_enabled("tools"), "mounted": [], "skipped": [], "tools": []}
        return {"enabled": True, **self._dsh_tools_status.report()}
```

- `__init__` 初始化 `self._dsh_tool_providers: dict[str, DshToolProvider] = {}` 与 `self._dsh_tools_status: DshToolBuild | None = None`。
- **provider 注入是可选参数**：默认空字典；未注入时不产生任何工具，行为与改动前一致（只多一次开关判定与一次空目录发现）。
- **不在模块导入期发现**：`manager.py` 顶层不 import `happyclaw.infra.dsh.tools`；发现只发生在 `_dsh_plugin_tools()` 内，即 `stage_enabled("tools")` 为真且 `_build_harness_config` 被调用时。
- `_dsh_local_roots()` 为模块级小函数：读 `OCTOP_DSH_TOOL_ROOTS`，空则 `()`。不设默认目录，避免扫描用户主目录。

### 4.3 状态查询

`dsh_tools_status()` 返回：

```python
{
  "enabled": bool,
  "mounted": ["dsh:demo"],
  "tools": ["dsh__demo__echo"],
  "skipped": [{"plugin_id": "dsh:x", "origin": "market", "reason": "unsafe_permission",
               "detail": "exec", "tool": ""}],
}
```

`skipped` 逐条保留 `plugin_id` / `reason` / `detail` / `tool`，可回答「某个插件因为什么被跳过」「某个工具名为什么没上」。

---

## 5. 零行为证明（要求 6）

1. 单测：`monkeypatch.delenv("OCTOP_DSH_RUNTIME")` + `manager._build_harness_config(_row())`，断言：
   - 返回的 `cfg.tools` 与同条件基线逐项 `name` 相等（`dsh_` 前缀数量为 0）；
   - `"happyclaw.infra.dsh.tools" not in sys.modules`，且 `happyclaw.infra.dsh.tools.catalog` 同样不在；
   - `manager._dsh_tools_status is None`。
2. 若环境此前已 import 过（同进程其它测试），测试内先 `pop` 相关模块并断言前后一致；用 `monkeypatch.setitem(sys.modules, ...)` 不适用，改为「只断言本次调用未新增」：调用前后取 `set(sys.modules)` 差集，断言不含 `happyclaw.infra.dsh.tools` 前缀。
3. provider 未注入（默认）时，即便开关打开，工具列表也只多出零项；`dsh_tools_status()` 中每个被发现的插件都有 `no_tool_provider` 或 `unsafe_permission` 记录，没有静默丢弃。

---

## 6. 测试计划

### 6.1 `tests/unit/infra/dsh/test_tools_discovery.py`
- 市场根 fixture：`<tmp>/dsh/demo/index.json`（`current.slot="1.0.0"`）+ `1.0.0/package.json` + `cordis.patch.yml` → 发现 `dsh:demo`，`origin=market`。
- 同一插件同时出现在 market 与 local → 只保留 market，local 产生 `duplicate_plugin_id`。
- 账本指向不存在 slot → `install_broken` 跳过记录（`broken()` 被转成 skip）。
- `market_root` 不存在 → `market_root_missing`，候选为空，**不抛**。
- `index.json` 内容非法 JSON → `market_slot_unreadable`，候选为空，**不抛**。
- 非 DSH 能力（无 `tool`）→ `not_tool_capability`。
- 声明 `permissions: [fs.read]` → 进入候选；`[fs.read, network]` → `unsafe_permission`、`detail` 含 `network`、**不进入候选**。
- 全程不产生文件写入（对比 tmp 目录快照）。

### 6.2 `tests/unit/infra/dsh/test_tools_mount.py`
- fixture provider 返回 `echo` 工具 → 暴露名 `dsh__demo__echo`，出现在 `build.tools`。
- 通过 `await tool.ainvoke({"text": "hi"})` 走完整管道：
  - 合法参数 → 返回文本；
  - 缺必填参数 → `TOOL_INVALID_ARGUMENTS`（证明 schema 校验未被绕过）；
  - `on_event` 记录到 `tool/call` 与 `tool/result` 各一条。
- 声明 `exec` 的插件：provider 计数器保持 0（**发现阶段就剔除，provider 未被调用**），`skipped` 里有 `unsafe_permission`。
- provider 抛异常 → `tool_provider_failed`，不挂载，不影响其它插件。
- 保留名冲突（`reserved={"dsh__demo__echo"}`）→ `skipped` 含 `reason="name_conflict"`、`plugin_id="dsh:demo"`、`tool="dsh__demo__echo"`；`build.tools` 为空，原有工具未被覆盖。
- HITL 关闭 + `risky_tools={"dsh__demo__echo": ("exec",)}` → 调用返回 `TOOL_APPROVAL_UNAVAILABLE`，provider 内部计数器为 0（未执行）。
- HITL 开启 + 假 approval 返回 `allowed-once` → 执行成功、approval 被调用一次；返回 `rejected` → `TOOL_APPROVAL_DENIED`。

### 6.3 `tests/unit/infra/dsh/test_tools_switch.py`
- 开关关闭：见 §5。
- 开关打开但 provider 为空（默认注入态）：工具列表仍为基线（所有插件 `no_tool_provider`），`dsh_tools_status()` 能列出跳过原因。
- 开关打开且发现源抛异常 → `_build_harness_config` 正常返回，`dsh_tools_status()["skipped"]` 含 `discovery_failed`。

### 6.4 `tests/dsh_integration/test_tools_end_to_end.py`
- 建一个 fixture 插件目录（复用 `fixtures/plugins/dsh_fixture`，换 `plugin.json` 的 `metadata.tools` 不需要）与内存 provider；
- 用假 chat model 产出一次 `tool_call`（`dsh__demo__echo`），经 `StructuredTool.ainvoke` 执行，断言：
  - 工具名出现在传给模型的工具列表；
  - 执行结果文本进入下一轮消息（模拟「结果回到对话」）；
  - `merged_tools` 中原有工具数量不变（只增不减，且无覆盖）。

---

## 7. 验收命令

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/infra/dsh tests/unit/dsh tests/unit/plugins_bridge tests/dsh_integration -q
```

要求：全绿；新增用例数 ≥ 18；关闭态用例证明零 import。

---

## 8. 风险与未确认

1. **未确认**：生产环境市场安装根尚无落点（`MarketInstallSource` 在 `src/happyclaw` 内无构造）。S2 因此只认 `OCTOP_DSH_MARKET_ROOT`，不猜目录；S9 接市场时统一。
2. **未确认**：真实 DSH 插件的工具体格式。S2 用 provider 注入；不执行 JS、不解析未定义的清单字段。
3. `CapabilityDecision` 无法表达 `not_applicable` 覆盖度，`SandboxBacking` 会记为 `unknown/backed=False`；S2 不开启 `require_sandbox_backing`，不影响执行，S4 再补真实探针。
4. 工具名最长 64 字符，`DshToolRegistry.exposed_name` 已有哈希兜底，不另写逻辑。

---

## 9. 已确认的决定

- A. 工具体走 **provider 注入**；注入为可选参数，未注入时行为与现状一致；不在模块导入期发现插件。
- B. 市场根只读 `OCTOP_DSH_MARKET_ROOT`，只认 `index.json` 的 `current` slot；读不到/目录不存在/JSON 坏 → 不挂工具 + 一条原因，不抛、不影响启动。
- C. 冲突处理：**跳过 + 双留痕**（`plugin_id` + `tool`），不加二次前缀、不覆盖。
- D. 只改 `manager.py` 一个插入点 + 新增 `infra/dsh/tools/` 包，不动 harness 包。
- E. 写/执行/外联能力的插件在**发现阶段**即剔除，不进入候选、不查 provider、不建 registry。
