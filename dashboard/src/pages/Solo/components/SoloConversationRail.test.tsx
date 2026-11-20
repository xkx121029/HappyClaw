import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { OctopAgent } from "../../../context/AgentContext";
import type { Session } from "../../Chat/hooks/useSessions";
import SoloConversationRail from "./SoloConversationRail";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      const templates: Record<string, string> = {
        "solo.sessions": "会话",
        "solo.searchSessions": "搜索会话",
        "solo.newTask": "新任务",
        "solo.newChat": "新建会话",
        "solo.openFiles": "打开文件",
        "solo.files": "文件",
        "solo.ready": "就绪",
        "solo.agentStoppedShort": "专家未运行",
        "solo.sessionsLoading": "正在加载会话…",
        "solo.sessionsEmpty": "还没有会话，输入内容即可开始",
        "solo.noAgent": "未选择专家",
        "solo.expert": "专家",
      };
      const fallback = typeof opts?.defaultValue === "string" ? opts.defaultValue : key;
      const template = templates[key] ?? fallback;
      return template.replace(/\{\{(\w+)\}\}/g, (match, name: string) =>
        opts?.[name] === undefined ? match : String(opts[name]),
      );
    },
  }),
}));

vi.mock("../../../hooks/useServerTimezone", () => ({
  useServerTimezone: () => "UTC",
}));

function makeSession(id: string, name: string): Session {
  return {
    id,
    name,
    threadId: id,
    updatedAt: "2026-01-02T03:04:05Z",
    channelType: "solo",
  };
}

function renderRail(props: {
  sessions?: Session[];
  sessionsLoading?: boolean;
  activeThreadId?: string | null;
  onNewChat?: () => void;
  onOpenFiles?: () => void;
} = {}) {
  const onNewChat = props.onNewChat ?? vi.fn();
  const onOpenFiles = props.onOpenFiles ?? vi.fn();
  render(
    <SoloConversationRail
      agents={[] as OctopAgent[]}
      agentId="55AK5S"
      agentReady
      onSelectAgent={vi.fn()}
      sessions={props.sessions ?? []}
      sessionsLoading={props.sessionsLoading ?? false}
      activeThreadId={props.activeThreadId ?? null}
      onSelectThread={vi.fn()}
      onNewChat={onNewChat}
      onOpenFiles={onOpenFiles}
      streaming={false}
    />,
  );
  return { onNewChat, onOpenFiles };
}

describe("SoloConversationRail", () => {
  it("renders the new-task entry and opens the file picker", () => {
    const { onNewChat, onOpenFiles } = renderRail();

    const newTask = screen.getByRole("button", {
      name: /新任务/,
    });
    expect(newTask).toHaveTextContent("Ctrl+Alt+N");
    fireEvent.click(newTask);
    expect(onNewChat).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "打开文件" }));
    expect(onOpenFiles).toHaveBeenCalledTimes(1);
  });

  it("no longer renders a model combobox", () => {
    renderRail();

    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("filters sessions by title once the search box is open", () => {
    renderRail({
      sessions: [makeSession("t1", "修复登录页"), makeSession("t2", "整理发布说明")],
    });

    expect(screen.getByText("修复登录页")).toBeInTheDocument();
    expect(screen.getByText("整理发布说明")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "搜索会话" }));
    fireEvent.change(screen.getByRole("textbox", { name: "搜索会话" }), {
      target: { value: "登录" },
    });

    expect(screen.getByText("修复登录页")).toBeInTheDocument();
    expect(screen.queryByText("整理发布说明")).not.toBeInTheDocument();
  });

  it("marks the active session and shows an empty state", () => {
    renderRail({
      sessions: [makeSession("t1", "修复登录页")],
      activeThreadId: "t1",
    });

    expect(screen.getByRole("button", { name: /修复登录页/ })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });

  it("shows the empty state when there are no sessions", () => {
    renderRail();

    expect(screen.getByText("还没有会话，输入内容即可开始")).toBeInTheDocument();
  });
});
