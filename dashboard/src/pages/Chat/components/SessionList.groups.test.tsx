import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import type { OctopAgent } from "../../../context/AgentContext";
import type { Session } from "../hooks/useSessions";
import { octopThreadsApi } from "../../../api/modules/octopThreads";
import { octopSettingsApi } from "../../../api/modules/settings";
import SessionList from "./SessionList";

// 会话列表时间分组：最近排序时出现「置顶/今天/昨天/更早」标题，
// 名称排序时不出现。

vi.mock("./ChatEditExpertDrawer", () => ({
  default: () => null,
  canEditExpertFromChat: () => false,
}));

function makeAgent(): OctopAgent {
  return {
    agent_id: "expert-0",
    name: "专家 000",
    description: "用于分组测试",
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
  } as OctopAgent;
}

function makeSession(overrides: {
  id: string;
  name: string;
  updatedAt?: string;
  pinned?: boolean;
}): Session {
  return {
    id: overrides.id,
    name: overrides.name,
    threadId: overrides.id,
    agentId: "expert-0",
    updatedAt: overrides.updatedAt,
    channelType: "dashboard",
    pinned: overrides.pinned ?? false,
    hasActivity: true,
  } as Session;
}

function sessions(): Session[] {
  return [
    makeSession({ id: "old-pinned", name: "置顶的旧会话", pinned: true }),
    makeSession({
      id: "today",
      name: "今天的会话",
      updatedAt: new Date().toISOString(),
    }),
    makeSession({
      id: "yesterday",
      name: "昨天的会话",
      updatedAt: new Date(Date.now() - 24 * 3600_000).toISOString(),
    }),
    makeSession({
      id: "old",
      name: "很久以前的会话",
      updatedAt: new Date(Date.now() - 60 * 24 * 3600_000).toISOString(),
    }),
  ];
}

function renderList() {
  render(
    <MemoryRouter>
      <SessionList
        agents={[makeAgent()]}
        sessions={sessions()}
        activeId={null}
        activeAgentId="expert-0"
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

describe("SessionList recency groups", () => {
  beforeAll(() => {
    vi.spyOn(octopThreadsApi, "list").mockResolvedValue([]);
    vi.spyOn(octopSettingsApi, "timezone").mockRejectedValue(
      new Error("no backend in unit test"),
    );
  });

  it("最近排序时渲染时间分组标题", () => {
    renderList();

    expect(screen.getByText("置顶")).toBeInTheDocument();
    expect(screen.getByText("今天")).toBeInTheDocument();
    expect(screen.getByText("昨天")).toBeInTheDocument();
    expect(screen.getByText("更早")).toBeInTheDocument();
    expect(screen.getByText("今天的会话")).toBeInTheDocument();
    expect(screen.getByText("置顶的旧会话")).toBeInTheDocument();
  });

  it("名称排序时不渲染时间分组标题", async () => {
    window.localStorage.setItem("octop.chat.sessionSort", "name");
    try {
      renderList();

      expect(screen.getByText("今天的会话")).toBeInTheDocument();
      expect(screen.queryByText("置顶")).toBeNull();
      expect(screen.queryByText("更早")).toBeNull();
    } finally {
      window.localStorage.removeItem("octop.chat.sessionSort");
    }
  });
});
