import { describe, expect, it } from "vitest";
import {
  AGENT_MIN_WIDTH,
  DEFAULT_LAYOUT,
  EDITOR_MIN_WIDTH,
  SPLITTER_GAP,
  SPLITTER_WIDTH,
  SIDE_MIN_WIDTH,
  TREE_AUTO_COLLAPSE_WIDTH,
  TREE_MIN_WIDTH,
  fitWidths,
} from "./useSoloLayout";

function editorWidth(
  available: number,
  fitted: ReturnType<typeof fitWidths>,
): number {
  const handles = SPLITTER_GAP * (fitted.tree > 0 ? 3 : 2);
  return available - fitted.side - fitted.agent - fitted.tree - handles;
}

function fit(available: number) {
  return fitWidths(
    available,
    DEFAULT_LAYOUT.side,
    DEFAULT_LAYOUT.agent,
    DEFAULT_LAYOUT.tree,
  );
}

describe("useSoloLayout 常量", () => {
  it("默认宽度与参照稿一致", () => {
    expect(DEFAULT_LAYOUT).toMatchObject({ side: 215, agent: 660, tree: 230 });
  });

  it("分栏条视觉 5px、布局占位 1px", () => {
    expect(SPLITTER_WIDTH).toBe(5);
    expect(SPLITTER_GAP).toBe(1);
  });

  it("文件树自动收起阈值", () => {
    expect(TREE_AUTO_COLLAPSE_WIDTH).toBe(1033);
  });
});

describe("fitWidths", () => {
  it("1440：完整保留 215 / 660 / 230", () => {
    expect(fit(1440)).toMatchObject({
      side: 215,
      agent: 660,
      tree: 230,
      treeFitted: true,
    });
    expect(editorWidth(1440, fit(1440))).toBe(332);
  });

  it("1366：只压对话栏到 598", () => {
    expect(fit(1366)).toMatchObject({ side: 215, agent: 598, tree: 230 });
    expect(editorWidth(1366, fit(1366))).toBeGreaterThanOrEqual(
      EDITOR_MIN_WIDTH,
    );
  });

  it("1280：对话栏压到 512", () => {
    expect(fit(1280)).toMatchObject({ side: 215, agent: 512, tree: 230 });
    expect(editorWidth(1280, fit(1280))).toBeGreaterThanOrEqual(
      EDITOR_MIN_WIDTH,
    );
  });

  it("1135：对话栏到 400 后压文件树到 197", () => {
    expect(fit(1135)).toMatchObject({ side: 215, agent: 400, tree: 197 });
    expect(editorWidth(1135, fit(1135))).toBeGreaterThanOrEqual(
      EDITOR_MIN_WIDTH,
    );
  });

  it("1033：三栏都压到下限", () => {
    expect(fit(1033)).toMatchObject({ side: 150, agent: 400, tree: 160 });
    expect(editorWidth(1033, fit(1033))).toBeGreaterThanOrEqual(
      EDITOR_MIN_WIDTH,
    );
  });

  it("1032：文件树让位，对话栏 495", () => {
    expect(fit(1032)).toMatchObject({
      side: 215,
      agent: 495,
      tree: 0,
      treeFitted: false,
    });
    expect(editorWidth(1032, fit(1032))).toBeGreaterThanOrEqual(
      EDITOR_MIN_WIDTH,
    );
  });

  it("900：侧栏 178 / 对话 400 / 无文件树", () => {
    expect(fit(900)).toMatchObject({ side: 178, agent: 400, tree: 0 });
    expect(editorWidth(900, fit(900))).toBeGreaterThanOrEqual(
      EDITOR_MIN_WIDTH,
    );
  });

  it("900–1920 任意宽度编辑器都不小于 320", () => {
    for (let available = 900; available <= 1920; available += 20) {
      const fitted = fit(available);
      expect(editorWidth(available, fitted)).toBeGreaterThanOrEqual(
        EDITOR_MIN_WIDTH,
      );
      expect(fitted.side).toBeGreaterThanOrEqual(SIDE_MIN_WIDTH);
      expect(fitted.agent).toBeGreaterThanOrEqual(AGENT_MIN_WIDTH);
      if (fitted.tree > 0) {
        expect(fitted.tree).toBeGreaterThanOrEqual(TREE_MIN_WIDTH);
      }
    }
  });
});
