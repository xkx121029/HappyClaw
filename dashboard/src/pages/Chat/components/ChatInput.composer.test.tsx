import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

const attachments = vi.hoisted(() => ({
  dragOver: { value: false },
  handleDrop: vi.fn(),
  handleDragEnter: vi.fn(),
  handleDragLeave: vi.fn(),
  handleDragOver: vi.fn(),
  clearAttachments: vi.fn(),
  restoreAttachments: vi.fn(),
}));

// 按 (agentId:threadId) 保存的草稿，供「按会话恢复草稿」用例使用。
const drafts = vi.hoisted(
  () =>
    new Map<
      string,
      {
        text: string;
        attachments: {
          url: string;
          filename?: string;
          mediaType?: string;
          workspacePath?: string;
          kind: "image" | "file" | "video" | "audio";
        }[];
      }
    >(),
);

vi.mock("../../../hooks/useIsMobile", () => ({
  useIsMobile: () => false,
}));

vi.mock("../../../hooks/useSlashCommands", () => ({
  useSlashCommands: () => ({
    commands: [],
    labelFor: (cmd: string) => cmd,
  }),
}));

vi.mock("../../../hooks/useVoiceInput", () => ({
  useVoiceInput: () => ({
    recording: false,
    transcribing: false,
    realtime: false,
    start: vi.fn(),
    stop: vi.fn(),
    toggle: vi.fn(),
  }),
}));

vi.mock("../../../hooks/useKeepInVisualViewport", () => ({
  useKeepInVisualViewport: () => undefined,
}));

vi.mock("../../../hooks/viewport", () => ({
  isPwaDisplay: () => false,
  needsComposerVisualViewportFix: () => false,
}));

vi.mock("../hooks/useChatAttachments", () => ({
  useChatAttachments: () => ({
    attachments: [],
    uploading: false,
    dragOver: attachments.dragOver.value,
    fileInputRef: { current: null },
    folderInputRef: { current: null },
    handleFileSelect: vi.fn(),
    handleFolderSelect: vi.fn(),
    handleFileChange: vi.fn(),
    removeAttachment: vi.fn(),
    clearAttachments: attachments.clearAttachments,
    restoreAttachments: attachments.restoreAttachments,
    handlePaste: vi.fn(),
    handleDragEnter: attachments.handleDragEnter,
    handleDragLeave: attachments.handleDragLeave,
    handleDragOver: attachments.handleDragOver,
    handleDrop: attachments.handleDrop,
  }),
}));

vi.mock("../hooks/chatStore", () => ({
  consumePendingPrefillAttachments: () => [],
  onSteerRestore: () => () => {},
}));

vi.mock("../utils/composerDraft", () => ({
  readComposerDraft: (agentId?: string | null, threadId?: string | null) =>
    drafts.get(`${agentId ?? ""}:${threadId ?? ""}`) ?? {
      text: "",
      attachments: [],
    },
  writeComposerDraft: vi.fn(),
  clearComposerDraft: vi.fn(),
}));

vi.mock("./ChatInputPreviewBar", () => ({
  default: () => null,
}));

vi.mock("./ChatInputActionsRow", () => ({
  default: ({
    onSubmit,
    canSend,
  }: {
    onSubmit: () => void;
    canSend: boolean;
  }) => (
    <button type="button" disabled={!canSend} onClick={onSubmit}>
      send
    </button>
  ),
}));

vi.mock("./ChatQueuedMessages", () => ({
  default: () => null,
}));

vi.mock("./SlashCommandMenu", () => ({
  default: () => null,
}));

vi.mock("./MentionPickerMenu", () => ({
  default: () => null,
  buildMentionItems: () => [],
}));

