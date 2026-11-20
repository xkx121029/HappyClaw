# Spec：把设备链路能力接成 Agent 可调用工具

## 目标
让 HappyClaw 在对话里真实调用手机能力（截图、点击、滑动、输入、元素树、应用列表），
结果（成功/失败、耗时、产出物）回流到对话；设备离线或链路未开时工具不出现，绝不假装能控制。

## 非目标
- 不引入 AgentEngine、规划、记忆、提示词、env/PRoot。
- 不新建传输通道；复用 `/api/device-link/*` 与 `protocol.json`。
- 不改设备侧协议、不改 `D:\xkx\xkx_appproj\happy_phone agent`。
- 不做应用商店分发。

## 关键决策

### D1 工具清单与命名（6 个）
| 工具名 | 协议命令 | 类型 |
|---|---|---|
| `phone_screenshot` | `screen.screenshot` | 只读 |
| `phone_ui_tree` | `screen.tree` | 只读 |
| `phone_list_apps` | `app.list` | 只读 |
| `phone_tap` | `ui.click` | 有副作用 |
| `phone_swipe` | `ui.swipe` | 有副作用 |
| `phone_type_text` | `ui.typeText` | 有副作用 |

### D2 可用性（三档，全部 fail-closed）
1. **未配对**（无 `credentials.json`）：构建 agent 配置时直接不挂载这 6 个工具。
2. **已配对但离线**：工具已挂载，但 `DeviceLinkToolGateMiddleware` 在每次模型调用前把它们从
   `request.tools` 中剔除 → 模型看不见，不会幻调。
3. **调用瞬间掉线**（模型已开始生成、中间件判定在线后设备断开）：工具内部兜底返回
   `{"ok": false, "code": "DEVICE_OFFLINE", ...}`，不执行动作。这是竞态兜底，不是主路径：
   主路径是第 2 档——离线时工具从 `request.tools` 中消失，模型根本看不到。

硬约束：**设备离线时 6 个工具一律不出现在工具列表里，不允许"先出现再报错"。**

"开关" 的口径 = 链路是否已配对 + 是否 online（面板上的连接/断开即开关），不新增第三个开关。

### D3 一次性审批
- 只对 3 个有副作用工具生效，`allowed_decisions = ["approve", "reject"]`。
- 审批文案为动态 callable，必须写明**具体元素或坐标**：
  - tap：`即将在手机屏幕点击坐标 (x, y)（设备像素），会触发该位置的控件，可能跳转页面或提交表单。`
  - swipe：`即将在手机屏幕上从 (x1, y1) 滑动到 (x2, y2)，耗时 Nms，会滚动列表或触发手势。`
  - type_text：有 `x/y` 时写 `即将在坐标 (x, y) 的输入框覆写文本「…」`；无坐标时写
    `即将向当前焦点输入框覆写文本「…」（原内容会被替换）`。
- 合并顺序：在 `apply_session_bypass(...)` **之后** 合并，确保即使全局 HITL 关闭或会话选了
  allow-all，设备副作用动作仍然逐次审批（硬约束，不静默执行）。
- 实现采用**独立挂载的 `HumanInTheLoopMiddleware(interrupt_on=device_link_interrupt_on())`**：
  实测 `cfg.interrupt_on` 会被 harness 在未 bootstrap 等情况下静默丢弃，直接挂中间件才能保证
  审批一定生效；该中间件随设备工具一起仅在已配对时加入。

### D4 结果结构
只读成功：
```json
{"ok": true, "tool": "phone_screenshot", "command": "screen.screenshot",
 "duration_ms": 187, "artifact": "C:\\...\\device-link\\screenshots\\<ts>-<id>.png",
 "width": 1080, "height": 2400}
```
`phone_ui_tree` 给摘要而非整棵树：
```json
{"ok": true, "duration_ms": 142,
 "summary": {"package": "com.android.settings", "screen": "1080x2400", "node_count": 87,
             "elements": [{"text": "...", "viewId": "...", "bounds": "[..]", "clickable": true}]}}
```
（`elements` 截断到 40 条，并给 `truncated: true`）
`phone_list_apps`：`{"ok": true, "count": N, "apps": [{package,label}]}`（截断 200）。
失败：`{"ok": false, "tool": ..., "command": ..., "code": "TIMEOUT|DEVICE_OFFLINE|...",
"message": "...", "retryable": bool, "duration_ms": N}`。
耗时一律取自 `run_command` 的 `duration_ms`，不估算。

