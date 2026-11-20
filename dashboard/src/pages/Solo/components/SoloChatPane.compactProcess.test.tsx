import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ChatMessage } from "../../Chat/hooks/useChat";
import SoloChatPane from "./SoloChatPane";
import { buildSoloActivity } from "./SoloActivityFeed";

/** 捕获 MessageList 收到的参数，验证 SOLO 确实关掉了对话区过程步骤。 */
let messageListProps: Record<string, unknown> | null = null;

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("react-router-dom", () => ({
  Link: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useNavigate: () => vi.fn(),
}));

vi.mock("@/utils/antdMessage", () => ({
  message: { warning: vi.fn(), error: vi.fn() },
}));

vi.mock("../../Agent/Skills/useSkills", () => ({
  useSkills: () => ({ skills: [] }),
}));

vi.mock("../../Chat/components/ChatInput", () => ({
  default: () => <div data-testid="chat-input" />,
}));

vi.mock("../../Chat/components/MessageList", () => ({
  default: (props: Record<string, unknown>) => {
    messageListProps = props;
    return <div data-testid="message-list" />;
  },
}));

/** 同一轮里的两次工具调用，正是用户看到「重复」的场景。 */
const TOOL_MESSAGES: ChatMessage[] = [
  {
    id: "tool-read",
    role: "assistant",
    content: "",
    status: "done",
    timestamp: 1,
    toolData: {
      name: "read_file",
      arguments: JSON.stringify({ path: "src/main.ts" }),
      output: "export {}",
    },
  },
  {
    id: "tool-shell",
    role: "assistant",
    content: "",
    status: "done",
    timestamp: 2,
    toolData: {
      name: "run_command",
      arguments: JSON.stringify({ command: "npm test" }),
      output: "ok\nexit code: 0",
      returnCode: 0,
    },
  },
];

function renderPane(messages: ChatMessage[]) {
  const chat = {
    messages,
    isStreaming: false,
    thinkingStartedAt: null,
    liveSpeakers: [],
    historyLoading: false,
    sendMessage: vi.fn(),
    cancelStream: vi.fn(),
    resumeHitl: vi.fn(),
  };
  const composer = {
    selectedConnectors: [],
    selectedKnowledgeBaseIds: [],
    selectedModel: null,
    reasoningMode: "auto",
    reasoningEffort: null,
    conversationMode: "craft",
    hitlPolicy: {},
    availableModels: [],
    chatConnectors: [],
    chatKnowledgeBases: undefined,
    selectedConnectorsSet: new Set(),
    handleReasoningChange: vi.fn(),
    handleConversationModeChange: vi.fn(),
    handleHitlPolicyChange: vi.fn(),
    handleConnectorsChange: vi.fn(),
    handleKnowledgeBaseIdsChange: vi.fn(),
    setSelectedModel: vi.fn(),
  };

  return {
    chat,
    ...render(
      <SoloChatPane
        agentId="55AK5S"
        activeAgent={null}
        agentReady
        threadId="thr_1"
        onSelectThread={vi.fn()}
        createSession={
          (() => ({
            session: null,
            resolvedId: Promise.resolve("thr_1"),
          })) as never
        }
        chat={chat as never}
        composer={composer as never}
      />,
    ),
  };
}

describe("SoloChatPane dedupe against the activity timeline", () => {
  it("hides in-chat process steps for a multi-tool turn and keeps them in the timeline", () => {
    renderPane(TOOL_MESSAGES);

    expect(screen.getByTestId("message-list")).toBeInTheDocument();
    expect(messageListProps?.compactProcess).toBe(true);

    // 右栏时间线拿到同一轮的两个工具动作，退出码也在。
    const items = buildSoloActivity(
      TOOL_MESSAGES,
      "55AK5S",
      { user: "你", expert: "专家", tool: "工具" },
    );
    const tools = items.filter((item) => item.kind === "tool");
    expect(tools).toHaveLength(2);
    expect(tools[0].title).toBe("read_file");
    expect(tools[1].title).toBe("run_command");
    expect(tools[1].exitCode).toBe(0);
  });
});

const ASK_MESSAGE: ChatMessage = {
  id: "hitl-ask",
  role: "assistant",
  content: "",
  status: "done",
  timestamp: 3,
  hitlData: {
    status: "pending",
    pending_id: "pending-1",
    action_requests: [
      {
        name: "ask_user_question",
        args: {
          questions: [
            {
              question: "选哪个方案？",
              options: [{ label: "方案 A" }, { label: "方案 B" }],
            },
          ],
        },
      },
    ],
  },
};

describe("SoloChatPane HITL wiring", () => {
  it("forwards approval decisions to the shared chat hook", () => {
    renderPane(TOOL_MESSAGES);

    expect(messageListProps?.onHitlDecision).toBeTypeOf("function");
  });

  it("renders a pending question and answers it through the same path", () => {
    const { chat } = renderPane([ASK_MESSAGE]);

    expect(screen.getByText("选哪个方案？")).toBeInTheDocument();
    fireEvent.click(screen.getByText("方案 A"));
    fireEvent.click(screen.getByText("chat.ask.submit"));

    expect(chat.resumeHitl).toHaveBeenCalledTimes(1);
    const [decisions, storeKey] = chat.resumeHitl.mock.calls[0];
    expect(decisions[0].type).toBe("respond");
    expect(storeKey).toBe("thr_1");
  });
});
