/**
 * Shared sample content for the three visual directions.
 *
 * The same records feed all three proposals, so a reviewer compares design and
 * not copy. Everything here is illustrative — the direction pages label it
 * `示例数据` so nobody mistakes it for a live thread.
 */

export type TraceState = "done" | "running" | "waiting";

export interface Trace {
  tool: string;
  target: string;
  meta: string;
  state: TraceState;
}

export interface Turn {
  id: string;
  role: "user" | "agent";
  time: string;
  /** Paragraphs; a line starting with "code:" is rendered as a mono block. */
  body: string[];
  traces?: Trace[];
  tokens?: string;
  streaming?: boolean;
}

export interface Thread {
  id: string;
  title: string;
  stamp: string;
  turns: number;
  tools: number;
  state: "running" | "settled" | "review";
}

export const agent = {
  name: "HappyClaw",
  role: "本机 · 默认智能体",
  model: "claude-fable-5-2",
  workspace: "~/happyclaw/workspace",
};

export const threads: Thread[] = [
  {
    id: "pool",
    title: "gateway 连接池泄漏排查",
    stamp: "14:02",
    turns: 8,
    tools: 12,
    state: "running",
  },
  {
    id: "recall",
    title: "memory 召回率重跑一遍",
    stamp: "11:36",
    turns: 14,
    tools: 31,
    state: "settled",
  },
  {
    id: "dryrun",
    title: "迁移脚本 dry-run 复盘",
    stamp: "昨天",
    turns: 6,
    tools: 9,
    state: "review",
  },
  {
    id: "front",
    title: "HAPA-20 前端遗留项",
    stamp: "周二",
    turns: 22,
    tools: 40,
    state: "settled",
  },
  {
    id: "posix",
    title: "browser 的 POSIX 强杀测试",
    stamp: "周一",
    turns: 9,
    tools: 15,
    state: "settled",
  },
];

export const turns: Turn[] = [
  {
    id: "t1",
    role: "user",
    time: "14:02:11",
    body: [
      "飞书长连接下 gateway 的 websocket 连接池会缓慢泄漏，帮我定位回收路径。先别改代码，我只要结论和最小补丁的范围。",
    ],
  },
  {
    id: "t2",
    role: "agent",
    time: "14:02:19",
    tokens: "1,204 tok · 0.8s",
    body: [
      "回收路径分成两段，泄漏点在第二段：`acquire()` 记了租约，但 `release()` 只在正常退出时触发，`asyncio.CancelledError` 绕过了它。",
      "复现条件是连接被服务端先关掉：此时读循环抛取消异常，连接对象留在 `_pool` 里，而 `finally` 只关 socket 不注销租约。",
    ],
    traces: [
      {
        tool: "read_file",
        target: "src/happyclaw_gateway/pool.py",
        meta: "1,204 tok · 0.8s",
        state: "done",
      },
      {
        tool: "grep",
        target: "pool.acquire(",
        meta: "12 处 · 4 个文件",
        state: "done",
      },
      {
        tool: "pytest",
        target: "tests/test_pool.py -k recycle",
        meta: "3 passed · 6.4s",
        state: "done",
      },
    ],
  },
  {
    id: "t3",
    role: "user",
    time: "14:05:40",
    body: ["按你列的第二条来，写一个最小补丁。补丁要能被现有测试覆盖，不要新增依赖。"],
  },
  {
    id: "t4",
    role: "agent",
    time: "14:05:52",
    tokens: "已生成 1 个补丁 · 待批准",
    streaming: true,
    body: [
      "补丁只动 `_lease` 的生命周期：把注销放进 `finally`，并在取消异常上补一次 `await self._drain(conn)`，共三处改动。",
      "code:async def _release(self, conn: Conn) -> None:\n    try:\n        await self._drain(conn)\n    finally:\n        self._leases.discard(conn.id)\n        self._pool.append(conn)",
    ],
    traces: [
      {
        tool: "apply_patch",
        target: "src/happyclaw_gateway/pool.py",
        meta: "3 处改动 · +11 −4",
        state: "waiting",
      },
    ],
  },
];

export const instrument = {
  contextUsed: 8.4,
  contextMax: 32,
  toolCalls: 12,
  tokensIn: "18,204",
  tokensOut: "3,916",
  elapsed: "3m 41s",
  approvals: 1,
};

export const traceLog = [
  { time: "14:02:19", text: "read_file pool.py" },
  { time: "14:02:24", text: "grep pool.acquire(" },
  { time: "14:02:31", text: "pytest -k recycle" },
  { time: "14:05:52", text: "apply_patch 待批准" },
];

export interface Swatch {
  name: string;
  role: string;
  /** Token read back from the live stylesheet, so the printed hex is real. */
  token: string;
}

export const palette: Swatch[] = [
  { name: "canvas", role: "页面底", token: "--hc-bg-canvas" },
  { name: "surface", role: "面板", token: "--hc-bg-surface" },
  { name: "sunken", role: "凹槽", token: "--hc-bg-sunken" },
  { name: "line", role: "分隔线", token: "--hc-border-default" },
  { name: "fg", role: "正文", token: "--hc-fg-default" },
  { name: "fg-muted", role: "次级", token: "--hc-fg-muted" },
  { name: "accent", role: "强调", token: "--hc-accent-default" },
  { name: "success", role: "成功", token: "--hc-success-default" },
  { name: "warning", role: "警告", token: "--hc-warning-default" },
  { name: "danger", role: "危险", token: "--hc-danger-default" },
];

export const typeScale = [
  { token: "--hc-text-2xs", size: "11", use: "徽标、密集元信息" },
  { token: "--hc-text-xs", size: "12", use: "说明、表头" },
  { token: "--hc-text-sm", size: "13", use: "密集界面、次级正文" },
  { token: "--hc-text-base", size: "14", use: "默认界面文字" },
  { token: "--hc-text-md", size: "16", use: "阅读正文" },
  { token: "--hc-text-lg", size: "18", use: "小节标题" },
  { token: "--hc-text-xl", size: "21", use: "页面标题" },
  { token: "--hc-text-2xl", size: "26", use: "展示" },
];

export const radii = [
  { token: "--hc-radius-xs", use: "徽标内角" },
  { token: "--hc-radius-sm", use: "小控件" },
  { token: "--hc-radius-md", use: "输入框、按钮" },
  { token: "--hc-radius-lg", use: "卡片" },
  { token: "--hc-radius-xl", use: "浮层" },
  { token: "--hc-radius-2xl", use: "大面板" },
];

export const spacingScale = [
  { token: "space-1", px: "4" },
  { token: "space-2", px: "8" },
  { token: "space-3", px: "12" },
  { token: "space-4", px: "16" },
  { token: "space-6", px: "24" },
  { token: "space-8", px: "32" },
  { token: "space-12", px: "48" },
];

export const tableRows = [
  { key: "pool.py", scope: "gateway", cost: "1,204", state: "已读" },
  { key: "test_pool.py", scope: "tests", cost: "486", state: "通过" },
  { key: "lease.py", scope: "gateway", cost: "312", state: "已读" },
  { key: "feishu.py", scope: "channel", cost: "2,048", state: "跳过" },
];
