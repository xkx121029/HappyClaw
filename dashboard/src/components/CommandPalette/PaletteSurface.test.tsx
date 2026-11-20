import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import PaletteSurface, {
  paletteFlatItems,
  type PaletteGroup,
} from "./PaletteSurface";

const groups: PaletteGroup[] = [
  {
    kind: "daily",
    label: "日常",
    items: [
      { id: "home", label: "主页", meta: "/home", run: vi.fn() },
      { id: "chat", label: "对话", meta: "/chat", run: vi.fn() },
    ],
  },
  {
    kind: "settings",
    label: "设置",
    items: [
      { id: "models", label: "模型配置", meta: "/admin/models", run: vi.fn() },
    ],
  },
];

function renderSurface(overrides: Record<string, unknown> = {}) {
  const onClose = vi.fn();
  const emptyAction = vi.fn();
  render(
    <MemoryRouter>
      <PaletteSurface
        open
        onClose={onClose}
        label="命令面板"
        placeholder="搜索"
        groups={groups}
        emptyText="没有匹配项"
        emptyActions={[{ id: "home", label: "回到主页", run: emptyAction }]}
        footerHint="↑↓ 选择 · ↵ 打开"
        {...overrides}
      />
    </MemoryRouter>,
  );
  return { onClose, emptyAction, input: screen.getByRole("textbox") };
}

describe("PaletteSurface", () => {
  it("renders every group and filters by label or meta", () => {
    const { input } = renderSurface();
    expect(screen.getByText("主页")).toBeInTheDocument();
    expect(screen.getByText("模型配置")).toBeInTheDocument();

    fireEvent.change(input, { target: { value: "models" } });
    // Meta (the path) matches too, so a path fragment finds the page.
    expect(screen.getByText("模型配置")).toBeInTheDocument();
    expect(screen.queryByText("主页")).not.toBeInTheDocument();
  });

  it("runs the highlighted row with Enter and closes first", async () => {
    const { onClose } = renderSurface();
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    await waitFor(() => expect(groups[0].items[0].run).toHaveBeenCalled());
    expect(onClose).toHaveBeenCalled();
  });

  it("moves the highlight with arrow keys", async () => {
    const { input, onClose } = renderSurface();
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(groups[0].items[1].run).toHaveBeenCalled());
    expect(onClose).toHaveBeenCalled();
  });

  it("keeps the empty-state actions reachable from the keyboard", async () => {
    const { input, emptyAction } = renderSurface();
    fireEvent.change(input, { target: { value: "zzz" } });
    expect(screen.getByText("没有匹配项")).toBeInTheDocument();

    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(emptyAction).toHaveBeenCalled());
  });

  it("flattens groups in render order for index-based selection", () => {
    expect(paletteFlatItems(groups).map((item) => item.id)).toEqual([
      "home",
      "chat",
      "models",
    ]);
  });
});
