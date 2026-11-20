import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ChatMessage } from "../../Chat/hooks/useChat";
import SoloPlanPanel from "./SoloPlanPanel";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      const templates: Record<string, string> = {
        "solo.plan": "计划",
        "solo.planProgress": "{{done}}/{{total}} 已完成",
        "solo.collapsePlan": "收起计划",
        "solo.expandPlan": "展开计划",
        "solo.planStatus.completed": "已完成",
        "solo.planStatus.inProgress": "进行中",
        "solo.planStatus.pending": "待开始",
        "solo.planStatus.cancelled": "已取消",
      };
      const template = templates[key] ?? key;
      return template.replace(/\{\{(\w+)\}\}/g, (match, name: string) =>
        opts?.[name] === undefined ? match : String(opts[name]),
      );
    },
  }),
}));

function todoTool(
  id: string,
  todos: Array<{ id: string; content: string; status: string }>,
): ChatMessage {
  return {
    id,
    role: "assistant",
    content: "",
    status: "done",
    timestamp: 1,
    toolData: {
      name: "write_todos",
      arguments: JSON.stringify({ todos }),
    },
  };
}

describe("SoloPlanPanel", () => {
  it("renders nothing when the turn has no plan", () => {
    const { container } = render(
      <SoloPlanPanel messages={[]} isStreaming={false} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("merges write_todos updates into one checklist with live progress", () => {
    const messages = [
      todoTool("t1", [
        { id: "1", content: "梳理需求", status: "completed" },
        { id: "2", content: "实现步骤清单", status: "in_progress" },
      ]),
      todoTool("t2", [
        { id: "1", content: "梳理需求", status: "completed" },
        { id: "2", content: "实现步骤清单", status: "completed" },
        { id: "3", content: "补测试", status: "pending" },
      ]),
    ];

    render(<SoloPlanPanel messages={messages} isStreaming={false} />);

    expect(screen.getByText("计划")).toBeInTheDocument();
    expect(screen.getByText("2/3 已完成")).toBeInTheDocument();
    expect(screen.getByText("梳理需求")).toBeInTheDocument();
    expect(screen.getByText("实现步骤清单")).toBeInTheDocument();
    expect(screen.getByText("补测试")).toBeInTheDocument();
    expect(screen.getAllByLabelText("已完成")).toHaveLength(2);
    expect(screen.getByLabelText("待开始")).toBeInTheDocument();
  });

  it("marks the running step while the turn is streaming", () => {
    const messages = [
      todoTool("t1", [
        { id: "1", content: "改代码", status: "in_progress" },
      ]),
    ];
    render(<SoloPlanPanel messages={messages} isStreaming />);

    expect(screen.getByLabelText("进行中")).toBeInTheDocument();
  });
});
