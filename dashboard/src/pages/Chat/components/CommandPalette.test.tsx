import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import CommandPalette from "./CommandPalette";
import type { Session } from "../hooks/useSessions";

function session(id: string, name: string, pinned = false): Session {
  return {
    id,
    name,
    threadId: id,
    updatedAt: "2026-03-01T00:00:00.000Z",
    channelType: "dashboard",
    pinned,
  };
}

const sessions = [
  session("s1", "Alpha 计划"),
  session("s2", "Beta 复盘", true),
];

const models = [
  { value: "gpt-5", label: "GPT-5", provider: "openai" },
  { value: "qwen3", label: "Qwen3", provider: "local" },
];

function renderPalette(
  overrides: Partial<Parameters<typeof CommandPalette>[0]> = {},
) {
  const props = {
    open: true,
    sessions,
    models,
    modelsReady: true,
    currentModel: "gpt-5",
    onClose: vi.fn(),
    onNewChat: vi.fn(),
    onSelectSession: vi.fn(),
    onSelectModel: vi.fn(),
    onOpenSettings: vi.fn(),
    onOpenBackup: vi.fn(),
    onOpenShortcuts: vi.fn(),
    ...overrides,
  };
  render(<CommandPalette {...props} />);
  const input = screen.getByRole("textbox");
  return { ...props, input };
}

describe("CommandPalette", () => {
  it("lists actions, models and sessions, and filters as you type", () => {
    const { input } = renderPalette();

    expect(screen.getByText("新建会话")).toBeInTheDocument();
    expect(screen.getByText("GPT-5")).toBeInTheDocument();
    expect(screen.getByText("Beta 复盘")).toBeInTheDocument();

    fireEvent.change(input, { target: { value: "alpha" } });

    expect(screen.queryByText("Beta 复盘")).not.toBeInTheDocument();
    expect(screen.getByText("Alpha 计划")).toBeInTheDocument();
  });

  it("runs the highlighted row with Enter after arrow-key navigation", async () => {
    const { onSelectModel } = renderPalette();

    const input = screen.getByRole("textbox");
    // 「操作」组有 4 项，四次下移落在第一个模型上。
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => expect(onSelectModel).toHaveBeenCalledWith("gpt-5"));
  });

  it("导出动作可被搜索并执行", async () => {
    const onExportTranscript = vi.fn();
    const { input, onClose } = renderPalette({ onExportTranscript });

    fireEvent.change(input, { target: { value: "导出" } });
    const item = await screen.findByRole("option", {
      name: /导出当前会话为 Markdown/,
    });
    fireEvent.click(item);
    await waitFor(() => expect(onExportTranscript).toHaveBeenCalledTimes(1));
    expect(onClose).toHaveBeenCalled();
  });

  it("未传导出回调时不显示导出动作", async () => {
    const { input } = renderPalette();

    fireEvent.change(input, { target: { value: "导出" } });
    // 「导出」只命中备份项的 meta（导出 / 导入），不出现导出会话动作。
    expect(
      await screen.findByRole("option", { name: /本机数据备份与恢复/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /导出当前会话/ })).toBeNull();
  });

  it("keeps no-result actions reachable from the keyboard", async () => {
    const { input, onNewChat, onOpenSettings, onClose } = renderPalette();

    fireEvent.change(input, { target: { value: "zzz" } });
    expect(
      screen.getByText("没有匹配项，换个关键词试试。"),
    ).toBeInTheDocument();

    // 默认高亮第一项「新建会话」。
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(onNewChat).toHaveBeenCalledTimes(1));

    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(onOpenSettings).toHaveBeenCalledTimes(1));

    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("closes on Escape", async () => {
    const { input, onClose } = renderPalette();

    await waitFor(() => expect(input).toHaveFocus());
    fireEvent.keyDown(input, { key: "Escape", keyCode: 27 });

    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});
