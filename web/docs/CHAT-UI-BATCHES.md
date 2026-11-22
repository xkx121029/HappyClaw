# Chat UI 批次（B5a / B5b / B5c）

前提：聊天逻辑层由 `happyclaw/chat-logic` 提供，落在
`web/src/features/chat/{lib,store,hooks}`。本文只描述**界面侧**要改的东西，三个批次
都不修改那三个目录。

## B5a · 消息列表与历史

| 动作 | 文件 |
| --- | --- |
| 改 | `components/MessageList.tsx`（重写为虚拟列表宿主）、`ChatPage.tsx`（接线）、`queries.ts`（改游标分页） |
| 新 | `message/MessageRow.tsx`、`message/ToolCallRow.tsx`（骨架）、`message/useAutoScroll.ts`、`message/useVirtualMessages.ts` |
| 依赖 | `@tanstack/react-virtual` |

验收断言：

1. 打开线程首屏渲染 N 条，且 `scrollTop` 在底部；
2. 滚到顶部触发一次 `GET .../history?cursor=`，两次都 200 且条数增加；
3. **切换 `:threadId` 时 `ChatPage` 不重挂载**（`useRef` 计数断言为 1）——防的正是历史滚回顶部这类回归；
4. 输入框草稿切换后仍在。

## B5b · 输入、工具卡与 HITL

| 动作 | 文件 |
| --- | --- |
| 改 | `Composer.tsx`（接逻辑层发送队列与取消）、`MessageList` 内工具卡、`useChatSocket.ts` 改为消费逻辑层流（不再"发完重取历史"） |
| 新 | `composer/ModelPicker.tsx`、`composer/ModePicker.tsx`、`composer/AttachmentTray.tsx`、`hitl/ApprovalCard.tsx`、`hitl/QuestionCard.tsx` |

验收断言：

1. 发送后 DOM 出现流式追加的助手节点（`data-streaming="true"`），结束时属性消失；
2. 中途刷新能续上同一回合（`turn_active` 为真时不重复发送）；
3. HITL 卡片「批准/拒绝」可点，点击后 `POST .../chat/hitl/resume` 返回 200，且卡片
   **保留 `data-hitl-state="resolved"` 一小段时间再消失**——用户要能确认自己点上了。

## B5c · 预览与渲染器

| 动作 | 文件 |
| --- | --- |
| 改 | 消息体渲染换 markdown 管线；预览宿主从 `ChatFilePreviewContext` 迁到 `preview/` |
| 新 | `preview/Markdown.tsx`、`preview/PdfPreview.tsx`、`preview/DocxPreview.tsx`、`preview/SheetPreview.tsx`、`preview/MonacoViewer.tsx` + 各自的懒加载入口 |

依赖与体积纪律：react-markdown / remark-gfm / remark-math / rehype-katex / mermaid 直接
引入；`react-pdf`、`docx-preview`、`xlsx`、`@monaco-editor/react` 四个大件**全部按文件
类型动态 import**。硬指标：**首屏 JS 增量 ≤ 15kB gzip**。哪个渲染器把首屏顶超了，就砍掉
它、先用「下载文件」兜底，理由写进报告。

验收断言：

1. 首屏增量 ≤ 15kB gzip；
2. 上传 PDF / DOCX / XLSX 各一，预览容器有内容节点且无控制台错误；
3. 含 `$$` 公式与 mermaid 块的消息渲染出 `.katex` / `<svg>` 节点。

## 通用门禁

每批：`tsc` = 0、`lint` = 0、`check:i18n` = 0、`build` = 0，浏览器侧 0 控制台错误，
相关接口全部 200。
