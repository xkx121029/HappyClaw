import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ChatMessage } from "../hooks/useChat";
import AssistantTurnView from "./AssistantTurnView";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: string | Record<string, unknown>) => {
      if (typeof opts === "string") return opts;
      const template = (opts?.defaultValue as string | undefined) ?? key;
      return template.replace(/\{\{(\w+)\}\}/g, (match, name: string) =>
        opts?.[name] === undefined ? match : String(opts[name]),
      );
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

function tool(id: string, extra: Partial<ChatMessage> = {}): ChatMessage {
  return message({
    id,
    toolData: { name: "execute", arguments: "{}" },
    ...extra,
  });
}

function turnChildren(container: HTMLElement): HTMLElement[] {
  return Array.from((container.firstElementChild as HTMLElement).children);
}

describe("AssistantTurnView edge cases", () => {
  it("thinking only, no narration: one collapsed thinking row", () => {
    const { container } = render(
      <AssistantTurnView
        messages={[
          message({
            id: "think",
            contentBlocks: [{ type: "thinking", content: "只有推理没有正文" }],
          }),
        ]}
      />,
    );

    const children = turnChildren(container);
    expect(children).toHaveLength(1);
    expect(screen.queryByText("只有推理没有正文")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /思考/ }));
    expect(screen.getByText("只有推理没有正文")).toBeInTheDocument();
  });

  it("tools only, no narration: one collapsed row per tool and no answer bubble", () => {
    const { container } = render(
      <AssistantTurnView messages={[tool("a"), tool("b")]} />,
    );

    const children = turnChildren(container);
    expect(children).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: /execute/ })).toHaveLength(2);
  });

  it("approval card in the middle stays between the two narration segments", () => {
    const { container } = render(
      <AssistantTurnView
        messages={[
          message({ id: "t1", content: "先确认磁盘" }),
          tool("tool1"),
          message({
            id: "card",
            hitlData: {
              action_requests: [{ name: "execute", args: { command: "df" } }],
              status: "pending",
            },
          }),
          message({ id: "t2", content: "确认后继续" }),
        ]}
      />,
    );

    const children = turnChildren(container);
    expect(children).toHaveLength(4);
    expect(children[0].textContent).toContain("先确认磁盘");
    expect(children[2].textContent).toContain("Confirm this action");
    expect(children[3].textContent).toContain("确认后继续");
  });

  it("truncated narration renders verbatim and never merges with the next paragraph", () => {
    const { container } = render(
      <AssistantTurnView
        messages={[
          message({ id: "t1", content: "我在检查配置文件的最后一" }),
          tool("tool1"),
          message({ id: "t2", content: "配置没问题" }),
        ]}
      />,
    );

    const children = turnChildren(container);
    expect(children).toHaveLength(3);
    expect(children[0].textContent).toContain("我在检查配置文件的最后一");
    expect(children[0].textContent).not.toContain("配置没问题");
    expect(children[2].textContent).toContain("配置没问题");
  });

  it("a failed tool between two paragraphs is flagged in the folded group", () => {
    render(
      <AssistantTurnView
        messages={[
          message({ id: "t1", content: "先跑测试", timestamp: 1000 }),
          tool("boom", {
            status: "error",
            timestamp: 2000,
            toolData: {
              name: "execute",
              arguments: "{}",
              output: "boom",
              errorCode: "tool_error",
            },
          }),
          message({ id: "t2", content: "测试挂了", timestamp: 3000 }),
          tool("ok", {
            timestamp: 4000,
            toolData: { name: "execute", arguments: "{}", output: "ok" },
          }),
          message({ id: "t3", content: "改完了", timestamp: 5000 }),
        ]}
      />,
    );

    // The failed step must be named, not just counted.
    const group = screen.getByRole("button", {
      name: /已执行 2 步.*失败：execute/,
    });
    expect(group).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(group);
    expect(
      screen.getByRole("button", { name: /execute.*Failed/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /execute.*Done/ }),
    ).toBeInTheDocument();
  });

  it("compactProcess hides chat-side steps but keeps narration", () => {
    const { container } = render(
      <AssistantTurnView
        compactProcess
        messages={[
          message({ id: "t1", content: "我先看目录" }),
          tool("tool1"),
          message({ id: "t2", content: "看完了" }),
        ]}
      />,
    );

    const children = turnChildren(container);
    expect(children).toHaveLength(2);
    expect(screen.getByText("我先看目录")).toBeInTheDocument();
    expect(screen.getByText("看完了")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /execute/ }),
    ).not.toBeInTheDocument();
  });

  it("compactProcess leaves an action-only turn empty for the activity feed", () => {
    const { container } = render(
      <AssistantTurnView compactProcess messages={[tool("tool1")]} />,
    );
    expect(container.firstChild).toBeNull();
  });
});
