# Tasks：设备链路能力接成 Agent 工具

> 顺序执行，每步可独立验证。完成后勾选。
> 复验日期：2026-11-14（只跑测试，未提交、未动暂存区）。

- [x] T1 `manager.py`：新增同步 `is_online()` / `is_paired()`（`_ensure_client().online`、`credential_summary() is not None`）。
  验证：`python -c` 导入并调用不报错。
  > 复验：`DeviceLinkManager(tmp_path).is_online() → False`、`is_paired() → False`，无异常；两个方法均为同步且内部吞异常（`manager.py:117` / `manager.py:124`）。
- [x] T2 新增 `device_link/agent_tools.py`：6 个 StructuredTool + `DEVICE_LINK_TOOL_NAMES` +
  `device_link_interrupt_on()` + `describe_device_action()`。
  验证：`pytest tests/unit/device_link/test_agent_tools.py -q`（T6 先写）。
  > 复验：`10 passed`（`test_agent_tools.py` 全绿）；`DEVICE_LINK_TOOL_NAMES` 长度 6。
- [x] T3 新增 `middleware/device_link_gate.py`：离线时从 `request.tools` 剔除；异常吞掉放行。
  验证：单测覆盖在线/离线两分支。
  > 复验：`test_gate_hides_device_tools_when_offline`、`test_gate_keeps_device_tools_when_online` 均 PASSED。
- [x] T4 `manager.py`：按 `is_paired()` 挂载工具、追加中间件、在 `apply_session_bypass` 之后合并
  `device_link_interrupt_on()`。
  验证：启动日志无异常；`device_link_interrupt_on()` 在配置里可见（可用 REPL 检查）。
  > 复验：`device_link_interrupt_on()` 返回 `phone_tap` / `phone_swipe` / `phone_type_text` 三个副作用工具（`approve`/`reject`）；`test_side_effect_tools_require_one_time_approval` 与 `test_approval_description_names_coordinates_and_target` 均 PASSED。未单独起服务看启动日志，由单测覆盖。
- [x] T5 `tool_catalog.py`：新增 `_DEVICE_LINK_TOOLS` 与 6 个 catalog 条目；`builtin_tool_available`
  增加 `device_link_enabled` 参数并更新调用方。
  验证：`pytest tests/unit -q -k "tool_catalog"`；面板工具设置不报错。
  > 复验：直接跑 `pytest tests/unit/agents/test_tool_catalog.py -q` → `9 passed`；同名模块冲突已在 T7 修掉，全树选择跑同样通过。
- [x] T6 新增 `tests/unit/device_link/test_agent_tools.py`：成功/失败/离线/摘要截断/审批配置/中间件过滤。
  验证：全绿。
  > 复验：`10 passed`，覆盖成功、失败码透传、离线 fail-closed、`ui_tree` 截断、审批配置、中间件过滤。
- [x] T7 全量回归：`python -m pytest tests/unit/device_link tests/unit -q -k "device_link or tool_catalog or hitl"`。
  > 复验（2026-11-14，修复后）：**194 passed, 5081 deselected**（59.64s），收集阶段不再中断。
  > 修复：新增 `tests/unit/device_link/__init__.py`（空文件），让该目录按包名 `device_link.test_agent_tools`
  > 收集，与 `tests/unit/agents/test_agent_tools.py` 的模块名 `test_agent_tools` 不再冲突；
  > 与仓内既有做法一致（`tests/unit/dsh/`、`tests/unit/infra/dsh/`、`tests/unit/migration/` 均有 `__init__.py`）。
  > 同时验证：`pytest tests/unit --collect-only -q` → **5275 tests collected**，退出码 0。
- [ ] T8 现场联调（假设备 linklab 在线）：
  - 对话内触发截图 + 元素树，确认工具调用出现在对话流、产物路径存在且为 PNG；
  - 断开链路后确认工具不可见 / 调用返回 `DEVICE_OFFLINE`；
  - 触发点击 → 审批卡 → 批准后设备状态文件变化（假设备记录），拒绝则无变化。
  > 未执行：本轮只跑单测，没有起后端 + 假设备 linklab，故不勾选。
- [ ] T9 里程碑汇报：`send_message_to_session`，结论写「链路已通、真机未验」。
  > 未执行：依赖 T8 的联调结论，等 T8 完成后再汇报。