vi.mock("../hooks/useSlashMentionInput", () => ({
  useSlashMentionInput: ({ setText }: { setText: (v: string) => void }) => ({
    slashMenuOpen: false,
    slashMenuIndex: 0,
    setSlashMenuIndex: vi.fn(),
    mentionMenuOpen: false,
    mentionMenuIndex: 0,
    setMentionMenuIndex: vi.fn(),
    mentionQuery: "",
    mentionAgents: [],
    slashMenuFlat: [],
    slashMenuGroups: [],
    slashPickerGroups: [],
    slashMenuItems: [],
    mentionItems: [],
    filesLoading: false,
    filesError: null,
    runSlashCommand: vi.fn(),
    matchSlashCommand: () => null,
    handleMentionSelect: vi.fn(),
    handleSlashSelect: vi.fn(),
    handleTextChange: setText,
    handleKeyDown: vi.fn(),
  }),
}));

import ChatInput from "./ChatInput";

beforeEach(() => {
  vi.clearAllMocks();
  attachments.dragOver.value = false;
  drafts.clear();
});

function renderComposer(onSend = vi.fn(), threadId = "thread-1") {
  const utils = render(
    <ChatInput
      onSend={onSend}
      onCancel={vi.fn()}
      onNewChat={vi.fn()}
      isStreaming={false}
      agentId="agent-1"
      threadId={threadId}
    />,
  );
  return { ...utils, onSend, textarea: screen.getByRole("textbox") };
}

describe("ChatInput composer affordances", () => {
  it("shows the Enter / Shift+Enter hint", () => {
    renderComposer();

    expect(
      screen.getByText(/chat\.composerHint|Enter 发送 \/ Shift\+Enter 换行/),
    ).toBeInTheDocument();
  });

  it("folds a long paste but still sends the full text", () => {
    const longText = "长".repeat(1300);
    const { onSend, textarea } = renderComposer();

    fireEvent.change(textarea, { target: { value: longText } });

    expect(
      screen.getByText(
        `长文本已折叠（${longText.length} 字），发送时仍为完整内容`,
      ),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "展开编辑" }));
    expect(screen.queryByText(/长文本已折叠/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "send" }));
    expect(onSend).toHaveBeenCalledWith(longText, undefined);
  });

  it("shows the drop overlay and accepts dropped files", () => {
    const { container, rerender } = renderComposer();

    expect(screen.queryByTestId("chat-drop-overlay")).not.toBeInTheDocument();

    attachments.dragOver.value = true;
    rerender(
      <ChatInput
        onSend={vi.fn()}
        onCancel={vi.fn()}
        onNewChat={vi.fn()}
        isStreaming={false}
        agentId="agent-1"
        threadId="thread-1"
      />,
    );

    expect(screen.getByTestId("chat-drop-overlay")).toBeInTheDocument();

    const shell = container.querySelector("#octop-chat-file-drop");
    expect(shell).not.toBeNull();
    fireEvent.drop(shell as Element, {
      dataTransfer: { files: [] },
    });
    expect(attachments.handleDrop).toHaveBeenCalled();
  });

  it("restores each session's draft text and attachments", () => {
    const image = {
      url: "https://example.test/pic.png",
      filename: "pic.png",
      mediaType: "image/png",
      kind: "image" as const,
    };
    drafts.set("agent-1:thread-1", {
      text: "会话一草稿",
      attachments: [image],
    });
    drafts.set("agent-1:thread-2", { text: "会话二草稿", attachments: [] });

    const { rerender, textarea } = renderComposer();
    expect((textarea as HTMLTextAreaElement).value).toBe("会话一草稿");
    expect(attachments.restoreAttachments).toHaveBeenCalledWith([image]);

    rerender(
      <ChatInput
        onSend={vi.fn()}
        onCancel={vi.fn()}
        onNewChat={vi.fn()}
        isStreaming={false}
        agentId="agent-1"
        threadId="thread-2"
      />,
    );

    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe(
      "会话二草稿",
    );
    expect(attachments.clearAttachments).toHaveBeenCalled();

    rerender(
      <ChatInput
        onSend={vi.fn()}
        onCancel={vi.fn()}
        onNewChat={vi.fn()}
        isStreaming={false}
        agentId="agent-1"
        threadId="thread-1"
      />,
    );

    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe(
      "会话一草稿",
    );
    expect(attachments.restoreAttachments).toHaveBeenLastCalledWith([image]);
  });
});