### D5 ID / 幂等 / 超时
- 每次工具调用生成新的 `command_id`（`new_short_id`），一次调用只发一次。
- 不自动重试；模型若重试则显式说明并用新 `command_id`（避免静默重复执行）。
- 超时使用 `run_command` 默认（协议默认值），失败按 `TIMEOUT` 原样上报。

### D6 权限
沿用面板的 `mobile` 权限口径：工具内部通过 `configurable.user` / `user_is_admin` 校验
`mobile` 权限，缺失则返回 `DENIED` 错误（不抛异常打断对话）。

## 文件与改动

### 1) 新增 `src/octop/infra/control/device_link/agent_tools.py`
- 常量：`DEVICE_LINK_TOOL_NAMES`、`DEVICE_LINK_READONLY_TOOLS`、`DEVICE_LINK_SIDE_EFFECT_TOOLS`。
- `build_device_link_tools(config, *, user_repo) -> list[StructuredTool]`
  - 每个工具：同步校验权限 → `await manager.run_command(...)` → 按 D4 整形返回 JSON 字符串。
  - 截图读 `result` 里的 `sizeBytes` + PNG 宽高（从 PNG IHDR 读 16~23 字节，读不到就省略）。
  - 元素树/应用列表做摘要与截断。
- `device_link_interrupt_on() -> dict[str, Any]`：3 个副作用工具的 HITL 配置（含中文描述 callable）。
- `describe_device_action(tool_call, state, runtime) -> str`。

### 2) 改 `src/octop/infra/control/device_link/manager.py`
- 新增同步方法 `is_online() -> bool`（`self._ensure_client().online`）。
- 新增同步方法 `is_paired() -> bool`（`credential_summary() is not None`）。

### 3) 新增 `src/octop/infra/agents/middleware/device_link_gate.py`
- `DeviceLinkToolGateMiddleware`：`wrap_model_call` / `awrap_model_call` 中若
  `not get_device_link_manager().is_online()`，用 `request.override(tools=[...])` 剔除非在线工具；
  异常一律吞掉并放行（不得因链路状态阻断对话）。

### 4) 改 `src/octop/infra/agents/manager.py`
- 在 `mobile_tools` 附近按 `is_paired()` 构建 `device_tools`（try/except 兜底）。
- `merged_tools.extend(device_tools)`。
- 配置阶段当 `device_tools` 非空时，把 `DeviceLinkToolGateMiddleware()` 加入 `agent_middleware`。
- 在 `apply_session_bypass(...)` 之后合并 `device_link_interrupt_on()`（见 D3）。

### 5) 改 `src/octop/infra/agents/settings/tool_catalog.py`
- 新增 `_DEVICE_LINK_TOOLS` 与 6 个 `BuiltinToolEntry(..., "mobile")`。
- `builtin_tool_available(*, device_link_enabled=False)` 增加该分支；同步更新调用方传参
  （先 grep `builtin_tool_available(` 找到唯一调用点）。

### 6) 新增 `tests/unit/device_link/test_agent_tools.py`
- 假 manager（monkeypatch 模块内 `get_device_link_manager`）验证：
  成功 envelope、失败码透传、离线拒绝、元素树摘要截断、截图 artifact 路径、
  `device_link_interrupt_on()` 恰好包含 3 个副作用工具且 `allowed_decisions == ["approve","reject"]`、
  middleware 离线时剔除工具/在线时保留。

## 验证
1. `python -m pytest tests/unit/device_link -q` 全绿；`python -m pytest tests/unit -q -k "tool_catalog or hitl"` 不回归。
2. 链路在线（linklab 假设备）时，对话里发「截个屏并给我元素树摘要」，确认：
   - 出现 `phone_screenshot` / `phone_ui_tree` 工具调用；
   - 截图返回绝对路径且文件存在、`file` 魔数为 PNG；耗时 > 0；
   - 元素树返回 packageName 与节点摘要。
3. 设备断开后同一对话再请求，工具不再出现在可选工具里；直接调用返回 `DEVICE_OFFLINE`。
4. 点击类请求弹出审批卡（文案含坐标与影响），批准后才下发 `ui.click`；拒绝则不下发。
5. 结论如实标注：假设备跑通 = 「链路已通、真机未验」。

## 风险
- 审批 UI 在 WS 流里的确认路径需现场确认；若脚本化审批受阻，改由面板手工批准并如实记录。
- 截图路径为宿主机绝对路径，模型无法直接读图；本轮只要求「给路径」，不额外做工作区拷贝。
