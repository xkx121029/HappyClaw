# S12 验收清单

## 后端

- [x] DSH 源可多条、可增删、可持久化：`config.json` → `plugin_market.dsh_sources`，实测重启后源仍在。
- [x] 提供 `GET /plugins/market/dsh`、`POST/DELETE /plugins/market/dsh/sources`、`POST /plugins/market/dsh/refresh`。
- [x] 安装/升级/卸载复用市集 pipeline，安装在 `<market_root>/dsh/<native>/<version>`，账本 `index.json`。
- [x] octop 市场接口 `/plugins/market` 与 `/plugins/market/{id}/install` 行为不变（回归测试与既有实现未改）。
- [x] DSH 与 octop 在数据结构上分离：DSH 走 `dsh_market_view`（sources/entries/runtime），不混入 `plugins.market` 列表。

## 前端

- [x] 插件市场顶部新增 DSH 区块：添加索引地址、源列表、删除、刷新。
- [x] 条目展示名称/说明/可用版本，版本下拉 + 安装 / 升级 / 卸载。
- [x] 无源空态明确说明「DSH 官方不提供索引，需自行填写静态 JSON 地址（format 1）」。
- [x] 安装后 `runtime.status !== "visible"` 时显示 warning + 错误码 + 原因，不出成功 toast。
- [x] 卸载返回 `cleaned=false` 时提示仍有其他版本残留。
- [x] 中英文文案齐备（`plugins.dsh.*`）。

## 诚实性

- [x] 缺 npm 依赖闭包：安装结果 `installed_not_ready`，`TOOL_RUNTIME_PLUGIN_NOT_LOADED`，原因写明缺失依赖名。
- [x] 索引格式错误：`PLUGIN_MANIFEST_INVALID` + `details.path`（如 `$.format`）。
- [x] 条目非法：明确 `details.path` 指向具体条目/字段，不静默丢弃。
- [x] 图标相对路径无法解析（file 源）：明确错误码与 path，源状态显示为 error。

## 验证

- [x] 本地 fixture 索引 + 动态 tgz（`tests/fixtures/dsh_market/serve.py`），未编造官方地址。
- [x] 完整流程：添加源 → 看到 2 个条目 → 安装 1.0.0 → 状态 visible → 升级 1.1.0 → 卸载（残留 1.0.0，cleaned=false）→ 卸载 1.0.0（cleaned=true，目录删除）。
- [x] 后端 8098 + 前端 5173 同时运行，页面模块经 dev server 编译通过。
- [x] `npx vite build` 更新 `src/octop/dashboard/assets`，产物包含 DSH 面板与文案 chunk。
- [x] `pip wheel .` 产出的 wheel 内含最新 assets 与 `market/sources/dsh.py`。
- [ ] 浏览器内逐项点击验收：本会话浏览器能力不可用（`browser_navigate` 返回 "inactive execution round"，子代理返回 "client does not support browser subagent isolation"），改为接口级 + 构建产物级验证，未声称已点击。
- [x] 未 commit、未 push。
