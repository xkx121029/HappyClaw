import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import type { OctopAgent } from "../../../context/AgentContext";
import type { Session } from "../hooks/useSessions";
import { happyclawThreadsApi } from "../../../api/modules/happyclawThreads";
import SessionList from "./SessionList";

// 侧栏渲染基线：几百条专家 / 会话时单次挂载的耗时。
// 用 console.log 记录数据，阈值只防明显回归，不作为精确性能断言。

vi.mock("./ChatEditExpertDrawer", () => ({
  default: () => null,
  canEditExpertFromChat: () => false,
}));

function makeAgents(count: number): OctopAgent[] {
  return Array.from({ length: count }, (_, index) => ({
    agent_id: `expert-${index}`,
    name: `专家 ${String(index).padStart(3, "0")}`,
    description: "用于渲染基线",
    persona_mbti: null,
    default_model: null,
    system_prompt: null,
    template_name: null,
    state: "running",
    last_error: null,
    icon: null,
    icon_name: null,
    icon_url: null,
    color: null,
    config: {},
  }));
}

function makeSessions(agentId: string, count: number): Session[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `session-${index}`,
    name: `会话 ${String(index).padStart(3, "0")}`,
    threadId: `session-${index}`,
    agentId,
    updatedAt: new Date(2026, 0, 1, 0, index).toISOString(),
    channelType: "dashboard",
    pinned: false,
    hasActivity: true,
  }));
}

function renderList(agents: OctopAgent[], sessions: Session[]) {
  render(
    <MemoryRouter>
      <SessionList
        agents={agents}
        sessions={sessions}
        activeId={null}
        activeAgentId={agents[0]?.agent_id ?? null}
        hasMore={false}
        loadingMore={false}
        onLoadMore={() => undefined}
        onFetchAllSessions={() => undefined}
        onSelect={() => undefined}
        onAgentSelect={() => undefined}
        onNewChat={() => undefined}
        onDelete={() => undefined}
        onRename={() => undefined}
        onPin={() => undefined}
        onFork={() => undefined}
      />
    </MemoryRouter>,
  );
}

describe("SessionList render baseline", () => {
  beforeAll(() => {
    vi.spyOn(happyclawThreadsApi, "list").mockResolvedValue([]);
  });

  it("renders 300 experts", () => {
    const agents = makeAgents(300);
    const started = performance.now();
    renderList(agents, []);
    const elapsed = performance.now() - started;

    // eslint-disable-next-line no-console
    console.log(`[perf] SessionList 300 experts: ${elapsed.toFixed(1)}ms`);
    expect(screen.getByText("专家 000")).toBeInTheDocument();
    expect(elapsed).toBeLessThan(8000);
  });

  it("renders 300 sessions under one expert", () => {
    const agents = makeAgents(1);
    const sessions = makeSessions("expert-0", 300);
    const started = performance.now();
    renderList(agents, sessions);
    const elapsed = performance.now() - started;

    // eslint-disable-next-line no-console
    console.log(`[perf] SessionList 300 sessions: ${elapsed.toFixed(1)}ms`);
    // 按最近排序，最新一条在首屏。
    expect(screen.getByText("会话 299")).toBeInTheDocument();
    expect(elapsed).toBeLessThan(8000);
  });
});
