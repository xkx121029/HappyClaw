import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, vi } from "vitest";
import type { OctopAgent } from "../../../context/AgentContext";
import { octopThreadsApi } from "../../../api/modules/octopThreads";
import MinimalAgentSessionNav from "./MinimalAgentSessionNav";
import SessionList from "./SessionList";
import { hiddenExpertsStorageKey } from "../utils/hiddenExpertsPrefs";
import { pinnedExpertsStorageKey } from "../utils/pinnedExpertsPrefs";

// 本机单人模式的用户 id 固定为 1，偏好键会带上该后缀。
const LOCAL_USER_ID = 1;

// 编辑专家抽屉会把 PDF / 浏览器预览整条链路带进 jsdom，
// 这些用例只覆盖导航范围，替身掉抽屉即可。
vi.mock("./ChatEditExpertDrawer", () => ({
  default: () => null,
  canEditExpertFromChat: () => false,
}));

function agent(
  partial: Pick<OctopAgent, "agent_id" | "name"> &
    Partial<Pick<OctopAgent, "kind" | "bridge">>,
): OctopAgent {
  return {
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
    ...partial,
  };
}

const agents = [
  agent({ agent_id: "local-expert", name: "本地专家" }),
  {
    ...agent({
      agent_id: "bridge:c1:expert",
      name: "云端专家",
      bridge: true,
    }),
    bridge_connection_name: "对端实验室",
  },
  agent({ agent_id: "local-team", name: "本地团队", kind: "team" }),
  agent({
    agent_id: "bridge:c1:team",
    name: "云端团队",
    kind: "team",
    bridge: true,
  }),
];

