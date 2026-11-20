import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ChatMessage } from "../hooks/useChat";
import { COLLAPSE_THINKING_TEAM_KEY } from "../hooks/useCollapseThinking";
import AssistantTurnView from "./AssistantTurnView";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: string | { defaultValue?: string }) => {
      if (typeof opts === "string") return opts;
      return opts?.defaultValue ?? key;
    },
  }),
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
}));

vi.mock("../../../hooks/useServerTimezone", () => ({
  useServerTimezone: () => "UTC",
}));

vi.mock("../../../hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ username: "ada", display_name: "Ada" }),
}));

vi.mock("../../../context/VoiceOutputContext", () => ({
  useVoiceOutputContext: () => ({ speakingId: null, speak: vi.fn() }),
}));

vi.mock("../../../context/AgentContext", () => ({
  useAgent: () => ({
    activeAgentId: "host",
    activeAgent: {
      agent_id: "host",
      name: "主持团队",
      kind: "team",
      icon_name: "bot",
    },
    agents: [
      {
        agent_id: "host",
        name: "主持团队",
        kind: "team",
        icon_name: "bot",
      },
    ],
  }),
}));

function message(
  extra: Partial<ChatMessage> & Pick<ChatMessage, "id">,
): ChatMessage {
  return {
    role: "assistant",
    content: "",
    status: "done",
    timestamp: 1,
    ...extra,
  };
}

describe("AssistantTurnView approval", () => {
  it("keeps the answer that arrived before the approval card", () => {
    render(
      <AssistantTurnView
        messages={[
          message({ id: "text", content: "磁盘还剩 8G" }),
          message({
            id: "tool",
            toolData: { name: "execute", arguments: "{}" },
          }),
          message({
            id: "card",
            hitlData: {
              action_requests: [{ name: "execute", args: { command: "df" } }],
              status: "pending",
            },
          }),
        ]}
      />,
    );

    expect(screen.getByText("磁盘还剩 8G")).toBeInTheDocument();
    expect(screen.getByText("Confirm this action")).toBeInTheDocument();
  });

  it("keeps host wrap-up below the divider and leaves the decision collapsed", () => {
    render(
      <AssistantTurnView
        messages={[
          message({
            id: "wrap",
            content: "今天就到这里",
            teamWrapup: true,
            speakerAgentId: "host",
            decision: {
              model: "laya",
              empty: false,
              parts: [
                { kind: "result", kept: [{ name: "结果充分", score: 0.91 }] },
              ],
            },
          }),
        ]}
      />,
    );

    const badge = screen.getByText("主持人总结");
    const answer = screen.getByText("今天就到这里");
    expect(
      badge.compareDocumentPosition(answer) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.getByText(/决策模型/)).toBeInTheDocument();
    expect(screen.queryByText(/结果充分/)).not.toBeInTheDocument();
  });

  it("does not flash a lone decision row before tools arrive", () => {
    localStorage.setItem(COLLAPSE_THINKING_TEAM_KEY, "true");
    const decision = {
      model: "laya",
      empty: true,
      parts: [],
    };
    const { rerender } = render(
      <AssistantTurnView
        isTurnInProgress
        messages={[
          message({
            id: "pending",
            status: "streaming",
            decision,
          }),
        ]}
      />,
    );
    expect(screen.queryByText(/决策模型/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();

    rerender(
      <AssistantTurnView
        isTurnInProgress
        messages={[
          message({
            id: "pending",
            status: "done",
            decision,
          }),
          message({
            id: "tool",
            status: "streaming",
            toolData: { name: "execute", arguments: "{}" },
          }),
        ]}
      />,
    );
    // Steps are one-line rows now: the decision and the running tool each get
    // their own collapsed row instead of one shared fold header.
    const decisionRow = screen.getByRole("button", { name: /决策模型/ });
    expect(screen.queryByText(/本轮保持原样/)).not.toBeInTheDocument();
    fireEvent.click(decisionRow);
    expect(screen.getByText(/本轮保持原样/)).toBeInTheDocument();
  });
});

describe("AssistantTurnView interleaved blocks", () => {
  it("renders each narration segment as its own block", () => {
    const { container } = render(
      <AssistantTurnView
        messages={[
          message({ id: "t1", content: "先看下目录" }),
          message({
            id: "tool1",
            toolData: { name: "execute", arguments: "{}" },
          }),
          message({ id: "t2", content: "只有一个文件" }),
        ]}
      />,
    );

    const turn = container.firstElementChild as HTMLElement;
    const blocks = Array.from(turn.children);
    expect(blocks).toHaveLength(3);
    expect(blocks[0].textContent).toContain("先看下目录");
    expect(blocks[1].textContent).not.toContain("先看下目录");
    expect(blocks[1].textContent).not.toContain("只有一个文件");
    expect(blocks[2].textContent).toContain("只有一个文件");
  });

  it("folds earlier steps into one group once a second segment lands", () => {
    render(
      <AssistantTurnView
        messages={[
          message({ id: "t1", content: "先读文件", timestamp: 1000 }),
          message({
            id: "tool1",
            timestamp: 2000,
            toolData: { name: "read", arguments: "{}" },
          }),
          message({ id: "t2", content: "读完了", timestamp: 5000 }),
          message({
            id: "tool2",
            timestamp: 6000,
            toolData: { name: "write", arguments: "{}" },
          }),
          message({ id: "t3", content: "改完了", timestamp: 12000 }),
        ]}
      />,
    );

    const group = screen.getByRole("button", {
      name: /已执行 \{\{count\}\} 步，用时/,
    });
    expect(group).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.queryByRole("button", { name: /read/ }),
    ).not.toBeInTheDocument();
    fireEvent.click(group);
    expect(screen.getByRole("button", { name: /read/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /write/ })).toBeInTheDocument();
  });

  it("keeps thinking collapsed until the row is clicked", () => {
    render(
      <AssistantTurnView
        messages={[
          message({
            id: "t1",
            content: "答案",
            contentBlocks: [
              { type: "thinking", content: "秘密推理" },
              { type: "text", content: "答案" },
            ],
          }),
        ]}
      />,
    );

    expect(screen.queryByText("秘密推理")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /思考/ }));
    expect(screen.getByText("秘密推理")).toBeInTheDocument();
  });

  it("marks a failed tool while collapsed", () => {
    render(
      <AssistantTurnView
        messages={[
          message({ id: "t1", content: "跑一下", timestamp: 1000 }),
          message({
            id: "boom",
            status: "error",
            timestamp: 2000,
            toolData: { name: "execute", arguments: "{}", output: "boom" },
          }),
          message({ id: "t2", content: "失败了", timestamp: 3000 }),
        ]}
      />,
    );

    expect(
      screen.getByRole("button", {
        name: /已执行 \{\{count\}\} 步.*失败：\{\{names\}\}/,
      }),
    ).toBeInTheDocument();
  });
});
