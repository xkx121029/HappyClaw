import type { Agent, Thread, ThreadHistory } from "./types";

/**
 * Sample data used only when the backend does not answer, so the new shell can
 * be reviewed (and screenshotted) on a machine where HappyClaw is not running.
 * Everything the UI renders from here is labelled "Sample data" in the toolbar;
 * the moment any request succeeds the mock is discarded.
 */
const now = Math.floor(Date.now() / 1000);

export const mockAgents: Agent[] = [
  {
    agent_id: "agt_happyclaw",
    name: "HappyClaw",
    description: "Local owner agent",
    state: "running",
    default_model: "claude-sonnet-5-5",
    unread_count: 2,
  },
  {
    agent_id: "agt_research",
    name: "Research helper",
    description: "Reads docs and summarizes",
    state: "stopped",
    default_model: "gpt-6.2-sol",
  },
];

export const mockThreads: Thread[] = [
  {
    thread_id: "thr_design",
    title: "Design system review",
    channel_type: "dashboard",
    last_active: now - 60 * 4,
    created_at: now - 60 * 90,
    has_messages: true,
    unread_count: 2,
  },
  {
    thread_id: "thr_gateway",
    title: "Port gateway tests",
    channel_type: "dashboard",
    last_active: now - 60 * 52,
    created_at: now - 60 * 60 * 5,
    has_messages: true,
  },
  {
    thread_id: "thr_readme",
    title: "README mismatch sweep",
    channel_type: "dashboard",
    last_active: now - 60 * 60 * 4,
    created_at: now - 60 * 60 * 30,
    has_messages: true,
  },
  {
    thread_id: "thr_empty",
    title: null,
    channel_type: "dashboard",
    last_active: now - 60 * 60 * 26,
    created_at: now - 60 * 60 * 26,
  },
];

export const mockHistory: ThreadHistory = {
  thread_id: "thr_design",
  messages: [
    {
      id: "msg_1",
      role: "user",
      content: "帮我看看新的设计 token 有没有问题，尤其是深色模式下的对比度。",
      timestamp: now - 60 * 30,
    },
    {
      id: "msg_2",
      role: "assistant",
      content:
        "我按三层结构整理了 token：primitives → semantic → scales。\n\n深色模式的问题集中在 `--hc-fg-subtle`：它压在 `--hc-bg-surface` 上只有 3.6:1，低于 4.5:1。建议把 subtle 提到 #85857f 以上，或者只把它用于 12px 以下且非关键的信息。\n\n其余角色（default / muted / accent）都在 7:1 以上。",
      timestamp: now - 60 * 29,
    },
    {
      id: "msg_3",
      role: "user",
      content: "那就把 subtle 提到 #8d8d87，同时给 danger 的柔和底色加一档。",
      timestamp: now - 60 * 12,
    },
    {
      id: "msg_4",
      role: "assistant",
      content:
        "改好了：\n\n- `--hc-fg-subtle` → `#8d8d87`（4.6:1）\n- `--hc-danger-soft` → `rgb(234 75 75 / 0.16)`\n\n组件层面只需要重新生成一次 tinted 变体，语义名不变，页面代码零改动。",
      timestamp: now - 60 * 11,
    },
  ],
  has_more: false,
};
