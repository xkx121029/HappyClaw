import { describe, expect, it } from "vitest";
import {
  CHAT_MIN_WIDTH,
  EDITOR_MIN_WIDTH,
  RAIL_COLLAPSED_WIDTH,
  TREE_MIN_WIDTH,
  fitWidths,
} from "./useSoloLayout";

const HANDLES = 18;

function editorWidth(available: number, fitted: ReturnType<typeof fitWidths>): number {
  const handles = fitted.tree > 0 ? HANDLES : HANDLES - 6;
  return available - fitted.rail - fitted.chat - fitted.tree - handles;
}

describe("fitWidths", () => {
  it("1366 宽屏（扣除 220 侧边栏）完整保留四区", () => {
    const fitted = fitWidths(1146, 208, 360, 220);
    expect(fitted).toMatchObject({ rail: 208, chat: 360, tree: 220, treeFitted: true });
    expect(editorWidth(1146, fitted)).toBeGreaterThanOrEqual(EDITOR_MIN_WIDTH);
  });

  it("大屏不做无谓压缩", () => {
    const fitted = fitWidths(1600, 208, 360, 220);
    expect(fitted).toMatchObject({ rail: 208, chat: 360, tree: 220 });
  });

  it("先压对话区，再压文件树，编辑器不小于最小宽度", () => {
    const available = 1060;
    const fitted = fitWidths(available, 208, 360, 220);
    expect(fitted.chat).toBeGreaterThanOrEqual(CHAT_MIN_WIDTH);
    expect(fitted.tree).toBeGreaterThanOrEqual(TREE_MIN_WIDTH);
    expect(editorWidth(available, fitted)).toBeGreaterThanOrEqual(EDITOR_MIN_WIDTH);
  });

  it("窄屏让文件树让位（浮层打开），保留对话与编辑器", () => {
    const available = 900;
    const fitted = fitWidths(available, 208, 360, 220);
    expect(fitted.tree).toBe(0);
    expect(fitted.treeFitted).toBe(false);
    expect(fitted.chat).toBeGreaterThanOrEqual(CHAT_MIN_WIDTH);
    expect(editorWidth(available, fitted)).toBeGreaterThanOrEqual(EDITOR_MIN_WIDTH);
  });

  it("极窄屏强制选择器收成图标栏", () => {
    const available = 700;
    const fitted = fitWidths(available, 260, 420, 300);
    expect(fitted.rail).toBe(RAIL_COLLAPSED_WIDTH);
    expect(fitted.tree).toBe(0);
    expect(editorWidth(available, fitted)).toBeGreaterThanOrEqual(EDITOR_MIN_WIDTH);
  });

  it("任意容器宽度下编辑器都不会被压成 0", () => {
    for (let available = 560; available <= 1920; available += 20) {
      const fitted = fitWidths(available, 208, 360, 220);
      expect(editorWidth(available, fitted)).toBeGreaterThanOrEqual(EDITOR_MIN_WIDTH - 1);
    }
  });
});