function renderList() {
  render(
    <MemoryRouter>
      <SessionList
        agents={agents}
        sessions={[]}
        activeId={null}
        activeAgentId="local-expert"
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

describe("MinimalAgentSessionNav nav scopes", () => {
  beforeEach(() => {
    vi.spyOn(octopThreadsApi, "list").mockResolvedValue([]);
  });

  it("filters the same expert, team, and cloud scopes", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <MinimalAgentSessionNav
          agents={agents}
          activeId={null}
          activeAgentId="local-expert"
          activeSessions={[]}
          onSelect={() => undefined}
          onAgentSelect={() => undefined}
          onNewChat={() => undefined}
          onDeleteActive={() => undefined}
          onRenameActive={() => undefined}
          onPinActive={() => undefined}
          onFork={() => undefined}
        />
      </MemoryRouter>,
    );

    // 默认落在「会话」，专家目录不再占首屏。
    expect(screen.getByRole("tab", { name: "会话" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    await user.click(screen.getByRole("tab", { name: "专家" }));
    expect(screen.getByText("本地专家")).toBeInTheDocument();
    expect(screen.getByText("云端专家")).toBeInTheDocument();
    expect(screen.queryByText("对端实验室")).not.toBeInTheDocument();
    expect(
      screen.getByLabelText("chat.remoteExpert.banner"),
    ).toBeInTheDocument();
    expect(screen.queryByText("本地团队")).not.toBeInTheDocument();

    // 云端协同不再是 tab，而是标签下方的一项入口。
    expect(screen.queryByRole("tab", { name: "云端" })).not.toBeInTheDocument();
    await user.click(screen.getByTestId("chat-cloud-entry"));
    expect(screen.getByText("云端专家")).toBeInTheDocument();
    expect(screen.getByText("云端团队")).toBeInTheDocument();
    expect(screen.queryByText("本地专家")).not.toBeInTheDocument();
    expect(screen.queryByText("本地团队")).not.toBeInTheDocument();
  });
});

function LocationProbe() {
  const location = useLocation();
  return (
    <div>
      {location.pathname}
      {location.search}
    </div>
  );
}

describe("SessionList nav scopes", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("shows a pin mark and expands hidden experts in place", async () => {
    const user = userEvent.setup();
    const onAgentSelect = vi.fn();
    localStorage.setItem(
      pinnedExpertsStorageKey(LOCAL_USER_ID),
      JSON.stringify(["local-expert"]),
    );
    localStorage.setItem(
      hiddenExpertsStorageKey(LOCAL_USER_ID),
      JSON.stringify(["shared-expert", "idle-expert"]),
    );
    const shared = {
      ...agent({ agent_id: "shared-expert", name: "共享专家" }),
      is_shared: true,
      is_owner: false,
    };
    render(
      <MemoryRouter>
        <SessionList
          agents={[
            agent({ agent_id: "local-expert", name: "本地专家" }),
            agent({ agent_id: "idle-expert", name: "闲置专家" }),
            shared,
          ]}
          sessions={[]}
          activeId={null}
          activeAgentId="local-expert"
          hasMore={false}
          loadingMore={false}
          onLoadMore={() => undefined}
          onFetchAllSessions={() => undefined}
          onSelect={() => undefined}
          onAgentSelect={onAgentSelect}
          onNewChat={() => undefined}
          onDelete={() => undefined}
          onRename={() => undefined}
          onPin={() => undefined}
          onFork={() => undefined}
        />
      </MemoryRouter>,
    );

    // 专家目录在「专家」tab 下，默认落在「会话」。
    await user.click(screen.getByRole("tab", { name: "专家" }));

    expect(screen.getByTitle("chat.expertPin")).toBeInTheDocument();
    expect(screen.queryByText("共享专家")).not.toBeInTheDocument();
    expect(screen.queryByText("闲置专家")).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "chat.expertListHidden" }),
    );
    expect(screen.getByText("共享专家")).toBeInTheDocument();
    expect(screen.getByText("闲置专家")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "chat.expertListHiddenCollapse" }),
    ).toHaveAttribute("aria-expanded", "true");

    await user.click(screen.getByText("共享专家"));
    expect(onAgentSelect).toHaveBeenCalledWith("shared-expert");
    expect(
      screen.getByRole("button", { name: "chat.expertListHiddenCollapse" }),
    ).toBeInTheDocument();
  });

  it("leaves the active hidden expert in the hidden group", async () => {
    const user = userEvent.setup();
    localStorage.setItem(
      hiddenExpertsStorageKey(LOCAL_USER_ID),
      JSON.stringify(["idle-expert"]),
    );
    render(
      <MemoryRouter>
        <SessionList
          agents={[
            agent({ agent_id: "local-expert", name: "本地专家" }),
            agent({ agent_id: "idle-expert", name: "闲置专家" }),
          ]}
          sessions={[]}
          activeId={null}
          activeAgentId="idle-expert"
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

    await user.click(screen.getByRole("tab", { name: "专家" }));

    expect(screen.queryByText("闲置专家")).not.toBeInTheDocument();
    const toggle = screen.getByRole("button", {
      name: "chat.expertListHidden",
    });
    expect(
      screen.getByText("本地专家").compareDocumentPosition(toggle) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    await user.click(toggle);
    const hiddenName = screen.getByText("闲置专家");
    const collapse = screen.getByRole("button", {
      name: "chat.expertListHiddenCollapse",
    });
    expect(
      collapse.compareDocumentPosition(hiddenName) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("filters experts, teams, and cloud under the search box", async () => {
    const user = userEvent.setup();
    renderList();

    // 四个 tab，会话优先；云端不在其中。
    expect(screen.getByRole("tab", { name: "会话" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: "项目" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "云端" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "专家" }));
    expect(screen.getByText("本地专家")).toBeInTheDocument();
    expect(screen.getByText("云端专家")).toBeInTheDocument();
    expect(screen.queryByText("对端实验室")).not.toBeInTheDocument();
    expect(
      screen.getByLabelText("chat.remoteExpert.banner"),
    ).toBeInTheDocument();
    expect(screen.queryByText("本地团队")).not.toBeInTheDocument();
    expect(screen.queryByText("云端团队")).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "团队" }));
    expect(screen.getByText("本地团队")).toBeInTheDocument();
    expect(screen.getByText("云端团队")).toBeInTheDocument();
    expect(screen.queryByText("本地专家")).not.toBeInTheDocument();
    expect(screen.queryByText("云端专家")).not.toBeInTheDocument();

    await user.click(screen.getByTestId("chat-cloud-entry"));
    expect(screen.getByText("云端专家")).toBeInTheDocument();
    expect(screen.getByText("云端团队")).toBeInTheDocument();
    expect(screen.queryByText("本地专家")).not.toBeInTheDocument();
    expect(screen.queryByText("本地团队")).not.toBeInTheDocument();
  });

  it("links an empty team tab to the create page", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <Routes>
          <Route
            path="/chat"
            element={
              <SessionList
                agents={[agent({ agent_id: "local-expert", name: "本地专家" })]}
                sessions={[]}
                activeId={null}
                activeAgentId="local-expert"
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
            }
          />
          <Route path="/experts" element={<LocationProbe />} />
          <Route path="/bridge" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>,
    );

    await user.click(screen.getByRole("tab", { name: "团队" }));
    await user.click(screen.getByRole("button", { name: "创建第一个团队" }));
    expect(screen.getByText("/experts?tab=teams")).toBeInTheDocument();
  });
});
