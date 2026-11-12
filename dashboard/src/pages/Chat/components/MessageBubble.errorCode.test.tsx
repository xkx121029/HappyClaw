import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import MessageBubble from "./MessageBubble";
import type { ChatMessage } from "../hooks/useChat";

const STALE =
  "此专家未启用，请先在专家页面启用此专家后再开始对话。";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

const navigate = vi.fn();
vi.mock("react-router-dom", () => ({
  useNavigate: () => navigate,
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
    activeAgent: { agent_id: "a1", name: "小助手", icon_name: "bot" },
    agents: [{ agent_id: "a1", name: "小助手", icon_name: "bot" }],
  }),
}));

function failed(extra: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: "e1",
    role: "assistant",
    content: STALE,
    status: "error",
    timestamp: Date.now(),
    errorInfo: { code: "AGENT_NO_MODEL", source: "history" },
    ...extra,
  };
}

describe("MessageBubble error copy", () => {
  it("shows the no-model hint and a settings action for AGENT_NO_MODEL", () => {
    render(<MessageBubble message={failed()} agentId="a1" />);

    expect(screen.getByText("chat.agentNoModel")).toBeInTheDocument();
    expect(screen.queryByText(STALE)).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "modelConfig.configureButton" }),
    ).toBeInTheDocument();
  });

  it("keeps the backend message for codes without dedicated copy", () => {
    render(
      <MessageBubble
        message={failed({
          content: "上游模型返回了无法解析的内容",
          errorInfo: { code: "SOME_OTHER_CODE", source: "history" },
        })}
        agentId="a1"
      />,
    );

    expect(
      screen.getByText("上游模型返回了无法解析的内容"),
    ).toBeInTheDocument();
  });
});
