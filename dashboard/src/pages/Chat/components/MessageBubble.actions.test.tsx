import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import MessageBubble from "./MessageBubble";
import type { ChatMessage } from "../hooks/useChat";
import { copyText } from "../../../utils/copyText";

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
    activeAgent: { agent_id: "a1", name: "小助手", icon_name: "bot" },
    agents: [{ agent_id: "a1", name: "小助手", icon_name: "bot" }],
  }),
}));

vi.mock("../../../utils/copyText", () => ({
  copyText: vi.fn().mockResolvedValue(true),
}));

vi.mock("@/utils/antdMessage", () => ({
  message: { success: vi.fn(), error: vi.fn() },
}));

function message(partial: Partial<ChatMessage>): ChatMessage {
  return {
    id: "m1",
    role: "assistant",
    content: "回答内容",
    status: "done",
    timestamp: Date.now(),
    ...partial,
  };
}

describe("MessageBubble message actions", () => {
  it("copies the message text", async () => {
    vi.useFakeTimers();
    try {
      render(
        <MessageBubble
          message={message({ role: "user", content: "旧的问题" })}
          agentId="a1"
        />,
      );

      fireEvent.click(screen.getByRole("button", { name: "复制" }));

      await vi.waitFor(() => expect(copyText).toHaveBeenCalledWith("旧的问题"));
      // 复制成功后组件会挂一个 2s 的「已复制」复位定时器，测试结束前清掉，
      // 否则环境销毁后定时器再触发会抛 window is not defined。
      act(() => {
        vi.runOnlyPendingTimers();
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it("regenerates an assistant reply", () => {
    const onRegenerate = vi.fn();
    render(
      <MessageBubble
        message={message({ id: "a1" })}
        agentId="a1"
        onRegenerate={onRegenerate}
      />,
    );

    fireEvent.click(screen.getByTitle("重新生成"));

    expect(onRegenerate).toHaveBeenCalledWith("a1");
  });

  it("retries a failed reply instead of only showing an error", () => {
    const onRegenerate = vi.fn();
    render(
      <MessageBubble
        message={message({
          id: "e1",
          status: "error",
          content: "上游超时",
          errorInfo: { code: "PROVIDER_TIMEOUT", source: "history" },
        })}
        agentId="a1"
        onRegenerate={onRegenerate}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "重试" }));

    expect(onRegenerate).toHaveBeenCalledWith("e1");
  });
});
