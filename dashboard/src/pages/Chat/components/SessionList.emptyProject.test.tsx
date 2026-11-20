import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import type { OctopAgent } from "../../../context/AgentContext";
import type { OctopThread } from "../../../api/modules/octopThreads";
import { octopThreadsApi } from "../../../api/modules/octopThreads";
import { octopSettingsApi } from "../../../api/modules/settings";
import SessionList from "./SessionList";
import MinimalAgentSessionNav from "./MinimalAgentSessionNav";

// 回归：空项目里直接发消息曾落到上一个会话。
// 根因是项目分组头部只展开/收起，聊天上下文仍停在旧会话；
// 现在点击空项目必须在该项目里开新会话，之后发送才会建在项目专家下。

vi.mock("./ChatEditExpertDrawer", () => ({
  default: () => null,
  canEditExpertFromChat: () => false,
}));

vi.mock("@/api/request", () => ({
  request: vi.fn(async (path: string) => {
    if (path === "/filesystem/defaults") {
      return { default_workspace_dir: "/workspaces/agents" };
    }
    if (path === "/agents/main") {
      return {
        agent_id: "main",
        name: "主专家",
        config: { workspace_dir: "/workspaces/agents/main" },
      };
    }
    if (path === "/agents/project-expert") {
      return {
        agent_id: "project-expert",
        name: "项目专家",
        config: { workspace_dir: "/workspaces/projects/workspace-project" },
      };
    }
    throw new Error(`unexpected request: ${path}`);
  }),
}));

function agent(agentId: string, name: string): OctopAgent {
  return {
    agent_id: agentId,
    name,
    description: null,
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

function projectThread(): OctopThread {
  return {
    thread_id: "project-thread",
    title: "项目里的会话",
    channel_type: "dashboard",
    session_key: "project-session",
    last_active: Math.floor(Date.now() / 1000),
    created_at: Math.floor(Date.now() / 1000),
    has_messages: true,
    agent_id: "project-expert",
  } as OctopThread;
}

const AGENTS = [agent("main", "主专家"), agent("project-expert", "项目专家")];

function renderList(onNewChat: (agentId: string) => void) {
  render(
    <MemoryRouter>
      <SessionList
        agents={AGENTS}
        sessions={[]}
        activeId={null}
        activeAgentId="main"
        hasMore={false}
        loadingMore={false}
        onLoadMore={() => undefined}
        onFetchAllSessions={() => undefined}
        onSelect={() => undefined}
        onAgentSelect={() => undefined}
        onNewChat={onNewChat}
        onDelete={() => undefined}
        onRename={() => undefined}
        onPin={() => undefined}
        onFork={() => undefined}
      />
    </MemoryRouter>,
  );
}

function renderMinimal(onNewChat: (agentId: string) => void) {
  render(
    <MemoryRouter>
      <MinimalAgentSessionNav
        agents={AGENTS}
        activeId={null}
        activeAgentId="main"
        activeSessions={[]}
        onSelect={() => undefined}
        onAgentSelect={() => undefined}
        onNewChat={onNewChat}
        onDeleteActive={() => undefined}
        onRenameActive={() => undefined}
        onPinActive={() => undefined}
        onFork={() => undefined}
      />
    </MemoryRouter>,
  );
}

describe("空项目的新会话入口", () => {
  beforeAll(() => {
    vi.spyOn(octopSettingsApi, "timezone").mockRejectedValue(
      new Error("no backend in unit test"),
    );
  });

  it("经典侧栏：点击空项目分组改为在该项目里开新会话", async () => {
    vi.spyOn(octopThreadsApi, "list").mockResolvedValue([]);
    const user = userEvent.setup();
    const onNewChat = vi.fn();
    renderList(onNewChat);

    await user.click(screen.getByRole("tab", { name: "项目" }));
    const header = await screen.findByRole("button", {
      name: /workspace-project/,
    });
    await user.click(header);

    expect(onNewChat).toHaveBeenCalledWith("project-expert", null);
    expect(header).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getAllByText("这个项目下还没有会话").length,
    ).toBeGreaterThan(0);
  });

  it("极简侧栏：点击空项目分组改为在该项目里开新会话", async () => {
    vi.spyOn(octopThreadsApi, "list").mockResolvedValue([]);
    const user = userEvent.setup();
    const onNewChat = vi.fn();
    renderMinimal(onNewChat);

    await user.click(screen.getByRole("tab", { name: "项目" }));
    const header = await screen.findByRole("button", {
      name: /workspace-project/,
    });
    await user.click(header);

    expect(onNewChat).toHaveBeenCalledWith("project-expert", null);
    expect(header).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getAllByText("这个项目下还没有会话").length,
    ).toBeGreaterThan(0);
  });

  it("非空项目分组仍只展开/收起，不新建会话", async () => {
    vi.spyOn(octopThreadsApi, "list").mockImplementation(
      async (agentId: string) =>
        agentId === "project-expert" ? [projectThread()] : [],
    );
    const user = userEvent.setup();
    const onNewChat = vi.fn();
    renderList(onNewChat);

    await user.click(screen.getByRole("tab", { name: "项目" }));
    const header = await screen.findByRole("button", {
      name: /workspace-project/,
    });
    await user.click(header);

    expect(onNewChat).not.toHaveBeenCalled();
    expect(header).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("项目里的会话")).toBeInTheDocument();
  });
});
